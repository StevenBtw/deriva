"""Tests for modules.extraction.repository module."""

from __future__ import annotations

from deriva.modules.extraction.repository import (
    build_repository_node,
    extract_repository,
)


class TestBuildRepositoryNode:
    """Tests for build_repository_node function."""

    def test_valid_repository_metadata(self):
        """Should create valid repository node from metadata."""
        metadata = {
            "name": "myproject",
            "url": "https://github.com/user/myproject.git",
            "description": "A test project",
            "total_size_mb": 15.5,
            "total_files": 120,
            "total_directories": 25,
            "languages": {"Python": 80, "JavaScript": 20},
            "created_at": "2024-01-01T00:00:00Z",
            "last_updated": "2024-06-15T10:30:00Z",
            "default_branch": "main",
        }

        result = build_repository_node(metadata)

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["nodes_created"] == 1
        assert result["stats"]["node_type"] == "Repository"

        data = result["data"]
        assert data["node_id"] == "repo_myproject"
        assert data["label"] == "Repository"
        assert data["properties"]["name"] == "myproject"
        assert data["properties"]["url"] == "https://github.com/user/myproject.git"
        assert data["properties"]["description"] == "A test project"
        assert data["properties"]["total_size_mb"] == 15.5
        assert data["properties"]["total_files"] == 120
        assert data["properties"]["total_directories"] == 25
        assert data["properties"]["languages"] == {"Python": 80, "JavaScript": 20}
        assert data["properties"]["created_at"] == "2024-01-01T00:00:00Z"
        assert data["properties"]["last_updated"] == "2024-06-15T10:30:00Z"
        assert data["properties"]["default_branch"] == "main"
        assert "extracted_at" in data["properties"]

    def test_missing_name(self):
        """Should fail when name is missing."""
        metadata = {"url": "https://github.com/user/myproject.git"}

        result = build_repository_node(metadata)

        assert result["success"] is False
        assert "Missing required field: name" in result["errors"]
        assert result["data"] == {}
        assert result["stats"]["nodes_created"] == 0

    def test_missing_url(self):
        """Should fail when url is missing."""
        metadata = {"name": "myproject"}

        result = build_repository_node(metadata)

        assert result["success"] is False
        assert "Missing required field: url" in result["errors"]

    def test_empty_name(self):
        """Should fail when name is empty string."""
        metadata = {"name": "", "url": "https://github.com/user/myproject.git"}

        result = build_repository_node(metadata)

        assert result["success"] is False
        assert "Missing required field: name" in result["errors"]

    def test_empty_url(self):
        """Should fail when url is empty string."""
        metadata = {"name": "myproject", "url": ""}

        result = build_repository_node(metadata)

        assert result["success"] is False
        assert "Missing required field: url" in result["errors"]

    def test_multiple_missing_fields(self):
        """Should report all missing fields."""
        metadata = {}

        result = build_repository_node(metadata)

        assert result["success"] is False
        assert len(result["errors"]) == 2
        assert any("name" in e for e in result["errors"])
        assert any("url" in e for e in result["errors"])

    def test_optional_fields_default_values(self):
        """Should use defaults for optional fields."""
        metadata = {"name": "myproject", "url": "https://github.com/user/myproject.git"}

        result = build_repository_node(metadata)

        assert result["success"] is True
        props = result["data"]["properties"]
        assert props["description"] == ""
        assert props["total_size_mb"] == 0.0
        assert props["total_files"] == 0
        assert props["total_directories"] == 0
        assert props["languages"] == {}
        assert props["created_at"] == ""
        assert props["last_updated"] == ""
        assert props["default_branch"] == "main"

    def test_node_id_format(self):
        """Should generate node ID with repo_ prefix."""
        metadata = {"name": "my-project", "url": "https://example.com/repo.git"}

        result = build_repository_node(metadata)

        assert result["success"] is True
        assert result["data"]["node_id"] == "repo_my-project"


class TestExtractRepository:
    """Tests for extract_repository function."""

    def test_successful_extraction(self):
        """Should extract repository and return proper structure."""
        metadata = {
            "name": "myproject",
            "url": "https://github.com/user/myproject.git",
            "description": "Test project",
        }

        result = extract_repository(metadata)

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["total_nodes"] == 1
        assert result["stats"]["total_edges"] == 0
        assert result["stats"]["node_types"]["Repository"] == 1

        # Check data structure
        assert len(result["data"]["nodes"]) == 1
        assert result["data"]["edges"] == []

        node = result["data"]["nodes"][0]
        assert node["label"] == "Repository"
        assert node["properties"]["name"] == "myproject"

    def test_extraction_failure_propagates(self):
        """Should propagate failures from build_repository_node."""
        metadata = {"name": ""}  # Missing url, empty name

        result = extract_repository(metadata)

        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []
        assert result["stats"]["total_nodes"] == 0
        assert result["stats"]["total_edges"] == 0

    def test_missing_required_fields(self):
        """Should fail when required fields are missing."""
        metadata = {}

        result = extract_repository(metadata)

        assert result["success"] is False
        assert len(result["errors"]) >= 1

    def test_partial_metadata(self):
        """Should succeed with minimal required fields."""
        metadata = {
            "name": "minimal-repo",
            "url": "git@github.com:user/minimal.git",
        }

        result = extract_repository(metadata)

        assert result["success"] is True
        node = result["data"]["nodes"][0]
        assert node["properties"]["name"] == "minimal-repo"
        assert node["properties"]["url"] == "git@github.com:user/minimal.git"
        # Defaults should be applied
        assert node["properties"]["description"] == ""

    def test_extracted_at_timestamp(self):
        """Should include extracted_at timestamp in node properties."""
        metadata = {
            "name": "myproject",
            "url": "https://github.com/user/myproject.git",
        }

        result = extract_repository(metadata)

        assert result["success"] is True
        node = result["data"]["nodes"][0]
        assert "extracted_at" in node["properties"]
        assert node["properties"]["extracted_at"].endswith("Z")
