"""Tests for modules.derivation.base module."""

from deriva.adapters.llm.models import ResponseType
from deriva.common import current_timestamp, extract_llm_details
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    RELATIONSHIP_SCHEMA,
    build_derivation_prompt,
    build_element,
    build_relationship_prompt,
    create_result,
    parse_derivation_response,
    parse_relationship_response,
)


class TestBuildDerivationPrompt:
    """Tests for build_derivation_prompt function."""

    def test_includes_graph_results(self):
        """Should include graph results in prompt."""
        graph_data = [{"name": "auth", "path": "src/auth"}]
        prompt = build_derivation_prompt(graph_data=graph_data, instruction="Group directories", example='{"identifier": "app:auth"}', element_type="ApplicationComponent")

        assert "auth" in prompt
        assert "src/auth" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_derivation_prompt(graph_data=[], instruction="Group top-level directories into components", example="{}", element_type="ApplicationComponent")

        assert "Group top-level directories" in prompt

    def test_includes_element_type(self):
        """Should reference element type in prompt."""
        prompt = build_derivation_prompt(graph_data=[], instruction="Test", example="{}", element_type="ApplicationService")

        assert "ApplicationService" in prompt


class TestParseDerivationResponse:
    """Tests for parse_derivation_response function."""

    def test_valid_response(self):
        """Should parse valid response with elements array."""
        response = '{"elements": [{"identifier": "app:auth", "name": "Auth"}]}'
        result = parse_derivation_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["identifier"] == "app:auth"

    def test_empty_elements(self):
        """Should accept empty elements array."""
        response = '{"elements": []}'
        result = parse_derivation_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_elements_key(self):
        """Should fail when elements key is missing."""
        response = '{"items": []}'
        result = parse_derivation_response(response)

        assert result["success"] is False
        assert 'missing "elements"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON."""
        response = "not valid json"
        result = parse_derivation_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestBuildElement:
    """Tests for build_element function."""

    def test_valid_element(self):
        """Should build element from valid data."""
        derived = {"identifier": "app:auth", "name": "Auth Component", "confidence": 0.9, "source": "Directory:src/auth"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is True
        assert result["data"]["name"] == "Auth Component"
        assert result["data"]["element_type"] == "ApplicationComponent"
        assert result["data"]["properties"]["confidence"] == 0.9

    def test_missing_identifier(self):
        """Should fail when identifier is missing."""
        derived = {"name": "Auth Component"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is False
        assert any("identifier" in e or "name" in e for e in result["errors"])

    def test_missing_name(self):
        """Should fail when name is missing."""
        derived = {"identifier": "app:auth"}
        result = build_element(derived, "ApplicationComponent")

        assert result["success"] is False
        assert any("identifier" in e or "name" in e for e in result["errors"])

    def test_uses_documentation(self):
        """Should use documentation field."""
        derived = {"identifier": "app:auth", "name": "Auth", "documentation": "Auth docs"}
        result = build_element(derived, "ApplicationComponent")
        assert result["data"]["documentation"] == "Auth docs"


class TestCreateResult:
    """Tests for create_result function."""

    def test_success_result(self):
        """Should create success result structure."""
        result = create_result(success=True, errors=[], stats={"count": 1})

        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"] == {"count": 1}
        assert "timestamp" in result

    def test_failure_result_with_errors(self):
        """Should include errors when provided."""
        result = create_result(success=False, errors=["Something went wrong"], stats={})

        assert result["success"] is False
        assert "Something went wrong" in result["errors"]


class TestCurrentTimestamp:
    """Tests for current_timestamp function."""

    def test_returns_iso_format(self):
        """Should return ISO format with Z suffix."""
        ts = current_timestamp()
        assert ts.endswith("Z")
        assert "T" in ts


class TestDerivationSchema:
    """Tests for DERIVATION_SCHEMA constant."""

    def test_schema_has_required_structure(self):
        """Should have name and schema properties."""
        assert "name" in DERIVATION_SCHEMA
        assert "schema" in DERIVATION_SCHEMA
        assert DERIVATION_SCHEMA["name"] == "derivation_output"

    def test_schema_requires_elements_array(self):
        """Should require elements array in response."""
        schema = DERIVATION_SCHEMA["schema"]
        assert "elements" in schema["properties"]
        assert "elements" in schema["required"]

    def test_elements_require_identifier_and_name(self):
        """Should require identifier and name for each element."""
        items_schema = DERIVATION_SCHEMA["schema"]["properties"]["elements"]["items"]
        assert "identifier" in items_schema["required"]
        assert "name" in items_schema["required"]


class TestRelationshipSchema:
    """Tests for RELATIONSHIP_SCHEMA constant."""

    def test_schema_has_required_structure(self):
        """Should have name and schema properties."""
        assert "name" in RELATIONSHIP_SCHEMA
        assert "schema" in RELATIONSHIP_SCHEMA
        assert RELATIONSHIP_SCHEMA["name"] == "relationship_output"

    def test_schema_requires_relationships_array(self):
        """Should require relationships array in response."""
        schema = RELATIONSHIP_SCHEMA["schema"]
        assert "relationships" in schema["properties"]
        assert "relationships" in schema["required"]

    def test_relationships_require_source_target_type(self):
        """Should require source, target, relationship_type for each relationship."""
        items_schema = RELATIONSHIP_SCHEMA["schema"]["properties"]["relationships"]["items"]
        assert "source" in items_schema["required"]
        assert "target" in items_schema["required"]
        assert "relationship_type" in items_schema["required"]


class TestBuildRelationshipPrompt:
    """Tests for build_relationship_prompt function."""

    def test_includes_elements(self):
        """Should include elements in prompt."""
        elements = [
            {"identifier": "app:auth", "name": "Auth", "element_type": "ApplicationComponent"},
            {"identifier": "app:api", "name": "API", "element_type": "ApplicationComponent"},
        ]
        prompt = build_relationship_prompt(elements)

        assert "app:auth" in prompt
        assert "app:api" in prompt
        assert "Auth" in prompt

    def test_includes_relationship_types(self):
        """Should mention ArchiMate relationship types."""
        prompt = build_relationship_prompt([])

        assert "Composition" in prompt
        assert "Serving" in prompt
        assert "Realization" in prompt

    def test_includes_instructions(self):
        """Should include instructions for relationship derivation."""
        prompt = build_relationship_prompt([])

        assert "relationships" in prompt.lower()
        assert "source" in prompt.lower()
        assert "target" in prompt.lower()


class TestParseRelationshipResponse:
    """Tests for parse_relationship_response function."""

    def test_valid_response(self):
        """Should parse valid response with relationships array."""
        response = '{"relationships": [{"source": "app:auth", "target": "app:api", "relationship_type": "Serving"}]}'
        result = parse_relationship_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["source"] == "app:auth"
        assert result["data"][0]["target"] == "app:api"

    def test_empty_relationships(self):
        """Should accept empty relationships array."""
        response = '{"relationships": []}'
        result = parse_relationship_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_missing_relationships_key(self):
        """Should fail when relationships key is missing."""
        response = '{"items": []}'
        result = parse_relationship_response(response)

        assert result["success"] is False
        assert 'missing "relationships"' in result["errors"][0]

    def test_invalid_json(self):
        """Should handle invalid JSON."""
        response = "not valid json"
        result = parse_relationship_response(response)

        assert result["success"] is False
        assert "JSON parsing error" in result["errors"][0]


class TestExtractLlmDetails:
    """Tests for extract_llm_details function."""

    def test_live_response_cache_used_false(self):
        """Should set cache_used=False for live responses."""

        class MockLiveResponse:
            response_type = ResponseType.LIVE
            content = "test content"
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        details = extract_llm_details(MockLiveResponse())

        assert details["cache_used"] is False
        assert details["response"] == "test content"
        assert details["tokens_in"] == 100
        assert details["tokens_out"] == 50

    def test_cached_response_cache_used_true(self):
        """Should set cache_used=True for cached responses."""

        class MockCachedResponse:
            response_type = ResponseType.CACHED
            content = "cached content"
            usage = None

        details = extract_llm_details(MockCachedResponse())

        assert details["cache_used"] is True
        assert details["response"] == "cached content"
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0

    def test_response_without_usage(self):
        """Should handle response without usage data."""

        class MockResponse:
            response_type = ResponseType.LIVE
            content = "no usage"
            usage = None

        details = extract_llm_details(MockResponse())

        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0

    def test_response_without_response_type(self):
        """Should default cache_used to False when response_type missing."""

        class MockResponse:
            content = "plain response"

        details = extract_llm_details(MockResponse())

        assert details["cache_used"] is False
        assert details["response"] == "plain response"

    def test_response_without_content(self):
        """Should handle response without content attribute."""

        class MockResponse:
            response_type = ResponseType.LIVE

        details = extract_llm_details(MockResponse())

        assert details["response"] == ""
        assert details["cache_used"] is False
