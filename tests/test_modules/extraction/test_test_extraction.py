"""Tests for modules.extraction.test module."""

from __future__ import annotations

from deriva.modules.extraction.test import (
    build_extraction_prompt,
    build_test_node,
    parse_llm_response,
)


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_content(self):
        """Should include file content in prompt."""
        prompt = build_extraction_prompt("def test_foo(): pass", "test_main.py", "Extract", "{}")
        assert "def test_foo(): pass" in prompt

    def test_includes_source_path(self):
        """Should include source file path in prompt."""
        prompt = build_extraction_prompt("code", "tests/test_main.py", "Extract", "{}")
        assert "tests/test_main.py" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_extraction_prompt("code", "test.py", "Find all tests", "{}")
        assert "Find all tests" in prompt

    def test_returns_string(self):
        """Should return a string prompt."""
        prompt = build_extraction_prompt("code", "test.py", "Extract", "{}")
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestBuildTestNode:
    """Tests for build_test_node function."""

    def test_valid_test_data(self):
        """Should create valid test node from complete data."""
        test_data = {
            "testName": "test_user_login",
            "testType": "unit",
            "description": "Tests user login functionality",
            "testedElement": "UserService.login",
            "framework": "pytest",
            "startLine": 10,
            "endLine": 25,
        }

        result = build_test_node(test_data, "tests/test_auth.py", "myrepo")

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["nodes_created"] == 1
        assert result["stats"]["node_type"] == "Test"

        data = result["data"]
        assert "test_myrepo_" in data["node_id"]
        assert data["label"] == "Test"
        assert data["properties"]["testName"] == "test_user_login"
        assert data["properties"]["testType"] == "unit"
        assert data["properties"]["description"] == "Tests user login functionality"
        assert data["properties"]["testedElement"] == "UserService.login"
        assert data["properties"]["framework"] == "pytest"
        assert data["properties"]["filePath"] == "tests/test_auth.py"
        assert data["properties"]["startLine"] == 10
        assert data["properties"]["endLine"] == 25
        assert "extracted_at" in data["properties"]

    def test_missing_test_name(self):
        """Should fail when testName is missing."""
        test_data = {"testType": "unit", "description": "Test"}

        result = build_test_node(test_data, "test.py", "repo")

        assert result["success"] is False
        assert "Missing required field: testName" in result["errors"]
        assert result["data"] == {}
        assert result["stats"]["nodes_created"] == 0

    def test_missing_test_type(self):
        """Should fail when testType is missing."""
        test_data = {"testName": "test_foo", "description": "Test"}

        result = build_test_node(test_data, "test.py", "repo")

        assert result["success"] is False
        assert "Missing required field: testType" in result["errors"]

    def test_missing_description(self):
        """Should fail when description is missing."""
        test_data = {"testName": "test_foo", "testType": "unit"}

        result = build_test_node(test_data, "test.py", "repo")

        assert result["success"] is False
        assert "Missing required field: description" in result["errors"]

    def test_invalid_test_type_defaults_to_other(self):
        """Should default invalid test type to 'other'."""
        test_data = {
            "testName": "test_foo",
            "testType": "invalid_type",
            "description": "Test description",
        }

        result = build_test_node(test_data, "test.py", "repo")

        assert result["success"] is True
        assert result["data"]["properties"]["testType"] == "other"

    def test_valid_test_types(self):
        """Should accept all valid test types."""
        valid_types = [
            "unit",
            "integration",
            "e2e",
            "performance",
            "smoke",
            "regression",
            "other",
        ]

        for test_type in valid_types:
            test_data = {
                "testName": "test_foo",
                "testType": test_type,
                "description": "Test description",
            }
            result = build_test_node(test_data, "test.py", "repo")
            assert result["success"] is True
            assert result["data"]["properties"]["testType"] == test_type

    def test_node_id_includes_file_path(self):
        """Should include file path in node ID."""
        test_data = {
            "testName": "test_foo",
            "testType": "unit",
            "description": "Test",
        }

        result = build_test_node(test_data, "tests/auth/test_login.py", "myrepo")

        assert "tests_auth_test_login.py" in result["data"]["node_id"]

    def test_node_id_handles_spaces_and_hyphens(self):
        """Should replace spaces and hyphens in node ID."""
        test_data = {
            "testName": "test user-login",
            "testType": "unit",
            "description": "Test",
        }

        result = build_test_node(test_data, "test.py", "repo")

        assert "test_user_login" in result["data"]["node_id"]

    def test_default_confidence(self):
        """Should use default confidence when not provided."""
        test_data = {
            "testName": "test_foo",
            "testType": "unit",
            "description": "Test",
        }

        result = build_test_node(test_data, "test.py", "repo")

        assert result["data"]["properties"]["confidence"] == 0.8

    def test_custom_confidence(self):
        """Should use provided confidence value."""
        test_data = {
            "testName": "test_foo",
            "testType": "unit",
            "description": "Test",
            "confidence": 0.95,
        }

        result = build_test_node(test_data, "test.py", "repo")

        assert result["data"]["properties"]["confidence"] == 0.95

    def test_optional_fields_default_values(self):
        """Should handle missing optional fields gracefully."""
        test_data = {
            "testName": "test_foo",
            "testType": "unit",
            "description": "Test",
        }

        result = build_test_node(test_data, "test.py", "repo")

        assert result["success"] is True
        props = result["data"]["properties"]
        assert props["testedElement"] is None
        assert props["framework"] is None
        assert props["startLine"] == 0
        assert props["endLine"] == 0


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_valid_response_with_tests(self):
        """Should parse valid JSON with tests array."""
        response = '{"tests": [{"testName": "test_foo"}]}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["errors"] == []

    def test_empty_tests_array(self):
        """Should handle empty tests array."""
        response = '{"tests": []}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_tests_key(self):
        """Should fail when tests key is missing."""
        response = '{"items": []}'

        result = parse_llm_response(response)

        assert result["success"] is False
        assert 'missing "tests"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "{invalid json"

        result = parse_llm_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]

    def test_non_array_tests(self):
        """Should fail when tests is not an array."""
        response = '{"tests": "not an array"}'

        result = parse_llm_response(response)

        assert result["success"] is False
        assert "must be an array" in result["errors"][0]
