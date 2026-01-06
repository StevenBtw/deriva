"""
Repository extraction - Build Repository graph node from repository metadata.

This module extracts the root Repository node that represents the analyzed codebase.
"""

from __future__ import annotations

from typing import Any

from .base import current_timestamp, validate_required_fields


def build_repository_node(repo_metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Build a Repository graph node from repository metadata.

    This is the root node in the graph - represents the analyzed repository.

    Args:
        repo_metadata: Dictionary containing repository metadata from RepositoryManager
            Expected keys: name, url, description, total_size_mb, total_files,
                          total_directories, languages, created_at, last_updated, default_branch

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = validate_required_fields(repo_metadata, ["name", "url"])

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Build the node structure
    node_data = {
        "node_id": f"repo_{repo_metadata['name']}",
        "label": "Repository",
        "properties": {
            "name": repo_metadata["name"],
            "url": repo_metadata["url"],
            "description": repo_metadata.get("description", ""),
            "total_size_mb": repo_metadata.get("total_size_mb", 0.0),
            "total_files": repo_metadata.get("total_files", 0),
            "total_directories": repo_metadata.get("total_directories", 0),
            "languages": repo_metadata.get("languages", {}),
            "created_at": repo_metadata.get("created_at", ""),
            "last_updated": repo_metadata.get("last_updated", ""),
            "default_branch": repo_metadata.get("default_branch", "main"),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "Repository"},
    }


def extract_repository(repo_metadata: dict[str, Any]) -> dict[str, Any]:
    """
    High-level function to extract repository graph data.

    This is the entry point for repository extraction. Builds the root Repository node.

    Args:
        repo_metadata: Repository metadata dictionary from RepositoryManager

    Returns:
        Dictionary with:
            - success: bool - Whether the extraction succeeded
            - data: Dict - Contains 'nodes' list and 'edges' list
            - errors: List[str] - Any errors encountered
            - stats: Dict - Statistics about the extraction
    """
    repo_result = build_repository_node(repo_metadata)

    if not repo_result["success"]:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": repo_result["errors"],
            "stats": {"total_nodes": 0, "total_edges": 0},
        }

    nodes = [repo_result["data"]]

    return {
        "success": True,
        "data": {"nodes": nodes, "edges": []},
        "errors": [],
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": 0,
            "node_types": {"Repository": 1},
        },
    }
