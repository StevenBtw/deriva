"""
Extraction service for Deriva.

Orchestrates the extraction pipeline by:
1. Loading extraction configs from DuckDB
2. Getting files from repositories
3. Calling extraction module functions
4. Persisting results to Neo4j GraphManager

Used by both Marimo (visual) and CLI (headless).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from deriva.common.file_utils import read_file_with_encoding
from deriva.common.ocel import create_edge_id
from deriva.modules import extraction
from deriva.modules.extraction import classification
from deriva.modules.extraction.base import deduplicate_nodes
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

    Returns:
        Dict with success, stats, errors
    """
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

    # Get extraction configs
    configs = config.get_extraction_configs(engine, enabled_only=enabled_only)

    if not configs:
        return {"success": False, "stats": stats, "errors": ["No extraction configs enabled"]}

    # Get file type registry for classification
    file_types = config.get_file_types(engine)
    registry_list = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in file_types]

    # Start progress tracking
    total_steps = len(configs) * len(repos)
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

        # Classify files
        classification_result = classification.classify_files(file_paths, registry_list)
        classified_files = classification_result["classified"]
        undefined_files = classification_result["undefined"]

        # Process each extraction step in sequence order
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
                        errors.append(err)

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

    # Special case: Method extraction with node-based sources (TypeDefinition.codeSnippet)
    # For Python files, we can use AST to extract methods directly from source files
    if not matching_files and node_type == "Method" and extraction.has_node_sources(input_sources):
        # Get all Python source files for AST-based method extraction
        matching_files = [f for f in classified_files if extraction.is_python_file(f.get("subtype"))]

    if not matching_files:
        return {"nodes_created": 0, "edges_created": 0, "errors": []}

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

    # Wrap llm_query_fn with per-step temperature/max_tokens overrides
    def step_llm_query_fn(prompt: str, schema: dict) -> Any:
        return llm_query_fn(
            prompt,
            schema,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )

    # Check if we can use AST extraction for Python files
    use_ast_for_python = node_type in ["TypeDefinition", "Method"]

    # Process each matching file
    for file_info in matching_files:
        file_path = repo_path / file_info["path"]

        try:
            content = read_file_with_encoding(file_path)
            if content is None:
                errors.append(f"Could not read {file_path}")
                continue
        except Exception as e:
            errors.append(f"Could not read {file_path}: {e}")
            continue

        # Check if this is a Python file and we can use AST
        is_python = extraction.is_python_file(file_info.get("subtype"))

        # Track extraction method for this file
        extraction_method = "llm"  # Default

        # ExternalDependency: use unified function (handles deterministic/AST/LLM)
        if node_type == "ExternalDependency":
            result = extraction.extract_external_dependencies(
                file_path=file_info["path"],
                file_content=content,
                repo_name=repo.name,
                llm_query_fn=step_llm_query_fn,
                config=extraction_config,
                subtype=file_info.get("subtype"),
            )
            file_nodes = result["data"]["nodes"] if result["success"] else []
            file_edges = result["data"].get("edges", []) if result["success"] else []
            file_errors = result.get("errors", [])
            # ExternalDependency uses AST for Python deps, structural for config files
            extraction_method = result.get("extraction_method", "llm")
        elif use_ast_for_python and is_python:
            # Use AST extraction for Python - faster and more precise
            if node_type == "TypeDefinition":
                result = extraction.extract_types_from_python(file_info["path"], content, repo.name)
            else:  # Method
                result = extraction.extract_methods_from_python(file_info["path"], content, repo.name)
            file_nodes = result["data"]["nodes"] if result["success"] else []
            file_edges = result["data"].get("edges", []) if result["success"] else []
            file_errors = result.get("errors", [])
            extraction_method = "ast"
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
            try:
                graph_manager.add_edge(
                    src_id=src_id,
                    dst_id=dst_id,
                    relationship=relationship,
                )
                edges_created += 1
            except RuntimeError as e:
                errors.append(f"Error in {node_type}: {e}")

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
