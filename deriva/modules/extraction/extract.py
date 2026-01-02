"""
Generic extraction entry point with chunking support.

This module provides a single entry point for extracting any node type,
similar to derivation's generate.py. It handles:
- Chunking for large files based on file type config
- Routing to LLM extraction with proper chunking
- Aggregating results from chunked extraction

Note: AST extraction functions are passed in from the services layer
(which can import adapters) to respect the architecture rules where
modules cannot import from adapters.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from deriva.common.chunking import Chunk, chunk_content, should_chunk

from .base import create_empty_llm_details


class FileTypeConfig(Protocol):
    """Protocol for file type configuration (avoids importing from services)."""

    chunk_delimiter: str | None
    chunk_max_tokens: int | None
    chunk_overlap: int


# Type alias for AST extraction function signature
ASTExtractorFn = Callable[[str, str, str, str, Chunk | None], dict[str, Any]]


def extract_with_chunking(
    file_path: str,
    file_content: str,
    repo_name: str,
    node_type: str,
    extraction_method: str,
    llm_query_fn: Callable | None,
    config: dict[str, Any],
    file_type_config: FileTypeConfig | None = None,
    model: str | None = None,
    ast_extractor_fn: ASTExtractorFn | None = None,
) -> dict[str, Any]:
    """
    Extract nodes from a file with automatic chunking for large files.

    This is the main entry point for extraction. It:
    1. Checks if file needs chunking based on file type config and model limits
    2. If chunking needed, splits file and extracts from each chunk
    3. Routes to appropriate extractor (LLM or AST) based on extraction_method
    4. Aggregates results from all chunks

    Args:
        file_path: Path to the file being analyzed (relative to repo)
        file_content: Content of the file
        repo_name: Repository name
        node_type: Type of node to extract (e.g., 'TypeDefinition', 'Method')
        extraction_method: 'llm' or 'ast'
        llm_query_fn: Function to call LLM (signature: (prompt, schema) -> response)
        config: Extraction config with 'instruction' and 'example' keys
        file_type_config: Optional config with chunking settings (chunk_delimiter, chunk_max_tokens, chunk_overlap)
        model: Optional model name for token limit lookup
        ast_extractor_fn: Optional AST extraction function (injected from services layer)

    Returns:
        Dictionary with:
            - success: bool - Whether the extraction succeeded
            - data: Dict - Contains 'nodes' list and 'edges' list
            - errors: List[str] - Any errors encountered
            - stats: Dict - Statistics about the extraction
            - llm_details: Dict - LLM call details for logging (if LLM used)
            - chunks_processed: int - Number of chunks processed
    """
    # Determine chunking parameters from file type config
    delimiter = None
    max_tokens = None
    overlap = 0

    if file_type_config:
        delimiter = file_type_config.chunk_delimiter
        max_tokens = file_type_config.chunk_max_tokens
        overlap = file_type_config.chunk_overlap

    # Check if chunking is needed
    needs_chunking = should_chunk(file_content, max_tokens=max_tokens, model=model)

    if not needs_chunking:
        # Extract from entire file
        return _extract_single(
            file_path=file_path,
            file_content=file_content,
            repo_name=repo_name,
            node_type=node_type,
            extraction_method=extraction_method,
            llm_query_fn=llm_query_fn,
            config=config,
            chunk_info=None,
            ast_extractor_fn=ast_extractor_fn,
        )

    # Chunk the file
    chunks = chunk_content(
        content=file_content,
        delimiter=delimiter,
        max_tokens=max_tokens,
        model=model,
        overlap=overlap,
    )

    # Extract from each chunk and aggregate
    return _extract_chunked(
        file_path=file_path,
        chunks=chunks,
        repo_name=repo_name,
        node_type=node_type,
        extraction_method=extraction_method,
        llm_query_fn=llm_query_fn,
        config=config,
        ast_extractor_fn=ast_extractor_fn,
    )


def _extract_single(
    file_path: str,
    file_content: str,
    repo_name: str,
    node_type: str,
    extraction_method: str,
    llm_query_fn: Callable | None,
    config: dict[str, Any],
    chunk_info: Chunk | None = None,
    ast_extractor_fn: ASTExtractorFn | None = None,
) -> dict[str, Any]:
    """Extract from a single file or chunk."""

    if extraction_method == "ast":
        if ast_extractor_fn is None:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": ["AST extraction requested but no ast_extractor_fn provided"],
                "stats": {"total_nodes": 0, "total_edges": 0},
                "llm_details": create_empty_llm_details(),
            }
        return ast_extractor_fn(
            file_path, file_content, repo_name, node_type, chunk_info
        )
    else:  # Default to LLM
        return _extract_with_llm(
            file_path=file_path,
            file_content=file_content,
            repo_name=repo_name,
            node_type=node_type,
            llm_query_fn=llm_query_fn,
            config=config,
            chunk_info=chunk_info,
        )


def _extract_chunked(
    file_path: str,
    chunks: list[Chunk],
    repo_name: str,
    node_type: str,
    extraction_method: str,
    llm_query_fn: Callable | None,
    config: dict[str, Any],
    ast_extractor_fn: ASTExtractorFn | None = None,
) -> dict[str, Any]:
    """Extract from multiple chunks and aggregate results."""
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    all_errors: list[str] = []
    llm_details_list: list[dict[str, Any]] = []

    for chunk in chunks:
        result = _extract_single(
            file_path=file_path,
            file_content=chunk.content,
            repo_name=repo_name,
            node_type=node_type,
            extraction_method=extraction_method,
            llm_query_fn=llm_query_fn,
            config=config,
            chunk_info=chunk,
            ast_extractor_fn=ast_extractor_fn,
        )

        if result.get("data", {}).get("nodes"):
            all_nodes.extend(result["data"]["nodes"])
        if result.get("data", {}).get("edges"):
            all_edges.extend(result["data"]["edges"])
        if result.get("errors"):
            all_errors.extend(result["errors"])
        if result.get("llm_details"):
            llm_details_list.append(result["llm_details"])

    # Deduplicate nodes by node_id
    seen_ids: set[str] = set()
    unique_nodes: list[dict[str, Any]] = []
    for node in all_nodes:
        node_id = node.get("node_id", "")
        if node_id and node_id not in seen_ids:
            seen_ids.add(node_id)
            unique_nodes.append(node)

    return {
        "success": len(unique_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": unique_nodes, "edges": all_edges},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(unique_nodes),
            "total_edges": len(all_edges),
            "chunks_processed": len(chunks),
            "node_types": {node_type: len(unique_nodes)},
        },
        "llm_details": llm_details_list[0]
        if llm_details_list
        else create_empty_llm_details(),
        "chunks_processed": len(chunks),
    }


def _extract_with_llm(
    file_path: str,
    file_content: str,
    repo_name: str,
    node_type: str,
    llm_query_fn: Callable | None,
    config: dict[str, Any],
    chunk_info: Chunk | None = None,
) -> dict[str, Any]:
    """Extract using LLM by delegating to the appropriate module."""

    # Import the appropriate extraction function based on node_type
    extraction_fn = _get_llm_extraction_function(node_type)

    if extraction_fn is None:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Unknown node type for LLM extraction: {node_type}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": create_empty_llm_details(),
        }

    # Add chunk info to file path for context
    effective_path = file_path
    if chunk_info:
        effective_path = (
            f"{file_path} (lines {chunk_info.start_line}-{chunk_info.end_line})"
        )

    return extraction_fn(
        file_path=effective_path,
        file_content=file_content,
        repo_name=repo_name,
        llm_query_fn=llm_query_fn,
        config=config,
    )


def _get_llm_extraction_function(node_type: str) -> Callable | None:
    """Get the LLM extraction function for a node type."""
    # Import here to avoid circular imports
    from . import (
        extract_business_concepts,
        extract_type_definitions,
        extract_methods,
        extract_technologies,
        extract_external_dependencies,
        extract_tests,
    )

    extraction_map = {
        "BusinessConcept": extract_business_concepts,
        "TypeDefinition": extract_type_definitions,
        "Method": extract_methods,
        "Technology": extract_technologies,
        "ExternalDependency": extract_external_dependencies,
        "Test": extract_tests,
    }

    return extraction_map.get(node_type)


__all__ = [
    "extract_with_chunking",
]
