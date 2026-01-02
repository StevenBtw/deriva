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

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deriva.adapters.graph import GraphManager
from deriva.common.chunking import chunk_content, should_chunk

if TYPE_CHECKING:
    from deriva.common.logging import RunLogger
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
    run_logger: RunLogger | None = None,
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
            if f.is_file() and not any(x in str(f) for x in [".git", "__pycache__", ".pyc"]):
                file_paths.append(str(f.relative_to(repo_path)))

        # Classify files
        classification_result = classification.classify_files(file_paths, registry_list)
        classified_files = classification_result["classified"]

        # Process each extraction step in sequence order
        for cfg in configs:
            node_type = cfg.node_type

            if verbose:
                print(f"  Extracting: {node_type}")

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
                    graph_manager=graph_manager,
                    llm_query_fn=llm_query_fn,
                    engine=engine,
                )

                nodes_created = result.get("nodes_created", 0)
                edges_created = result.get("edges_created", 0)
                stats["nodes_created"] += nodes_created
                stats["edges_created"] += edges_created
                stats["steps_completed"] += 1

                # Complete step logging
                if step_ctx:
                    step_ctx.items_created = nodes_created + edges_created
                    step_ctx.complete()

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

    # Complete phase logging
    if run_logger:
        if errors:
            run_logger.phase_error("extraction", "; ".join(errors[:3]), "Extraction completed with errors")
        else:
            run_logger.phase_complete("extraction", "Extraction completed successfully", stats=stats)

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
    graph_manager: GraphManager,
    llm_query_fn: Callable | None,
    engine: Any,
) -> dict[str, Any]:
    """Run a single extraction step based on node type."""
    node_type = cfg.node_type

    if node_type == "Repository":
        result = _extract_repository(repo, graph_manager)
    elif node_type == "Directory":
        result = _extract_directories(repo, repo_path, graph_manager)
    elif node_type == "File":
        result = _extract_files(repo, repo_path, classified_files, graph_manager)
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

    if result["success"]:
        for node_data in result["data"]["nodes"]:
            dir_node = DirectoryNode(
                name=node_data["properties"]["name"],
                path=node_data["properties"]["path"],
                repository_name=repo.name,
            )
            graph_manager.add_node(dir_node, node_id=node_data["node_id"])

        for edge_data in result["data"]["edges"]:
            graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=edge_data["to_node_id"],
                relationship=edge_data["relationship_type"],
            )

    return {
        "nodes_created": result["stats"].get("total_nodes", 0),
        "edges_created": result["stats"].get("total_edges", 0),
        "errors": result.get("errors", []),
    }


def _extract_files(repo: Any, repo_path: Path, classified_files: list[dict], graph_manager: GraphManager) -> dict[str, Any]:
    """Extract file nodes."""
    # Use the module to scan all files from repo path
    result = extraction.extract_files(str(repo_path), repo.name)

    # Build a lookup for classification info
    classification_lookup = {f["path"]: f for f in classified_files}

    if result["success"]:
        for node_data in result["data"]["nodes"]:
            props = node_data["properties"]
            # Get classification info from lookup
            class_info = classification_lookup.get(props["path"], {})
            file_node = FileNode(
                name=props["name"],
                path=props["path"],
                repository_name=repo.name,
                file_type=class_info.get("file_type", ""),
                subtype=class_info.get("subtype"),
            )
            graph_manager.add_node(file_node, node_id=node_data["node_id"])

        for edge_data in result["data"]["edges"]:
            graph_manager.add_edge(
                src_id=edge_data["from_node_id"],
                dst_id=edge_data["to_node_id"],
                relationship=edge_data["relationship_type"],
            )

    return {
        "nodes_created": result["stats"].get("total_nodes", 0),
        "edges_created": result["stats"].get("total_edges", 0),
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

        # Extract from file, with chunking if needed
        file_nodes, file_edges, file_errors = _extract_file_content(
            file_path=file_info["path"],
            content=content,
            repo_name=repo.name,
            extract_fn=extract_fn,
            extraction_config=extraction_config,
            llm_query_fn=llm_query_fn,
        )

        errors.extend(file_errors)

        # Persist extracted nodes
        for node_data in file_nodes:
            node = _create_node_from_data(node_type, node_data, repo.name)
            if node:
                node_id = node_data.get("node_id")
                graph_manager.add_node(node, node_id=node_id)
                nodes_created += 1

        # Persist extracted edges
        for edge_data in file_edges:
            src_id = edge_data.get("from_id", edge_data.get("from_node_id"))
            dst_id = edge_data.get("to_id", edge_data.get("to_node_id"))
            relationship = edge_data.get("relationship", edge_data.get("relationship_type"))
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

    Returns:
        Tuple of (nodes, edges, errors)
    """
    # Check if chunking is needed
    if not should_chunk(content):
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
    chunks = chunk_content(content)
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


def _create_node_from_data(node_type: str, node_data: dict, repo_name: str) -> Any:
    """Create a node model instance from extracted data."""
    props = node_data.get("properties", node_data)

    if node_type == "BusinessConcept":
        return BusinessConceptNode(
            name=props.get("name", ""),
            concept_type=props.get("concept_type", props.get("type", "other")),
            description=props.get("description", ""),
            origin_source=props.get("origin_source", props.get("source_file", props.get("file_path", ""))),
            repository_name=repo_name,
            confidence=props.get("confidence", 0.8),
        )
    elif node_type == "TypeDefinition":
        return TypeDefinitionNode(
            name=props.get("name", ""),
            type_category=props.get("type_category", props.get("definition_type", props.get("category", "class"))),
            file_path=props.get("file_path", props.get("source_file", "")),
            repository_name=repo_name,
            description=props.get("description"),
            interface_type=props.get("interface_type"),
            start_line=props.get("start_line", 0),
            end_line=props.get("end_line", 0),
            code_snippet=props.get("code_snippet"),
            confidence=props.get("confidence", 0.8),
        )
    elif node_type == "Method":
        return MethodNode(
            name=props.get("name", ""),
            return_type=props.get("return_type", "void"),
            visibility=props.get("visibility", "public"),
            file_path=props.get("file_path", props.get("source_file", "")),
            type_name=props.get("type_name", props.get("class_name", "")),
            repository_name=repo_name,
            description=props.get("description"),
            parameters=props.get("parameters"),
            is_static=props.get("is_static", False),
            is_async=props.get("is_async", False),
            start_line=props.get("start_line", 0),
            end_line=props.get("end_line", 0),
            confidence=props.get("confidence", 0.8),
        )
    elif node_type == "Technology":
        return TechnologyNode(
            name=props.get("name", ""),
            tech_category=props.get("tech_category", props.get("category", "service")),
            repository_name=repo_name,
            description=props.get("description"),
            version=props.get("version"),
            origin_source=props.get("origin_source", props.get("source_file")),
            confidence=props.get("confidence", 0.8),
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
        )

    return None
