"""Tests for modules.extraction.directory module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from deriva.modules.extraction.directory import (
    build_directory_node,
    extract_directories,
)


class TestBuildDirectoryNode:
    """Tests for build_directory_node function."""

    def test_valid_directory_metadata(self):
        """Should create valid directory node from metadata."""
        metadata = {
            "path": "src/utils",
            "name": "utils",
            "file_count": 5,
            "subdirectory_count": 2,
            "total_size_bytes": 10240,
        }

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["nodes_created"] == 1
        assert result["stats"]["node_type"] == "Directory"

        data = result["data"]
        assert data["node_id"] == "dir_myrepo_src_utils"
        assert data["label"] == "Directory"
        assert data["properties"]["path"] == "src/utils"
        assert data["properties"]["name"] == "utils"
        assert data["properties"]["file_count"] == 5
        assert data["properties"]["subdirectory_count"] == 2
        assert data["properties"]["total_size_bytes"] == 10240
        assert "extracted_at" in data["properties"]

    def test_missing_path(self):
        """Should fail when path is missing."""
        metadata = {"name": "utils"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: path" in result["errors"]
        assert result["data"] == {}
        assert result["stats"]["nodes_created"] == 0

    def test_missing_name(self):
        """Should fail when name is missing."""
        metadata = {"path": "src/utils"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: name" in result["errors"]

    def test_empty_path(self):
        """Should fail when path is empty string."""
        metadata = {"path": "", "name": "utils"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: path" in result["errors"]

    def test_optional_fields_default_to_zero(self):
        """Should use defaults for optional fields."""
        metadata = {"path": "src", "name": "src"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is True
        props = result["data"]["properties"]
        assert props["file_count"] == 0
        assert props["subdirectory_count"] == 0
        assert props["total_size_bytes"] == 0

    def test_path_with_backslashes_normalized(self):
        """Should normalize backslashes in path for node ID."""
        metadata = {"path": "src\\utils\\helpers", "name": "helpers"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is True
        # Node ID should have underscores instead of slashes
        assert result["data"]["node_id"] == "dir_myrepo_src_utils_helpers"

    def test_path_with_forward_slashes_normalized(self):
        """Should normalize forward slashes in path for node ID."""
        metadata = {"path": "src/utils/helpers", "name": "helpers"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["data"]["node_id"] == "dir_myrepo_src_utils_helpers"


class TestExtractDirectories:
    """Tests for extract_directories function."""

    def test_nonexistent_path(self):
        """Should fail gracefully for nonexistent path."""
        result = extract_directories("/nonexistent/path/that/does/not/exist", "myrepo")

        assert result["success"] is False
        assert "does not exist" in result["errors"][0]
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []
        assert result["stats"]["total_nodes"] == 0

    def test_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["data"]["nodes"] == []
            assert result["data"]["edges"] == []
            assert result["stats"]["total_nodes"] == 0

    def test_single_directory(self):
        """Should extract single subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory
            subdir = Path(tmpdir) / "src"
            subdir.mkdir()

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1
            assert len(result["data"]["nodes"]) == 1
            assert len(result["data"]["edges"]) == 1

            node = result["data"]["nodes"][0]
            assert node["label"] == "Directory"
            assert node["properties"]["name"] == "src"
            assert node["properties"]["path"] == "src"

            edge = result["data"]["edges"][0]
            assert edge["relationship_type"] == "CONTAINS"
            assert edge["from_node_id"] == "repo_myrepo"

    def test_nested_directories(self):
        """Should extract nested directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure: src/utils/helpers
            helpers = Path(tmpdir) / "src" / "utils" / "helpers"
            helpers.mkdir(parents=True)

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 3  # src, utils, helpers
            assert len(result["data"]["edges"]) == 3

            # Verify hierarchy in edges
            node_ids = {n["node_id"] for n in result["data"]["nodes"]}
            assert "dir_myrepo_src" in node_ids
            assert "dir_myrepo_src_utils" in node_ids
            assert "dir_myrepo_src_utils_helpers" in node_ids

    def test_skips_git_directory(self):
        """Should skip .git directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .git and src directories
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            (git_dir / "objects").mkdir()

            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            # Should only have src, not .git or its contents
            assert result["stats"]["total_nodes"] == 1
            node_names = [n["properties"]["name"] for n in result["data"]["nodes"]]
            assert "src" in node_names
            assert ".git" not in node_names
            assert "objects" not in node_names

    def test_counts_files_in_directory(self):
        """Should count files in each directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            src.mkdir()

            # Create 3 files
            (src / "main.py").touch()
            (src / "utils.py").touch()
            (src / "config.yaml").touch()

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            node = result["data"]["nodes"][0]
            assert node["properties"]["file_count"] == 3

    def test_counts_subdirectories(self):
        """Should count subdirectories in each directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            src.mkdir()

            # Create 2 subdirectories
            (src / "utils").mkdir()
            (src / "models").mkdir()

            result = extract_directories(tmpdir, "myrepo")

            # Find the src node
            src_nodes = [
                n for n in result["data"]["nodes"] if n["properties"]["name"] == "src"
            ]
            assert len(src_nodes) == 1
            assert src_nodes[0]["properties"]["subdirectory_count"] == 2

    def test_calculates_total_size(self):
        """Should calculate total size of files in directory tree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "src"
            src.mkdir()

            # Create a file with known content
            test_file = src / "test.txt"
            test_file.write_text("Hello, World!")  # 13 bytes

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            node = result["data"]["nodes"][0]
            assert node["properties"]["total_size_bytes"] == 13

    def test_parent_directory_relationship(self):
        """Should create correct parent-child relationships."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create src/utils
            utils = Path(tmpdir) / "src" / "utils"
            utils.mkdir(parents=True)

            result = extract_directories(tmpdir, "myrepo")

            # Find the edge from src to utils
            edges_to_utils = [
                e
                for e in result["data"]["edges"]
                if e["to_node_id"] == "dir_myrepo_src_utils"
            ]
            assert len(edges_to_utils) == 1
            assert edges_to_utils[0]["from_node_id"] == "dir_myrepo_src"

    def test_multiple_sibling_directories(self):
        """Should handle multiple sibling directories correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "docs").mkdir()

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 3

            # All should have repo as parent
            repo_edges = [
                e for e in result["data"]["edges"] if e["from_node_id"] == "repo_myrepo"
            ]
            assert len(repo_edges) == 3
