"""Tests for modules.extraction.business_concept module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from deriva.modules.extraction.business_concept import (
    BUSINESS_CONCEPT_SCHEMA,
    _dir_name_to_concept_name,
    build_extraction_prompt,
    extract_seed_concepts_from_structure,
    get_existing_concepts_from_graph,
)


class TestBusinessConceptSchema:
    """Tests for the JSON schema definition."""

    def test_schema_has_required_structure(self):
        """Schema should have the expected structure."""
        assert BUSINESS_CONCEPT_SCHEMA["name"] == "business_concepts_extraction"
        assert BUSINESS_CONCEPT_SCHEMA["strict"] is True
        schema = cast(dict[str, Any], BUSINESS_CONCEPT_SCHEMA["schema"])
        assert "concepts" in schema["properties"]

    def test_schema_concept_fields(self):
        """Schema should define all concept fields."""
        schema = cast(dict[str, Any], BUSINESS_CONCEPT_SCHEMA["schema"])
        items = schema["properties"]["concepts"]["items"]
        required_fields = items["required"]

        assert "conceptName" in required_fields
        assert "conceptType" in required_fields
        assert "description" in required_fields
        assert "confidence" in required_fields

    def test_concept_type_enum_values(self):
        """Schema should have correct enum values for conceptType."""
        schema = cast(dict[str, Any], BUSINESS_CONCEPT_SCHEMA["schema"])
        items = schema["properties"]["concepts"]["items"]
        enum_values = items["properties"]["conceptType"]["enum"]

        assert "actor" in enum_values
        assert "service" in enum_values
        assert "process" in enum_values
        assert "entity" in enum_values
        assert "event" in enum_values


class TestDirNameToConceptName:
    """Tests for _dir_name_to_concept_name helper function."""

    def test_converts_snake_case(self):
        """Should convert snake_case to PascalCase."""
        assert _dir_name_to_concept_name("data_processing") == "DataProcessing"
        assert _dir_name_to_concept_name("user_management") == "UserManagement"

    def test_converts_kebab_case(self):
        """Should convert kebab-case to PascalCase."""
        assert _dir_name_to_concept_name("message-queue") == "MessageQueue"
        assert _dir_name_to_concept_name("api-gateway") == "ApiGateway"

    def test_handles_single_word(self):
        """Should capitalize single word directories."""
        assert _dir_name_to_concept_name("orders") == "Orders"
        assert _dir_name_to_concept_name("analytics") == "Analytics"

    def test_handles_empty_string(self):
        """Should handle empty string."""
        assert _dir_name_to_concept_name("") == ""

    def test_handles_mixed_separators(self):
        """Should handle mixed underscores and hyphens."""
        assert _dir_name_to_concept_name("data-stream_processor") == "DataStreamProcessor"


class TestExtractSeedConceptsFromStructure:
    """Tests for extract_seed_concepts_from_structure function."""

    def test_extracts_from_directories(self):
        """Should extract concepts from directory names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test directories
            (Path(tmpdir) / "orders").mkdir()
            (Path(tmpdir) / "customers").mkdir()
            (Path(tmpdir) / "processing_pipeline").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            names = [c["conceptName"] for c in concepts]
            assert "Orders" in names
            assert "Customers" in names
            assert "ProcessingPipeline" in names

    def test_skips_common_directories(self):
        """Should skip non-business directories like .git, node_modules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directories that should be skipped
            (Path(tmpdir) / ".git").mkdir()
            (Path(tmpdir) / "node_modules").mkdir()
            (Path(tmpdir) / "__pycache__").mkdir()
            (Path(tmpdir) / "tests").mkdir()
            (Path(tmpdir) / "venv").mkdir()
            # Create one that should be included
            (Path(tmpdir) / "orders").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            names = [c["conceptName"] for c in concepts]
            assert "Orders" in names
            assert len(concepts) == 1  # Only 'orders' should be included

    def test_classifies_process_keywords(self):
        """Should classify directories with process keywords as 'process'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "data_processing").mkdir()
            (Path(tmpdir) / "stream_pipeline").mkdir()
            (Path(tmpdir) / "job_scheduler").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            for concept in concepts:
                assert concept["conceptType"] == "process"

    def test_classifies_entity_keywords(self):
        """Should classify directories with entity keywords as 'entity'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "data_model").mkdir()
            (Path(tmpdir) / "user_repository").mkdir()
            (Path(tmpdir) / "cache_storage").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            for concept in concepts:
                assert concept["conceptType"] == "entity"

    def test_classifies_unknown_as_capability(self):
        """Should classify unknown directories as 'capability'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "orders").mkdir()
            (Path(tmpdir) / "customers").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            for concept in concepts:
                assert concept["conceptType"] == "capability"

    def test_includes_source_info(self):
        """Should include source information for each concept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "orders").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            assert len(concepts) == 1
            assert concepts[0]["source"] == "directory:orders/"

    def test_skips_short_names(self):
        """Should skip directories with names <= 2 characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "ab").mkdir()
            (Path(tmpdir) / "xy").mkdir()
            (Path(tmpdir) / "orders").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            names = [c["conceptName"] for c in concepts]
            assert "Orders" in names
            assert "Ab" not in names
            assert "Xy" not in names

    def test_skips_hidden_directories(self):
        """Should skip directories starting with dot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / ".hidden").mkdir()
            (Path(tmpdir) / ".config").mkdir()
            (Path(tmpdir) / "orders").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir)

            names = [c["conceptName"] for c in concepts]
            assert "Orders" in names
            assert len(concepts) == 1

    def test_disabled_when_include_directories_false(self):
        """Should return empty when include_directories is False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "orders").mkdir()
            (Path(tmpdir) / "customers").mkdir()

            concepts = extract_seed_concepts_from_structure(tmpdir, include_directories=False)

            assert len(concepts) == 0


class TestGetExistingConceptsFromGraph:
    """Tests for get_existing_concepts_from_graph function."""

    def test_returns_concepts_from_query(self):
        """Should return concepts from graph query."""
        mock_manager = MagicMock()
        mock_manager.run_cypher.return_value = [
            {"conceptName": "OrderManagement", "conceptType": "entity", "source": "graph"},
            {"conceptName": "CustomerService", "conceptType": "service", "source": "graph"},
        ]

        concepts = get_existing_concepts_from_graph(mock_manager, "myrepo")

        assert len(concepts) == 2
        assert concepts[0]["conceptName"] == "OrderManagement"
        assert concepts[1]["conceptName"] == "CustomerService"

    def test_filters_none_concept_names(self):
        """Should filter out results with None conceptName."""
        mock_manager = MagicMock()
        mock_manager.run_cypher.return_value = [
            {"conceptName": "ValidConcept", "conceptType": "entity", "source": "graph"},
            {"conceptName": None, "conceptType": "entity", "source": "graph"},
        ]

        concepts = get_existing_concepts_from_graph(mock_manager, "myrepo")

        assert len(concepts) == 1
        assert concepts[0]["conceptName"] == "ValidConcept"

    def test_returns_empty_on_exception(self):
        """Should return empty list when query fails."""
        mock_manager = MagicMock()
        mock_manager.run_cypher.side_effect = Exception("Connection failed")

        concepts = get_existing_concepts_from_graph(mock_manager, "myrepo")

        assert concepts == []

    def test_uses_correct_query_params(self):
        """Should pass correct parameters to query."""
        mock_manager = MagicMock()
        mock_manager.run_cypher.return_value = []

        get_existing_concepts_from_graph(mock_manager, "testrepo", limit=25)

        mock_manager.run_cypher.assert_called_once()
        call_args = mock_manager.run_cypher.call_args
        assert call_args[0][1]["repo_name"] == "testrepo"
        assert call_args[0][1]["limit"] == 25


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_file_content(self):
        """Should include file content in prompt."""
        prompt = build_extraction_prompt(
            file_content="class OrderService:\n    pass",
            file_path="src/orders/service.py",
            instruction="Extract business concepts",
            example='{"concepts": []}',
        )

        assert "OrderService" in prompt

    def test_includes_file_path(self):
        """Should include file path in prompt."""
        prompt = build_extraction_prompt(
            file_content="test content",
            file_path="src/orders/service.py",
            instruction="Extract concepts",
            example="{}",
        )

        assert "src/orders/service.py" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        prompt = build_extraction_prompt(
            file_content="content",
            file_path="test.py",
            instruction="Focus on domain entities and business processes",
            example="{}",
        )

        assert "Focus on domain entities" in prompt

    def test_includes_example(self):
        """Should include example output in prompt."""
        prompt = build_extraction_prompt(
            file_content="content",
            file_path="test.py",
            instruction="Extract",
            example='{"concepts": [{"conceptName": "Order"}]}',
        )

        assert "Order" in prompt

    def test_includes_existing_concepts_when_provided(self):
        """Should include existing concepts section when provided."""
        existing: list[dict[str, Any]] = [
            {"conceptName": "CustomerManagement", "conceptType": "entity", "confidence": 0.9},
        ]
        prompt = build_extraction_prompt(
            file_content="content",
            file_path="test.py",
            instruction="Extract",
            example="{}",
            existing_concepts=existing,  # type: ignore[arg-type]
        )

        assert "CustomerManagement" in prompt
        assert "Previously Identified Concepts" in prompt

    def test_filters_low_confidence_existing_concepts(self):
        """Should filter out low confidence existing concepts."""
        existing: list[dict[str, Any]] = [
            {"conceptName": "HighConfidence", "conceptType": "entity", "confidence": 0.9},
            {"conceptName": "LowConfidence", "conceptType": "entity", "confidence": 0.5},
        ]
        prompt = build_extraction_prompt(
            file_content="content",
            file_path="test.py",
            instruction="Extract",
            example="{}",
            existing_concepts=existing,  # type: ignore[arg-type]
        )

        assert "HighConfidence" in prompt
        assert "LowConfidence" not in prompt

    def test_handles_empty_existing_concepts(self):
        """Should handle empty existing concepts list."""
        prompt = build_extraction_prompt(
            file_content="content",
            file_path="test.py",
            instruction="Extract",
            example="{}",
            existing_concepts=[],
        )

        assert "Previously Identified Concepts" not in prompt


# =============================================================================
# build_multi_file_user_prompt Tests
# =============================================================================


class TestBuildMultiFileUserPrompt:
    """Tests for build_multi_file_user_prompt function."""

    def test_includes_all_file_paths(self):
        """Should include all file paths in prompt."""
        from deriva.modules.extraction.business_concept import build_multi_file_user_prompt

        files = [
            {"path": "src/orders/service.py", "content": "class OrderService: pass"},
            {"path": "src/customers/model.py", "content": "class Customer: pass"},
        ]

        prompt = build_multi_file_user_prompt(files, '{"concepts": []}')

        assert "src/orders/service.py" in prompt
        assert "src/customers/model.py" in prompt

    def test_includes_file_content(self):
        """Should include file content for each file."""
        from deriva.modules.extraction.business_concept import build_multi_file_user_prompt

        files = [
            {"path": "test.py", "content": "class UniqueClassName: pass"},
        ]

        prompt = build_multi_file_user_prompt(files, "{}")

        assert "UniqueClassName" in prompt

    def test_includes_example(self):
        """Should include example in prompt."""
        from deriva.modules.extraction.business_concept import build_multi_file_user_prompt

        files = [{"path": "test.py", "content": "x = 1"}]

        prompt = build_multi_file_user_prompt(files, '{"concepts": [{"name": "Test"}]}')

        assert "concepts" in prompt

    def test_includes_existing_concepts_when_provided(self):
        """Should include existing concepts context."""
        from deriva.modules.extraction.business_concept import build_multi_file_user_prompt

        files = [{"path": "test.py", "content": "x = 1"}]
        existing: list[dict[str, str]] = [
            {"conceptName": "OrderManagement", "conceptType": "entity", "confidence": "0.9"},
        ]

        prompt = build_multi_file_user_prompt(files, "{}", existing)

        assert "OrderManagement" in prompt
        assert "Previously Identified Concepts" in prompt

    def test_filters_low_confidence_existing_concepts(self):
        """Should filter out low confidence existing concepts."""
        from deriva.modules.extraction.business_concept import build_multi_file_user_prompt

        files = [{"path": "test.py", "content": "x = 1"}]
        existing: list[dict[str, str]] = [
            {"conceptName": "HighConf", "conceptType": "entity", "confidence": "0.9"},
            {"conceptName": "LowConf", "conceptType": "entity", "confidence": "0.5"},
        ]

        prompt = build_multi_file_user_prompt(files, "{}", existing)

        assert "HighConf" in prompt
        assert "LowConf" not in prompt


# =============================================================================
# build_business_concept_node Tests
# =============================================================================


class TestBuildBusinessConceptNode:
    """Tests for build_business_concept_node function."""

    def test_builds_valid_node(self):
        """Should build valid node from concept data."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "OrderManagement",
            "conceptType": "entity",
            "description": "Handles order processing",
            "confidence": 0.9,
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="src/orders/service.py",
            repo_name="test-repo",
        )

        assert result["success"] is True
        assert result["data"]["label"] == "BusinessConcept"
        assert result["data"]["properties"]["conceptName"] == "OrderManagement"
        assert result["data"]["properties"]["conceptType"] == "entity"
        assert "node_id" in result["data"]
        assert result["stats"]["nodes_created"] == 1

    def test_validates_required_fields(self):
        """Should fail when required fields are missing."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "Test",
            # Missing conceptType and description
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="test.py",
            repo_name="test-repo",
        )

        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert result["stats"]["nodes_created"] == 0

    def test_validates_empty_fields(self):
        """Should fail when required fields are empty."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "",
            "conceptType": "entity",
            "description": "Test",
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="test.py",
            repo_name="test-repo",
        )

        assert result["success"] is False

    def test_normalizes_invalid_concept_type(self):
        """Should normalize invalid concept type to 'other'."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "Test",
            "conceptType": "INVALID_TYPE",
            "description": "Test desc",
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="test.py",
            repo_name="test-repo",
        )

        assert result["success"] is True
        assert result["data"]["properties"]["conceptType"] == "other"

    def test_generates_proper_node_id(self):
        """Should generate proper node ID format."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "Order Processing",
            "conceptType": "process",
            "description": "Process orders",
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="test.py",
            repo_name="my-repo",
        )

        assert result["success"] is True
        assert result["data"]["node_id"] == "concept::my-repo::order_processing"

    def test_uses_default_confidence(self):
        """Should use default confidence when not provided."""
        from deriva.modules.extraction.business_concept import build_business_concept_node

        concept_data = {
            "conceptName": "Test",
            "conceptType": "entity",
            "description": "Test desc",
            # No confidence provided
        }

        result = build_business_concept_node(
            concept_data=concept_data,
            origin_source="test.py",
            repo_name="test-repo",
        )

        assert result["success"] is True
        assert result["data"]["properties"]["confidence"] == 0.8


# =============================================================================
# parse_llm_response Tests
# =============================================================================


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_parses_valid_json(self):
        """Should parse valid JSON response."""
        from deriva.modules.extraction.business_concept import parse_llm_response

        response = '{"concepts": [{"conceptName": "Order", "conceptType": "entity", "description": "An order", "confidence": 0.9}]}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["conceptName"] == "Order"

    def test_handles_empty_concepts(self):
        """Should handle empty concepts array."""
        from deriva.modules.extraction.business_concept import parse_llm_response

        response = '{"concepts": []}'

        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 0

    def test_handles_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        from deriva.modules.extraction.business_concept import parse_llm_response

        response = "not valid json"

        result = parse_llm_response(response)

        assert result["success"] is False
        assert len(result["errors"]) > 0


# =============================================================================
# extract_business_concepts Tests
# =============================================================================


class TestExtractBusinessConcepts:
    """Tests for extract_business_concepts function."""

    def test_extracts_concepts_from_file(self):
        """Should extract concepts from a file."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        # Create a simple response class to avoid MagicMock attribute issues
        class MockResponse:
            content = '{"concepts": [{"conceptName": "Order", "conceptType": "entity", "description": "An order", "confidence": 0.9}]}'
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=MockResponse())

        result = extract_business_concepts(
            file_path="src/orders/service.py",
            file_content="class OrderService: pass",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract concepts", "example": "{}"},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1
        assert len(result["data"]["edges"]) == 1
        assert result["stats"]["concepts_found"] == 1

    def test_handles_llm_error(self):
        """Should handle LLM errors gracefully."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        mock_response = MagicMock()
        mock_response.error = "API rate limit exceeded"
        mock_response.content = None

        mock_llm_fn = MagicMock(return_value=mock_response)

        result = extract_business_concepts(
            file_path="test.py",
            file_content="x = 1",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert "LLM error" in result["errors"][0]
        assert result["stats"]["llm_error"] is True

    def test_handles_parse_error(self):
        """Should handle parse errors gracefully."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        mock_response = MagicMock()
        mock_response.content = "not valid json"
        delattr(mock_response, "error")

        mock_llm_fn = MagicMock(return_value=mock_response)

        result = extract_business_concepts(
            file_path="test.py",
            file_content="x = 1",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert result["stats"]["parse_error"] is True

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        mock_llm_fn = MagicMock(side_effect=Exception("Connection error"))

        result = extract_business_concepts(
            file_path="test.py",
            file_content="x = 1",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert "Fatal error" in result["errors"][0]

    def test_creates_references_edge(self):
        """Should create REFERENCES edge from file to concept."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        class MockResponse:
            content = '{"concepts": [{"conceptName": "Order", "conceptType": "entity", "description": "An order", "confidence": 0.9}]}'
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=MockResponse())

        result = extract_business_concepts(
            file_path="src/orders.py",
            file_content="class Order: pass",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert len(result["data"]["edges"]) == 1
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "REFERENCES"
        assert "file::test-repo" in edge["from_node_id"]
        assert "concept::test-repo" in edge["to_node_id"]

    def test_includes_llm_details(self):
        """Should include LLM details for logging."""
        from deriva.modules.extraction.business_concept import extract_business_concepts

        mock_response = MagicMock()
        mock_response.content = '{"concepts": []}'
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=mock_response)

        result = extract_business_concepts(
            file_path="test.py",
            file_content="x = 1",
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert "llm_details" in result
        assert result["llm_details"]["tokens_in"] == 100
        assert result["llm_details"]["tokens_out"] == 50


# =============================================================================
# extract_business_concepts_multi Tests
# =============================================================================


class TestExtractBusinessConceptsMulti:
    """Tests for extract_business_concepts_multi function."""

    def test_extracts_from_multiple_files(self):
        """Should extract concepts from multiple files in one call."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_multi

        class MockResponse:
            content = """{"results": [
                {"file_path": "a.py", "concepts": [{"conceptName": "OrderA", "conceptType": "entity", "description": "Order A", "confidence": 0.9}]},
                {"file_path": "b.py", "concepts": [{"conceptName": "OrderB", "conceptType": "entity", "description": "Order B", "confidence": 0.9}]}
            ]}"""
            usage = {"prompt_tokens": 200, "completion_tokens": 100}

        mock_llm_fn = MagicMock(return_value=MockResponse())

        files = [
            {"path": "a.py", "content": "class A: pass"},
            {"path": "b.py", "content": "class B: pass"},
        ]

        result = extract_business_concepts_multi(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 2
        assert result["stats"]["files_in_batch"] == 2

    def test_handles_llm_error(self):
        """Should handle LLM errors in multi-file extraction."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_multi

        mock_response = MagicMock()
        mock_response.error = "Rate limited"
        mock_response.content = None

        mock_llm_fn = MagicMock(return_value=mock_response)

        result = extract_business_concepts_multi(
            files=[{"path": "test.py", "content": "x = 1"}],
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert "LLM error" in result["errors"][0]

    def test_handles_json_decode_error(self):
        """Should handle JSON decode errors."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_multi

        mock_response = MagicMock()
        mock_response.content = "not valid json"
        delattr(mock_response, "error")

        mock_llm_fn = MagicMock(return_value=mock_response)

        result = extract_business_concepts_multi(
            files=[{"path": "test.py", "content": "x = 1"}],
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert "parse" in result["errors"][0].lower()

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_multi

        mock_llm_fn = MagicMock(side_effect=Exception("Connection failed"))

        result = extract_business_concepts_multi(
            files=[{"path": "test.py", "content": "x = 1"}],
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["success"] is False
        assert "Fatal error" in result["errors"][0]


# =============================================================================
# extract_business_concepts_batch Tests
# =============================================================================


class TestExtractBusinessConceptsBatch:
    """Tests for extract_business_concepts_batch function."""

    def test_processes_all_files(self):
        """Should process all files in batch."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_batch

        mock_response = MagicMock()
        mock_response.content = '{"concepts": [{"conceptName": "Test", "conceptType": "entity", "description": "Test", "confidence": 0.9}]}'
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=mock_response)

        files = [
            {"path": "a.py", "content": "class A: pass"},
            {"path": "b.py", "content": "class B: pass"},
        ]

        result = extract_business_concepts_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert result["stats"]["files_processed"] == 2
        assert mock_llm_fn.call_count == 2

    def test_calls_progress_callback(self):
        """Should call progress callback for each file."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_batch

        mock_response = MagicMock()
        mock_response.content = '{"concepts": []}'

        mock_llm_fn = MagicMock(return_value=mock_response)

        progress_calls = []

        def callback(current, total, path):
            progress_calls.append((current, total, path))

        files = [
            {"path": "a.py", "content": "x = 1"},
            {"path": "b.py", "content": "y = 2"},
        ]

        extract_business_concepts_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
            progress_callback=callback,
        )

        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "a.py")
        assert progress_calls[1] == (2, 2, "b.py")

    def test_aggregates_results(self):
        """Should aggregate nodes and edges from all files."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_batch

        class MockResponse:
            content = '{"concepts": [{"conceptName": "Test", "conceptType": "entity", "description": "Test", "confidence": 0.9}]}'
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=MockResponse())

        files = [
            {"path": "a.py", "content": "class A: pass"},
            {"path": "b.py", "content": "class B: pass"},
        ]

        result = extract_business_concepts_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        # Should have 2 nodes (one per file) but they have same conceptName
        # so might be deduplicated depending on implementation
        assert result["stats"]["total_nodes"] == 2
        assert result["stats"]["files_with_concepts"] == 2

    def test_includes_file_results(self):
        """Should include per-file results with llm_details."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_batch

        mock_response = MagicMock()
        mock_response.content = '{"concepts": []}'
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=mock_response)

        files = [{"path": "test.py", "content": "x = 1"}]

        result = extract_business_concepts_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        assert "file_results" in result
        assert len(result["file_results"]) == 1
        assert result["file_results"][0]["file_path"] == "test.py"
        assert "llm_details" in result["file_results"][0]

    def test_collects_errors_from_all_files(self):
        """Should collect errors from all files."""
        from deriva.modules.extraction.business_concept import extract_business_concepts_batch

        mock_response = MagicMock()
        mock_response.content = "invalid json"
        delattr(mock_response, "error")

        mock_llm_fn = MagicMock(return_value=mock_response)

        files = [
            {"path": "a.py", "content": "x = 1"},
            {"path": "b.py", "content": "y = 2"},
        ]

        result = extract_business_concepts_batch(
            files=files,
            repo_name="test-repo",
            llm_query_fn=mock_llm_fn,
            config={"instruction": "Extract", "example": "{}"},
        )

        # Should have errors from both files
        assert len(result["errors"]) >= 2


class TestSystemPromptFromConfig:
    """The system prompt is the versioned config instruction, used verbatim (no text added in code)."""

    def test_multi_file_system_prompt_is_the_config_instruction(self):
        from unittest.mock import MagicMock

        from deriva.modules.extraction.business_concept import extract_business_concepts_multi

        llm = MagicMock(return_value=MagicMock(content='{"concepts": []}', usage=None))

        extract_business_concepts_multi(
            files=[{"path": "docs/a.md", "content": "text"}],
            repo_name="repo",
            llm_query_fn=llm,
            config={"instruction": "SYSTEM FROM CONFIG", "example": "{}"},
        )

        assert llm.call_args.args[2] == "SYSTEM FROM CONFIG"

    def test_single_file_prompt_starts_with_the_config_instruction(self):
        from deriva.modules.extraction.business_concept import build_extraction_prompt

        prompt = build_extraction_prompt("text", "docs/a.md", "SYSTEM FROM CONFIG", "{}")

        assert prompt.startswith("SYSTEM FROM CONFIG\n\n")


class TestMergeConceptProperties:
    """One concept seen in several files: the combined node must not depend on file order."""

    README = {"conceptName": "User", "conceptType": "entity", "confidence": 0.9, "description": "from readme", "originSource": "README.md"}
    RTF = {"conceptName": "User", "conceptType": "actor", "confidence": 0.9, "description": "from requirements", "originSource": "docs/requirements.rtf"}
    DOC = {"conceptName": "User", "conceptType": "actor", "confidence": 0.7, "description": "weak", "originSource": "docs/a.md"}

    @staticmethod
    def _fold(occurrences):
        from deriva.modules.extraction.business_concept import merge_concept_properties

        merged = None
        for o in occurrences:
            merged = merge_concept_properties(merged, o)
        return merged

    def test_all_types_are_kept(self):
        merged = self._fold([self.README, self.RTF])

        assert merged["conceptTypes"] == ["actor", "entity"]
        assert merged["confidence"] == 0.9

    def test_result_is_independent_of_order(self):
        import itertools

        results = {json.dumps(self._fold(p), sort_keys=True) for p in itertools.permutations([self.README, self.RTF, self.DOC])}

        assert len(results) == 1

    def test_primary_fields_come_from_the_strongest_occurrence(self):
        merged = self._fold([self.DOC, self.README])

        assert (merged["conceptType"], merged["description"], merged["originSource"]) == ("entity", "from readme", "README.md")

    def test_single_occurrence_gets_its_type_as_the_set(self):
        assert self._fold([self.DOC])["conceptTypes"] == ["actor"]
