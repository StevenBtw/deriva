"""
Directory extraction - Build Directory graph nodes from repository filesystem.

This module extracts Directory nodes representing folders in the repository structure.
Directories form the hierarchical container structure of the graph, with CONTAINS
relationships linking parent directories to child directories and files.

Note:
    Excluded directories (the excluded_directories setting) and their contents are
    skipped without being walked.

Example:
    >>> from deriva.modules.extraction import extract_directories
    >>> result = extract_directories("/path/to/repo", "my-project")
    >>> result["stats"]["total_nodes"]
    15
    >>> result["data"]["nodes"][0]["properties"]["path"]
    'src'
"""

from __future__ import annotations

import os
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .base import (
    current_timestamp,
    generate_edge_id,
    is_excluded_path,
    validate_required_fields,
)


def build_directory_node(dir_metadata: dict[str, Any], repo_name: str) -> dict[str, Any]:
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
    errors = validate_required_fields(dir_metadata, ["path", "name"])

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Build the node structure
    # Use :: separator to avoid conflicts with repo names containing underscores
    path_value = str(dir_metadata["path"])
    safe_path = path_value.replace("/", "_").replace("\\", "_")
    node_id = f"dir::{repo_name}::{safe_path}"

    node_data = {
        "node_id": node_id,
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


def _walk_directories(root: Path, excluded_dirs: Collection[str]) -> dict[Path, tuple[int, int, int]]:
    """Every non-excluded directory below ``root`` with (file count, subdirectory count, total size).

    Same directories in the same order as filtering ``root.rglob("*")``, but every
    directory is scanned once and excluded directories are never entered. The file
    count covers the directory's own files; the total size covers its subtree without
    files on an excluded path. Like ``rglob``, symlinked directories are listed but
    not recursed into.
    """
    scans: dict[Path, list[os.DirEntry[str]]] = {}

    def scan(directory: Path) -> list[os.DirEntry[str]]:
        if directory not in scans:
            with os.scandir(directory) as entries:
                scans[directory] = list(entries)
        return scans[directory]

    def excluded(entry: os.DirEntry[str]) -> bool:
        return is_excluded_path(Path(entry.path).relative_to(root).as_posix(), excluded_dirs)

    def listed(directory: Path) -> list[Path]:
        return [Path(e.path) for e in scan(directory) if e.is_dir() and not excluded(e)]

    # rglob("*") lists a directory's children as soon as the directory is found and
    # recurses through a stack (last found, first scanned)
    order = listed(root)
    stack = [root]
    while stack:
        for entry in scan(stack.pop()):
            if entry.is_dir(follow_symlinks=False) and not excluded(entry):
                order.extend(listed(Path(entry.path)))
                stack.append(Path(entry.path))

    totals: dict[Path, int] = {}

    def total(directory: Path) -> int:
        if directory not in totals:
            size = 0
            for entry in scan(directory):
                if entry.is_file():
                    if not excluded(entry):
                        size += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False) and not excluded(entry):
                    size += total(Path(entry.path))
            totals[directory] = size
        return totals[directory]

    return {
        d: (
            sum(1 for e in scan(d) if e.is_file()),
            sum(1 for e in scan(d) if e.is_dir() and e.name not in excluded_dirs),
            total(d),
        )
        for d in order
    }


def extract_directories(repo_path: str, repo_name: str, excluded_dirs: Collection[str] = (".git",)) -> dict[str, Any]:
    """
    Extract all directories from a repository path.

    Scans the repository filesystem and builds Directory nodes for each directory
    found, skipping excluded directories (dependency and tool directories) and
    everything below them. Also creates CONTAINS relationships.

    Args:
        repo_path: Full path to the repository (from RepositoryManager)
        repo_name: Repository name for node ID generation
        excluded_dirs: Directory names skipped with their contents (whole path segments)

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

        repo_id = f"repo::{repo_name}"

        # One walk (excluded directories are never entered), then the directories in order
        for dir_path, (file_count, subdir_count, total_size) in _walk_directories(repo_path_obj, excluded_dirs).items():
            try:
                rel_path = dir_path.relative_to(repo_path_obj)
                rel_path_str = str(rel_path).replace("\\", "/")

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
                        from_node_id = f"dir::{repo_name}::{parent_path.replace('/', '_')}"

                    edge = {
                        "edge_id": generate_edge_id(from_node_id, node_data["node_id"], "CONTAINS"),
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
