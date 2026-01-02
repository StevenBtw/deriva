"""Tests for modules.extraction.extraction_base module."""

from deriva.common.types import LLMDetails
from deriva.modules.extraction.base import (
    create_empty_llm_details,
    create_extraction_result,
    current_timestamp,
    generate_edge_id,
    generate_node_id,
    parse_json_response,
    validate_required_fields,
)


class TestGenerateNodeId:
    """Tests for generate_node_id function."""

    def test_basic_node_id(self):
        """Should generate formatted node ID."""
        node_id = generate_node_id("concept", "myrepo", "UserAuth")
        assert node_id == "concept_myrepo_userauth"

    def test_normalizes_spaces(self):
        """Should replace spaces with underscores."""
        node_id = generate_node_id("type", "repo", "User Auth Service")
        assert node_id == "type_repo_user_auth_service"

    def test_normalizes_hyphens(self):
        """Should replace hyphens with underscores."""
        node_id = generate_node_id("method", "repo", "get-user-data")
        assert node_id == "method_repo_get_user_data"

    def test_removes_special_chars(self):
        """Should remove non-alphanumeric characters."""
        node_id = generate_node_id("concept", "repo", "User@Auth#123")
        assert node_id == "concept_repo_userauth123"


class TestGenerateEdgeId:
    """Tests for generate_edge_id function."""

    def test_basic_edge_id(self):
        """Should generate formatted edge ID."""
        edge_id = generate_edge_id("node_a", "node_b", "DEPENDS_ON")
        assert edge_id == "depends_on_node_a_to_node_b"


class TestCurrentTimestamp:
    """Tests for current_timestamp function."""

    def test_returns_iso_format(self):
        """Should return ISO format timestamp with Z suffix."""
        ts = current_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts


class TestParseJsonResponse:
    """Tests for parse_json_response function."""

    def test_valid_json_with_array(self):
        """Should parse valid JSON with expected array key."""
        response = '{"concepts": [{"name": "Auth"}, {"name": "User"}]}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["errors"] == []

    def test_missing_array_key(self):
        """Should fail when array key is missing."""
        response = '{"items": []}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert 'missing "concepts"' in result["errors"][0]

    def test_non_array_value(self):
        """Should fail when value is not an array."""
        response = '{"concepts": "not an array"}'
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert "must be an array" in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "{invalid json"
        result = parse_json_response(response, "concepts")

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestValidateRequiredFields:
    """Tests for validate_required_fields function."""

    def test_all_fields_present(self):
        """Should return empty errors when all fields present."""
        data = {"name": "Test", "id": "123"}
        errors = validate_required_fields(data, ["name", "id"])
        assert errors == []

    def test_missing_field(self):
        """Should return error for missing field."""
        data = {"name": "Test"}
        errors = validate_required_fields(data, ["name", "id"])
        assert len(errors) == 1
        assert "id" in errors[0]

    def test_empty_field(self):
        """Should return error for empty field."""
        data = {"name": "", "id": "123"}
        errors = validate_required_fields(data, ["name", "id"])
        assert len(errors) == 1
        assert "name" in errors[0]


class TestCreateExtractionResult:
    """Tests for create_extraction_result function."""

    def test_success_result(self):
        """Should create success result structure."""
        result = create_extraction_result(
            success=True,
            nodes=[{"id": "node1"}],
            edges=[{"from": "a", "to": "b"}],
            errors=[],
            stats={"count": 1}
        )

        assert result["success"] is True
        assert len(result["elements"]) == 1
        assert len(result["relationships"]) == 1
        assert result["errors"] == []
        assert result["stage"] == "extraction"
        assert "timestamp" in result
        assert "duration_ms" in result
        assert "llm_details" not in result

    def test_result_with_llm_details(self):
        """Should include LLM details when provided."""
        llm_details: LLMDetails = {"tokens_in": 100, "tokens_out": 50}
        result = create_extraction_result(
            success=True,
            nodes=[],
            edges=[],
            errors=[],
            stats={},
            llm_details=llm_details
        )

        assert result["llm_details"] == llm_details


class TestCreateEmptyLlmDetails:
    """Tests for create_empty_llm_details function."""

    def test_returns_expected_structure(self):
        """Should return dict with all expected keys."""
        details = create_empty_llm_details()

        assert details["prompt"] == ""
        assert details["response"] == ""
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0
        assert details["cache_used"] is False
