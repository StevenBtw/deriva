"""Tests for modules.extraction.file module."""

from __future__ import annotations

import tempfile
from pathlib import Path

from deriva.modules.extraction.file import (
    build_file_node,
    extract_files,
)


class TestBuildFileNode:
    """Tests for build_file_node function."""

    def test_valid_file_metadata(self):
        """Should create valid file node from metadata."""
        metadata = {
            "path": "src/main.py",
            "name": "main.py",
            "extension": ".py",
            "size_bytes": 1024,
            "language": "python",
            "last_modified": "2024-01-15T10:30:00Z",
        }

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["nodes_created"] == 1
        assert result["stats"]["node_type"] == "File"

        data = result["data"]
        assert data["node_id"] == "file_myrepo_src_main.py"
        assert data["label"] == "File"
        assert data["properties"]["path"] == "src/main.py"
        assert data["properties"]["name"] == "main.py"
        assert data["properties"]["extension"] == ".py"
        assert data["properties"]["size_bytes"] == 1024
        assert data["properties"]["language"] == "python"
        assert data["properties"]["last_modified"] == "2024-01-15T10:30:00Z"
        assert "extracted_at" in data["properties"]

    def test_missing_path(self):
        """Should fail when path is missing."""
        metadata = {"name": "main.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: path" in result["errors"]
        assert result["data"] == {}
        assert result["stats"]["nodes_created"] == 0

    def test_missing_name(self):
        """Should fail when name is missing."""
        metadata = {"path": "src/main.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: name" in result["errors"]

    def test_empty_path(self):
        """Should fail when path is empty string."""
        metadata = {"path": "", "name": "main.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is False
        assert "Missing required field: path" in result["errors"]

    def test_optional_fields_default_values(self):
        """Should use defaults for optional fields."""
        metadata = {"path": "src/main.py", "name": "main.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is True
        props = result["data"]["properties"]
        assert props["extension"] == ""
        assert props["size_bytes"] == 0
        assert props["language"] == ""
        assert props["last_modified"] == ""

    def test_path_with_backslashes_normalized(self):
        """Should normalize backslashes in path for node ID."""
        metadata = {"path": "src\\utils\\helpers.py", "name": "helpers.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["data"]["node_id"] == "file_myrepo_src_utils_helpers.py"

    def test_path_with_forward_slashes_normalized(self):
        """Should normalize forward slashes in path for node ID."""
        metadata = {"path": "src/utils/helpers.py", "name": "helpers.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["data"]["node_id"] == "file_myrepo_src_utils_helpers.py"


class TestExtractFiles:
    """Tests for extract_files function."""

    def test_nonexistent_path(self):
        """Should fail gracefully for nonexistent path."""
        result = extract_files("/nonexistent/path/that/does/not/exist", "myrepo")

        assert result["success"] is False
        assert "does not exist" in result["errors"][0]
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []
        assert result["stats"]["total_nodes"] == 0

    def test_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["data"]["nodes"] == []
            assert result["data"]["edges"] == []
            assert result["stats"]["total_nodes"] == 0

    def test_single_file_in_root(self):
        """Should extract single file in root directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file
            test_file = Path(tmpdir) / "main.py"
            test_file.write_text("print('hello')")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1
            assert len(result["data"]["nodes"]) == 1
            assert len(result["data"]["edges"]) == 1

            node = result["data"]["nodes"][0]
            assert node["label"] == "File"
            assert node["properties"]["name"] == "main.py"
            assert node["properties"]["path"] == "main.py"
            assert node["properties"]["extension"] == ".py"

            edge = result["data"]["edges"][0]
            assert edge["relationship_type"] == "CONTAINS"
            assert edge["from_node_id"] == "repo_myrepo"

    def test_file_in_subdirectory(self):
        """Should extract file from subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create subdirectory and file
            src = Path(tmpdir) / "src"
            src.mkdir()
            (src / "main.py").write_text("print('hello')")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1

            node = result["data"]["nodes"][0]
            assert node["properties"]["path"] == "src/main.py"

            edge = result["data"]["edges"][0]
            assert edge["from_node_id"] == "dir_myrepo_src"

    def test_skips_git_files(self):
        """Should skip files in .git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .git directory with files
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("[core]")
            (git_dir / "HEAD").write_text("ref: refs/heads/main")

            # Create a normal file
            (Path(tmpdir) / "main.py").write_text("print('hello')")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1
            file_names = [n["properties"]["name"] for n in result["data"]["nodes"]]
            assert "main.py" in file_names
            assert "config" not in file_names
            assert "HEAD" not in file_names

    def test_multiple_files(self):
        """Should extract multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("main")
            (root / "utils.py").write_text("utils")
            (root / "README.md").write_text("# Readme")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 3
            assert result["stats"]["node_types"]["File"] == 3

    def test_nested_files(self):
        """Should extract files from nested directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            helpers = Path(tmpdir) / "src" / "utils" / "helpers"
            helpers.mkdir(parents=True)
            (helpers / "string_utils.py").write_text("def trim(): pass")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            node = result["data"]["nodes"][0]
            assert node["properties"]["path"] == "src/utils/helpers/string_utils.py"

            edge = result["data"]["edges"][0]
            assert edge["from_node_id"] == "dir_myrepo_src_utils_helpers"

    def test_file_extension_extracted(self):
        """Should extract file extension correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "script.py").touch()
            (root / "config.yaml").touch()
            (root / "README.md").touch()
            (root / "Dockerfile").touch()  # No extension

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            extensions = {n["properties"]["name"]: n["properties"]["extension"] for n in result["data"]["nodes"]}
            assert extensions["script.py"] == ".py"
            assert extensions["config.yaml"] == ".yaml"
            assert extensions["README.md"] == ".md"
            assert extensions["Dockerfile"] == ""

    def test_file_size_extracted(self):
        """Should extract file size in bytes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Hello, World!")  # 13 bytes

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            node = result["data"]["nodes"][0]
            assert node["properties"]["size_bytes"] == 13

    def test_last_modified_extracted(self):
        """Should extract last modified timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            node = result["data"]["nodes"][0]
            # Should be ISO format with Z suffix
            assert node["properties"]["last_modified"].endswith("Z")
            assert "T" in node["properties"]["last_modified"]

    def test_parent_directory_relationship_for_nested(self):
        """Should create correct parent-child relationships for nested files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            utils = Path(tmpdir) / "src" / "utils"
            utils.mkdir(parents=True)
            (utils / "helpers.py").write_text("code")

            result = extract_files(tmpdir, "myrepo")

            edge = result["data"]["edges"][0]
            assert edge["from_node_id"] == "dir_myrepo_src_utils"
            assert edge["to_node_id"] == "file_myrepo_src_utils_helpers.py"
            assert edge["relationship_type"] == "CONTAINS"

    def test_edge_has_created_at_timestamp(self):
        """Should include timestamp in edge properties."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").touch()

            result = extract_files(tmpdir, "myrepo")

            edge = result["data"]["edges"][0]
            assert "created_at" in edge["properties"]
            assert edge["properties"]["created_at"].endswith("Z")
