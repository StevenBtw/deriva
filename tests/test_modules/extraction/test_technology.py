"""Tests for modules.extraction.technology module."""

from __future__ import annotations

from deriva.modules.extraction.technology import (
    build_extraction_prompt,
    build_technology_node,
    parse_llm_response,
)


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_content(self):
        """Should include file content in prompt."""
        prompt = build_extraction_prompt("print('hello')", "main.py", "Extract", "{}")
        assert "print('hello')" in prompt

    def test_includes_source_path(self):
        """Should include source file path in prompt."""
        prompt = build_extraction_prompt("code", "src/main.py", "Extract", "{}")
        assert "src/main.py" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_extraction_prompt("code", "file.py", "Find all technologies", "{}")
        assert "Find all technologies" in prompt

    def test_returns_string(self):
        """Should return a string prompt."""
        prompt = build_extraction_prompt("code", "file.py", "Extract", "{}")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestBuildTechnologyNode:
    """Tests for build_technology_node function."""

    def test_valid_technology_data(self):
        """Should create valid technology node from complete data."""
        tech_data = {
            "techName": "PostgreSQL",
            "techCategory": "service",
            "description": "Relational database",
            "version": "14.0",
        }

        result = build_technology_node(tech_data, "src/db.py", "myrepo")

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["nodes_created"] == 1
        assert result["stats"]["node_type"] == "Technology"

        data = result["data"]
        assert data["node_id"] == "tech_myrepo_postgresql"
        assert data["label"] == "Technology"
        assert data["properties"]["techName"] == "PostgreSQL"
        assert data["properties"]["techCategory"] == "service"
        assert data["properties"]["description"] == "Relational database"
        assert data["properties"]["version"] == "14.0"
        assert data["properties"]["originSource"] == "src/db.py"
        assert "extracted_at" in data["properties"]

    def test_missing_tech_name(self):
        """Should fail when techName is missing."""
        tech_data = {"techCategory": "service", "description": "Test"}

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["success"] is False
        assert "Missing required field: techName" in result["errors"]
        assert result["data"] == {}
        assert result["stats"]["nodes_created"] == 0

    def test_missing_category(self):
        """Should fail when techCategory is missing."""
        tech_data = {"techName": "Redis", "description": "Cache"}

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["success"] is False
        assert "Missing required field: techCategory" in result["errors"]

    def test_missing_description(self):
        """Should fail when description is missing."""
        tech_data = {"techName": "Redis", "techCategory": "service"}

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["success"] is False
        assert "Missing required field: description" in result["errors"]

    def test_invalid_category_defaults_to_infrastructure(self):
        """Should default invalid category to infrastructure."""
        tech_data = {
            "techName": "CustomTool",
            "techCategory": "invalid_category",
            "description": "Some tool",
        }

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["success"] is True
        assert result["data"]["properties"]["techCategory"] == "infrastructure"

    def test_valid_categories(self):
        """Should accept all valid categories."""
        valid_categories = [
            "service",
            "system_software",
            "infrastructure",
            "platform",
            "network",
            "security",
        ]

        for category in valid_categories:
            tech_data = {
                "techName": "Test",
                "techCategory": category,
                "description": "Test description",
            }
            result = build_technology_node(tech_data, "file.py", "repo")
            assert result["success"] is True
            assert result["data"]["properties"]["techCategory"] == category

    def test_node_id_slugifies_name(self):
        """Should slugify tech name for node ID."""
        tech_data = {
            "techName": "Redis Cache",
            "techCategory": "service",
            "description": "Cache service",
        }

        result = build_technology_node(tech_data, "file.py", "myrepo")

        assert result["data"]["node_id"] == "tech_myrepo_redis_cache"

    def test_node_id_handles_hyphens(self):
        """Should replace hyphens with underscores in node ID."""
        tech_data = {
            "techName": "Vue-Router",
            "techCategory": "platform",
            "description": "Vue router",
        }

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["data"]["node_id"] == "tech_repo_vue_router"

    def test_default_confidence(self):
        """Should use default confidence when not provided."""
        tech_data = {
            "techName": "Test",
            "techCategory": "service",
            "description": "Test",
        }

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["data"]["properties"]["confidence"] == 0.8

    def test_custom_confidence(self):
        """Should use provided confidence value."""
        tech_data = {
            "techName": "Test",
            "techCategory": "service",
            "description": "Test",
            "confidence": 0.95,
        }

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["data"]["properties"]["confidence"] == 0.95

    def test_version_optional(self):
        """Should handle missing version gracefully."""
        tech_data = {
            "techName": "Test",
            "techCategory": "service",
            "description": "Test",
        }

        result = build_technology_node(tech_data, "file.py", "repo")

        assert result["success"] is True
        assert result["data"]["properties"]["version"] is None


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_valid_response_with_technologies(self):
        """Should parse valid JSON with technologies array."""
        response = '{"technologies": [{"techName": "Redis"}]}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["errors"] == []

    def test_empty_technologies_array(self):
        """Should handle empty technologies array."""
        response = '{"technologies": []}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_technologies_key(self):
        """Should fail when technologies key is missing."""
        response = '{"items": []}'

        result = parse_llm_response(response)

        assert result["success"] is False
        assert 'missing "technologies"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "{invalid json"

        result = parse_llm_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]

    def test_non_array_technologies(self):
        """Should fail when technologies is not an array."""
        response = '{"technologies": "not an array"}'

        result = parse_llm_response(response)

        assert result["success"] is False
        assert "must be an array" in result["errors"][0]
