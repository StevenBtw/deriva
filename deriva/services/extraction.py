"""
Extraction service for Deriva.

Orchestrates the extraction pipeline by:
1. Loading extraction configs from DuckDB
2. Getting files from repositories
3. Calling extraction module functions
4. Persisting results to GraphManager

Used by both the studio (web UI) and the CLI (headless).

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

import fnmatch
import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from deriva.adapters.graph import STORAGE_FORMAT, GraphManager
from deriva.common.chunking import chunk_content, should_chunk
from deriva.common.types import ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph.models import (
    INCLUDES,
    BuildModuleNode,
    BusinessConceptNode,
    DataDomainNode,
    DataEntityNode,
    DeployableUnitNode,
    DeploymentNode,
    DirectoryNode,
    EnvironmentNode,
    ExternalDependencyNode,
    FileNode,
    LifecycleEventNode,
    LifecycleNode,
    MethodNode,
    RepositoryNode,
    RoleNode,
    SoftwareNode,
    TechnologyNode,
    TestNode,
    TypeDefinitionNode,
    repo_relative,
)
from deriva.adapters.nlp import NlpTool
from deriva.adapters.repository import RepoManager
from deriva.adapters.treesitter import cdk
from deriva.common.cache_utils import hash_inputs
from deriva.common.document_reader import read_document
from deriva.common.file_utils import read_file_with_encoding
from deriva.common.naming import UNCOUNTABLE_WORDS, name_key
from deriva.common.ocel import create_edge_id
from deriva.modules import extraction
from deriva.modules.extraction import (
    build_modules,
    classification,
    concept_candidates,
    cooperation,
    data_domains,
    data_entities,
    deployable_units,
    deployments,
    lifecycles,
    roles,
    step_tags,
    technologies,
    technology_candidates,
)
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

    return hash_inputs("extraction", ext_versions, commit, config.get_excluded_directories(engine), STORAGE_FORMAT)


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
                with graph_manager.recording() as written:
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
                if result.get("stats"):
                    step_stats.setdefault(str(repo.name), {})[node_type] = result["stats"]
                stats["nodes_created"] += nodes_created
                stats["edges_created"] += edges_created
                stats["steps_completed"] += 1

                # Complete step logging
                if step_ctx:
                    step_ctx.items_created = nodes_created + edges_created
                    step_ctx.stats = result.get("stats")
                    # Every node and edge the step wrote, once each, for OCEL logging
                    for node_id in dict.fromkeys(written.nodes):
                        step_ctx.add_object(node_id)
                    for edge_id in dict.fromkeys(written.edges):
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


def tag_steps(graph_manager: GraphManager, repo_name: str) -> dict[str, Any]:
    """Tag the nodes and edges of a repository's graph that no step has tagged yet, by rule (no LLM).

    Each node gets ``extractSteps`` (and ``extractStep``) from its kind (``step_tags.node_step``), each
    edge ``extractStep`` from its type and the kinds of its ends (``step_tags.edge_step``). What no
    rule covers stays untagged, so no sweep ever removes it; the report counts it per kind.
    """
    in_repo = "(n.repository_name = $repo OR n.id CONTAINS $marker)"
    params = {"repo": repo_name, "marker": f"::{repo_name}::"}
    report: dict[str, Any] = {"nodes": Counter(), "edges": Counter(), "untagged_nodes": Counter(), "untagged_edges": Counter()}
    updates: dict[str, dict[str, Any]] = {}
    for row in graph_manager.query(
        f"MATCH (n) WHERE n.id IS NOT NULL AND n.extractSteps IS NULL AND {in_repo} RETURN n.id AS id, labels(n) AS labels, properties(n) AS props", params
    ):
        labels = [str(label) for label in row.get("labels") or []]
        step = step_tags.node_step(labels, row.get("props") or {})
        if step is None:
            report["untagged_nodes"][next((label for label in labels if label != "Graph"), "?")] += 1
            continue
        updates[str(row["id"])] = {"extractSteps": [step], "extractStep": step}
        report["nodes"][step] += 1
    if updates:
        graph_manager.batch_update_properties(updates)
    edges = graph_manager.query(
        f"MATCH (n)-[r]->(b) WHERE r.extractStep IS NULL AND n.id IS NOT NULL AND b.id IS NOT NULL AND {in_repo} "
        "RETURN n.id AS a, type(r) AS t, b.id AS b, labels(n) AS la, labels(b) AS lb, r.module AS module",
        params,
    )
    for row in edges:
        kind = lambda labels: next((str(label) for label in labels or [] if label != "Graph"), "?")  # noqa: E731 - a one-line helper
        edge_type = str(row["t"]).removeprefix("Graph:")
        step = step_tags.edge_step(edge_type, kind(row["la"]), kind(row["lb"]), {"module": row.get("module")})
        if step is None:
            report["untagged_edges"][f"{edge_type} {kind(row['la'])}->{kind(row['lb'])}"] += 1
            continue
        graph_manager.set_edge_property(str(row["a"]), edge_type, str(row["b"]), "extractStep", step)
        report["edges"][step] += 1
    return {key: dict(value) for key, value in report.items()}


def _step_version(engine: Any, node_type: str) -> int | None:
    """The active config version of an extraction step, for the extractVersion tag (None when unknown)."""
    try:
        row = engine.execute("SELECT version FROM extraction_config WHERE node_type = ? AND is_active", [node_type]).fetchone()
        return int(row[0]) if row and isinstance(row[0], int) else None
    except Exception:
        return None


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
    """Run a single extraction step, then sweep what it wrote before and no longer produces.

    The step's writes carry its name (``extractStep``); a node keeps the list of steps that produce it
    (``extractSteps``). After a run without errors, the nodes and edges this step wrote before and did
    not write again are removed (a node another step also produces only loses this step), so a step
    can run again on its own and the same configuration leaves the same graph. A run with errors
    sweeps nothing.
    """
    if graph_manager is None:
        return _run_step_writes(cfg, repo, repo_path, classified_files, undefined_files, graph_manager, llm_query_fn, engine, model)
    step = cfg.node_type
    repo_name = str(getattr(repo, "name", "") or "")
    in_repo = "(n.repository_name = $repo OR n.id CONTAINS $marker)"
    prior_nodes = {
        str(r["id"]): [str(s) for s in r["steps"] or []]
        for r in graph_manager.query(
            f"MATCH (n) WHERE n.extractSteps IS NOT NULL AND {in_repo} RETURN n.id AS id, n.extractSteps AS steps", {"repo": repo_name, "marker": f"::{repo_name}::"}
        )
        if r.get("id")
    }
    prior_edges = {
        (str(r["a"]), str(r["t"]).removeprefix("Graph:"), str(r["b"]))
        for r in graph_manager.query(
            f"MATCH (n)-[r]->(b) WHERE r.extractStep = $step AND {in_repo} RETURN n.id AS a, type(r) AS t, b.id AS b",
            {"step": step, "repo": repo_name, "marker": f"::{repo_name}::"},
        )
    }
    with graph_manager.step_tags(step, _step_version(engine, step)), graph_manager.recording() as writes:
        result = _run_step_writes(cfg, repo, repo_path, classified_files, undefined_files, graph_manager, llm_query_fn, engine, model)
    if result.get("errors"):
        logger.warning("Extraction step %s had errors: nothing swept", step)
        # A rewritten node keeps the other steps that own it (writing a node sets only this step), so a later sweep
        # of this step cannot remove a node another step still produces
        restore = {node: sorted({*prior_nodes[node], step}) for node in set(writes.nodes) if node in prior_nodes and set(prior_nodes[node]) - {step}}
        if restore:
            graph_manager.batch_update_properties({node: {"extractSteps": steps} for node, steps in restore.items()})
        return {**result, "swept": {"nodes": 0, "edges": 0, "skipped": "errors"}}
    produced_nodes = set(writes.nodes)
    produced_edges = {(a, t.removeprefix("Graph:"), b) for a, t, b in writes.edge_ends}
    # A node of this step that it only links to again (a placeholder or stub that exists, so it is not rewritten) is still in use
    produced_nodes |= {n for a, _, b in produced_edges for n in (a, b) if step in prior_nodes.get(n, [])}
    plan = step_tags.plan_sweep(step, prior_nodes, produced_nodes, prior_edges, produced_edges)
    if plan.set_steps:
        graph_manager.batch_update_properties({node: {"extractSteps": steps} for node, steps in plan.set_steps.items()})
    for node in plan.delete_nodes:
        graph_manager.delete_node(node)
    for a, t, b in plan.delete_edges:
        graph_manager.delete_edge(a, t, b)
    return {**result, "swept": {"nodes": len(plan.delete_nodes), "edges": len(plan.delete_edges)}}


def _run_step_writes(
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
    """Run a single extraction step based on node type (its writes; the sweep is _run_extraction_step's)."""
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
        result = _extract_calls(cfg, repo, repo_path, classified_files, graph_manager)
    elif node_type == "Decorators":
        # Tree-sitter based decorator edge extraction (deterministic, no LLM)
        result = _extract_decorators(repo, repo_path, classified_files, graph_manager)
    elif node_type == "References":
        # Tree-sitter based type reference edge extraction (deterministic, no LLM)
        result = _extract_references(repo, repo_path, classified_files, graph_manager)
    elif node_type == "Edges":
        # Unified edge extraction: all edge types in one efficient pass (4x faster)
        result = _extract_edges(repo, repo_path, classified_files, graph_manager)
    elif node_type == "DataEntity":
        # Persistent concepts from structure (roots, ORM entities, shared records, tables); no LLM
        result = _extract_data_entities(cfg, repo, repo_path, graph_manager)
    elif node_type == "DeployableUnit":
        # Deployable units from structure (containers, manifest entry points, mainframe applications); no LLM
        result = _extract_deployable_units(cfg, repo, repo_path, graph_manager)
    elif node_type == "BuildModule":
        # Build modules and parent systems from the manifests; which unit builds which module; no LLM
        result = _extract_build_modules(cfg, repo, repo_path, graph_manager)
    elif node_type == "BusinessLayer":
        # Processes (lifecycles), events and roles from code and documentation; no LLM
        result = _extract_business_layer(cfg, repo, repo_path, graph_manager)
    elif node_type == "DataDomain":
        # Information domains from the data entities, their relations and the units; no LLM
        result = _extract_data_domains(cfg, repo, repo_path, graph_manager, engine)
    elif node_type == "Cooperation":
        # Which deployable unit uses which, and which sends messages to which, from configuration and code; no LLM
        result = _extract_cooperation(cfg, repo, repo_path, graph_manager)
    elif node_type == "Deployment":
        # The primary environment, its deployed services and the system software from a closed list; no LLM
        result = _extract_deployments(cfg, repo, repo_path, graph_manager)
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
        # Without an LLM the parsers still run (tree-sitter, manifest files); only Test is LLM-only
        if llm_query_fn is None and node_type == "Test":
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


# Manifests the DeployableUnit step reads from the checkout
UNIT_MANIFESTS = frozenset({"pyproject.toml", "package.json", "pom.xml", "build.gradle", "build.gradle.kts"})


def _unit_rules(params: str | None) -> deployable_units.UnitRules:
    """The DeployableUnit step's rules (``params``): ``code_subtypes``, ``container_files``, ``readme_lines`` and the
    Web UI signals ``web_ui`` (``files``, ``template_dirs``, ``template_suffixes``, ``excluded_dirs``: lists of strings)."""
    settings = json.loads(params) if params else {}
    subtypes = settings.get("code_subtypes")
    if not isinstance(subtypes, list) or not subtypes or not all(isinstance(s, str) and s for s in subtypes):
        raise ValueError("DeployableUnit params need code_subtypes: the file subtypes that count as the repository's own code")
    defaults = deployable_units.UnitRules(code_subtypes=frozenset())
    containers = settings.get("container_files", list(defaults.container_files))
    lines = settings.get("readme_lines", defaults.readme_lines)
    if not isinstance(containers, list) or not all(isinstance(c, str) and c for c in containers) or not isinstance(lines, int) or isinstance(lines, bool) or lines < 0:
        raise ValueError("DeployableUnit params: container_files is a list of file name patterns, readme_lines a whole number of at least 0")
    web = settings.get("web_ui", {})
    keys = {"files": "web_files", "template_dirs": "web_template_dirs", "template_suffixes": "web_template_suffixes", "excluded_dirs": "web_excluded_dirs"}
    if not isinstance(web, dict) or set(web) - set(keys) or not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v) for v in web.values()):
        raise ValueError(f"DeployableUnit params: web_ui holds lists of strings under {sorted(keys)}")
    signals = {field: tuple(x.lower() for x in web[key]) for key, field in keys.items() if key in web}
    naming = settings.get("naming", {})
    if not isinstance(naming, dict):
        raise ValueError("DeployableUnit params: naming must be an object")
    words, cut, nouns, docs = naming.get("generic_words", []), naming.get("title_cut_words", []), naming.get("kind_nouns", {}), naming.get("max_doc_names", 3)
    if (
        not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v) for v in (words, cut))
        or not isinstance(nouns, dict)
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in nouns.items())
        or not isinstance(docs, int)
        or isinstance(docs, bool)
        or docs < 0
    ):
        raise ValueError(
            "DeployableUnit params: naming holds generic_words and title_cut_words (lists of strings), kind_nouns (unit kind -> noun) and max_doc_names (a whole number)"
        )
    return deployable_units.UnitRules(
        code_subtypes=frozenset(subtypes),
        container_files=tuple(containers),
        readme_lines=lines,
        generic_words=tuple(words),
        title_cut_words=tuple(cut),
        kind_nouns=tuple(sorted(nouns.items())),
        max_doc_names=docs,
        **signals,
    )


_ENTITY_LISTS = (
    "root_markers",
    "entity_annotations",
    "orm_bases",
    "value_markers",
    "id_markers",
    "dto_bases",
    "dto_suffixes",
    "dto_dirs",
    "config_markers",
    "config_suffixes",
    "technical_words",
    "name_suffixes",
)


def _entity_rules(params: str | None) -> data_entities.EntityRules:
    """The DataEntity step's signals (``params``): lists of names, ``min_importers``, ``record_pattern`` and
    ``table_mentions`` (link a table to the code files that name it)."""
    settings = json.loads(params) if params else {}
    unknown = set(settings) - {*_ENTITY_LISTS, "min_importers", "record_pattern", "table_mentions"}
    lists_ok = all(isinstance(settings.get(k, []), list) and all(isinstance(x, str) and x for x in settings.get(k, [])) for k in _ENTITY_LISTS)
    importers, pattern = settings.get("min_importers", 3), settings.get("record_pattern", "")
    mentions = settings.get("table_mentions", False)
    bad_numbers = not isinstance(importers, int) or isinstance(importers, bool) or importers < 0
    if unknown or not lists_ok or bad_numbers or not isinstance(pattern, str) or not isinstance(mentions, bool):
        raise ValueError(
            f"DataEntity params: lists of names under {list(_ENTITY_LISTS)}, min_importers (a whole number), record_pattern (a pattern), table_mentions (true or false)"
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"DataEntity params: record_pattern is no valid pattern: {exc}") from exc
    return data_entities.EntityRules(**{k: tuple(settings.get(k, [])) for k in _ENTITY_LISTS}, min_importers=importers, record_pattern=pattern, table_mentions=mentions)


def _entity_facts(q: Callable[..., list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, str]]:
    """The DataEntity step's inputs: the repository's types (with bases), importer counts per file, file -> unit name."""
    types = q(
        "MATCH (t:Graph:TypeDefinition) WHERE t.active = true AND t.repository_name = $repo_name "
        "RETURN t.id AS id, t.typeName AS name, t.category AS category, t.decorators AS decorators, t.filePath AS path"
    )
    bases: dict[str, list[str]] = {}
    for row in q("MATCH (a:Graph:TypeDefinition)-[:`Graph:INHERITS`]->(b) WHERE a.repository_name = $repo_name RETURN a.id AS a, b.typeName AS name, b.id AS id"):
        bases.setdefault(row["a"], []).append(row.get("name") or str(row.get("id") or "").split("::")[-1])
    facts = [
        {
            "id": t["id"],
            "name": t["name"] or "",
            "category": t["category"] or "",
            "decorators": list(t["decorators"] or []),
            "path": t["path"] or "",
            "bases": bases.get(t["id"], []),
        }
        for t in types
        if t.get("id")
    ]
    # Importers are programs: the importing file holds a program (a copybook's COPY of a record does not count)
    importers = Counter(
        r["f"]
        for r in q(
            "MATCH (a:Graph:File)-[:`Graph:IMPORTS`]->(f:Graph:File), (p:Graph:TypeDefinition) "
            "WHERE f.repository_name = $repo_name AND p.category = 'program' AND p.filePath = a.filePath "
            "RETURN DISTINCT f.filePath AS f, a.filePath AS a"
        )
        if r.get("f")
    )
    # The unit that holds a file names it; a dotted unit name is known by its last part
    owners = {
        r["p"]: str(r["n"]).split(".")[-1]
        for r in q("MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(f:Graph:File) WHERE u.repository_name = $repo_name RETURN f.filePath AS p, u.name AS n")
        if r.get("p") and r.get("n")
    }
    return facts, dict(importers), owners


def _extract_data_entities(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """Data entity nodes with INCLUDES edges to their types, from the types, their bases and their importers (no LLM)."""
    rules = _entity_rules(cfg.params)
    # Only this repository's nodes (a combined graph holds several)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    facts, importers, owners = _entity_facts(q)
    result = data_entities.detect_entities(facts, importers, owners, rules)

    # What an earlier run wrote and this one no longer produces is swept after the step (_run_extraction_step)
    nodes = edges = 0
    for entity in result.entities:
        node_id = f"entity::{repo.name}::{entity.key}"
        graph_manager.add_node(
            DataEntityNode(
                name=entity.name_candidates[0][0],
                signal=entity.signal,
                repository_name=repo.name,
                name_candidates=[n for n, _ in entity.name_candidates],
                name_sources=[s for _, s in entity.name_candidates],
                paths=entity.paths,
                type_count=len(entity.type_ids),
            ),
            node_id=node_id,
        )
        nodes += 1
        for type_id in entity.type_ids:
            graph_manager.add_edge(node_id, type_id, INCLUDES)
            edges += 1
    if rules.table_mentions:
        # A table is reached through its name in a query, not through an import: the code files that name it
        tables = {e.key: e.tables for e in result.entities if e.tables}
        own = {path for e in result.entities if e.tables for path in e.paths}
        code = q("MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name AND f.fileType = 'source' RETURN f.id AS id, f.filePath AS path")
        texts = {r["path"]: text for r in code if tables and r["path"] not in own and (text := _read_checkout(repo_path, repo.name, r["path"])) is not None}
        file_ids = {r["path"]: r["id"] for r in code}
        for key, paths in data_entities.table_mentions(tables, texts, own_files=own).items():
            for path in paths:
                graph_manager.add_edge(f"entity::{repo.name}::{key}", file_ids[path], "NAMED_IN")
                edges += 1
    excluded = [{"type": x.name, "reason": x.reason} for x in result.excluded]
    return {"nodes_created": nodes, "edges_created": edges, "errors": [], "excluded": excluded}


def _deployment_rules(params: str | None) -> tuple[deployments.DeploymentRules, tuple[technologies.Technology, ...]]:
    """The Deployment step's signals (``params``): the closed list ``technologies`` ([{name, kind, aliases}]),
    ``cloud_resources`` (resource type -> container, function or managed), ``markers`` ([{pattern, technology}]),
    ``manifest_runtimes`` (manifest file pattern -> runtime alias), ``environment_names`` (kind -> name), the
    file name patterns ``compose_files``, ``build_scripts`` and ``marker_suffixes``, ``cloud_qualifiers``
    (resource type -> {property, default}) and ``cdk_constructs`` ("module.Class" -> {type, environment, properties})."""
    settings = json.loads(params) if params else {}
    lists, maps = ("compose_files", "build_scripts", "marker_suffixes"), ("cloud_resources", "manifest_runtimes", "environment_names")
    unknown = set(settings) - {*lists, *maps, "technologies", "markers", "cloud_qualifiers", "cdk_constructs"}
    qualifiers, constructs = settings.get("cloud_qualifiers", {}), settings.get("cdk_constructs", {})
    text = lambda v: isinstance(v, str) and bool(v)  # noqa: E731 - a one-line helper
    qualifiers_ok = isinstance(qualifiers, dict) and all(isinstance(q, dict) and text(q.get("property")) and isinstance(q.get("default", ""), str) for q in qualifiers.values())
    constructs_ok = isinstance(constructs, dict) and all(
        isinstance(c, dict)
        and text(c.get("type"))
        and isinstance(c.get("environment", ""), str)
        and isinstance(c.get("properties", {}), dict)
        and all(text(v) for v in c.get("properties", {}).values())
        for c in constructs.values()
    )
    if not qualifiers_ok or not constructs_ok:
        raise ValueError("Deployment params: cloud_qualifiers as {type: {property, default}} and cdk_constructs as {construct: {type, environment, properties}}")
    lists_ok = all(isinstance(settings.get(k, []), list) and all(isinstance(x, str) and x for x in settings.get(k, [])) for k in lists)
    maps_ok = all(isinstance(settings.get(k, {}), dict) and all(isinstance(v, str) and v for v in settings.get(k, {}).values()) for k in maps)
    markers = settings.get("markers", [])
    markers_ok = isinstance(markers, list) and all(isinstance(m, dict) and isinstance(m.get("pattern"), str) and isinstance(m.get("technology"), str) for m in markers)
    if unknown or not lists_ok or not maps_ok or not markers_ok:
        raise ValueError(
            f"Deployment params: lists of strings under {list(lists)}, objects of strings under {list(maps)}, "
            "markers as [{pattern, technology}] and technologies as [{name, kind, aliases}]"
        )
    for m in markers:
        try:
            re.compile(m["pattern"])
        except re.error as exc:
            raise ValueError(f"Deployment params: marker pattern {m['pattern']!r} is no valid pattern: {exc}") from exc
    try:
        catalog = technologies.catalog_from_params(settings.get("technologies", []))
    except ValueError as exc:
        raise ValueError(f"Deployment params: {exc}") from exc
    defaults = deployments.DeploymentRules()
    rules = deployments.DeploymentRules(
        cloud_resources=tuple(sorted(settings.get("cloud_resources", {}).items())),
        cloud_qualifiers=tuple((t, q["property"], q.get("default", "")) for t, q in sorted(qualifiers.items())),
        cdk_constructs=tuple((k, c["type"], c.get("environment", ""), tuple(sorted(c.get("properties", {}).items()))) for k, c in sorted(constructs.items())),
        compose_files=tuple(settings.get("compose_files", defaults.compose_files)),
        environment_names=tuple(sorted({**dict(defaults.environment_names), **settings.get("environment_names", {})}.items())),
        build_scripts=tuple(settings.get("build_scripts", defaults.build_scripts)),
        markers=tuple((m["pattern"], m["technology"]) for m in markers),
        marker_suffixes=tuple(s.lower() for s in settings.get("marker_suffixes", [])),
        manifest_runtimes=tuple(settings.get("manifest_runtimes", {}).items()),
    )
    return rules, catalog


def _cdk_resources(paths: list[str], rules: deployments.DeploymentRules, repo: Any, repo_path: Path) -> dict[str, dict[str, Any]]:
    """The resources the repository's CDK apps declare (a folder with ``cdk.json``; its TypeScript files outside
    ``node_modules`` and ``cdk.out``), read statically with the construct table."""
    if not rules.cdk_constructs:
        return {}
    roots = sorted({p.rsplit("/", 1)[0] + "/" if "/" in p else "" for p in paths if p.rsplit("/", 1)[-1].lower() == "cdk.json"})
    if not roots:
        return {}
    skipped = ("/node_modules/", "/cdk.out/")
    sources = {
        p: text
        for p in paths
        if p.lower().endswith(".ts")
        and not p.lower().endswith(".d.ts")
        and any(p.startswith(root) for root in roots)
        and not any(s in f"/{p}" for s in skipped)
        and (text := _read_checkout(repo_path, repo.name, p)) is not None
    }
    constructs = {key: cdk.CdkConstruct(type=kind, environment=environment or None, properties=props) for key, kind, environment, props in rules.cdk_constructs}
    return cdk.cdk_resources(sources, constructs, properties=tuple(sorted({prop for _, prop, _ in rules.cloud_qualifiers})))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def _slug_ids(prefix: str, names: Iterable[str]) -> dict[str, str]:
    """Node ids by name: the slug, and for names that share one (my_api, my-api) the slug with a hash of the name."""
    by_slug: dict[str, set[str]] = {}
    for name in names:
        by_slug.setdefault(_slug(name), set()).add(name)
    return {
        name: f"{prefix}::{slug}" if len(group) == 1 else f"{prefix}::{slug}-{hashlib.sha1(name.encode()).hexdigest()[:8]}" for slug, group in by_slug.items() for name in group
    }


def _service_ids(prefix: str, services: list[tuple[str, str | None]]) -> list[str]:
    """Node ids per (name, unit) service, in order: by name (``_slug_ids``); services that share a name are told apart by
    the last part of their unit's id, or by their position when they deploy none."""
    counts = Counter(name for name, _ in services)
    keys = [name if counts[name] == 1 else f"{name} {unit.rsplit('::', 1)[-1] if unit else i}" for i, (name, unit) in enumerate(services)]
    ids = _slug_ids(prefix, keys)
    return [ids[k] for k in keys]


def _extract_deployments(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """The primary environment (RUNS its deployed services, which DEPLOY units; HOSTS the software that
    runs in it) and the system software (SERVES the units that use it), from the checkout (no LLM)."""
    rules, catalog = _deployment_rules(cfg.params)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    paths = [
        str(r["path"]).replace(chr(92), "/") for r in q("MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name RETURN f.filePath AS path") if r.get("path")
    ]
    scripts = rules.build_scripts + rules.compose_files

    def wanted(path: str) -> bool:
        name = path.rsplit("/", 1)[-1].lower()
        return (
            name.endswith((".yml", ".yaml", ".json", ".dockerfile"))
            or name == "dockerfile"
            or name.startswith("dockerfile.")
            or name in UNIT_MANIFESTS
            or (name.startswith("requirements") and name.endswith(".txt"))
            or any(fnmatch.fnmatchcase(name, p) for p in scripts)
        )

    files = {p: text for p in paths if wanted(p) and (text := _read_checkout(repo_path, repo.name, p)) is not None}
    sources = {p: text for p in paths if p.lower().endswith(rules.marker_suffixes) and rules.marker_suffixes and (text := _read_checkout(repo_path, repo.name, p)) is not None}
    units = _units_with_members(q)
    layer = deployments.technology_layer(repo.name, files, units, rules, catalog, sources, cdk=_cdk_resources(paths, rules, repo, repo_path))

    nodes = edges = 0
    env = layer.environment
    env_id = f"environment::{repo.name}::{env.kind}" if env else None
    if env and env_id:
        others = [f"{e.kind} {e.file}" for e in layer.deployments.others]
        other_services = [
            json.dumps({"name": s.name, "unit": s.unit, "environment": s.environment, "ports": s.ports}, sort_keys=True) for e in layer.deployments.others for s in e.services
        ]
        graph_manager.add_node(
            EnvironmentNode(name=env.name, kind=env.kind, repository_name=repo.name, file=env.file, others=others, other_services=other_services), node_id=env_id
        )
        nodes += 1
        deployment_ids = _service_ids(f"deployment::{repo.name}::{env.kind}", [(s.name, s.unit) for s in env.services])
        for service, deployment_id in zip(env.services, deployment_ids, strict=True):
            graph_manager.add_node(
                DeploymentNode(name=service.name, environment=env.kind, repository_name=repo.name, image=service.image or "", variables=service.environment, ports=service.ports),
                node_id=deployment_id,
            )
            graph_manager.add_edge(env_id, deployment_id, "RUNS")
            nodes, edges = nodes + 1, edges + 1
            if service.unit:
                graph_manager.add_edge(deployment_id, service.unit, "DEPLOYS")
                edges += 1
    software_ids = _slug_ids(f"software::{repo.name}", (s.name for s in layer.software))
    for software in layer.software:
        software_id = software_ids[software.name]
        graph_manager.add_node(
            SoftwareNode(
                name=software.name,
                kind=software.kind,
                listed=software.listed,
                repository_name=repo.name,
                in_environment=software.in_environment,
                evidence=software.evidence,
            ),
            node_id=software_id,
        )
        nodes += 1
        if software.in_environment and env_id:
            graph_manager.add_edge(env_id, software_id, "HOSTS")
            edges += 1
        for unit in software.serves:
            graph_manager.add_edge(software_id, unit, "SERVES")
            edges += 1
    listed = sum(1 for s in layer.software if s.listed)
    return {
        "nodes_created": nodes,
        "edges_created": edges,
        "errors": [],
        "environment": f"{env.kind} {env.file}".strip() if env else None,
        "other_environments": [f"{e.kind} {e.file}" for e in layer.deployments.others],
        "software": {"listed": listed, "fallback": len(layer.software) - listed, "unconnected": len(layer.unconnected)},
    }


def _units_with_members(q: Callable[..., list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The repository's deployable units: {"id", "path", "name", "members"}. Units that share a folder are told apart
    by their members (files, and the files of their programs and screens)."""
    members: dict[str, set[str]] = {}
    for r in q("MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(m) WHERE u.repository_name = $repo_name RETURN u.id AS u, m.filePath AS path"):
        if r.get("path"):
            members.setdefault(r["u"], set()).add(str(r["path"]).replace(chr(92), "/"))
    return [
        {"id": r["id"], "path": str(r["path"]).replace(chr(92), "/"), "name": r["name"], "members": sorted(members.get(r["id"], ()))}
        for r in q("MATCH (u:Graph:DeployableUnit) WHERE u.active = true AND u.repository_name = $repo_name RETURN u.id AS id, u.path AS path, u.name AS name")
    ]


def _cooperation_rules(params: str | None) -> cooperation.CooperationRules:
    """The Cooperation step's signals (``params``): file name patterns (``config_files``, ``gateway_files``,
    ``code_files``), ``excluded_dirs``, ``destination_key`` (a pattern for a configuration key's last segment)
    and the message ``send_markers`` / ``listen_markers`` (code fragments)."""
    settings = json.loads(params) if params else {}
    lists = ("config_files", "gateway_files", "code_files", "excluded_dirs", "send_markers", "listen_markers")
    unknown = set(settings) - {*lists, "destination_key"}
    lists_ok = all(isinstance(settings.get(k, []), list) and all(isinstance(x, str) and x for x in settings.get(k, [])) for k in lists)
    key = settings.get("destination_key", cooperation.CooperationRules.destination_key)
    if unknown or not lists_ok or not isinstance(key, str):
        raise ValueError(f"Cooperation params: lists of strings under {list(lists)}, destination_key a pattern")
    try:
        re.compile(key)
    except re.error as exc:
        raise ValueError(f"Cooperation params: destination_key is no valid pattern: {exc}") from exc
    defaults = cooperation.CooperationRules()
    return cooperation.CooperationRules(
        **{k: tuple(settings[k]) if k in settings else getattr(defaults, k) for k in lists},
        destination_key=key,
    )


def _extract_cooperation(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """CONSUMES (consumer unit -> provider unit, with channel and evidence) and SENDS_TO (sender -> listener) edges
    between deployable units, from configuration, gateway routes, service catalogs and code edges (no LLM)."""
    rules = _cooperation_rules(cfg.params)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    units = _units_with_members(q)
    services = [
        {"name": r["name"], "unit": r["unit"], "environment": dict(r["variables"] or {}), "ports": list(r["ports"] or [])}
        for r in q(
            "MATCH (d:Graph:Deployment)-[:`Graph:DEPLOYS`]->(u:Graph:DeployableUnit) WHERE d.repository_name = $repo_name "
            "RETURN d.name AS name, u.id AS unit, d.variables AS variables, d.ports AS ports"
        )
    ]
    # The other environments' services too (a cloud primary can hide the compose names and ports configuration uses)
    named = {s["name"] for s in services}
    for row in q("MATCH (e:Graph:Environment) WHERE e.repository_name = $repo_name RETURN e.otherServices AS services"):
        for raw in row.get("services") or []:
            other = json.loads(raw)
            if other.get("unit") and other.get("name") not in named:
                named.add(other["name"])
                services.append({"name": other["name"], "unit": other["unit"], "environment": dict(other.get("environment") or {}), "ports": list(other.get("ports") or [])})
    patterns = rules.config_files + rules.gateway_files + rules.code_files + ("dockerfile", "dockerfile.*", "*.dockerfile")
    paths = [norm(r["path"]) for r in q("MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name RETURN f.filePath AS path") if r.get("path")]
    files = {
        p: text
        for p in paths
        if any(fnmatch.fnmatchcase(p.rsplit("/", 1)[-1].lower(), pattern.lower()) for pattern in patterns) and (text := _read_checkout(repo_path, repo.name, p)) is not None
    }
    code_edges = [
        (norm(r["a"]), norm(r["b"]))
        for r in q("MATCH (a:Graph:File)-[:`Graph:IMPORTS`]->(b:Graph:File) WHERE a.repository_name = $repo_name RETURN a.filePath AS a, b.filePath AS b")
    ] + [
        (norm(r["a"]), norm(r["b"]))
        for r in q("MATCH (a:Graph:Method)-[:`Graph:CALLS`]->(b:Graph:Method) WHERE a.repository_name = $repo_name RETURN DISTINCT a.filePath AS a, b.filePath AS b")
        if r.get("a") and r.get("b") and r["a"] != r["b"]
    ]
    links = cooperation.detect_links(files, units, services, rules, code_edges)
    for link in links:
        graph_manager.add_edge(link.source, link.target, link.relation, properties={"channel": link.channel, "evidence": link.evidence, "detail": link.detail})
    return {"nodes_created": 0, "edges_created": len(links), "errors": [], "links": dict(Counter(link.evidence for link in links))}


def _domain_rules(params: str | None) -> data_domains.DomainRules:
    """The DataDomain step's signals (``params``): ``identity_words``, ``unit_noise``, ``data_nouns`` (lists of words)
    and ``name_template`` (with ``{name}``)."""
    settings = json.loads(params) if params else {}
    lists = ("identity_words", "unit_noise", "data_nouns")
    template = settings.get("name_template", data_domains.DomainRules.name_template)
    lists_ok = all(isinstance(settings.get(k, []), list) and all(isinstance(x, str) and x for x in settings.get(k, [])) for k in lists)
    if set(settings) - {*lists, "name_template"} or not lists_ok or not isinstance(template, str) or "{name}" not in template:
        raise ValueError(f"DataDomain params: lists of words under {list(lists)}, name_template a text with {{name}}")
    defaults = data_domains.DomainRules()
    return data_domains.DomainRules(**{k: tuple(settings[k]) if k in settings else getattr(defaults, k) for k in lists}, name_template=template)


def _extract_data_domains(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager, engine: Any) -> dict[str, Any]:
    """Information domains (DataDomain nodes with INCLUDES edges to their entities and types) from the data entities,
    the data types the DataEntity step left out, type references, ORM relations and the units (no LLM)."""
    rules = _domain_rules(cfg.params)
    entity_cfg = config.get_extraction_config(engine, "DataEntity")
    entity_rules = _entity_rules(entity_cfg.params if entity_cfg else None)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    facts, importers, owners = _entity_facts(q)
    detected = data_entities.detect_entities(facts, importers, owners, entity_rules)
    fact_of = {f["id"]: f for f in facts}
    unit_of_file: dict[str, list[str]] = {}
    units = _units_with_members(q)
    for u in units:
        for member in u["members"]:
            unit_of_file.setdefault(member, []).append(u["id"])
    type_units = lambda type_ids: sorted({unit for t in type_ids for unit in unit_of_file.get(norm(fact_of.get(t, {}).get("path")), [])})  # noqa: E731

    entities = [{"key": e.key, "name": e.name_candidates[0][0], "signal": e.signal, "type_ids": list(e.type_ids), "units": type_units(e.type_ids)} for e in detected.entities]
    candidates = [
        {
            "type_id": x.type_id,
            "name": data_entities.entity_name(x.name, owners.get(fact_of.get(x.type_id, {}).get("path", ""), ""), entity_rules),
            "reason": x.reason,
            "units": type_units([x.type_id]),
        }
        for x in detected.excluded
    ]
    roots = {x.type_id for x in detected.excluded if x.type_id in fact_of and data_entities.is_root(fact_of[x.type_id]["decorators"], fact_of[x.type_id]["bases"], entity_rules)}
    references = [
        (r["a"], r["b"])
        for r in q(
            "MATCH (a:Graph:TypeDefinition)-[:`Graph:CONTAINS`]->(:Graph:Method)-[:`Graph:REFERENCES`]->(b:Graph:TypeDefinition) "
            "WHERE a.repository_name = $repo_name RETURN DISTINCT a.id AS a, b.id AS b"
        )
    ]
    # ORM relations by class or table name, resolved to the entity (by key) or the left-out type
    node_by_name: dict[str, str] = {}
    for e in detected.entities:
        for t in e.type_ids:
            node_by_name[str(fact_of.get(t, {}).get("name", "")).casefold()] = e.key
        for table in e.tables:
            node_by_name[table.casefold()] = e.key
    for c in candidates:
        node_by_name.setdefault(str(fact_of.get(c["type_id"], {}).get("name", "")).casefold(), c["type_id"])
    relations: list[tuple[str, str, str]] = []
    for path in sorted(
        {norm(f["path"]) for f in facts if f["path"]}
        | {norm(r["p"]) for r in q("MATCH (f:Graph:File) WHERE f.repository_name = $repo_name AND f.subtype = 'sql' RETURN f.filePath AS p")}
    ):
        text = _read_checkout(repo_path, repo.name, path)
        if text is None:
            continue
        for a, how, b in data_domains.orm_relations(path, text):
            if a.casefold() in node_by_name and b.casefold() in node_by_name:
                relations.append((node_by_name[a.casefold()], how, node_by_name[b.casefold()]))
    docs = {
        norm(r["p"]): text
        for r in q("MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name AND f.fileType = 'docs' RETURN f.filePath AS p")
        if (text := _read_checkout(repo_path, repo.name, norm(r["p"]))) is not None
    }
    result = data_domains.detect_domains(entities, candidates, references, sorted(set(relations)), rules, roots=roots, unit_names={u["id"]: u["path"] for u in units}, docs=docs)

    entity_ids = {e.key: f"entity::{repo.name}::{e.key}" for e in detected.entities}
    edges = 0
    for d in result.domains:
        domain_id = f"domain::{repo.name}::{d.key}"
        graph_manager.add_node(
            DataDomainNode(name=d.anchor, kind=d.kind, repository_name=repo.name, name_candidates=d.name_candidates, business_object=d.business_object, exception=d.exception),
            node_id=domain_id,
        )
        for node in d.nodes:
            graph_manager.add_edge(domain_id, entity_ids.get(node, node), INCLUDES)
            edges += 1
    excluded = [{"name": x.name, "reason": x.reason} for x in result.excluded]
    return {"nodes_created": len(result.domains), "edges_created": edges, "errors": [], "domains": len(result.domains), "excluded": excluded}


def _business_layer_rules(params: str | None) -> tuple[lifecycles.LifecycleRules, roles.RoleRules]:
    """The BusinessLayer step's signals (``params``): lifecycle words and patterns (``status_words``, ``min_states``,
    ``value_pattern``, ``flow_words``, ``heading_noise``, ``unit_noise``, ``name_templates``) and the role signals
    (``markers``: patterns whose first group holds role constants, ``generic_roles``, ``generic_actors``)."""
    settings = json.loads(params) if params else {}
    lists = ("status_words", "flow_words", "heading_noise", "unit_noise", "name_templates", "markers", "generic_roles", "generic_actors")
    unknown = set(settings) - {*lists, "min_states", "value_pattern"}
    lists_ok = all(isinstance(settings.get(k, []), list) and all(isinstance(x, str) and x for x in settings.get(k, [])) for k in lists)
    states = settings.get("min_states", lifecycles.LifecycleRules.min_states)
    pattern = settings.get("value_pattern", lifecycles.LifecycleRules.value_pattern)
    if unknown or not lists_ok or not isinstance(states, int) or isinstance(states, bool) or states < 2 or not isinstance(pattern, str):
        raise ValueError(f"BusinessLayer params: lists of strings under {list(lists)}, min_states a whole number of at least 2, value_pattern a pattern")
    for p in [pattern, *settings.get("markers", [])]:
        try:
            re.compile(p)
        except re.error as exc:
            raise ValueError(f"BusinessLayer params: {p!r} is no valid pattern: {exc}") from exc
    life_defaults = lifecycles.LifecycleRules()
    life = lifecycles.LifecycleRules(
        **{k: tuple(settings[k]) if k in settings else getattr(life_defaults, k) for k in ("status_words", "flow_words", "heading_noise", "unit_noise", "name_templates")},
        min_states=states,
        value_pattern=pattern,
    )
    return life, roles.RoleRules(**{k: tuple(settings.get(k, [])) for k in ("markers", "generic_roles", "generic_actors")})


def _extract_business_layer(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """Lifecycles of the business domains (processes, with their events) and the roles and actors assigned to them,
    from code, documentation and the units (no LLM)."""
    life_rules, role_rules = _business_layer_rules(cfg.params)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    members = []
    for row in q(
        "MATCH (d:Graph:DataDomain)-[:`Graph:INCLUDES`]->(m) WHERE d.repository_name = $repo_name AND d.businessObject IS NOT NULL "
        "OPTIONAL MATCH (m)-[:`Graph:INCLUDES`]->(t:Graph:TypeDefinition) "
        "RETURN d.id AS domain, d.businessObject AS object, m.typeName AS member, m.filePath AS member_path, t.typeName AS type, t.filePath AS type_path"
    ):
        for name, path in ((row.get("member"), row.get("member_path")), (row.get("type"), row.get("type_path"))):
            if name and path:
                members.append({"domain": row["domain"], "object": row["object"], "name": str(name), "path": norm(path)})
    paths = q("MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name RETURN f.filePath AS path, f.fileType AS kind, f.subtype AS subtype")
    files = {norm(r["path"]): text for r in paths if r.get("kind") == "source" and (text := _read_checkout(repo_path, repo.name, norm(r["path"]))) is not None}
    docs = {norm(r["path"]): text for r in paths if r.get("kind") == "docs" and (text := _read_checkout(repo_path, repo.name, norm(r["path"]))) is not None}
    units = [
        {"id": r["id"], "path": norm(r["path"]), "name": r["name"], "web": bool(r.get("web"))}
        for r in q("MATCH (u:Graph:DeployableUnit) WHERE u.active = true AND u.repository_name = $repo_name RETURN u.id AS id, u.path AS path, u.name AS name, u.webEntries AS web")
    ]
    found = lifecycles.detect_lifecycles(files, members, units, life_rules, docs)
    concepts = [
        {"id": r["id"], "name": r["name"], "files": [norm(f) for f in r["files"] or []]}
        for r in q(
            "MATCH (c:Graph:BusinessConcept) WHERE c.repository_name = $repo_name AND ANY(t IN COALESCE(c.conceptTypes, []) WHERE t IN ['actor', 'role']) "
            "OPTIONAL MATCH (f:Graph:File)-[:`Graph:REFERENCES`]->(c) RETURN c.id AS id, c.conceptName AS name, collect(f.filePath) AS files"
        )
        if r.get("name")
    ]
    consumes = [
        (r["a"], r["b"]) for r in q("MATCH (a:Graph:DeployableUnit)-[:`Graph:CONSUMES`]->(b:Graph:DeployableUnit) WHERE a.repository_name = $repo_name RETURN a.id AS a, b.id AS b")
    ]
    lifecycle_id = {life.key: f"lifecycle::{repo.name}::{_slug(life.key.split('::', 2)[-1])}" for life in found}
    reached = {lifecycle_id[life.key]: sorted({u for units_ in life.units_of_state.values() for u in units_}) for life in found}
    found_roles = roles.detect_roles(files, concepts, units, reached, consumes, role_rules)

    edges = 0
    for life in found:
        node = lifecycle_id[life.key]
        graph_manager.add_node(
            LifecycleNode(
                name=life.name_candidates[0],
                domain=life.domain,
                entity=life.entity,
                attribute=life.attribute,
                repository_name=repo.name,
                states=life.states,
                events=life.events,
                sites=sorted({p for ps in life.sites.values() for p in ps}),
                name_candidates=life.name_candidates,
                flow=life.flow or "",
                transitions=[f"{a}>{b}" for a, b in life.transitions],
                state_sites=[f"{state}>{path}" for state in life.states for path in life.sites.get(state, [])],
            ),
            node_id=node,
        )
        event_id = {state: f"event::{repo.name}::{_slug(life.key.split('::', 2)[-1])}::{state.casefold()}" for state in life.events}
        for state in life.events:
            label = lifecycles.display(state) if life.from_enum else f"{life.entity} {lifecycles.display(state)}"
            graph_manager.add_node(LifecycleEventNode(name=label, lifecycle=node, state=state, repository_name=repo.name), node_id=event_id[state])
        # Only transitions code or the documented flow shows chain events; an event without one hangs off the lifecycle
        for before, state in life.triggers:
            graph_manager.add_edge(event_id[before] if before else node, event_id[state], "TRIGGERS")
            edges += 1
    for role in found_roles:
        node = f"role::{repo.name}::{_slug(role.name)}"
        graph_manager.add_node(RoleNode(name=role.name, kind=role.kind, source=role.source, repository_name=repo.name), node_id=node)
        for life in role.lifecycles:
            graph_manager.add_edge(node, life, "ASSIGNED")
            edges += 1
    events = sum(len(life.events) for life in found)
    return {"nodes_created": len(found) + events + len(found_roles), "edges_created": edges, "errors": [], "lifecycles": len(found), "events": events, "roles": len(found_roles)}


def _read_checkout(repo_path: Path, repo_name: str, path: str, max_bytes: int = 200_000) -> str | None:
    """A file's text from the checkout (graph paths start with the repository folder)."""
    relative = path[len(repo_name) + 1 :] if path.startswith(repo_name + "/") else path
    file = repo_path / relative
    try:
        if file.is_file() and file.stat().st_size <= max_bytes:
            return file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return None


def _module_rules(params: str | None) -> build_modules.ModuleRules:
    """The BuildModule step's rules (``params``): ``manifests`` (build manifest file names), ``code_subtypes`` (the
    file subtypes of the repository's own code), ``min_members`` (modules an aggregator lists to be a system),
    ``iac_dependencies`` and ``test_dependencies`` (dependency patterns of modules that are no components) and
    ``test_words`` (words in a folder or manifest name that mark a test module)."""
    settings = json.loads(params) if params else {}
    manifests, subtypes = settings.get("manifests"), settings.get("code_subtypes")
    if not isinstance(manifests, list) or not manifests or not all(isinstance(m, str) and m for m in manifests):
        raise ValueError("BuildModule params need manifests: the build manifest file names (a list of strings)")
    if not isinstance(subtypes, list) or not subtypes or not all(isinstance(s, str) and s for s in subtypes):
        raise ValueError("BuildModule params need code_subtypes: the file subtypes that count as the repository's own code")
    minimum = settings.get("min_members", 2)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2:
        raise ValueError("BuildModule params: min_members is a whole number of at least 2")
    lists = {key: settings.get(key, []) for key in ("iac_dependencies", "test_dependencies", "test_words")}
    if not all(isinstance(v, list) and all(isinstance(p, str) and p for p in v) for v in lists.values()):
        raise ValueError("BuildModule params: iac_dependencies, test_dependencies and test_words are lists of strings")
    return build_modules.ModuleRules(
        manifests=tuple(manifests),
        code_subtypes=frozenset(subtypes),
        min_members=minimum,
        iac_dependencies=tuple(lists["iac_dependencies"]),
        test_dependencies=tuple(lists["test_dependencies"]),
        test_words=tuple(lists["test_words"]),
    )


def _kind_nouns(params: str | None) -> dict[str, str]:
    """``kind_nouns`` of the BuildModule params: the word a system or module name gets when a unit has that name."""
    nouns = (json.loads(params) if params else {}).get("kind_nouns", {})
    if not isinstance(nouns, dict) or not all(k in ("system", "module") and isinstance(v, str) and v for k, v in nouns.items()):
        raise ValueError("BuildModule params: kind_nouns maps system and/or module to a word")
    return dict(nouns)


def _extract_build_modules(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """BuildModule nodes with INCLUDES (own files), NESTS (parent to nested module) and BUILDS (unit to module) edges (no LLM)."""
    rules, nouns = _module_rules(cfg.params), _kind_nouns(cfg.params)
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    files = [
        {"id": r["id"], "path": norm(r["path"]), "name": r["name"] or "", "file_type": r["file_type"], "subtype": r["subtype"]}
        for r in q(
            "MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name "
            "RETURN f.id AS id, f.filePath AS path, f.fileName AS name, f.fileType AS file_type, f.subtype AS subtype"
        )
        if r.get("id") and r.get("path")
    ]
    patterns = [m.lower() for m in rules.manifests]
    manifests = {
        f["path"]: text for f in files if any(fnmatch.fnmatchcase(f["name"].lower(), p) for p in patterns) and (text := _read_checkout(repo_path, repo.name, f["path"])) is not None
    }
    found = build_modules.detect_modules(repo.name, files, manifests, rules)
    file_ids = {f["path"]: f["id"] for f in files}
    ids = {m.path: build_modules.module_id(repo.name, m.path) for m in found}
    unit_rows = q("MATCH (u:Graph:DeployableUnit) WHERE u.repository_name = $repo_name RETURN u.id AS id, u.path AS path, u.name AS name, u.nameCandidates AS candidates")
    units = [(str(r["id"]), norm(r["path"])) for r in unit_rows if r.get("path")]

    def same_as(m: build_modules.BuildModule) -> str | None:
        # The folder of exactly one unit, holding no other module or system: the unit and the module are one structure
        at = [uid for uid, path in units if path == m.path]
        nested = any(o.path.startswith(m.path + "/") for o in found)
        return at[0] if m.excluded is None and m.module and not m.system and len(at) == 1 and not nested else None

    # A component candidate named like a unit (its name or one of its name candidates) or an earlier candidate (as written, or without the repository's name, as
    # derivation sees it) takes the first free name of: its kind noun added, the words of its path, those with the noun.
    # Candidates whose path says no more than their name go first: they have the fewest names to choose from
    keys = lambda name: {name_key(name), name_key(build_modules.display_name(name, repo.name))} - {""}  # noqa: E731 - a one-line helper
    path_words = lambda m: build_modules.display_name(m.path.removeprefix(repo.name + "/").replace("/", " "), repo.name)  # noqa: E731 - a one-line helper
    taken = set().union(*(keys(str(n or "")) for r in unit_rows for n in [r.get("name"), *(r.get("candidates") or [])]))
    candidates = [m for m in found if m.excluded is None and not same_as(m)]
    for m in sorted(candidates, key=lambda m: (bool(keys(path_words(m)) - keys(m.name)), m.path)):
        noun = nouns.get("system" if m.system else "module")
        if keys(m.name) & taken:
            options = [f"{m.name} {noun}"] if noun else []
            if m.path != repo.name:
                options += [path_words(m)] + ([f"{path_words(m)} {noun}"] if noun else [])
            if options:
                m.name = next((o for o in options if not keys(o) & taken), options[0])
        taken |= keys(m.name)

    nodes = edges = 0
    for m in found:
        node = BuildModuleNode(
            name=m.name,
            path=m.path,
            manifest=m.manifest,
            repository_name=repo.name,
            is_module=m.module,
            is_system=m.system,
            members=m.members,
            same_as=same_as(m),
            excluded=m.excluded,
        )
        graph_manager.add_node(node, node_id=ids[m.path])
        nodes += 1
        for path in m.files:
            if path in file_ids:
                graph_manager.add_edge(ids[m.path], file_ids[path], INCLUDES)
                edges += 1
        if m.parent is not None:
            graph_manager.add_edge(ids[m.parent], ids[m.path], "NESTS")
            edges += 1
    # A unit builds the modules in its folder that no deeper unit holds; a unit inside a module builds that module
    for module in (m for m in found if m.module):
        holders = [(uid, path) for uid, path in units if module.path == path or module.path.startswith(path + "/")]
        if holders:
            deepest = max(len(path) for _, path in holders)
            targets = sorted(uid for uid, path in holders if len(path) == deepest)
        else:
            # Units inside the module whose folder no deeper module holds
            targets = sorted(
                uid
                for uid, path in units
                if path.startswith(module.path + "/") and not any(o.module and len(o.path) > len(module.path) and (path == o.path or path.startswith(o.path + "/")) for o in found)
            )
        for uid in targets:
            graph_manager.add_edge(uid, ids[module.path], "BUILDS")
            edges += 1
    return {"nodes_created": nodes, "edges_created": edges, "errors": [], "modules": sum(1 for m in found if m.module), "systems": sum(1 for m in found if m.system)}


def _extract_deployable_units(cfg: config.ExtractionConfig, repo: Any, repo_path: Path, graph_manager: GraphManager) -> dict[str, Any]:
    """Deployable unit nodes with INCLUDES edges to their members, from the graph and the manifests (no LLM)."""
    rules = _unit_rules(cfg.params)
    # A combined graph holds several repositories: every source read is this repository's
    q = lambda query, params=None: graph_manager.query(query, {**(params or {}), "repo_name": repo.name})  # noqa: E731 - a one-line helper
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    files = [
        {"id": r["id"], "path": norm(r["path"]), "name": r["name"] or "", "file_type": r["file_type"], "subtype": r["subtype"]}
        for r in q(
            "MATCH (f:Graph:File) WHERE f.active = true AND f.repository_name = $repo_name "
            "RETURN f.id AS id, f.filePath AS path, f.fileName AS name, f.fileType AS file_type, f.subtype AS subtype"
        )
        if r.get("id") and r.get("path")
    ]
    manifests = {f["path"]: text for f in files if f["name"].lower() in UNIT_MANIFESTS and (text := _read_checkout(repo_path, repo.name, f["path"])) is not None}
    documents = {f["path"]: text for f in files if f["file_type"] == "docs" and (text := _read_checkout(repo_path, repo.name, f["path"])) is not None}
    imports = [
        (norm(r["a"]), norm(r["b"]))
        for r in q(
            "MATCH (a:Graph:File)-[:`Graph:IMPORTS`]->(b:Graph:File) WHERE a.repository_name = $repo_name AND b.repository_name = $repo_name "
            "RETURN a.filePath AS a, b.filePath AS b"
        )
    ]
    kinds = (
        "MATCH (t:Graph:TypeDefinition) WHERE t.active = true AND t.repository_name = $repo_name AND t.category = $category "
        "RETURN t.id AS id, t.filePath AS path, t.typeName AS name, t.decorators AS decorators"
    )
    programs = [{**r, "path": norm(r["path"])} for r in q(kinds, {"category": "program"})]
    screens = [{**r, "path": norm(r["path"])} for r in q(kinds, {"category": "screen"})]
    job_files = {norm(r["path"]) for category in ("job", "procedure") for r in q(kinds, {"category": category})}
    entry_calls = q(
        "MATCH (a:Graph:Method)-[:`Graph:CALLS`]->(b:Graph:Method), (p:Graph:TypeDefinition) "
        "WHERE p.category = 'program' AND p.repository_name = $repo_name AND a.repository_name = $repo_name AND b.filePath = p.filePath AND b.methodName = p.typeName "
        "RETURN DISTINCT a.filePath AS caller, p.id AS program"
    )
    program_of_file = {p["path"]: p["id"] for p in programs}
    job_runs = [(norm(r["caller"]), r["program"]) for r in entry_calls if norm(r["caller"]) in job_files]
    program_calls = [
        (program_of_file[norm(r["caller"])], r["program"]) for r in entry_calls if norm(r["caller"]) in program_of_file and program_of_file[norm(r["caller"])] != r["program"]
    ]

    facts = deployable_units.RepoFacts(
        repository=repo.name,
        files=files,
        manifests=manifests,
        imports=imports,
        programs=programs,
        screens=screens,
        job_runs=job_runs,
        program_calls=program_calls,
        documents=documents,
        # Names no unit may take: the technologies and dependencies the graph already names
        reserved={str(r["name"]) for r in q("MATCH (n:Graph:Technology) WHERE n.active = true AND n.repository_name = $repo_name RETURN n.techName AS name") if r.get("name")}
        | {
            str(r["name"])
            for r in q("MATCH (n:Graph:ExternalDependency) WHERE n.active = true AND n.repository_name = $repo_name RETURN n.dependencyName AS name")
            if r.get("name")
        },
    )
    units = deployable_units.detect_units(facts, rules)

    # What an earlier run wrote and this one no longer produces is swept after the step (_run_extraction_step)
    file_ids = {f["path"]: f["id"] for f in files}
    nodes = edges = 0
    for unit in units:
        node_id = deployable_units.unit_id(repo.name, unit)
        graph_manager.add_node(
            DeployableUnitNode(
                name=unit.name,
                path=unit.path,
                unit_kind=unit.kind,
                repository_name=repo.name,
                evidence=unit.evidence,
                entry=unit.entry,
                manifest_name=unit.manifest_name,
                manifest_description=unit.manifest_description,
                module=unit.module,
                readme_lines=unit.readme_lines,
                readme_title=unit.readme_title,
                web_entries=unit.web_entries,
                product=unit.product,
                name_candidates=[name for name, _ in unit.name_candidates],
                name_sources=[source for _, source in unit.name_candidates],
                member_count=len(unit.members | set(unit.web_entries)),
            ),
            node_id=node_id,
        )
        nodes += 1
        for target in sorted({file_ids[p] for p in unit.members | set(unit.web_entries) if p in file_ids} | unit.nodes):
            graph_manager.add_edge(node_id, target, INCLUDES)
            edges += 1
    return {"nodes_created": nodes, "edges_created": edges, "errors": []}


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
    call_languages: dict[str, frozenset[str]] | None = None,
    scope_of: Callable[[str], str] | None = None,
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
            # The graph stores "<repo>/<path>"; the files being parsed are repo-relative
            file_path = repo_relative(props.get("filePath") or props.get("file_path", ""), repo.name)
            node_id = m.get("id", "")

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
            file_path = repo_relative(props.get("filePath") or props.get("file_path", ""), repo.name)
            node_id = t.get("id", "")

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
        call_languages=call_languages,
        scope_of=scope_of,
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


def _call_rules(params: str | None) -> tuple[dict[str, frozenset[str]], tuple[str, ...]]:
    """The Calls step's rules (``params``): ``call_languages`` (caller language -> the other languages its calls
    may reach, such as a job language and the program language its steps run) and ``module_files`` (file name
    patterns, case-insensitive; a folder holding one is a module root)."""
    settings = json.loads(params) if params else {}
    languages, modules = settings.get("call_languages", {}), settings.get("module_files", [])
    if (
        set(settings) - {"call_languages", "module_files"}
        or not isinstance(languages, dict)
        or not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v) for v in languages.values())
        or not isinstance(modules, list)
        or not all(isinstance(m, str) and m for m in modules)
    ):
        raise ValueError("Calls params: call_languages maps a caller language to a list of languages, module_files is a list of file name patterns")
    return {k: frozenset(v) for k, v in languages.items()}, tuple(m.lower() for m in modules)


def _module_roots(paths: list[str], module_files: tuple[str, ...]) -> Callable[[str], str]:
    """Path -> its module root: the nearest folder above it that holds a module file, else "" (the repository root)."""
    roots = {str(PurePosixPath(p).parent) for p in paths if any(fnmatch.fnmatchcase(PurePosixPath(p).name.lower(), m) for m in module_files)}
    roots = {"" if r == "." else r for r in roots}

    def root_of(path: str) -> str:
        for parent in PurePosixPath(path).parents:
            folder = "" if str(parent) == "." else str(parent)
            if folder in roots:
                return folder
        return ""

    return root_of


def _extract_calls(
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
) -> dict[str, Any]:
    """Extract CALLS edges from source files using Tree-sitter.

    A call without an import stays within its module root (``params.module_files``) and its language,
    or reaches one of the languages ``params.call_languages`` allows for its language."""
    from deriva.modules.extraction.edges import EdgeType

    call_languages, module_files = _call_rules(cfg.params)
    scope_of = _module_roots([str(f["path"]).replace(chr(92), "/") for f in classified_files if f.get("path")], module_files)
    return _extract_edges(repo, repo_path, classified_files, graph_manager, {EdgeType.CALLS}, call_languages=call_languages, scope_of=scope_of)


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

    # A technology answer for a directory named after the repository is skipped (params.skip_repository_name)
    skip_name = extraction_config["params"].get("skip_repository_name", False)
    if not isinstance(skip_name, bool):
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"DirectoryClassification params.skip_repository_name must be true or false, got {skip_name!r}"]}

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
            repository_name=repo.name if skip_name else "",
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

    # Per name entry (one decision for all its directories) the nodes it became, None for none: decision stability
    targets: dict[str, set[str]] = {}
    for edge_data in all_edges:
        targets.setdefault(str(edge_data.get("source")), set()).add(str(edge_data.get("target")))
    decisions = {name_key(str(group["name"])): sorted({t for i in group["ids"] for t in targets.get(str(i), ())}) or None for group in directories}

    return {
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "edge_ids": edge_ids,
        "errors": errors,
        "stats": {"decisions": decisions},
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


# Languages the tree-sitter adapter extracts types and methods from
_TREESITTER_LANGUAGES = frozenset({"python", "javascript", "typescript", "java", "csharp", "cobol", "jcl", "bms", "sql"})


def _extract_llm_based(
    node_type: str,
    cfg: config.ExtractionConfig,
    repo: Any,
    repo_path: Path,
    classified_files: list[dict],
    graph_manager: GraphManager,
    llm_query_fn: Callable | None,
    engine: Any,
    model: str | None = None,
) -> dict[str, Any]:
    """Extract LLM-based nodes (TypeDefinition, Method, Technology, ExternalDependency, Test).

    Without an LLM (``llm_query_fn`` None) the parsers still run; files that only the LLM can read are skipped and counted.
    """
    nodes_created = 0
    edges_created = 0
    errors = []
    skipped_without_llm = 0
    deferred_inherits: list[dict] = []

    # Parse input sources from config
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None

    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"No input sources for {node_type}"]}

    # Get files matching the input sources
    matching_files = extraction.filter_files_by_input_sources(classified_files, input_sources)

    # Binary and image files can't be meaningfully analyzed as text
    matching_files = [f for f in matching_files if not _is_unreadable(f)]

    # Special case: Method extraction with node-based sources (TypeDefinition.codeSnippet): tree-sitter
    # parses the source files of the languages in params.languages (Python when absent)
    if not matching_files and node_type == "Method" and extraction.has_node_sources(input_sources):
        languages = (json.loads(cfg.params) if cfg.params else {}).get("languages", ["python"])
        if not isinstance(languages, list) or not languages or not set(languages) <= _TREESITTER_LANGUAGES:
            return {"nodes_created": 0, "edges_created": 0, "errors": [f"Method params.languages must be a non-empty list of {sorted(_TREESITTER_LANGUAGES)}, got {languages!r}"]}
        matching_files = [f for f in classified_files if (f.get("subtype") or "").lower() in languages]

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
        assert llm_query_fn is not None  # only handed out when an LLM is given (step_llm below)
        return llm_query_fn(
            prompt,
            schema,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            system_prompt=system_prompt,
        )

    step_llm = step_llm_query_fn if llm_query_fn is not None else None

    # Check if we can use tree-sitter extraction for supported languages
    use_treesitter = node_type in ["TypeDefinition", "Method"]

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
        is_treesitter_supported = file_subtype in _TREESITTER_LANGUAGES

        # Track extraction method for this file
        extraction_method = "llm"  # Default

        # ExternalDependency: use unified function (handles deterministic/treesitter/LLM)
        if node_type == "ExternalDependency":
            result = extraction.extract_external_dependencies(
                file_path=file_info["path"],
                file_content=content,
                repo_name=repo.name,
                llm_query_fn=step_llm,
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
        elif step_llm is None:
            # A file only the LLM can read: skipped without one
            skipped_without_llm += 1
            continue
        else:
            # Use LLM extraction for non-Python files or other node types
            file_nodes, file_edges, file_errors = _extract_file_content(
                file_path=file_info["path"],
                content=content,
                repo_name=repo.name,
                extract_fn=extract_fn,
                extraction_config=extraction_config,
                llm_query_fn=step_llm,
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

    if skipped_without_llm:
        # "LLM required" makes the caller report this as a warning, not an error
        errors.append(f"LLM required for {node_type} in {skipped_without_llm} file{'' if skipped_without_llm == 1 else 's'} without a parser (skipped)")

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
    prompt_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Labels for one batch of a closed classification. Items an answer leaves out are asked again on their
    own, up to `missing_retries` times; every item still gets one decision, never a vote.

    ``classifier`` is the step's candidate module: ``build_classification_prompt``, ``CLASSIFICATION_SCHEMA``
    and ``parse_labels``; ``prompt_options`` are extra arguments for its prompt builder.

    Returns the labels by key, the answer issues, errors, retry calls and the labels the retries recovered.
    """
    labels: dict[str, str] = {}
    issues = {"unmatched": 0, "duplicates": 0, "missing": 0}
    errors: list[str] = []
    pending, answered, attempt, recovered = batch, False, 0, 0
    while True:
        label = f"{where}, retry {attempt}" if attempt else where
        prompt = classifier.build_classification_prompt(cfg.instruction or "", pending, **(prompt_options or {}))
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
    description_chars, context_sources = params.get("system_description_chars", 0), params.get("context_sources", False)
    if not isinstance(description_chars, int) or isinstance(description_chars, bool) or description_chars < 0:
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"BusinessConcept params.system_description_chars must be a non-negative integer, got {description_chars!r}"]}
    if not isinstance(context_sources, bool):
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"BusinessConcept params.context_sources must be true or false, got {context_sources!r}"]}
    # Absent in config versions before the switch: the key order decides inside the tie group at the cut
    keep_ties = params.get("evidence_keep_ties", False)
    if not isinstance(keep_ties, bool):
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"BusinessConcept params.evidence_keep_ties must be true or false, got {keep_ties!r}"]}
    input_sources = extraction.parse_input_sources(cfg.input_sources) if cfg.input_sources else None
    if not input_sources:
        return {"nodes_created": 0, "edges_created": 0, "errors": ["No input sources for BusinessConcept"]}

    files = [f for f in extraction.filter_files_by_input_sources(classified_files, input_sources) if not _is_unreadable(f)]
    documents, errors = _read_documents(repo_path, files, repo.name)
    if not documents:
        return {"nodes_created": 0, "edges_created": 0, "errors": errors, "warnings": [f"No documents for BusinessConcept in {repo.name}"]}
    # The system's own description for the classifier: the opening of the README at the repository root
    readme = next((d for d in documents if "/" not in d["path"].replace(chr(92), "/") and d["path"].lower().startswith("readme")), None)
    prompt_options = {"system_description": concept_candidates.system_description(readme["text"], description_chars) if readme else "", "show_sources": context_sources}

    tool = NlpTool()
    tool.ensure_models()
    found = tool.extract(documents, params["nlp"], sorted(UNCOUNTABLE_WORDS))

    candidates = concept_candidates.merge_candidates(found["candidates"], repo.name)
    candidates = concept_candidates.add_support(candidates, _code_names(graph_manager, repo.name))
    selected, selection = concept_candidates.select_candidates(
        candidates, int(params["evidence_min_count"]), float(params["evidence_share"]), int(params["max_candidates"]), float(params["support_factor"]), keep_ties
    )
    selected, phrases = concept_candidates.without_phrases(selected, frozenset(params["stop_words"]))

    labelled: list[tuple[concept_candidates.ConceptCandidate, str]] = []
    issues = {"unmatched": 0, "duplicates": 0, "missing": 0}
    retries = {"calls": 0, "recovered": 0}
    decisions: dict[str, str | None] = dict.fromkeys(sorted(c.key for c in selected))  # None: no label (skipped, failed batch)
    batches = concept_candidates.classification_batches(selected, cfg.batch_size)
    for number, batch in enumerate(batches, 1):
        result = _classify_batch(cfg, concept_candidates, batch, f"batch {number}", int(params["missing_retries"]), llm_query_fn, prompt_options)
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
        # What each decision does to the graph (reject labels alike), for output-level stability
        "outcomes": {key: concept_candidates.outcome(label) for key, label in decisions.items()},
    }
    return {"nodes_created": len(nodes), "edges_created": len(edge_ids), "edge_ids": edge_ids, "errors": errors, "stats": stats}


# Params the Technology step reads from its config row (every one of them changes results)
_TECHNOLOGY_PARAMS = ("confidence", "missing_retries", "platforms")


def _own_units(params: dict[str, Any], classified_files: list[dict]) -> frozenset[str]:
    """Name keys of the repository's own modules (``params.own_modules``): directories holding a file of the given types or subtypes.

    ``{"file_types": ["build", "dependency"], "subtypes": ["docker"]}``. Without the key there are none.
    """
    settings = params.get("own_modules")
    if settings is None:
        return frozenset()
    types = settings.get("file_types") if isinstance(settings, dict) else None
    subtypes = settings.get("subtypes", []) if isinstance(settings, dict) else None
    if not isinstance(types, list) or not types or not isinstance(subtypes, list) or not all(isinstance(t, str) and t for t in [*types, *subtypes]):
        raise ValueError(f"params.own_modules needs non-empty file_types and optional subtypes, as lists of names, got {settings!r}")
    return technology_candidates.own_unit_names(classified_files, frozenset(types), frozenset(subtypes))


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

    try:
        own_units = _own_units(params, classified_files)
    except ValueError as e:
        return {"nodes_created": 0, "edges_created": 0, "errors": [str(e)]}
    skip_name = params.get("skip_repository_name", False)
    if not isinstance(skip_name, bool):
        return {"nodes_created": 0, "edges_created": 0, "errors": [f"Technology params.skip_repository_name must be true or false, got {skip_name!r}"]}
    collected = technology_candidates.collect(files, params["platforms"], own_units, repository_name=repo.name if skip_name else "")
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
    node.origin_source = repo_relative(merged["originSource"], node.repository_name)  # stored paths carry the repo prefix
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

    This is the generator version of run_extraction() the studio streams its
    updates to the browser as run events.

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
        for update in run_extraction_iter(engine, graph_manager):
            print(update)
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
