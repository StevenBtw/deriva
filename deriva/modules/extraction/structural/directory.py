"""
Directory extraction - Build Directory graph nodes from repository filesystem.

This module extracts Directory nodes representing folders in the repository structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..base import current_timestamp


def build_directory_node(
    dir_metadata: dict[str, Any], repo_name: str
) -> dict[str, Any]:
    """
    Build a Directory graph node from directory metadata.

    Args:
        dir_metadata: Dictionary containing directory metadata
            Expected keys: path, name, file_count, subdirectory_count, total_size_bytes
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
        if field not in dir_metadata or not dir_metadata[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Build the node structure
    path_value = str(dir_metadata["path"])
    safe_path = path_value.replace("/", "_").replace("\\", "_")
    node_data = {
        "node_id": f"dir_{repo_name}_{safe_path}",
        "label": "Directory",
        "properties": {
            "path": dir_metadata["path"],
            "name": dir_metadata["name"],
            "file_count": dir_metadata.get("file_count", 0),
            "subdirectory_count": dir_metadata.get("subdirectory_count", 0),
            "total_size_bytes": dir_metadata.get("total_size_bytes", 0),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "Directory"},
    }


def extract_directories(repo_path: str, repo_name: str) -> dict[str, Any]:
    """
    Extract all directories from a repository path.

    Scans the repository filesystem and builds Directory nodes for each directory
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

        # Walk through all directories
        for dir_path in repo_path_obj.rglob("*"):
            # Skip non-directories and .git directories
            if not dir_path.is_dir() or ".git" in dir_path.parts:
                continue

            try:
                rel_path = dir_path.relative_to(repo_path_obj)
                rel_path_str = str(rel_path).replace("\\", "/")

                # Count files and subdirectories
                file_count = len([f for f in dir_path.iterdir() if f.is_file()])
                subdir_count = len(
                    [
                        d
                        for d in dir_path.iterdir()
                        if d.is_dir() and ".git" not in d.parts
                    ]
                )

                # Calculate total size
                total_size = sum(
                    f.stat().st_size for f in dir_path.rglob("*") if f.is_file()
                )

                dir_metadata = {
                    "path": rel_path_str,
                    "name": dir_path.name,
                    "file_count": file_count,
                    "subdirectory_count": subdir_count,
                    "total_size_bytes": total_size,
                }

                result = build_directory_node(dir_metadata, repo_name)

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
                errors.append(f"Error processing directory {dir_path}: {str(e)}")

        return {
            "success": len(errors) == 0 or len(nodes) > 0,
            "data": {"nodes": nodes, "edges": edges},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"Directory": len(nodes)},
            },
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during directory extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
        }
