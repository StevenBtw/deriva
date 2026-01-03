"""
Base utilities for extraction modules.

This module provides shared functions and patterns used across all extraction modules:
- Prompt building helpers
- Response parsing utilities
- Node ID generation
- Error handling patterns

All extraction modules should use these utilities to maintain consistency.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from deriva.common import (
    calculate_duration_ms,
    create_empty_llm_details,
    current_timestamp,
    extract_llm_details,
    parse_json_array,
)
from deriva.common.types import LLMDetails, PipelineResult


def strip_chunk_suffix(file_path: str) -> str:
    """
    Strip chunk suffix from file path.

    When files are chunked, paths get "(lines X-Y)" suffix. This strips it
    to get the original file path for node ID generation.

    Args:
        file_path: File path potentially with chunk suffix

    Returns:
        Original file path without chunk suffix

    Examples:
        >>> strip_chunk_suffix("src/app.py (lines 1-100)")
        'src/app.py'
        >>> strip_chunk_suffix("src/app.py")
        'src/app.py'
    """
    return re.sub(r"\s*\(lines \d+-\d+\)$", "", file_path)


def generate_node_id(prefix: str, repo_name: str, identifier: str) -> str:
    """
    Generate a consistent node ID.

    Args:
        prefix: Node type prefix (e.g., 'concept', 'type', 'method')
        repo_name: Repository name
        identifier: Unique identifier within the type

    Returns:
        Formatted node ID string
    """
    # Normalize identifier for consistent IDs
    normalized = identifier.lower().replace(" ", "_").replace("-", "_")
    normalized = "".join(c for c in normalized if c.isalnum() or c == "_")
    return f"{prefix}_{repo_name}_{normalized}"


def generate_edge_id(from_node_id: str, to_node_id: str, relationship_type: str) -> str:
    """
    Generate a consistent edge ID.

    Args:
        from_node_id: Source node ID
        to_node_id: Target node ID
        relationship_type: Type of relationship

    Returns:
        Formatted edge ID string
    """
    rel_type = relationship_type.lower()
    return f"{rel_type}_{from_node_id}_to_{to_node_id}"


def parse_json_response(response_content: str, array_key: str) -> dict[str, Any]:
    """
    Parse and validate LLM JSON response with a specific array key.

    Args:
        response_content: Raw JSON string from LLM
        array_key: Expected key containing the array (e.g., 'concepts', 'types')

    Returns:
        Dictionary with:
            - success: bool
            - data: Parsed items list
            - errors: List of parsing errors
    """
    return parse_json_array(response_content, array_key).to_dict()


def validate_required_fields(
    data: dict[str, Any], required_fields: list[str]
) -> list[str]:
    """
    Validate that required fields are present and non-empty.

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Returns:
        List of error messages (empty if all valid)
    """
    errors = []
    for field in required_fields:
        if field not in data or not data[field]:
            errors.append(f"Missing required field: {field}")
    return errors


def deduplicate_nodes(
    nodes: list[dict[str, Any]], key: str = "node_id"
) -> list[dict[str, Any]]:
    """
    Deduplicate nodes by a key field, preserving order.

    Used when aggregating results from chunked extraction where the same
    node might be extracted from overlapping chunks.

    Args:
        nodes: List of node dictionaries to deduplicate
        key: Field name to use for deduplication (default: "node_id")

    Returns:
        List of unique nodes, preserving first occurrence order
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for node in nodes:
        node_key = node.get(key, "")
        if node_key and node_key not in seen:
            seen.add(node_key)
            unique.append(node)
    return unique


def create_extraction_result(
    success: bool,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    errors: list[str],
    stats: dict[str, Any],
    llm_details: LLMDetails | None = None,
    warnings: list[str] | None = None,
    start_time: datetime | None = None,
) -> PipelineResult:
    """
    Create a standardized extraction result dictionary.

    Args:
        success: Whether the extraction succeeded
        nodes: List of created nodes (mapped to 'elements')
        edges: List of created edges (mapped to 'relationships')
        errors: List of error messages
        stats: Statistics dictionary
        llm_details: Optional LLM call details
        warnings: Optional list of warning messages
        start_time: Optional start time for duration calculation

    Returns:
        Standardized PipelineResult
    """
    timestamp = current_timestamp()
    duration_ms = calculate_duration_ms(start_time) if start_time else 0

    result: PipelineResult = {
        "success": success,
        "elements": nodes,
        "relationships": edges,
        "errors": errors,
        "warnings": warnings or [],
        "stats": stats,
        "stage": "extraction",
        "timestamp": timestamp,
        "duration_ms": duration_ms,
    }

    if llm_details is not None:
        result["llm_details"] = llm_details

    return result


# Backward compatibility alias
extract_llm_details_from_response = extract_llm_details


__all__ = [
    "generate_node_id",
    "generate_edge_id",
    "current_timestamp",
    "parse_json_response",
    "validate_required_fields",
    "deduplicate_nodes",
    "create_extraction_result",
    "create_empty_llm_details",
    "extract_llm_details_from_response",
    "strip_chunk_suffix",
]
