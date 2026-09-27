"""
File extraction - Build File graph nodes from repository filesystem.

This module extracts File nodes representing individual files in the repository.
Integrates with classification to add file_type and subtype properties.
Can also generate TESTS edges based on naming conventions.
"""

from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .base import (
    current_timestamp,
    generate_edge_id,
    is_excluded_path,
    validate_required_fields,
)


def build_file_node(file_metadata: dict[str, Any], repo_name: str) -> dict[str, Any]:
    """
    Build a File graph node from file metadata.

    Args:
        file_metadata: Dictionary containing file metadata
            Expected keys: path, name, extension, size_bytes, last_modified
            Optional keys: file_type, subtype (from classification)
        repo_name: The repository name for node ID generation

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = validate_required_fields(file_metadata, ["path", "name"])

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Build the node structure
    # Use :: separator to avoid conflicts with repo names containing underscores
    path_value = str(file_metadata["path"])
    safe_path = path_value.replace("/", "_").replace("\\", "_")
    node_id = f"file::{repo_name}::{safe_path}"

    node_data = {
        "node_id": node_id,
        "label": "File",
        "properties": {
            "path": file_metadata["path"],
            "name": file_metadata["name"],
            "extension": file_metadata.get("extension", ""),
            "size_bytes": file_metadata.get("size_bytes", 0),
            "file_type": file_metadata.get("file_type", ""),
            "subtype": file_metadata.get("subtype", ""),
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


def _infer_tested_file(test_path: str, all_paths: set[str]) -> str | None:
    """
    Infer which source file a test file is testing based on naming conventions.

    Naming patterns supported:
    - test_foo.py -> foo.py
    - foo_test.py -> foo.py
    - test_foo.py in tests/ -> foo.py in src/ or root
    - foo.spec.js -> foo.js
    - foo.test.js -> foo.js

    Args:
        test_path: Path of the test file
        all_paths: Set of all file paths in the repository

    Returns:
        Path of the inferred source file, or None if not found

    Examples:
        >>> all_files = {"src/app.py", "tests/test_app.py", "utils.py"}
        >>> _infer_tested_file("tests/test_app.py", all_files)
        'src/app.py'
        >>> _infer_tested_file("tests/test_unknown.py", all_files)
        None
    """
    path = Path(test_path)
    name = path.stem  # filename without extension
    ext = path.suffix
    parent = str(path.parent).replace("\\", "/")

    candidates = []

    # Pattern: test_foo.py -> foo.py
    if name.startswith("test_"):
        source_name = name[5:]  # Remove "test_"
        candidates.append(f"{parent}/{source_name}{ext}")

    # Pattern: foo_test.py -> foo.py
    if name.endswith("_test"):
        source_name = name[:-5]  # Remove "_test"
        candidates.append(f"{parent}/{source_name}{ext}")

    # Pattern: foo.spec.js or foo.test.js -> foo.js
    if ".spec" in name or ".test" in name:
        source_name = re.sub(r"\.(spec|test)$", "", name)
        candidates.append(f"{parent}/{source_name}{ext}")

    # Try looking in parallel directories (tests/ -> src/, tests/ -> root)
    if "/tests/" in parent or "/test/" in parent or parent.startswith("tests"):
        base_name = name
        if name.startswith("test_"):
            base_name = name[5:]
        elif name.endswith("_test"):
            base_name = name[:-5]

        # Try src/ directory
        src_parent = re.sub(r"tests?/?", "src/", parent)
        candidates.append(f"{src_parent}/{base_name}{ext}")

        # Try root directory
        candidates.append(f"{base_name}{ext}")

        # Try same-level directory (if tests is subdirectory)
        parent_parent = str(Path(parent).parent).replace("\\", "/")
        if parent_parent and parent_parent != ".":
            candidates.append(f"{parent_parent}/{base_name}{ext}")

    # Normalize and check candidates
    for candidate in candidates:
        normalized = candidate.lstrip("./").replace("//", "/")
        if normalized in all_paths:
            return normalized

    return None


def extract_files(
    repo_path: str,
    repo_name: str,
    classification_lookup: dict[str, dict[str, str]] | None = None,
    excluded_dirs: Collection[str] = (".git",),
) -> dict[str, Any]:
    """
    Extract all files from a repository path.

    Scans the repository filesystem and builds File nodes for each file
    found outside excluded directories (dependency and tool directories). Also creates CONTAINS relationships
    and optionally TESTS edges for test files.

    Args:
        repo_path: Full path to the repository (from RepositoryManager)
        repo_name: Repository name for node ID generation
        classification_lookup: Optional dict mapping file paths to classification
            info (file_type, subtype). If provided, adds classification data to nodes.
        excluded_dirs: Directory names whose contents are skipped (whole path segments)

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
    file_paths_set: set[str] = set()  # For test -> source matching

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

        # First pass: collect all file paths for test matching
        for file_path in repo_path_obj.rglob("*"):
            if file_path.is_dir() or is_excluded_path(
                file_path.relative_to(repo_path_obj).as_posix(), excluded_dirs
            ):
                continue
            rel_path = file_path.relative_to(repo_path_obj)
            file_paths_set.add(str(rel_path).replace("\\", "/"))

        # Second pass: build nodes and edges
        test_edges: list[dict[str, Any]] = []

        for file_path in repo_path_obj.rglob("*"):
            if file_path.is_dir() or is_excluded_path(
                file_path.relative_to(repo_path_obj).as_posix(), excluded_dirs
            ):
                continue

            try:
                rel_path = file_path.relative_to(repo_path_obj)
                rel_path_str = str(rel_path).replace("\\", "/")

                file_stats = file_path.stat()

                # Get classification data if available
                classification = {}
                if classification_lookup and rel_path_str in classification_lookup:
                    classification = classification_lookup[rel_path_str]

                file_metadata = {
                    "path": rel_path_str,
                    "name": file_path.name,
                    "extension": file_path.suffix,
                    "size_bytes": file_stats.st_size,
                    "file_type": classification.get("file_type", ""),
                    "subtype": classification.get("subtype", ""),
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
                            f"dir::{repo_name}::{parent_path.replace('/', '_')}"
                        )

                    edge = {
                        "edge_id": generate_edge_id(
                            from_node_id, node_data["node_id"], "CONTAINS"
                        ),
                        "from_node_id": from_node_id,
                        "to_node_id": node_data["node_id"],
                        "relationship_type": "CONTAINS",
                        "properties": {"created_at": current_timestamp()},
                    }
                    edges.append(edge)

                    # Check for TESTS relationship
                    if classification.get("file_type") == "test":
                        tested_path = _infer_tested_file(rel_path_str, file_paths_set)
                        if tested_path:
                            safe_tested = tested_path.replace("/", "_")
                            tested_node_id = f"file::{repo_name}::{safe_tested}"
                            test_edge = {
                                "edge_id": generate_edge_id(
                                    node_data["node_id"], tested_node_id, "TESTS"
                                ),
                                "from_node_id": node_data["node_id"],
                                "to_node_id": tested_node_id,
                                "relationship_type": "TESTS",
                                "properties": {
                                    "inferred": True,
                                    "created_at": current_timestamp(),
                                },
                            }
                            test_edges.append(test_edge)
                else:
                    errors.extend(result["errors"])

            except Exception as e:
                errors.append(f"Error processing file {file_path}: {str(e)}")

        # Add test edges
        edges.extend(test_edges)

        return {
            "success": len(errors) == 0 or len(nodes) > 0,
            "data": {"nodes": nodes, "edges": edges},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"File": len(nodes)},
                "edge_types": {
                    "CONTAINS": len(edges) - len(test_edges),
                    "TESTS": len(test_edges),
                },
            },
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during file extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
        }
