"""
Extraction service for Deriva.

Orchestrates the extraction pipeline by:
1. Loading extraction configs from DuckDB
2. Getting files from repositories
3. Calling extraction module functions
4. Persisting results to GraphManager

Used by both Marimo (visual) and CLI (headless).

Usage:
    from deriva.services import extraction
    from deriva.adapters.graph import GraphManager
    from deriva.adapters.database import get_connection

    engine = get_connection()

    with GraphManager() as gm:
        result = extraction.run_extraction(
            engine=engine,
            graph_manager=gm,
            llm_query_fn=my_llm_query,
            repo_name="my-repo",
            verbose=True,
        )
        print(f"Nodes created: {result['stats']['total_nodes']}")
        print(f"Edges created: {result['stats']['total_edges']}")
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from deriva.adapters.graph import GraphManager
from deriva.common.chunking import chunk_content, should_chunk
from deriva.common.types import ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph.models import (
    BusinessConceptNode,
    DirectoryNode,
    ExternalDependencyNode,
    FileNode,
    MethodNode,
    RepositoryNode,
    TechnologyNode,
    TestNode,
    TypeDefinitionNode,
)
from deriva.adapters.nlp import NlpTool
from deriva.adapters.repository import RepoManager
from deriva.common.cache_utils import hash_inputs
from deriva.common.document_reader import read_document
from deriva.common.file_utils import read_file_with_encoding
from deriva.common.naming import UNCOUNTABLE_WORDS, name_key
from deriva.common.ocel import create_edge_id
from deriva.modules import extraction
from deriva.modules.extraction import classification, concept_candidates, technology_candidates
from deriva.modules.extraction.base import deduplicate_nodes
from deriva.modules.extraction.directory_classification import (
    classify_directories,
    group_directories_by_name,
    structural_skip,
)
from deriva.services import config


def list_repo_files(repo_path: Path, excluded_dirs: list[str]) -> list[str]:
    """Repository-relative file paths (forward slashes), skipping excluded directories and .pyc files."""
    return [
        rel
        for f in repo_path.rglob("*")
        if f.is_file() and not str(f).endswith(".pyc") and not extraction.is_excluded_path(rel := f.relative_to(repo_path).as_posix(), excluded_dirs)
    ]


def compute_extraction_fingerprint(
    engine: Any,
    repo_name: str,
    config_versions: dict[str, dict[str, int]] | None = None,
) -> str:
    """Compute a fingerprint for the current extraction state of a repository.

    The fingerprint combines:
    - Extraction config versions (what instructions/prompts are active)
    - Repository HEAD commit hash (what code is being extracted)
    - Excluded directories setting (which parts of the repository are walked)

    If either changes, the fingerprint changes, signaling re-extraction is needed.

    Args:
        engine: DuckDB connection for config queries
        repo_name: Repository name to get commit hash for
        config_versions: Optional pre-loaded config versions. If None, fetched from DB.

    Returns:
        SHA256 hash string
    """
    # Get extraction config versions
    if config_versions and "extraction" in config_versions:
        ext_versions = config_versions["extraction"]
    else:
        all_versions = config.get_active_config_versions(engine)
        ext_versions = all_versions.get("extraction", {})

    # Get repo commit hash
    repo_mgr = RepoManager()
    repo_info = repo_mgr.get_repository_info(repo_name)
    commit = repo_info.last_commit if repo_info else "unknown"

    return hash_inputs("extraction", ext_versions, commit, config.get_excluded_directories(engine))


def llm_extraction_labels(engine: Any, config_versions: dict[str, dict[str, int]] | None = None) -> list[str]:
    """Node types created by the enabled LLM extraction steps (what an LLM-only re-run replaces)."""
    if config_versions and "extraction" in config_versions:
        configs = config.get_extraction_configs_by_version(engine, config_versions["extraction"], enabled_only=True)
    else:
        configs = config.get_extraction_configs(engine, enabled_only=True)
    return [c.node_type for c in configs if c.extraction_method == "llm"]


def run_extraction(
    engine: Any,
    graph_manager: GraphManager,
    llm_query_fn: Callable[[str, dict], Any] | None = None,
    repo_name: str | None = None,
    enabled_only: bool = True,
    verbose: bool = False,
    run_logger: RunLoggerProtocol | None = None,
    progress: ProgressReporter | None = None,
    model: str | None = None,
    phases: list[str] | None = None,
    config_versions: dict[str, dict[str, int]] | None = None,
    extraction_methods: list[str] | None = None,
    steps: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run the extraction pipeline.

    Args:
        engine: DuckDB connection for config
        graph_manager: Connected GraphManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        repo_name: Specific repo to extract, or None for all repos
        enabled_only: Only run enabled extraction steps
        verbose: Print progress to stdout
        run_logger: Optional RunLogger for structured logging
        progress: Optional progress reporter for visual feedback
        model: LLM model name for token limit lookup (chunking)
        phases: Phases to run (classify, parse), or None for all
        config_versions: Optional config version snapshot (for benchmark consistency).
                        Dict with {"extraction": {node_type: version}}
        extraction_methods: If set, only run steps with matching extraction_method
                           (e.g., ["llm"] to run only LLM steps). None runs all steps.
        steps: If set, only run these steps (node types), in their sequence order.
               None runs all steps.

    Returns:
        Dict with success, stats, errors
    """
    # Determine which phases to run
    run_classify = phases is None or "classify" in phases
    run_parse = phases is None or "parse" in phases
    stats = {
        "repos_processed": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "steps_completed": 0,
        "steps_skipped": 0,
    }
    errors = []
    warnings = []  # For "LLM required" type messages that aren't real errors
    step_stats: dict[str, dict[str, Any]] = {}  # repo -> step -> the step's own report

    # Start phase logging
    if run_logger:
        run_logger.phase_start("extraction", "Starting extraction pipeline")

    # Get repositories
    repo_mgr = RepoManager()
    repos = repo_mgr.list_repositories(detailed=True)

    if repo_name:
        repos = [r for r in repos if hasattr(r, "name") and r.name == repo_name]

    if not repos:
        return {"success": False, "stats": stats, "errors": ["No repositories found"]}

    # Get extraction configs - use snapshot versions if provided (for benchmark consistency)
    if config_versions and "extraction" in config_versions:
        configs = config.get_extraction_configs_by_version(engine, config_versions["extraction"], enabled_only=enabled_only)
    else:
        configs = config.get_extraction_configs(engine, enabled_only=enabled_only)

    if not configs:
        return {"success": False, "stats": stats, "errors": ["No extraction configs enabled"]}
    if steps is not None:
        unknown = sorted(set(steps) - {c.node_type for c in configs})
        if unknown:
            return {"success": False, "stats": stats, "errors": [f"Unknown or disabled extraction step(s): {', '.join(unknown)}"]}
        configs = [c for c in configs if c.node_type in steps]

    # Get file type registry for classification
    file_types = config.get_file_types(engine)
    registry_list = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in file_types]

    # Start progress tracking
    # If only classify: 1 step per repo; if parse: steps = selected configs (by method) * repos
    selected = [c for c in configs if extraction_methods is None or c.extraction_method in extraction_methods]
    if run_parse and not selected:
        warnings.append(f"No enabled extraction step uses method(s): {', '.join(extraction_methods or [])}")
    if run_parse:
        total_steps = len(selected) * len(repos)
    else:
        total_steps = len(repos)  # Just classification
    if progress:
        progress.start_phase("extraction", total_steps)

    # Process each repository
    for repo in repos:
        # Skip if not a proper RepositoryInfo object
        if not hasattr(repo, "name") or not hasattr(repo, "path"):
            continue
        if verbose:
            print(f"\nProcessing repository: {repo.name}")

        repo_path = Path(str(repo.path))
        stats["repos_processed"] += 1

        # Get all files for classification (outside excluded dependency directories)
        file_paths = list_repo_files(repo_path, config.get_excluded_directories(engine))

        # Classify files (always needed - prerequisite for parse phase)
        classification_result = classification.classify_files(file_paths, registry_list)
        classified_files = classification_result["classified"]
        undefined_files = classification_result["undefined"]

        # Track classification stats
        stats["files_classified"] = stats.get("files_classified", 0) + len(classified_files)
        stats["files_undefined"] = stats.get("files_undefined", 0) + len(undefined_files)

        if verbose and run_classify:
            print(f"  Classify: {len(classified_files)} files classified, {len(undefined_files)} undefined")

        # Skip parse phase if only running classify
        if not run_parse:
            if verbose:
                print("  Skipping parse phase (classify only)")
            # Track progress for classify-only mode
            if progress:
                progress.start_step("classify")
                progress.complete_step(f"{len(classified_files)} files classified")
            stats["steps_completed"] += 1
            continue

        # Process each extraction step in sequence order (parse phase)
        for cfg in configs:
            # Skip steps that don't match the requested extraction methods
            if extraction_methods is not None and cfg.extraction_method not in extraction_methods:
                stats["steps_skipped"] += 1
                if verbose:
                    print(f"  Skipping: {cfg.node_type} (method={cfg.extraction_method})")
                continue

            node_type = cfg.node_type

            if verbose:
                print(f"  Extracting: {node_type}")

            # Start progress tracking for this step
            if progress:
                progress.start_step(node_type)

            # Start step logging
            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(node_type, f"Extracting {node_type} from {repo.name}")

            try:
                result = _run_extraction_step(
                    cfg=cfg,
                    repo=repo,
                    repo_path=repo_path,
                    classified_files=classified_files,
                    undefined_files=undefined_files,
                    graph_manager=graph_manager,
                    llm_query_fn=llm_query_fn,
                    engine=engine,
                    model=model,
                )

                nodes_created = result.get("nodes_created", 0)
                edges_created = result.get("edges_created", 0)
                edge_ids = result.get("edge_ids", [])
                if result.get("stats"):
                    step_stats.setdefault(str(repo.name), {})[node_type] = result["stats"]
                stats["nodes_created"] += nodes_created
                stats["edges_created"] += edges_created
                stats["steps_completed"] += 1

                # Complete step logging
                if step_ctx:
                    step_ctx.items_created = nodes_created + edges_created
                    step_ctx.stats = result.get("stats")
                    # Add edge IDs for OCEL logging
                    for edge_id in edge_ids:
                        step_ctx.add_edge(edge_id)
                    step_ctx.complete()

                # Complete progress tracking for this step
                if progress:
                    progress.complete_step(f"{nodes_created} nodes, {edges_created} edges")

                # Separate warnings (skipped steps) from real errors
                for err in result.get("errors", []):
                    if "LLM required" in err or "No input sources" in err:
                        warnings.append(err)
                    else:
                        # Add step context to error messages
                        error_with_context = f"[Extraction - {node_type}] {err}"
                        errors.append(error_with_context)
                        logger.error(error_with_context)

            except Exception as e:
                error_msg = f"Error in {node_type}: {str(e)}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1
                if step_ctx:
                    step_ctx.error(str(e))
                if progress:
                    progress.log(error_msg, level="error")
                    progress.complete_step()

    # Complete phase logging
    if run_logger:
        if errors:
            run_logger.phase_error("extraction", "; ".join(errors[:3]), "Extraction completed with errors")
        else:
            run_logger.phase_complete("extraction", "Extraction completed successfully", stats=stats)

    # Set extraction fingerprint on each processed repo (for cache validation); a
    # method- or step-filtered run leaves the other steps' data as it was, so it is not current
    if not errors and extraction_methods is None and steps is None:
        for repo in repos:
            if not hasattr(repo, "name"):
                continue
            try:
                repo_name_str = str(repo.name)
                fp = compute_extraction_fingerprint(engine, repo_name_str, config_versions)
                graph_manager.set_extraction_fingerprint(repo_name_str, fp)
            except Exception as e:
                logger.warning("Failed to set extraction fingerprint for '%s': %s", repo.name, e)

    # Complete progress tracking
    if progress:
        msg = f"Extraction complete: {stats['nodes_created']} nodes, {stats['edges_created']} edges"
        progress.complete_phase(msg)

    return {
        "success": len(errors) == 0,
        "stats": stats,
        "errors": errors,
        "warnings": warnings,
        "step_stats": step_stats,
    }


def _run_extraction_step(
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    undefined_files: list[dict],
    graph_manager: GraphManager,
    llm_query_fn: Callable | None,
    engine: Any,
    model: str | None = None,
) -> dict[str, Any]:
    """Run a single extraction step based on node type."""
    node_type = cfg.node_type

    if node_type == "Repository":
        result = _extract_repository(repo, graph_manager)
    elif node_type == "Directory":
        result = _extract_directories(repo, repo_path, graph_manager, config.get_excluded_directories(engine))
    elif node_type == "File":
        result = _extract_files(repo, repo_path, classified_files, undefined_files, graph_manager, config.get_excluded_directories(engine))
    elif node_type == "Imports":
        # Tree-sitter based import edge extraction (deterministic, no LLM)
        result = _extract_imports(repo, repo_path, classified_files, graph_manager)
    elif node_type == "Calls":
        # Tree-sitter based call edge extraction (deterministic, no LLM)
        result = _extract_calls(repo, repo_path, classified_files, graph_manager)
    elif node_type == "Decorators":
        # Tree-sitter based decorator edge extraction (deterministic, no LLM)
        result = _extract_decorators(repo, repo_path, classified_files, graph_manager)
    elif node_type == "References":
        # Tree-sitter based type reference edge extraction (deterministic, no LLM)
        result = _extract_references(repo, repo_path, classified_files, graph_manager)
    elif node_type == "Edges":
        # Unified edge extraction: all edge types in one efficient pass (4x faster)
        result = _extract_edges(repo, repo_path, classified_files, graph_manager)
    elif node_type == "DirectoryClassification":
        if llm_query_fn is None:
            return {"nodes_created": 0, "edges_created": 0, "errors": [f"LLM required for {node_type}"]}
        result = _extract_directory_classification(
            cfg=cfg,
            repo=repo,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
        )
    elif node_type == "Technology":
        if llm_query_fn is None:
            return {"nodes_created": 0, "edges_created": 0, "errors": [f"LLM required for {node_type}"]}
        result = _extract_technologies(
            cfg=cfg,
            repo=repo,
            repo_path=repo_path,
            classified_files=classified_files,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
        )
    elif node_type == "BusinessConcept":
        if llm_query_fn is None:
            return {"nodes_created": 0, "edges_created": 0, "errors": [f"LLM required for {node_type}"]}
        result = _extract_business_concepts(
            cfg=cfg,
            repo=repo,
            repo_path=repo_path,
            classified_files=classified_files,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
        )
    elif node_type in ["TypeDefinition", "Method", "ExternalDependency", "Test"]:
        if llm_query_fn is None:
            return {"nodes_created": 0, "edges_created": 0, "errors": [f"LLM required for {node_type}"]}
        result = _extract_llm_based(
            node_type=node_type,
            cfg=cfg,
            repo=repo,
            repo_path=repo_path,
            classified_files=classified_files,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
            engine=engine,
            model=model,
        )
    else:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"Unknown node type: {node_type}"]}

    return result


def _extract_repository(repo: Any, graph_manager: GraphManager) -> dict[str, Any]:
    """Extract repository node."""
    repo_metadata = {
        "name": repo.name,
        "url": repo.url,
        "description": "",
        "default_branch": repo.branch,
    }

    result = extraction.extract_repository(repo_metadata)

    if result["success"]:
        for node_data in result["data"]["nodes"]:
            repo_node = RepositoryNode(
                name=node_data["properties"]["name"],
                url=node_data["properties"]["url"],
                created_at=datetime.now(),
                branch=node_data["properties"].get("default_branch"),
                description=node_data["properties"].get("description"),
            )
            graph_manager.add_node(repo_node, node_id=node_data["node_id"])

    return {
        "nodes_created": result["stats"].get("total_nodes", 0),
        "edges_created": result["stats"].get("total_edges", 0),
        "errors": result.get("errors", []),
    }


def _extract_directories(repo: Any, repo_path: Path, graph_manager: GraphManager, excluded_dirs: list[str]) -> dict[str, Any]:
    """Extract directory nodes (outside excluded dependency directories)."""
    result = extraction.extract_directories(str(repo_path), repo.name, excluded_dirs=excluded_dirs)
    edge_ids: list[str] = []

    if result["success"]:
        for node_data in result["data"]["nodes"]:
            dir_node = DirectoryNode(
                name=node_data["properties"]["name"],
                path=node_data["properties"]["path"],
                repository_name=repo.name,
            )
            graph_manager.add_node(dir_node, node_id=node_data["node_id"])

        for edge_data in result["data"]["edges"]:
            edge_id = create_edge_id(
                edge_data["from_node_id"],
                edge_data["relationship_type"],
                edge_data["to_node_id"],
            )
            edge_ids.append(edge_id)
            graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=edge_data["to_node_id"],
                relationship=edge_data["relationship_type"],
            )

    return {
        "nodes_created": result["stats"].get("total_nodes", 0),
        "edges_created": result["stats"].get("total_edges", 0),
        "edge_ids": edge_ids,
        "errors": result.get("errors", []),
    }


def _extract_files(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    undefined_files: list[dict],
    graph_manager: GraphManager,
    excluded_dirs: list[str],
) -> dict[str, Any]:
    """Extract file nodes (outside excluded dependency directories).

    Args:
        repo: Repository info object
        repo_path: Path to the repository
        classified_files: List of classified file dicts with file_type/subtype
        undefined_files: List of undefined file dicts (files with unknown extensions)
        graph_manager: GraphManager for persistence
        excluded_dirs: Directory names skipped with their contents
    """
    # Use the module to scan all files from repo path
    result = extraction.extract_files(str(repo_path), repo.name, excluded_dirs=excluded_dirs)
    edge_ids: list[str] = []

    # Build a lookup for classification info (normalize paths to forward slashes)
    classification_lookup = {f["path"].replace("\\", "/"): f for f in classified_files}

    # Add undefined files to lookup with default file_type="unknown"
    for f in undefined_files:
        path = f["path"].replace("\\", "/")
        if path not in classification_lookup:
            classification_lookup[path] = {
                "path": path,
                "file_type": "unknown",
                "subtype": f.get("extension", "").lstrip(".") or None,
            }

    if result["success"]:
        for node_data in result["data"]["nodes"]:
            props = node_data["properties"]
            # Get classification info from lookup
            # If not found, use "unknown" as default file_type
            class_info = classification_lookup.get(props["path"], {})
            file_type = class_info.get("file_type") or "unknown"
            subtype = class_info.get("subtype")

            # If subtype is not set, try to infer from file extension
            if not subtype:
                ext = Path(props["path"]).suffix.lower().lstrip(".")
                subtype = ext if ext else None

            file_node = FileNode(
                name=props["name"],
                path=props["path"],
                repository_name=repo.name,
                file_type=file_type,
                subtype=subtype,
            )
            graph_manager.add_node(file_node, node_id=node_data["node_id"])

        for edge_data in result["data"]["edges"]:
            edge_id = create_edge_id(
                edge_data["from_node_id"],
                edge_data["relationship_type"],
                edge_data["to_node_id"],
            )
            edge_ids.append(edge_id)
            graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=edge_data["to_node_id"],
                relationship=edge_data["relationship_type"],
            )

    return {
        "nodes_created": result["stats"].get("total_nodes", 0),
        "edges_created": result["stats"].get("total_edges", 0),
        "edge_ids": edge_ids,
        "errors": result.get("errors", []),
    }


def _extract_edges(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
    edge_types: set | None = None,
) -> dict[str, Any]:
    """Extract edges from source files using Tree-sitter (unified extraction).

    This is the efficient unified extraction that parses each file only once
    and extracts all requested edge types in a single pass.

    Creates edges:
    - File → File (IMPORTS) for internal imports
    - File → ExternalDependency (USES) for external package imports
    - Method → Method (CALLS) for function/method calls
    - Method → Method (DECORATED_BY) for decorator relationships
    - Method → TypeDefinition (REFERENCES) for type annotations

    Args:
        repo: Repository info object
        repo_path: Path to the repository
        classified_files: List of classified file dicts with file_type/subtype
        graph_manager: GraphManager for persistence
        edge_types: Set of EdgeType values to extract (None = all)
    """
    from deriva.modules.extraction.edges import extract_edges_batch

    edge_ids: list[str] = []
    edges_created = 0
    nodes_created = 0

    # Get known external packages from the graph (for import resolution)
    external_packages: set[str] = set()
    try:
        extdeps = graph_manager.get_nodes_by_type("ExternalDependency")
        for dep in extdeps:
            props = dep.get("properties", {})
            name = props.get("name") or props.get("dependencyName")
            if name:
                # Normalize: flask-sqlalchemy -> flask_sqlalchemy
                external_packages.add(name.lower().replace("-", "_"))
    except Exception:
        pass  # Proceed without external package list

    # Build global method lookup from graph for cross-file CALLS/DECORATED_BY resolution
    # Key: (method_name, class_name or None) -> list of node_ids with file_paths
    global_method_lookup: dict[tuple[str, str | None], list[dict]] = {}
    try:
        methods = graph_manager.get_nodes_by_type("Method")
        for m in methods:
            # Properties may be nested in a "properties" dict or at top level
            props = m.get("properties", m)
            method_name = props.get("methodName") or props.get("name", "")
            class_name = props.get("typeName") or props.get("class_name") or None
            if class_name == "":
                class_name = None
            file_path = props.get("filePath") or props.get("file_path", "")
            node_id = m.get("id", "")

            # Keep file_path as-is (with repo prefix) to match classified_files format
            # Both graph filePath and classified_files paths include the full relative path
            # e.g., "deriva/cli/cli.py" for files inside the deriva/ subdirectory

            key = (method_name, class_name)
            if key not in global_method_lookup:
                global_method_lookup[key] = []
            global_method_lookup[key].append(
                {
                    "node_id": node_id,
                    "file_path": file_path,
                    "class_name": class_name,
                }
            )
        logger.debug(f"Built global method lookup with {len(global_method_lookup)} unique signatures")
    except Exception as e:
        logger.warning(f"Failed to build global method lookup: {e}")

    # Build global type lookup from graph for cross-file REFERENCES resolution
    # Key: type_name -> list of node_ids with file_paths
    global_type_lookup: dict[str, list[dict]] = {}
    try:
        types = graph_manager.get_nodes_by_type("TypeDefinition")
        for t in types:
            # Properties may be nested in a "properties" dict or at top level
            props = t.get("properties", t)
            type_name = props.get("typeName") or props.get("name", "")
            file_path = props.get("filePath") or props.get("file_path", "")
            node_id = t.get("id", "")

            # Keep file_path as-is (with repo prefix) to match classified_files format
            # Both graph filePath and classified_files paths include the full relative path

            if type_name not in global_type_lookup:
                global_type_lookup[type_name] = []
            global_type_lookup[type_name].append(
                {
                    "node_id": node_id,
                    "file_path": file_path,
                }
            )
        logger.debug(f"Built global type lookup with {len(global_type_lookup)} unique types")
    except Exception as e:
        logger.warning(f"Failed to build global type lookup: {e}")

    # Run unified batch extraction (one pass over all files)
    result = extract_edges_batch(
        files=classified_files,
        repo_name=repo.name,
        repo_path=repo_path,
        edge_types=edge_types,
        external_packages=external_packages,
        global_method_lookup=global_method_lookup,
        global_type_lookup=global_type_lookup,
    )

    # First, process ExternalDependency nodes from imports
    # These have declared=False, used=True (discovered via imports, not manifests)
    for node_data in result["data"].get("nodes", []):
        node_id = node_data.get("node_id")
        if not node_id:
            continue

        # Check if node already exists (e.g., from ExternalDependency manifest parsing)
        if graph_manager.node_exists(node_id):
            # Node exists from manifest - update 'used' property to True
            try:
                graph_manager.update_node_property(node_id, "used", True)
                logger.debug("Updated ExternalDependency node used=True: %s", node_id)
            except Exception as e:
                logger.debug(f"Failed to update node {node_id}: {e}")
        else:
            # Node doesn't exist - create it (import without manifest declaration)
            try:
                props = node_data.get("properties", {})
                stub_node = ExternalDependencyNode(
                    name=props.get("dependencyName", "unknown"),
                    dependency_category=props.get("dependencyCategory", "library"),
                    repository_name=repo.name,
                    description="External package discovered via import",
                    confidence=props.get("confidence", 1.0),
                    extraction_method="treesitter",
                )
                # Add additional properties
                stub_node.declared = props.get("declared", False)
                stub_node.used = props.get("used", True)
                stub_node.ecosystem = props.get("ecosystem", "unknown")

                graph_manager.add_node(stub_node, node_id=node_id)
                nodes_created += 1
                logger.debug("Created ExternalDependency node from import: %s", node_id)
            except Exception as e:
                logger.debug(f"Failed to create node {node_id}: {e}")

    # Persist edges to graph
    for edge_data in result["data"]["edges"]:
        relationship = edge_data["relationship_type"]
        dst_id = edge_data["to_node_id"]

        try:
            edge_id = graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=dst_id,
                relationship=relationship,
                properties=edge_data.get("properties"),
            )
            edge_ids.append(edge_id)
            edges_created += 1
        except Exception as e:
            # Edge target might not exist (expected for some external references)
            logger.debug(f"Failed to create {relationship} edge: {e}")

    return {
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "edge_ids": edge_ids,
        "errors": result.get("errors", []),
        "stats": result.get("stats", {}),
    }


def _extract_imports(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract IMPORTS and USES edges from source files using Tree-sitter."""
    from deriva.modules.extraction.edges import EdgeType

    return _extract_edges(repo, repo_path, classified_files, graph_manager, {EdgeType.IMPORTS, EdgeType.USES})


def _extract_calls(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract CALLS edges from source files using Tree-sitter."""
    from deriva.modules.extraction.edges import EdgeType

    return _extract_edges(repo, repo_path, classified_files, graph_manager, {EdgeType.CALLS})


def _extract_decorators(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract DECORATED_BY edges from source files using Tree-sitter."""
    from deriva.modules.extraction.edges import EdgeType

    return _extract_edges(repo, repo_path, classified_files, graph_manager, {EdgeType.DECORATED_BY})


def _extract_references(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract REFERENCES edges from type annotations using Tree-sitter."""
    from deriva.modules.extraction.edges import EdgeType

    return _extract_edges(repo, repo_path, classified_files, graph_manager, {EdgeType.REFERENCES})


def _extract_directory_classification(
    cfg: config.ExtractionConfig,
    repo: Any,
    graph_manager: GraphManager,
    llm_query_fn: Callable,
) -> dict[str, Any]:
    """Extract BusinessConcept and Technology nodes from Directory classification.

    This queries Directory nodes from the graph and classifies them using LLM
    into business concepts, technologies, or skips.
    """
    nodes_created = 0
    edges_created = 0
    errors = []
    edge_ids: list[str] = []

    # Query Directory nodes from the graph for this repository
    # Include file stats for better LLM context (now that File extraction runs before this).
    # Dependency directories never become nodes (excluded_directories setting).
    # Sorted by path, so the batches never depend on storage order.
    query = """
    MATCH (d:Directory)
    WHERE d.repository_name = $repo_name
    OPTIONAL MATCH (d)-[:`Graph:CONTAINS`]->(f:File)
    WITH d,
         count(f) AS file_count,
         sum(CASE WHEN f.fileType = 'source' THEN 1 ELSE 0 END) AS source_count,
         sum(CASE WHEN f.fileType = 'config' THEN 1 ELSE 0 END) AS config_count,
         sum(CASE WHEN f.fileType = 'docs' THEN 1 ELSE 0 END) AS docs_count,
         sum(CASE WHEN f.fileType = 'test' THEN 1 ELSE 0 END) AS test_count,
         collect(DISTINCT f.subtype) AS subtypes
    OPTIONAL MATCH (d)-[:`Graph:CONTAINS`]->(c:Directory)
    WITH d, file_count, source_count, config_count, docs_count, test_count, subtypes,
         count(c) AS subdir_count
    RETURN d.name AS name, d.path AS path, d.id AS id,
           file_count, source_count, config_count, docs_count, test_count,
           subtypes, subdir_count
    ORDER BY d.path
    """
    try:
        directories = graph_manager.query(query, {"repo_name": repo.name})
    except Exception as e:
        return {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [f"Failed to query directories: {e}"],
        }

    if not directories:
        return {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
            "warnings": [f"No directories found for {repo.name}"],
        }

    # Build config dict from ExtractionConfig (params: samples/min_votes for majority voting)
    extraction_config = {
        "instruction": cfg.instruction or "",
        "example": cfg.example or "",
        "params": json.loads(cfg.params) if cfg.params else {},
    }

    # Wrap llm_query_fn with per-step temperature/max_tokens overrides
    def step_llm_query_fn(prompt: str, schema: dict, system_prompt: str | None = None) -> Any:
        return llm_query_fn(
            prompt,
            schema,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            system_prompt=system_prompt,
        )

    # Directories the structure decides (skip names, skipped trees, path steps) never reach the LLM;
    # the rest go as one entry per name, so copies of a name share one decision
    directories, _skipped = structural_skip(directories, extraction_config["params"])
    directories = group_directories_by_name(directories)

    # Process directories in batches (default 50 directories per batch)
    batch_size = cfg.batch_size if cfg.batch_size and cfg.batch_size > 1 else 50
    all_nodes = []
    all_edges = []

    for i in range(0, len(directories), batch_size):
        batch = directories[i : i + batch_size]
        logger.debug(f"Processing directory batch {i // batch_size + 1}/{(len(directories) + batch_size - 1) // batch_size}")

        # Classify directories batch
        result = classify_directories(
            directories=batch,
            repo_name=repo.name,
            llm_query_fn=step_llm_query_fn,
            config=extraction_config,
        )

        if not result["success"]:
            errors.extend(result.get("errors", []))
            continue

        all_nodes.extend(result["data"]["nodes"])
        all_edges.extend(result["data"]["edges"])

    # Persist extracted nodes
    for node_data in all_nodes:
        props = node_data.get("properties", {})
        labels = node_data.get("labels", [])

        # Determine node type from labels
        if "Graph:BusinessConcept" in labels:
            node = BusinessConceptNode(
                name=props.get("conceptName", ""),
                concept_type=props.get("conceptType", "entity"),
                description=props.get("description", ""),
                origin_source=props.get("originSource", ""),
                repository_name=repo.name,
                confidence=props.get("confidence", 0.8),
                extraction_method="llm-directory",
            )
        elif "Graph:Technology" in labels:
            node = TechnologyNode(
                name=props.get("technologyName", ""),
                tech_category=props.get("technologyType", "infrastructure"),
                repository_name=repo.name,
                description=props.get("description", ""),
                origin_source=props.get("originSource", ""),
                confidence=props.get("confidence", 0.8),
                extraction_method="llm-directory",
            )
        else:
            continue

        node_id = node_data.get("id")
        if isinstance(node, BusinessConceptNode):
            _add_concept_node(graph_manager, node, node_id)
        else:
            graph_manager.add_node(node, node_id=node_id)
        nodes_created += 1

    # Persist extracted edges
    for edge_data in all_edges:
        src_id = edge_data.get("source")
        dst_id = edge_data.get("target")
        relationship = edge_data.get("relationship_type", "REPRESENTS")

        try:
            edge_id = create_edge_id(src_id, relationship, dst_id)
            edge_ids.append(edge_id)
            graph_manager.add_edge(
                src_id=src_id,
                dst_id=dst_id,
                relationship=relationship,
            )
            edges_created += 1
        except RuntimeError as e:
            errors.append(f"Error creating edge {relationship}: {e}")

    return {
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "edge_ids": edge_ids,
        "errors": errors,
    }


# Files that can't be meaningfully analyzed as text
_UNREADABLE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".bmp",
    ".svg",
    ".webp",
    ".xcf",
    ".psd",
    ".ai",
    ".eps",  # Image editing formats
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",  # Archives
    ".exe",
    ".dll",
    ".so",
    ".dylib",  # Binaries
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",  # Fonts
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",  # Media
    ".class",
    ".pyc",
    ".pyo",  # Compiled code
    ".archimate",
    ".archimate.bak",
}  # ArchiMate model files (already contain architecture)


def _is_unreadable(file_info: dict) -> bool:
    return any(file_info.get("path", "").lower().endswith(ext) for ext in _UNREADABLE_EXTENSIONS)


def _extract_llm_based(
    node_type: str,
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
    llm_query_fn: Callable,
    engine: Any,
    model: str | None = None,
) -> dict[str, Any]:
    """Extract LLM-based nodes (TypeDefinition, Method, Technology, ExternalDependency, Test)."""
    nodes_created = 0
    edges_created = 0
    errors = []
    deferred_inherits: list[dict] = []

    # Parse input sources from config
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None

    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"No input sources for {node_type}"]}

    # Get files matching the input sources
    matching_files = extraction.filter_files_by_input_sources(classified_files, input_sources)

    # Binary and image files can't be meaningfully analyzed as text
    matching_files = [f for f in matching_files if not _is_unreadable(f)]

    # Special case: Method extraction with node-based sources (TypeDefinition.codeSnippet)
    # For Python files, we can use AST to extract methods directly from source files
    if not matching_files and node_type == "Method" and extraction.has_node_sources(input_sources):
        # Get all Python source files for AST-based method extraction
        matching_files = [f for f in classified_files if extraction.is_python_file(f.get("subtype"))]

    if not matching_files:
        # Not an error - valid case when no files match input sources
        return {
            "nodes_created": 0,
            "edges_created": 0,
            "errors": [],
            "warnings": [f"No matching files for {node_type} in {repo.name}"],
        }

    # Get extraction function and schema based on node type
    extract_fn, schema, node_class = _get_extraction_config(node_type)

    if extract_fn is None:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"No extraction function for {node_type}"]}

    # Build config dict from ExtractionConfig
    extraction_config = {
        "instruction": cfg.instruction or "",
        "example": cfg.example or "",
        "input_sources": cfg.input_sources or "",
        "params": json.loads(cfg.params) if cfg.params else {},
    }

    # Wrap llm_query_fn with per-step temperature/max_tokens overrides
    def step_llm_query_fn(prompt: str, schema: dict, system_prompt: str | None = None) -> Any:
        return llm_query_fn(
            prompt,
            schema,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            system_prompt=system_prompt,
        )

    # Check if we can use tree-sitter extraction for supported languages
    use_treesitter = node_type in ["TypeDefinition", "Method"]
    treesitter_languages = {"python", "javascript", "typescript", "java", "csharp"}

    # Process each matching file
    for file_info in matching_files:
        file_path = repo_path / file_info["path"]

        try:
            # Route document files to specialized reader
            if file_path.suffix.lower() in (".docx", ".pdf"):
                content = read_document(file_path)
            else:
                content = read_file_with_encoding(file_path)
            if content is None:
                errors.append(f"Could not read {file_path} | repo={repo.name} | step={node_type}")
                continue
        except Exception as e:
            errors.append(f"Could not read {file_path} | repo={repo.name} | step={node_type} | exception={type(e).__name__}: {e}")
            continue

        # Check if this file's language is supported by tree-sitter
        file_subtype = file_info.get("subtype", "").lower()
        is_treesitter_supported = file_subtype in treesitter_languages

        # Track extraction method for this file
        extraction_method = "llm"  # Default

        # ExternalDependency: use unified function (handles deterministic/treesitter/LLM)
        if node_type == "ExternalDependency":
            result = extraction.extract_external_dependencies(
                file_path=file_info["path"],
                file_content=content,
                repo_name=repo.name,
                llm_query_fn=step_llm_query_fn,
                config=extraction_config,
                subtype=file_info.get("subtype"),
                model=model,
            )
            file_nodes = result["data"]["nodes"] if result["success"] else []
            file_edges = result["data"].get("edges", []) if result["success"] else []
            file_errors = result.get("errors", [])
            # ExternalDependency uses tree-sitter for supported languages, structural for config files
            extraction_method = result.get("extraction_method", "llm")
        elif use_treesitter and is_treesitter_supported:
            # Use tree-sitter extraction for supported languages - faster and more precise
            if node_type == "TypeDefinition":
                result = extraction.extract_types_from_source(file_info["path"], content, repo.name)
            else:  # Method
                result = extraction.extract_methods_from_source(file_info["path"], content, repo.name)
            file_nodes = result["data"]["nodes"] if result["success"] else []
            file_edges = result["data"].get("edges", []) if result["success"] else []
            file_errors = result.get("errors", [])
            extraction_method = "treesitter"
        else:
            # Use LLM extraction for non-Python files or other node types
            file_nodes, file_edges, file_errors = _extract_file_content(
                file_path=file_info["path"],
                content=content,
                repo_name=repo.name,
                extract_fn=extract_fn,
                extraction_config=extraction_config,
                llm_query_fn=step_llm_query_fn,
                model=model,
            )
            extraction_method = "llm"

        errors.extend(file_errors)

        # Normalize node names for consistency
        if node_type == "ExternalDependency":
            file_nodes = extraction.normalize_nodes(file_nodes, node_type, repo.name)

        # Persist extracted nodes
        for node_data in file_nodes:
            node = _create_node_from_data(node_type, node_data, repo.name, extraction_method)
            if node:
                graph_manager.add_node(node, node_id=node_data.get("node_id"))
                nodes_created += 1

        # Persist extracted edges
        for edge_data in file_edges:
            # Note: extraction modules use from_node_id/to_node_id/relationship_type
            src_id = edge_data.get("from_node_id", edge_data.get("from_id"))
            dst_id = edge_data.get("to_node_id", edge_data.get("to_id"))
            relationship = edge_data.get("relationship_type", edge_data.get("relationship"))

            # A base type outside this file is resolved once every file is extracted (below)
            if relationship == "INHERITS" and not graph_manager.node_exists(dst_id):
                deferred_inherits.append(edge_data)
                continue
            # For CALLS edges, create placeholder node if target doesn't exist
            # These are semantic edges to types that may be external or in other files
            if relationship == "CALLS" and not graph_manager.node_exists(dst_id):
                _add_type_placeholder(graph_manager, edge_data, dst_id, repo.name)
            elif not graph_manager.node_exists(dst_id):
                # Skip edges where target node doesn't exist (may have been filtered/failed)
                logger.debug(f"Skipping edge to non-existent node: {dst_id}")
                continue

            edges_created += _add_extracted_edge(graph_manager, src_id, dst_id, relationship, edge_data.get("properties"), errors)

    # Inheritance edges to a base type in another file point at the repository's own type of that
    # name when exactly one exists (structure decides); otherwise at a placeholder, as before
    if deferred_inherits:
        definitions = _type_definitions_by_name(graph_manager, repo.name)
        for edge_data in deferred_inherits:
            src_id = edge_data.get("from_node_id", edge_data.get("from_id"))
            dst_id = edge_data.get("to_node_id", edge_data.get("to_id"))
            base_name = (edge_data.get("properties") or {}).get("base_name") or ""
            target = extraction.resolve_base_type(base_name, definitions, source_id=src_id)
            if target is None:
                target = dst_id
                if not graph_manager.node_exists(dst_id):
                    _add_type_placeholder(graph_manager, edge_data, dst_id, repo.name)
            edges_created += _add_extracted_edge(graph_manager, src_id, target, "INHERITS", edge_data.get("properties"), errors)

    return {
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "errors": errors,
    }


def _add_type_placeholder(graph_manager: GraphManager, edge_data: dict, node_id: str, repo_name: str) -> None:
    """A placeholder TypeDefinition for a referenced type that is external or unresolved."""
    edge_props = edge_data.get("properties", {})
    type_name = edge_props.get("base_name") or edge_props.get("type_annotation") or node_id.split("_")[-1]
    placeholder_node = TypeDefinitionNode(
        name=type_name,
        type_category="external_reference",
        file_path="external",  # Placeholder for external/unresolved types
        repository_name=repo_name,
        description=f"External or unresolved type reference: {type_name}",
        confidence=0.5,
        extraction_method="structural",
    )
    graph_manager.add_node(placeholder_node, node_id=node_id)
    logger.debug(f"Created placeholder node for {edge_data.get('relationship_type')} target: {node_id}")


def _add_extracted_edge(graph_manager: GraphManager, src_id: str, dst_id: str, relationship: str, properties: dict | None, errors: list[str]) -> int:
    """Add one extracted edge; returns 1 when it was created (errors are collected)."""
    try:
        graph_manager.add_edge(src_id=src_id, dst_id=dst_id, relationship=relationship, properties=properties)
        return 1
    except RuntimeError as e:
        errors.append(f"Error creating edge {relationship}: {e}")
        return 0


def _type_definitions_by_name(graph_manager: GraphManager, repo_name: str) -> dict[str, list[str]]:
    """The repository's own type definitions (no placeholders) by type name, ids sorted."""
    rows = graph_manager.query(
        "MATCH (t:Graph:TypeDefinition) WHERE t.repository_name = $repo_name AND t.category <> 'external_reference' RETURN t.typeName AS name, t.id AS id",
        {"repo_name": repo_name},
    )
    definitions: dict[str, list[str]] = {}
    for row in rows:
        if row.get("name") and row.get("id"):
            definitions.setdefault(row["name"], []).append(row["id"])
    return {name: sorted(ids) for name, ids in definitions.items()}


# Params the BusinessConcept step reads from its config row (every one of them changes results)
_CONCEPT_PARAMS = ("confidence", "evidence_min_count", "evidence_share", "max_candidates", "missing_retries", "nlp", "stop_words", "support_factor")


def _code_names(graph_manager: GraphManager, repo_name: str) -> list[str]:
    """The names that give a candidate term code support: the repository's own type definitions
    (not external references) and its directory names. Structure only (no LLM decision)."""
    params = {"repo_name": repo_name}
    types = graph_manager.query(
        "MATCH (t:Graph:TypeDefinition) WHERE t.repository_name = $repo_name AND t.category <> 'external_reference' RETURN DISTINCT t.typeName AS name",
        params,
    )
    directories = graph_manager.query("MATCH (d:Graph:Directory) WHERE d.repository_name = $repo_name RETURN DISTINCT d.name AS name", params)
    return sorted({row["name"] for row in types + directories if row.get("name")})


def _read_documents(repo_path: Path, files: list[dict], repo_name: str) -> tuple[list[dict[str, str]], list[str]]:
    """The text of every file in path order; empty files are left out, unreadable ones reported."""
    documents, errors = [], []
    for file_info in sorted(files, key=lambda f: f["path"]):
        file_path = repo_path / file_info["path"]
        try:
            text = read_document(file_path) if file_path.suffix.lower() in (".docx", ".pdf") else read_file_with_encoding(file_path)
        except Exception as e:
            errors.append(f"Could not read {file_path} | repo={repo_name} | step=BusinessConcept | exception={type(e).__name__}: {e}")
            continue
        if text is None:
            errors.append(f"Could not read {file_path} | repo={repo_name} | step=BusinessConcept")
        elif text:
            documents.append({"path": file_info["path"], "text": text})
    return documents, errors


def _classify_batch(
    cfg: config.ExtractionConfig,
    classifier: ModuleType,
    batch: list[Any],
    where: str,
    missing_retries: int,
    llm_query_fn: Callable,
) -> dict[str, Any]:
    """Labels for one batch of a closed classification. Items an answer leaves out are asked again on their
    own, up to `missing_retries` times; every item still gets one decision, never a vote.

    ``classifier`` is the step's candidate module: ``build_classification_prompt``, ``CLASSIFICATION_SCHEMA``
    and ``parse_labels``.

    Returns the labels by key, the answer issues, errors, retry calls and the labels the retries recovered.
    """
    labels: dict[str, str] = {}
    issues = {"unmatched": 0, "duplicates": 0, "missing": 0}
    errors: list[str] = []
    pending, answered, attempt, recovered = batch, False, 0, 0
    while True:
        label = f"{where}, retry {attempt}" if attempt else where
        prompt = classifier.build_classification_prompt(cfg.instruction or "", pending)
        response = llm_query_fn(prompt, classifier.CLASSIFICATION_SCHEMA, temperature=cfg.temperature, max_tokens=cfg.max_tokens)
        if getattr(response, "error", None):
            errors.append(f"LLM error in {label}: {response.error}")
            break
        try:
            found, answer_issues = classifier.parse_labels(response.content, pending)
        except ValueError as e:  # also invalid JSON
            errors.append(f"Unreadable answer in {label}: {e}")
            break
        answered = True
        labels.update(found)
        recovered += len(found) if attempt else 0
        issues["unmatched"] += len(answer_issues["unmatched"])
        issues["duplicates"] += len(answer_issues["duplicates"])
        pending = [c for c in pending if c.key not in found]
        if not pending or attempt >= missing_retries:
            break
        attempt += 1
    if answered:
        issues["missing"] = len(pending)
    return {"labels": labels, "issues": issues, "errors": errors, "retry_calls": attempt, "recovered": recovered}


def _extract_business_concepts(
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
    llm_query_fn: Callable,
) -> dict[str, Any]:
    """BusinessConcept step: structure decides the candidates, the LLM classifies them.

    The NLP tool finds candidate terms in the documentation inputs (English, German, French) with
    an English form. Candidates are merged per English identity, supported by type definition and
    directory names, selected by evidence and classified in stable-hash batches against a closed label set.
    Names, identities and document references come from the candidates, never from the LLM.
    """
    params = json.loads(cfg.params) if cfg.params else {}
    missing = [name for name in _CONCEPT_PARAMS if name not in params]
    if missing:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"BusinessConcept params missing: {', '.join(missing)}"]}
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None
    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": ["No input sources for BusinessConcept"]}

    files = [f for f in extraction.filter_files_by_input_sources(classified_files, input_sources) if not _is_unreadable(f)]
    documents, errors = _read_documents(repo_path, files, repo.name)
    if not documents:
        return {"nodes_created": 0, "edges_created": 0, "errors": errors, "warnings": [f"No documents for BusinessConcept in {repo.name}"]}

    tool = NlpTool()
    tool.ensure_models()
    found = tool.extract(documents, params["nlp"], sorted(UNCOUNTABLE_WORDS))

    candidates = concept_candidates.merge_candidates(found["candidates"], repo.name)
    candidates = concept_candidates.add_support(candidates, _code_names(graph_manager, repo.name))
    selected, selection = concept_candidates.select_candidates(
        candidates, int(params["evidence_min_count"]), float(params["evidence_share"]), int(params["max_candidates"]), float(params["support_factor"])
    )
    selected, phrases = concept_candidates.without_phrases(selected, frozenset(params["stop_words"]))

    labelled: list[tuple[concept_candidates.ConceptCandidate, str]] = []
    issues = {"unmatched": 0, "duplicates": 0, "missing": 0}
    retries = {"calls": 0, "recovered": 0}
    decisions: dict[str, str | None] = dict.fromkeys(sorted(c.key for c in selected))  # None: no label (skipped, failed batch)
    batches = concept_candidates.classification_batches(selected, cfg.batch_size)
    for number, batch in enumerate(batches, 1):
        result = _classify_batch(cfg, concept_candidates, batch, f"batch {number}", int(params["missing_retries"]), llm_query_fn)
        errors.extend(result["errors"])
        labelled.extend((c, result["labels"][c.key]) for c in batch if c.key in result["labels"])
        decisions.update(result["labels"])
        for kind, count in result["issues"].items():
            issues[kind] += count
        retries["calls"] += result["retry_calls"]
        retries["recovered"] += result["recovered"]

    nodes, edges = concept_candidates.concept_nodes_and_edges(labelled, repo.name, float(params["confidence"]))
    for node_data in nodes:
        _add_concept_node(graph_manager, _create_node_from_data("BusinessConcept", node_data, repo.name, "llm"), node_data["node_id"])
    edge_ids: list[str] = []
    for edge in edges:
        if graph_manager.node_exists(edge["from_node_id"]):
            graph_manager.add_edge(src_id=edge["from_node_id"], dst_id=edge["to_node_id"], relationship=edge["relationship_type"], properties=edge["properties"])
            edge_ids.append(create_edge_id(edge["from_node_id"], edge["relationship_type"], edge["to_node_id"]))

    stats = {
        "selection": selection,
        "batches": len(batches),
        "labels": dict(sorted(Counter(label for _, label in labelled).items())),
        "issues": issues,
        "retries": retries,
        "phrases": phrases,
        "tool": found["tool"],
        "decisions": decisions,
    }
    return {"nodes_created": len(nodes), "edges_created": len(edge_ids), "edge_ids": edge_ids, "errors": errors, "stats": stats}


# Params the Technology step reads from its config row (every one of them changes results)
_TECHNOLOGY_PARAMS = ("confidence", "missing_retries", "platforms")


def _extract_technologies(
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
    llm_query_fn: Callable,
) -> dict[str, Any]:
    """Technology step: structure decides the candidates, the LLM classifies them.

    The input files' types imply platforms (a params table, no LLM); what the files declare (libraries,
    build plugins and profiles, compose services, base images, environment variable names) is classified in
    stable-hash batches against a closed category set. Nodes, ids and edges come from structure, never from
    generated text; a technology that exists before the step (directory classification) keeps its node.
    """
    params = json.loads(cfg.params) if cfg.params else {}
    missing = [name for name in _TECHNOLOGY_PARAMS if name not in params]
    if missing:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"Technology params missing: {', '.join(missing)}"]}
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None
    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": ["No input sources for Technology"]}

    files: list[dict[str, Any]] = []
    errors: list[str] = []
    for file_info in extraction.filter_files_by_input_sources(classified_files, input_sources):
        if _is_unreadable(file_info):
            continue
        content = read_file_with_encoding(repo_path / file_info["path"])
        if content is None:
            errors.append(f"Could not read {repo_path / file_info['path']} | repo={repo.name} | step=Technology")
            continue
        files.append({**file_info, "content": content})
    if not files:
        return {"nodes_created": 0, "edges_created": 0, "errors": errors, "warnings": [f"No input files for Technology in {repo.name}"]}

    collected = technology_candidates.collect(files, params["platforms"])
    labels: dict[str, dict[str, str]] = {}
    issues = {"unmatched": 0, "duplicates": 0, "missing": 0}
    retries = {"calls": 0, "recovered": 0}
    decisions: dict[str, dict[str, str] | None] = dict.fromkeys(sorted(collected.items))  # None: no label (skipped, failed batch)
    batches = concept_candidates.classification_batches(list(collected.items.values()), cfg.batch_size)
    for number, batch in enumerate(batches, 1):
        result = _classify_batch(cfg, technology_candidates, batch, f"batch {number}", int(params["missing_retries"]), llm_query_fn)
        errors.extend(result["errors"])
        labels.update(result["labels"])
        decisions.update(result["labels"])
        for kind, count in result["issues"].items():
            issues[kind] += count
        retries["calls"] += result["retry_calls"]
        retries["recovered"] += result["recovered"]

    rows = graph_manager.query("MATCH (t:Graph:Technology) WHERE t.repository_name = $repo_name RETURN t.id AS id, t.techName AS name", {"repo_name": repo.name})
    existing = {name_key(row["name"]): row["id"] for row in rows if row.get("name")}
    nodes, edges = technology_candidates.technology_nodes_and_edges(labels, collected, repo.name, float(params["confidence"]), existing)
    for node_data in nodes:
        graph_manager.add_node(_create_node_from_data("Technology", node_data, repo.name, node_data["method"]), node_id=node_data["node_id"])
    edge_ids: list[str] = []
    for edge in edges:
        if graph_manager.node_exists(edge["from_node_id"]):
            graph_manager.add_edge(src_id=edge["from_node_id"], dst_id=edge["to_node_id"], relationship=edge["relationship_type"], properties=edge["properties"])
            edge_ids.append(create_edge_id(edge["from_node_id"], edge["relationship_type"], edge["to_node_id"]))

    stats = {
        "items": dict(sorted(Counter(item.kind.split(",")[0] for item in collected.items.values()).items())),
        "platforms": len(collected.platforms),
        "batches": len(batches),
        "labels": dict(sorted(Counter(label["category"] for label in labels.values()).items())),
        "issues": issues,
        "retries": retries,
        "decisions": decisions,
    }
    return {"nodes_created": len(nodes), "edges_created": len(edge_ids), "edge_ids": edge_ids, "errors": errors, "stats": stats}


def _extract_file_content(
    file_path: str,
    content: str,
    repo_name: str,
    extract_fn: Callable,
    extraction_config: dict[str, Any],
    llm_query_fn: Callable,
    model: str | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """
    Extract from file content, with automatic chunking for large files.

    Args:
        file_path: Relative path to file
        content: File content
        repo_name: Repository name
        extract_fn: Extraction function to call
        extraction_config: Config with instruction/example
        llm_query_fn: LLM query function
        model: Model name for token limit lookup (optional)

    Returns:
        Tuple of (nodes, edges, errors)
    """
    # Check if chunking is needed
    if not should_chunk(content, model=model):
        # Extract from entire file
        result = extract_fn(file_path, content, repo_name, llm_query_fn, extraction_config)
        if result["success"]:
            return result["data"]["nodes"], result["data"].get("edges", []), []
        return [], [], result.get("errors", [])

    # Chunk the content and extract from each chunk
    chunks = chunk_content(content, model=model)
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    all_errors: list[str] = []

    for chunk in chunks:
        # Add chunk context to file path for LLM
        chunk_path = f"{file_path} (lines {chunk.start_line}-{chunk.end_line})"

        result = extract_fn(chunk_path, chunk.content, repo_name, llm_query_fn, extraction_config)

        if result["success"]:
            all_nodes.extend(result["data"]["nodes"])
            all_edges.extend(result["data"].get("edges", []))
        else:
            all_errors.extend(result.get("errors", []))

    # Deduplicate nodes (same node might appear in overlapping chunks)
    unique_nodes = deduplicate_nodes(all_nodes)

    return unique_nodes, all_edges, all_errors


def _get_extraction_config(node_type: str) -> tuple:
    """Get extraction function, schema, and node class for a node type."""
    configs = {
        "TypeDefinition": (
            extraction.extract_type_definitions,
            extraction.TYPE_DEFINITION_SCHEMA,
            TypeDefinitionNode,
        ),
        "Method": (
            extraction.extract_methods,
            extraction.METHOD_SCHEMA,
            MethodNode,
        ),
        "ExternalDependency": (
            extraction.extract_external_dependencies,
            extraction.EXTERNAL_DEPENDENCY_SCHEMA,
            ExternalDependencyNode,
        ),
        "Test": (
            extraction.extract_tests,
            extraction.TEST_SCHEMA,
            TestNode,
        ),
    }
    return configs.get(node_type, (None, None, None))


def _build_llm_prompt(node_type: str, content: str, instruction: str | None, example: str | None) -> str:
    """Build LLM prompt for extraction."""
    prompt = f"Extract {node_type} information from the following code/content:\n\n"
    prompt += f"```\n{content}\n```\n\n"

    if instruction:
        prompt += f"Instructions: {instruction}\n\n"

    if example:
        prompt += f"Example output format:\n{example}\n\n"

    return prompt


def _add_concept_node(graph_manager: GraphManager, node: BusinessConceptNode, node_id: str | None) -> None:
    """Persist a BusinessConcept merged with the occurrence already stored under its id.

    Several files (and directory classification) can yield the same concept with
    different types; merging keeps all of them, so the stored node does not
    depend on the order in which files are processed.
    """
    node_id = node_id or node.generate_id()  # same fallback as GraphManager.add_node
    existing = graph_manager.get_node(node_id)
    merged = extraction.merge_concept_properties(existing["properties"] if existing else None, node.to_dict())
    node.name = merged["conceptName"]
    node.concept_type = merged["conceptType"]
    node.concept_types = merged["conceptTypes"]
    node.source_terms = merged["sourceTerms"]
    node.description = merged["description"]
    node.origin_source = merged["originSource"]
    node.confidence = merged["confidence"]
    node.extraction_method = merged["extractionMethod"]
    graph_manager.add_node(node, node_id=node_id)


def _create_node_from_data(node_type: str, node_data: dict, repo_name: str, extraction_method: str = "llm") -> Any:
    """Create a node model instance from extracted data.

    Args:
        node_type: Type of node to create
        node_data: Extracted data for the node
        repo_name: Repository name
        extraction_method: How the node was extracted ('structural', 'ast', or 'llm')
    """
    props = node_data.get("properties", node_data)

    if node_type == "BusinessConcept":
        return BusinessConceptNode(
            name=props.get("conceptName", props.get("name", "")),
            concept_type=props.get("conceptType", props.get("concept_type", props.get("type", "other"))),
            description=props.get("description", ""),
            origin_source=props.get("originSource", props.get("origin_source", props.get("source_file", props.get("file_path", "")))),
            repository_name=repo_name,
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
            concept_types=props.get("conceptTypes"),
            source_terms=props.get("sourceTerms"),
        )
    elif node_type == "TypeDefinition":
        return TypeDefinitionNode(
            name=props.get("typeName", props.get("name", "")),
            type_category=props.get("category", props.get("type_category", props.get("definition_type", "class"))),
            file_path=props.get("filePath", props.get("file_path", props.get("source_file", ""))),
            repository_name=repo_name,
            description=props.get("description"),
            interface_type=props.get("interfaceType", props.get("interface_type")),
            start_line=props.get("startLine", props.get("start_line", 0)),
            end_line=props.get("endLine", props.get("end_line", 0)),
            code_snippet=props.get("codeSnippet", props.get("code_snippet")),
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
            decorators=list(props.get("decorators") or []),
        )
    elif node_type == "Method":
        return MethodNode(
            name=props.get("methodName", props.get("name", "")),
            return_type=props.get("returnType", props.get("return_type", "void")),
            visibility=props.get("visibility", "public"),
            file_path=props.get("filePath", props.get("file_path", props.get("source_file", ""))),
            type_name=props.get("typeName", props.get("type_name", props.get("class_name", ""))),
            repository_name=repo_name,
            description=props.get("description"),
            parameters=props.get("parameters"),
            is_static=props.get("isStatic", props.get("is_static", False)),
            is_async=props.get("isAsync", props.get("is_async", False)),
            start_line=props.get("startLine", props.get("start_line", 0)),
            end_line=props.get("endLine", props.get("end_line", 0)),
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
            decorators=list(props.get("decorators") or []),
        )
    elif node_type == "Technology":
        return TechnologyNode(
            name=props.get("techName", props.get("name", "")),
            tech_category=props.get("techCategory", props.get("tech_category", props.get("category", "service"))),
            repository_name=repo_name,
            description=props.get("description"),
            version=props.get("version"),
            origin_source=props.get("originSource", props.get("origin_source", props.get("source_file"))),
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
        )
    elif node_type == "ExternalDependency":
        return ExternalDependencyNode(
            name=props.get("dependencyName", props.get("name", "")),
            dependency_category=props.get("dependencyCategory", props.get("dependency_category", props.get("category", "library"))),
            repository_name=repo_name,
            version=props.get("version"),
            ecosystem=props.get("ecosystem"),
            description=props.get("description"),
            origin_source=props.get("origin_source", props.get("source_file")),
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
        )
    elif node_type == "Test":
        return TestNode(
            name=props.get("name", ""),
            test_type=props.get("test_type", "unit"),
            file_path=props.get("file_path", props.get("source_file", "")),
            repository_name=repo_name,
            description=props.get("description"),
            tested_element=props.get("tested_element"),
            framework=props.get("framework"),
            start_line=props.get("start_line", 0),
            end_line=props.get("end_line", 0),
            confidence=props.get("confidence", 0.8),
            extraction_method=extraction_method,
        )

    return None


def run_extraction_iter(
    engine: Any,
    graph_manager: GraphManager,
    llm_query_fn: Callable[[str, dict], Any] | None = None,
    repo_name: str | None = None,
    enabled_only: bool = True,
    verbose: bool = False,
) -> Iterator[ProgressUpdate]:
    """
    Run extraction pipeline as a generator, yielding progress updates.

    This is the generator version of run_extraction() designed for use with
    Marimo's mo.status.progress_bar iterator pattern.

    Args:
        engine: DuckDB connection for config
        graph_manager: Connected GraphManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        repo_name: Specific repo to extract, or None for all repos
        enabled_only: Only run enabled extraction steps
        verbose: Print progress to stdout

    Yields:
        ProgressUpdate objects for each step in the pipeline

    Example:
        for update in mo.status.progress_bar(
            run_extraction_iter(engine, graph_manager),
            title="Extraction"
        ):
            pass  # Marimo renders between yields
    """
    stats = {
        "repos_processed": 0,
        "nodes_created": 0,
        "edges_created": 0,
        "steps_completed": 0,
        "steps_skipped": 0,
    }
    errors: list[str] = []

    # Get repositories
    repo_mgr = RepoManager()
    repos = repo_mgr.list_repositories(detailed=True)

    if repo_name:
        repos = [r for r in repos if hasattr(r, "name") and r.name == repo_name]

    if not repos:
        yield ProgressUpdate(
            phase="extraction",
            status="error",
            message="No repositories found",
            stats=stats,
        )
        return

    # Get extraction configs
    configs = config.get_extraction_configs(engine, enabled_only=enabled_only)

    if not configs:
        yield ProgressUpdate(
            phase="extraction",
            status="error",
            message="No extraction configs enabled",
            stats=stats,
        )
        return

    # Get file type registry for classification
    file_types = config.get_file_types(engine)
    registry_list = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in file_types]

    total_steps = len(configs) * len(repos)
    current_step = 0

    # Process each repository (no phase start yield - let progress bar show from first step)
    for repo in repos:
        if not hasattr(repo, "name") or not hasattr(repo, "path"):
            continue

        if verbose:
            print(f"\nProcessing repository: {repo.name}")

        repo_path = Path(str(repo.path))
        stats["repos_processed"] += 1

        # Get all files for classification (outside excluded dependency directories)
        file_paths = list_repo_files(repo_path, config.get_excluded_directories(engine))

        # Classify files
        classification_result = classification.classify_files(file_paths, registry_list)
        classified_files = classification_result["classified"]
        undefined_files = classification_result["undefined"]

        # Process each extraction step
        for cfg in configs:
            node_type = cfg.node_type
            current_step += 1

            if verbose:
                print(f"  Extracting: {node_type}")

            try:
                result = _run_extraction_step(
                    cfg=cfg,
                    repo=repo,
                    repo_path=repo_path,
                    classified_files=classified_files,
                    undefined_files=undefined_files,
                    graph_manager=graph_manager,
                    llm_query_fn=llm_query_fn,
                    engine=engine,
                )

                nodes_created = result.get("nodes_created", 0)
                edges_created = result.get("edges_created", 0)
                stats["nodes_created"] += nodes_created
                stats["edges_created"] += edges_created
                stats["steps_completed"] += 1

                # Yield step complete
                yield ProgressUpdate(
                    phase="extraction",
                    step=node_type,
                    status="complete",
                    current=current_step,
                    total=total_steps,
                    message=f"{nodes_created} nodes, {edges_created} edges",
                    stats={"nodes_created": nodes_created, "edges_created": edges_created},
                )

                for err in result.get("errors", []):
                    if "LLM required" not in err and "No input sources" not in err:
                        errors.append(err)

            except Exception as e:
                error_msg = f"Error in {node_type}: {e!s}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1

                # Yield step error
                yield ProgressUpdate(
                    phase="extraction",
                    step=node_type,
                    status="error",
                    current=current_step,
                    total=total_steps,
                    message=error_msg,
                )

    # Yield final completion
    final_message = f"{stats['nodes_created']} nodes, {stats['edges_created']} edges from {stats['repos_processed']} repo(s)"
    if errors:
        final_message += f" ({len(errors)} errors)"

    yield ProgressUpdate(
        phase="extraction",
        step="",
        status="complete",
        current=total_steps,
        total=total_steps,
        message=final_message,
        stats={
            "success": len(errors) == 0,
            "stats": stats,
            "errors": errors,
        },
    )
