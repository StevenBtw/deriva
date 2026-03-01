"""
Extraction service for Deriva.

Orchestrates the extraction pipeline by:
1. Loading extraction configs from DuckDB
2. Getting files from repositories
3. Calling extraction module functions
4. Persisting results to Neo4j GraphManager

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

import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
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
from deriva.adapters.repository import RepoManager
from deriva.common.document_reader import read_document
from deriva.common.file_utils import read_file_with_encoding
from deriva.common.ocel import create_edge_id
from deriva.modules import extraction
from deriva.modules.extraction import classification
from deriva.modules.extraction.base import deduplicate_nodes
from deriva.modules.extraction.business_concept import (
    extract_seed_concepts_from_structure,
    get_existing_concepts_from_graph,
)
from deriva.modules.extraction.directory_classification import (
    classify_directories,
)
from deriva.services import config


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

    # Get file type registry for classification
    file_types = config.get_file_types(engine)
    registry_list = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in file_types]

    # Start progress tracking
    # If only classify: 1 step per repo; if parse: steps = configs * repos
    if run_parse:
        total_steps = len(configs) * len(repos)
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

        # Get all files for classification
        file_paths = []
        for f in repo_path.rglob("*"):
            # Exclude .git directory contents, __pycache__, and .pyc files
            # Use f.parts to check for exact directory names (avoids matching .gitignore)
            if f.is_file() and not any(x in f.parts for x in [".git", "__pycache__"]) and not str(f).endswith(".pyc"):
                # Normalize to forward slashes for consistent path handling
                file_paths.append(str(f.relative_to(repo_path)).replace("\\", "/"))

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
                stats["nodes_created"] += nodes_created
                stats["edges_created"] += edges_created
                stats["steps_completed"] += 1

                # Complete step logging
                if step_ctx:
                    step_ctx.items_created = nodes_created + edges_created
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

    # Complete progress tracking
    if progress:
        msg = f"Extraction complete: {stats['nodes_created']} nodes, {stats['edges_created']} edges"
        progress.complete_phase(msg)

    return {
        "success": len(errors) == 0,
        "stats": stats,
        "errors": errors,
        "warnings": warnings,
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
        result = _extract_directories(repo, repo_path, graph_manager)
    elif node_type == "File":
        result = _extract_files(repo, repo_path, classified_files, undefined_files, graph_manager)
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
    elif node_type == "Technology" and cfg.extraction_method == "structural":
        # Structural Technology extraction - derives from ExternalDependency nodes
        result = _extract_technology_structural(
            repo=repo,
            repo_path=repo_path,
            classified_files=classified_files,
            graph_manager=graph_manager,
        )
    elif node_type in ["BusinessConcept", "TypeDefinition", "Method", "Technology", "ExternalDependency", "Test"]:
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


def _extract_directories(repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """Extract directory nodes."""
    result = extraction.extract_directories(str(repo_path), repo.name)
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
) -> dict[str, Any]:
    """Extract file nodes.

    Args:
        repo: Repository info object
        repo_path: Path to the repository
        classified_files: List of classified file dicts with file_type/subtype
        undefined_files: List of undefined file dicts (files with unknown extensions)
        graph_manager: GraphManager for persistence
    """
    # Use the module to scan all files from repo path
    result = extraction.extract_files(str(repo_path), repo.name)
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


def _extract_technology_structural(
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract Technology nodes structurally from config files.

    Parses docker-compose.yml, Dockerfile, and .env files to extract
    infrastructure technologies. Uses existing Technology nodes from
    DirectoryClassification to avoid duplicates.

    Args:
        repo: Repository object
        repo_path: Path to repository root
        classified_files: List of classified files
        graph_manager: Connected GraphManager

    Returns:
        Dict with nodes_created, edges_created, errors
    """
    from deriva.modules.extraction.technology import extract_technologies_structural

    # 1. Query existing Technology nodes from graph (from DirectoryClassification)
    existing_technologies: list[dict[str, Any]] = []
    try:
        tech_query = """
        MATCH (t:Technology)
        WHERE t.repository_name = $repo_name OR t.originSource CONTAINS $repo_name
        RETURN t.id as id, t.techName as name, t.techCategory as category
        """
        results = graph_manager.query(tech_query, {"repo_name": repo.name})
        for r in results:
            existing_technologies.append({
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "category": r.get("category", ""),
            })
        logger.debug(f"Found {len(existing_technologies)} existing Technology nodes")
    except Exception as e:
        logger.debug(f"Could not query existing Technology nodes: {e}")

    # 2. Get infrastructure config files (docker-compose, Dockerfile, .env)
    infra_files: list[dict[str, str]] = []
    infra_file_patterns = {
        "dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "compose.yml", "compose.yaml", ".env", ".env.example",
        ".env.local", ".env.development"
    }

    for file_info in classified_files:
        file_path = file_info.get("path", "")
        file_name = Path(file_path).name.lower()

        # Check if it's an infrastructure file
        is_infra = (
            file_name in infra_file_patterns
            or file_name.startswith("dockerfile.")
            or "docker-compose" in file_name
        )

        if is_infra:
            try:
                full_path = repo_path / file_path
                if full_path.exists():
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    infra_files.append({"path": file_path, "content": content})
            except Exception as e:
                logger.debug(f"Could not read {file_path}: {e}")

    logger.debug(f"Found {len(infra_files)} infrastructure files to process")

    # 3. Run structural extraction
    result = extract_technologies_structural(
        existing_technologies=existing_technologies,
        files=infra_files,
        repo_name=repo.name,
    )

    # 4. Persist new nodes
    nodes_created = 0
    for node_data in result["data"]["nodes"]:
        props = node_data["properties"]
        tech_node = TechnologyNode(
            name=props.get("techName", ""),
            tech_category=props.get("techCategory", "infrastructure"),
            repository_name=repo.name,
            description=props.get("description", ""),
            version=props.get("version"),
        )
        graph_manager.add_node(tech_node, node_id=node_data["node_id"])
        nodes_created += 1

    # 5. Persist edges
    edges_created = 0
    for edge_data in result["data"]["edges"]:
        try:
            graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=edge_data["to_node_id"],
                relationship=edge_data["relationship_type"],
                properties=edge_data.get("properties", {}),
            )
            edges_created += 1
        except Exception as e:
            logger.debug(f"Could not create edge: {e}")

    return {
        "nodes_created": nodes_created,
        "edges_created": edges_created,
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

    # Build global method lookup from Neo4j for cross-file CALLS/DECORATED_BY resolution
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
            # Both Neo4j filePath and classified_files paths include the full relative path
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

    # Build global type lookup from Neo4j for cross-file REFERENCES resolution
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
            # Both Neo4j filePath and classified_files paths include the full relative path

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
    # Include file stats for better LLM context (now that File extraction runs before this)
    # Exclude node_modules, vendor, and other dependency directories
    query = """
    MATCH (d:Directory)
    WHERE d.repository_name = $repo_name
      AND NOT d.path CONTAINS 'node_modules'
      AND NOT d.path CONTAINS 'vendor/'
      AND NOT d.path CONTAINS '.git/'
      AND NOT d.path CONTAINS '__pycache__'
      AND NOT d.path CONTAINS '.venv'
      AND NOT d.path CONTAINS 'venv/'
      AND NOT d.path CONTAINS 'site-packages'
    OPTIONAL MATCH (d)-[:CONTAINS]->(f:File)
    WITH d,
         count(f) AS file_count,
         sum(CASE WHEN f.file_type = 'source' THEN 1 ELSE 0 END) AS source_count,
         sum(CASE WHEN f.file_type = 'config' THEN 1 ELSE 0 END) AS config_count,
         sum(CASE WHEN f.file_type = 'documentation' THEN 1 ELSE 0 END) AS docs_count,
         sum(CASE WHEN f.file_type = 'test' THEN 1 ELSE 0 END) AS test_count,
         collect(DISTINCT f.subtype) AS subtypes
    RETURN d.name AS name, d.path AS path, d.id AS id,
           file_count, source_count, config_count, docs_count, test_count,
           subtypes
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

    # Build config dict from ExtractionConfig
    extraction_config = {
        "instruction": cfg.instruction or "",
        "example": cfg.example or "",
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
    """Extract LLM-based nodes (BusinessConcept, TypeDefinition, etc.)."""
    nodes_created = 0
    edges_created = 0
    errors = []

    # Parse input sources from config
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None

    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"No input sources for {node_type}"]}

    # Get files matching the input sources
    matching_files = extraction.filter_files_by_input_sources(classified_files, input_sources)

    # Filter out files from dependency directories (node_modules, vendor, etc.)
    dependency_patterns = ["node_modules", "vendor/", ".git/", "__pycache__", ".venv", "venv/", "site-packages"]
    matching_files = [f for f in matching_files if not any(pattern in f.get("path", "") for pattern in dependency_patterns)]

    # Filter out binary/image files that can't be meaningfully analyzed as text
    binary_extensions = {
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
    matching_files = [f for f in matching_files if not any(f.get("path", "").lower().endswith(ext) for ext in binary_extensions)]

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
    }

    # For BusinessConcept: get seed concepts for context-aware extraction (hybrid approach)
    # This improves consistency by guiding the LLM with existing/structural concepts
    existing_concepts: list[dict[str, str]] | None = None
    if node_type == "BusinessConcept":
        # Layer 1: Get deterministic seed concepts from code structure
        seed_concepts = extract_seed_concepts_from_structure(repo_path)

        # Layer 2: Get existing concepts from graph (if any were previously extracted)
        graph_concepts = get_existing_concepts_from_graph(graph_manager, repo.name)

        # Merge seed and graph concepts, preferring seed (deterministic) names
        seen_names = {c["conceptName"].lower() for c in seed_concepts}
        for gc in graph_concepts:
            if gc["conceptName"].lower() not in seen_names:
                seed_concepts.append(gc)
                seen_names.add(gc["conceptName"].lower())

        if seed_concepts:
            existing_concepts = seed_concepts
            logger.debug(f"Using {len(existing_concepts)} existing concepts for context-aware extraction")

    # For Technology: get ExternalDependency and existing Technology nodes as context
    # so LLM focuses on infrastructure (databases, caches, queues) and avoids duplicates
    existing_dependencies: list[dict[str, str]] | None = None
    existing_technologies: list[dict[str, str]] | None = None
    if node_type == "Technology":
        # Get ExternalDependency nodes (to avoid overlap with libraries)
        try:
            dep_query = """
            MATCH (ed:ExternalDependency)
            WHERE ed.repository_name = $repo_name
            RETURN ed.dependencyName AS name, ed.ecosystem AS ecosystem
            ORDER BY ed.confidence DESC
            LIMIT 50
            """
            deps = graph_manager.query(dep_query, {"repo_name": repo.name})
            if deps:
                existing_dependencies = [{"name": d["name"], "ecosystem": d.get("ecosystem", "unknown")} for d in deps]
                logger.debug(f"Using {len(existing_dependencies)} ExternalDependency nodes for Technology context")
        except Exception as e:
            logger.debug(f"Could not query ExternalDependency nodes for Technology context: {e}")

        # Get existing Technology nodes (to avoid duplicates)
        try:
            tech_query = """
            MATCH (t:Technology)
            WHERE t.repository_name = $repo_name
            RETURN t.techName AS name, t.techCategory AS category
            ORDER BY t.confidence DESC
            LIMIT 30
            """
            techs = graph_manager.query(tech_query, {"repo_name": repo.name})
            if techs:
                existing_technologies = [{"name": t["name"], "category": t.get("category", "")} for t in techs]
                logger.debug(f"Using {len(existing_technologies)} existing Technology nodes")
        except Exception as e:
            logger.debug(f"Could not query existing Technology nodes: {e}")

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

    # Check for batched extraction (BusinessConcept with batch_size > 1)
    batch_size = getattr(cfg, "batch_size", 1) or 1
    use_batching = node_type == "BusinessConcept" and batch_size > 1

    if use_batching:
        # Batched extraction: read all files first, then process in batches
        logger.info(f"Using batched extraction for {node_type} with batch_size={batch_size}")

        # Read all file contents
        files_with_content: list[dict[str, str]] = []
        for file_info in matching_files:
            file_path = repo_path / file_info["path"]
            try:
                if file_path.suffix.lower() in (".docx", ".pdf"):
                    content = read_document(file_path)
                else:
                    content = read_file_with_encoding(file_path)
                if content is not None:
                    files_with_content.append({"path": file_info["path"], "content": content})
                else:
                    errors.append(f"Could not read {file_path} | repo={repo.name} | step={node_type}")
            except Exception as e:
                errors.append(f"Could not read {file_path} | repo={repo.name} | step={node_type} | exception={type(e).__name__}: {e}")

        # Process in batches
        for batch_start in range(0, len(files_with_content), batch_size):
            batch_files = files_with_content[batch_start : batch_start + batch_size]

            if len(batch_files) == 1:
                # Single file - use regular extraction
                result = extract_fn(
                    batch_files[0]["path"],
                    batch_files[0]["content"],
                    repo.name,
                    step_llm_query_fn,
                    extraction_config,
                    existing_concepts=existing_concepts,
                )
            else:
                # Multiple files - use multi-file extraction
                result = extraction.extract_business_concepts_multi(
                    batch_files,
                    repo.name,
                    step_llm_query_fn,
                    extraction_config,
                    existing_concepts=existing_concepts,
                )

            if result.get("errors"):
                errors.extend(result["errors"])

            batch_nodes = result.get("data", {}).get("nodes", [])
            batch_edges = result.get("data", {}).get("edges", [])

            # Normalize and persist nodes
            batch_nodes = extraction.normalize_nodes(batch_nodes, node_type, repo.name)
            for node_data in batch_nodes:
                node = _create_node_from_data(node_type, node_data, repo.name, "llm")
                if node:
                    node_id = node_data.get("node_id")
                    graph_manager.add_node(node, node_id=node_id)
                    nodes_created += 1

            # Persist edges
            for edge_data in batch_edges:
                src_id = edge_data.get("from_node_id", edge_data.get("from_id"))
                dst_id = edge_data.get("to_node_id", edge_data.get("to_id"))
                relationship = edge_data.get("relationship_type", edge_data.get("relationship"))

                if not graph_manager.node_exists(dst_id):
                    logger.debug(f"Skipping edge to non-existent node: {dst_id}")
                    continue

                try:
                    graph_manager.add_edge(src_id=src_id, dst_id=dst_id, relationship=relationship)
                    edges_created += 1
                except RuntimeError as e:
                    errors.append(f"Error creating edge {relationship}: {e}")

        return {
            "nodes_created": nodes_created,
            "edges_created": edges_created,
            "errors": errors,
        }

    # Process each matching file (non-batched path)
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
                existing_concepts=existing_concepts,
                existing_dependencies=existing_dependencies,
                existing_technologies=existing_technologies,
            )
            extraction_method = "llm"

        errors.extend(file_errors)

        # Normalize node names for consistency
        if node_type in ["ExternalDependency", "BusinessConcept", "Technology"]:
            file_nodes = extraction.normalize_nodes(file_nodes, node_type, repo.name)

        # Persist extracted nodes
        for node_data in file_nodes:
            node = _create_node_from_data(node_type, node_data, repo.name, extraction_method)
            if node:
                node_id = node_data.get("node_id")
                graph_manager.add_node(node, node_id=node_id)
                nodes_created += 1

        # Persist extracted edges
        for edge_data in file_edges:
            # Note: extraction modules use from_node_id/to_node_id/relationship_type
            src_id = edge_data.get("from_node_id", edge_data.get("from_id"))
            dst_id = edge_data.get("to_node_id", edge_data.get("to_id"))
            relationship = edge_data.get("relationship_type", edge_data.get("relationship"))

            # For INHERITS/CALLS edges, create placeholder node if target doesn't exist
            # These are semantic edges to types that may be external or in other files
            if relationship in ("INHERITS", "CALLS") and not graph_manager.node_exists(dst_id):
                # Create a placeholder TypeDefinition node for the referenced type
                edge_props = edge_data.get("properties", {})
                type_name = edge_props.get("base_name") or edge_props.get("type_annotation") or dst_id.split("_")[-1]
                placeholder_node = TypeDefinitionNode(
                    name=type_name,
                    type_category="external_reference",
                    file_path="external",  # Placeholder for external/unresolved types
                    repository_name=repo.name,
                    description=f"External or unresolved type reference: {type_name}",
                    confidence=0.5,
                    extraction_method="structural",
                )
                graph_manager.add_node(placeholder_node, node_id=dst_id)
                logger.debug(f"Created placeholder node for {relationship} target: {dst_id}")
            elif not graph_manager.node_exists(dst_id):
                # Skip edges where target node doesn't exist (may have been filtered/failed)
                logger.debug(f"Skipping edge to non-existent node: {dst_id}")
                continue

            try:
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
        "errors": errors,
    }


def _extract_file_content(
    file_path: str,
    content: str,
    repo_name: str,
    extract_fn: Callable,
    extraction_config: dict[str, Any],
    llm_query_fn: Callable,
    model: str | None = None,
    existing_concepts: list[dict[str, str]] | None = None,
    existing_dependencies: list[dict[str, str]] | None = None,
    existing_technologies: list[dict[str, str]] | None = None,
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
        existing_concepts: Optional list of existing concepts for context-aware extraction
        existing_dependencies: Optional list of ExternalDependency nodes for Technology context
        existing_technologies: Optional list of existing Technology nodes for deduplication

    Returns:
        Tuple of (nodes, edges, errors)
    """
    # Build optional kwargs for extraction function
    extra_kwargs: dict[str, Any] = {}
    if existing_concepts is not None:
        extra_kwargs["existing_concepts"] = existing_concepts
    if existing_dependencies is not None:
        extra_kwargs["existing_dependencies"] = existing_dependencies
    if existing_technologies is not None:
        extra_kwargs["existing_technologies"] = existing_technologies

    # Check if chunking is needed
    if not should_chunk(content, model=model):
        # Extract from entire file
        if extra_kwargs:
            result = extract_fn(
                file_path,
                content,
                repo_name,
                llm_query_fn,
                extraction_config,
                **extra_kwargs,
            )
        else:
            result = extract_fn(
                file_path,
                content,
                repo_name,
                llm_query_fn,
                extraction_config,
            )
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

        if extra_kwargs:
            result = extract_fn(
                chunk_path,
                chunk.content,
                repo_name,
                llm_query_fn,
                extraction_config,
                **extra_kwargs,
            )
        else:
            result = extract_fn(
                chunk_path,
                chunk.content,
                repo_name,
                llm_query_fn,
                extraction_config,
            )

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
        "BusinessConcept": (
            extraction.extract_business_concepts,
            extraction.BUSINESS_CONCEPT_SCHEMA,
            BusinessConceptNode,
        ),
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
        "Technology": (
            extraction.extract_technologies,
            extraction.TECHNOLOGY_SCHEMA,
            TechnologyNode,
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

        # Get all files for classification
        file_paths = []
        for f in repo_path.rglob("*"):
            if f.is_file() and not any(x in f.parts for x in [".git", "__pycache__"]) and not str(f).endswith(".pyc"):
                file_paths.append(str(f.relative_to(repo_path)).replace("\\", "/"))

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
