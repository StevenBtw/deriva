"""
File extraction - Build File graph nodes from repository filesystem.

This module extracts File nodes representing individual files in the repository.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .base import current_timestamp


def build_file_node(file_metadata: dict[str, Any], repo_name: str) -> dict[str, Any]:
    """
    Build a File graph node from file metadata.

    Args:
        file_metadata: Dictionary containing file metadata
            Expected keys: path, name, extension, size_bytes, language, last_modified
        repo_name: The repository name for node ID generation

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = []

    # Validate required fields
    required_fields = ["path", "name"]
    for field in required_fields:
        if field not in file_metadata or not file_metadata[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Build the node structure
    path_value = str(file_metadata["path"])
    safe_path = path_value.replace("/", "_").replace("\\", "_")
    node_data = {
        "node_id": f"file_{repo_name}_{safe_path}",
        "label": "File",
        "properties": {
            "path": file_metadata["path"],
            "name": file_metadata["name"],
            "extension": file_metadata.get("extension", ""),
            "size_bytes": file_metadata.get("size_bytes", 0),
            "language": file_metadata.get("language", ""),
            "last_modified": file_metadata.get("last_modified", ""),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "File"},
    }


def extract_files(repo_path: str, repo_name: str) -> dict[str, Any]:
    """
    Extract all files from a repository path.

    Scans the repository filesystem and builds File nodes for each file
    found (excluding .git directories). Also creates CONTAINS relationships.

    Args:
        repo_path: Full path to the repository (from RepositoryManager)
        repo_name: Repository name for node ID generation

    Returns:
        Dictionary with:
            - success: bool - Whether the extraction succeeded
            - data: Dict - Contains 'nodes' list and 'edges' list
            - errors: List[str] - Any errors encountered
            - stats: Dict - Statistics about the extraction
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        repo_path_obj = Path(repo_path)

        if not repo_path_obj.exists():
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"Repository path does not exist: {repo_path}"],
                "stats": {"total_nodes": 0, "total_edges": 0},
            }

        repo_id = f"repo_{repo_name}"

        # Walk through all files
        for file_path in repo_path_obj.rglob("*"):
            # Skip directories and files in .git
            if file_path.is_dir() or ".git" in file_path.parts:
                continue

            try:
                rel_path = file_path.relative_to(repo_path_obj)
                rel_path_str = str(rel_path).replace("\\", "/")

                file_stats = file_path.stat()

                file_metadata = {
                    "path": rel_path_str,
                    "name": file_path.name,
                    "extension": file_path.suffix,
                    "size_bytes": file_stats.st_size,
                    "language": "",  # Will be filled by classification
                    "last_modified": datetime.fromtimestamp(
                        file_stats.st_mtime
                    ).isoformat()
                    + "Z",
                }

                result = build_file_node(file_metadata, repo_name)

                if result["success"]:
                    node_data = result["data"]
                    nodes.append(node_data)

                    # Create CONTAINS relationship
                    if rel_path.parent == Path("."):
                        from_node_id = repo_id
                    else:
                        parent_path = str(rel_path.parent).replace("\\", "/")
                        from_node_id = (
                            f"dir_{repo_name}_{parent_path.replace('/', '_')}"
                        )

                    edge = {
                        "edge_id": f"contains_{from_node_id}_to_{node_data['node_id']}",
                        "from_node_id": from_node_id,
                        "to_node_id": node_data["node_id"],
                        "relationship_type": "CONTAINS",
                        "properties": {"created_at": current_timestamp()},
                    }
                    edges.append(edge)
                else:
                    errors.extend(result["errors"])

            except Exception as e:
                errors.append(f"Error processing file {file_path}: {str(e)}")

        return {
            "success": len(errors) == 0 or len(nodes) > 0,
            "data": {"nodes": nodes, "edges": edges},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"File": len(nodes)},
            },
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during file extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
        }
