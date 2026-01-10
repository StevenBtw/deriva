"""Tests for adapters.repository.models module."""

from __future__ import annotations

from deriva.adapters.repository.models import (
    FileNode,
    RepositoryInfo,
    RepositoryMetadata,
)


class TestRepositoryInfo:
    """Tests for RepositoryInfo dataclass."""

    def test_creates_with_required_fields(self):
        """Should create with required fields."""
        info = RepositoryInfo(name="myrepo", path="/path/to/repo")
        assert info.name == "myrepo"
        assert info.path == "/path/to/repo"

    def test_has_optional_fields_with_defaults(self):
        """Should have default values for optional fields."""
        info = RepositoryInfo(name="test", path="/test")
        assert info.url is None
        assert info.branch is None
        assert info.last_commit is None
        assert info.is_dirty is False
        assert info.size_mb == 0.0
        assert info.cloned_at is None

    def test_to_dict_returns_dictionary(self):
        """Should convert to dictionary."""
        info = RepositoryInfo(
            name="myrepo",
            path="/path",
            url="https://github.com/user/repo",
            branch="main",
        )
        result = info.to_dict()
        assert result["name"] == "myrepo"
        assert result["path"] == "/path"
        assert result["url"] == "https://github.com/user/repo"
        assert result["branch"] == "main"


class TestRepositoryMetadata:
    """Tests for RepositoryMetadata dataclass."""

    def test_creates_with_all_fields(self):
        """Should create with all required fields."""
        metadata = RepositoryMetadata(
            name="myrepo",
            url="https://github.com/user/repo",
            description="A test repo",
            total_size_mb=10.5,
            total_files=100,
            total_directories=20,
            languages={"Python": 80, "JavaScript": 20},
            created_at="2024-01-01",
            last_updated="2024-06-01",
            default_branch="main",
        )
        assert metadata.name == "myrepo"
        assert metadata.total_files == 100
        assert metadata.languages["Python"] == 80

    def test_to_dict_returns_dictionary(self):
        """Should convert to dictionary."""
        metadata = RepositoryMetadata(
            name="test",
            url="https://test.com",
            description=None,
            total_size_mb=5.0,
            total_files=50,
            total_directories=10,
            languages={},
            created_at="2024-01-01",
            last_updated="2024-01-01",
            default_branch="main",
        )
        result = metadata.to_dict()
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["total_files"] == 50


class TestFileNode:
    """Tests for FileNode dataclass."""

    def test_creates_file_node(self):
        """Should create file node."""
        node = FileNode(
            name="test.py",
            path="/src/test.py",
            type="file",
            size_bytes=1024,
        )
        assert node.name == "test.py"
        assert node.type == "file"
        assert node.size_bytes == 1024

    def test_creates_directory_node(self):
        """Should create directory node with children."""
        child = FileNode(name="child.py", path="/src/child.py", type="file")
        node = FileNode(
            name="src",
            path="/src",
            type="directory",
            children=[child],
        )
        assert node.type == "directory"
        assert node.children is not None
        assert len(node.children) == 1

    def test_to_dict_returns_dictionary(self):
        """Should convert to dictionary."""
        node = FileNode(name="test.py", path="/test.py", type="file")
        result = node.to_dict()
        assert result["name"] == "test.py"
        assert result["type"] == "file"

    def test_to_dict_converts_children_recursively(self):
        """Should convert children recursively."""
        child = FileNode(name="child.py", path="/src/child.py", type="file")
        node = FileNode(
            name="src",
            path="/src",
            type="directory",
            children=[child],
        )
        result = node.to_dict()
        assert "children" in result
        assert result["children"][0]["name"] == "child.py"
