"""Tests for modules.extraction.directory_classification module."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from deriva.modules.extraction.directory_classification import (
    DIRECTORY_CLASSIFICATION_SCHEMA,
    build_business_concept_node,
    build_classification_prompt,
    build_technology_node,
    classify_directories,
)


class TestDirectoryClassificationSchema:
    """Tests for the JSON schema definition."""

    def test_schema_has_required_structure(self):
        """Schema should have the expected structure."""
        assert DIRECTORY_CLASSIFICATION_SCHEMA["name"] == "directory_classification"
        assert DIRECTORY_CLASSIFICATION_SCHEMA["strict"] is True
        schema = cast(dict[str, Any], DIRECTORY_CLASSIFICATION_SCHEMA["schema"])
        assert "classifications" in schema["properties"]

    def test_schema_classification_fields(self):
        """Schema should define all classification fields."""
        schema = cast(dict[str, Any], DIRECTORY_CLASSIFICATION_SCHEMA["schema"])
        items = schema["properties"]["classifications"]["items"]
        required_fields = items["required"]

        assert "directoryName" in required_fields
        assert "conceptName" not in required_fields  # names come from the directory
        assert "classification" in required_fields
        assert "conceptType" in required_fields
        assert "description" in required_fields
        assert "confidence" in required_fields

    def test_classification_enum_values(self):
        """Schema should have correct enum values for classification."""
        schema = cast(dict[str, Any], DIRECTORY_CLASSIFICATION_SCHEMA["schema"])
        items = schema["properties"]["classifications"]["items"]
        enum_values = items["properties"]["classification"]["enum"]

        assert "business" in enum_values
        assert "technology" in enum_values
        assert "skip" in enum_values


class TestBuildClassificationPrompt:
    """Tests for build_classification_prompt function."""

    def test_builds_prompt_with_directories(self):
        """Should build prompt containing directory information."""
        directories = [
            {"name": "orders", "path": "src/orders"},
            {"name": "kafka", "path": "infra/kafka"},
        ]
        instruction = "Classify directories by domain."
        example = '{"classifications": []}'

        prompt = build_classification_prompt(directories, instruction, example)

        assert "Classify directories by domain." in prompt
        assert "orders" in prompt
        assert "src/orders" in prompt
        assert "kafka" in prompt
        assert "infra/kafka" in prompt
        assert '{"classifications": []}' in prompt

    def test_handles_empty_directories(self):
        """Should build prompt even with empty directory list."""
        directories = []
        instruction = "Test instruction"
        example = "{}"

        prompt = build_classification_prompt(directories, instruction, example)

        assert "Test instruction" in prompt
        assert "[]" in prompt  # Empty JSON array

    def test_handles_alternate_key_names(self):
        """Should handle dirName/dirPath alternative keys."""
        directories = [
            {"dirName": "customers", "dirPath": "src/customers"},
        ]
        instruction = "Classify"
        example = "{}"

        prompt = build_classification_prompt(directories, instruction, example)

        assert "customers" in prompt
        assert "src/customers" in prompt


class TestBuildBusinessConceptNode:
    """Tests for build_business_concept_node function."""

    def test_builds_node_with_correct_labels(self):
        """Should create node with Graph:BusinessConcept label."""
        classification = {
            "directoryName": "orders",
            "conceptName": "OrderManagement",
            "conceptType": "entity",
            "description": "Manages orders",
            "confidence": 0.9,
        }

        node = build_business_concept_node(classification, "dir_orders", "myrepo")

        assert "Graph" in node["labels"]
        assert "Graph:BusinessConcept" in node["labels"]

    def test_builds_node_with_correct_properties(self):
        """Should populate node properties correctly."""
        classification = {
            "directoryName": "orders",
            "conceptName": "OrderManagement",
            "conceptType": "entity",
            "description": "Manages orders",
            "confidence": 0.9,
        }

        node = build_business_concept_node(classification, "dir_orders", "myrepo")

        props = node["properties"]
        assert props["conceptName"] == "Orders"  # from the directory, not the LLM
        assert props["conceptType"] == "entity"
        assert props["description"] == "Manages orders"
        assert props["confidence"] == 0.9
        assert props["repositoryName"] == "myrepo"
        assert props["originSource"] == "directory:orders/"
        assert props["active"] is True

    def test_generates_deterministic_id(self):
        """Should generate consistent node IDs."""
        classification = {
            "directoryName": "customers",
            "conceptName": "CustomerManagement",
            "conceptType": "entity",
            "description": "Handles customers",
            "confidence": 0.85,
        }

        node = build_business_concept_node(classification, "dir_customers", "testrepo")

        assert node["id"] == "concept::testrepo::customers"

    def test_separators_in_directory_name(self):
        """Directory 'user_management' becomes concept 'UserManagement'."""
        classification = {
            "directoryName": "user_management",
            "conceptName": "User Management",
            "conceptType": "entity",
            "description": "User management",
            "confidence": 0.8,
        }

        node = build_business_concept_node(classification, "dir_users", "repo")

        assert node["id"] == "concept::repo::usermanagement"
        assert node["properties"]["conceptName"] == "UserManagement"


class TestBuildTechnologyNode:
    """Tests for build_technology_node function."""

    def test_builds_node_with_correct_labels(self):
        """Should create node with Graph:Technology label."""
        classification = {
            "directoryName": "kafka",
            "conceptName": "Kafka",
            "conceptType": "infrastructure",
            "description": "Message broker",
            "confidence": 0.95,
        }

        node = build_technology_node(classification, "dir_kafka", "myrepo")

        assert "Graph" in node["labels"]
        assert "Graph:Technology" in node["labels"]

    def test_builds_node_with_correct_properties(self):
        """Should populate technology-specific properties."""
        classification = {
            "directoryName": "redis",
            "conceptName": "Redis",
            "conceptType": "cache",
            "description": "In-memory cache",
            "confidence": 0.9,
        }

        node = build_technology_node(classification, "dir_redis", "myrepo")

        props = node["properties"]
        assert props["technologyName"] == "Redis"
        assert props["technologyType"] == "cache"
        assert props["description"] == "In-memory cache"
        assert props["confidence"] == 0.9
        assert props["repositoryName"] == "myrepo"
        assert props["originSource"] == "directory:redis/"

    def test_generates_tech_prefixed_id(self):
        """Should generate ID with tech_ prefix."""
        classification = {
            "directoryName": "elasticsearch",
            "conceptName": "Elasticsearch",
            "conceptType": "search",
            "description": "Search engine",
            "confidence": 0.85,
        }

        node = build_technology_node(classification, "dir_es", "repo")

        assert node["id"] == "tech::repo::elasticsearch"


class TestClassifyDirectories:
    """Tests for classify_directories function."""

    def test_returns_empty_result_for_no_directories(self):
        """Should return success with empty data when no directories provided."""
        result = classify_directories(
            directories=[],
            repo_name="test",
            llm_query_fn=MagicMock(),
            config={},
        )

        assert result["success"] is True
        assert not result["data"]["nodes"]
        assert not result["data"]["edges"]
        assert result["stats"]["total_nodes"] == 0

    def test_handles_llm_error_response(self):
        """Should handle LLM error gracefully."""
        mock_response = MagicMock()
        mock_response.error = "API rate limit exceeded"
        mock_response.content = None

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "orders", "path": "src/orders", "id": "dir_1"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "test", "example": "{}"},
        )

        assert result["success"] is False
        assert "LLM error" in result["errors"][0]

    def test_classifies_business_directories(self):
        """Should create BusinessConcept nodes for business classifications."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "orders",
                    "conceptName": "OrderManagement",
                    "classification": "business",
                    "conceptType": "entity",
                    "description": "Order processing",
                    "confidence": 0.9
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "orders", "path": "src/orders", "id": "dir_orders"}],
            repo_name="testrepo",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert result["success"] is True
        assert result["stats"]["business_concepts"] == 1
        assert len(result["data"]["nodes"]) == 1
        assert "Graph:BusinessConcept" in result["data"]["nodes"][0]["labels"]

    def test_classifies_technology_directories(self):
        """Should create Technology nodes for technology classifications."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "kafka",
                    "conceptName": "Kafka",
                    "classification": "technology",
                    "conceptType": "messaging",
                    "description": "Message broker",
                    "confidence": 0.95
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "kafka", "path": "infra/kafka", "id": "dir_kafka"}],
            repo_name="testrepo",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert result["success"] is True
        assert result["stats"]["technologies"] == 1
        assert len(result["data"]["nodes"]) == 1
        assert "Graph:Technology" in result["data"]["nodes"][0]["labels"]

    def test_skips_low_confidence_classifications(self):
        """Should skip directories with confidence below 0.7."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "maybe_business",
                    "conceptName": "Uncertain",
                    "classification": "business",
                    "conceptType": "entity",
                    "description": "Not sure",
                    "confidence": 0.5
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "maybe_business", "path": "src/maybe", "id": "dir_1"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert result["success"] is True
        assert result["stats"]["skipped"] == 1
        assert result["stats"]["total_nodes"] == 0
        assert len(result["data"]["nodes"]) == 0

    def test_skips_skip_classifications(self):
        """Should skip directories classified as 'skip'."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "utils",
                    "conceptName": "Utils",
                    "classification": "skip",
                    "conceptType": "utility",
                    "description": "Generic utilities",
                    "confidence": 0.95
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "utils", "path": "src/utils", "id": "dir_utils"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert result["success"] is True
        assert result["stats"]["skipped"] == 1
        assert len(result["data"]["nodes"]) == 0

    def test_creates_edges_from_directories(self):
        """Should create REPRESENTS edges from Directory to created nodes."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "orders",
                    "conceptName": "OrderManagement",
                    "classification": "business",
                    "conceptType": "entity",
                    "description": "Orders",
                    "confidence": 0.9
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "orders", "path": "src/orders", "id": "dir_orders"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert len(result["data"]["edges"]) == 1
        edge = result["data"]["edges"][0]
        assert edge["source"] == "dir_orders"
        assert edge["relationship_type"] == "REPRESENTS"
        assert edge["properties"]["confidence"] == 0.9

    def test_handles_mixed_classifications(self):
        """Should handle a mix of business, technology, and skip."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = """{
            "classifications": [
                {
                    "directoryName": "orders",
                    "conceptName": "OrderManagement",
                    "classification": "business",
                    "conceptType": "entity",
                    "description": "Orders",
                    "confidence": 0.9
                },
                {
                    "directoryName": "kafka",
                    "conceptName": "Kafka",
                    "classification": "technology",
                    "conceptType": "messaging",
                    "description": "Messaging",
                    "confidence": 0.95
                },
                {
                    "directoryName": "utils",
                    "conceptName": "Utils",
                    "classification": "skip",
                    "conceptType": "utility",
                    "description": "Utilities",
                    "confidence": 0.8
                }
            ]
        }"""
        mock_response.usage = {"prompt_tokens": 200, "completion_tokens": 100}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        directories = [
            {"name": "orders", "path": "src/orders", "id": "dir_orders"},
            {"name": "kafka", "path": "infra/kafka", "id": "dir_kafka"},
            {"name": "utils", "path": "src/utils", "id": "dir_utils"},
        ]

        result = classify_directories(
            directories=directories,
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Classify", "example": "{}"},
        )

        assert result["success"] is True
        assert result["stats"]["business_concepts"] == 1
        assert result["stats"]["technologies"] == 1
        assert result["stats"]["skipped"] == 1
        assert result["stats"]["total_nodes"] == 2
        assert len(result["data"]["nodes"]) == 2
        assert len(result["data"]["edges"]) == 2

    def test_captures_llm_details(self):
        """Should capture LLM usage details in response."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = '{"classifications": []}'
        mock_response.usage = {"prompt_tokens": 150, "completion_tokens": 25}
        mock_response.response_type = "ResponseType.CACHED"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "test", "path": "test", "id": "dir_1"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Test", "example": "{}"},
        )

        assert "llm_details" in result
        assert result["llm_details"]["tokens_in"] == 150
        assert result["llm_details"]["tokens_out"] == 25
        assert result["llm_details"]["cache_used"] is True

    def test_handles_parse_error(self):
        """Should handle invalid JSON from LLM gracefully."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = "This is not valid JSON {{"
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        mock_llm = MagicMock(return_value=mock_response)

        result = classify_directories(
            directories=[{"name": "test", "path": "test", "id": "dir_1"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Test", "example": "{}"},
        )

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_handles_exception_gracefully(self):
        """Should catch and return exceptions as errors."""
        mock_llm = MagicMock(side_effect=Exception("Network error"))

        result = classify_directories(
            directories=[{"name": "test", "path": "test", "id": "dir_1"}],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Test", "example": "{}"},
        )

        assert result["success"] is False
        assert "Network error" in result["errors"][0]


class TestDirectoryClassificationVoting:
    """The LLM only classifies directories (k samples, majority); names come from the directory."""

    def test_vote_takes_the_majority_classification(self):
        from deriva.modules.extraction.directory_classification import vote_directory_classifications

        samples = [
            [{"directoryName": "claims_handling", "classification": "business", "conceptType": "process", "confidence": 0.9, "description": "a"}],
            [{"directoryName": "claims_handling", "classification": "business", "conceptType": "process", "confidence": 0.8, "description": "b"}],
            [{"directoryName": "claims_handling", "classification": "skip", "conceptType": "", "confidence": 0.9, "description": "c"}],
        ]

        (winner,) = vote_directory_classifications(samples, min_votes=2)

        assert (winner["classification"], winner["conceptType"]) == ("business", "process")
        assert winner["confidence"] == 0.85

    def test_no_majority_means_skip(self):
        from deriva.modules.extraction.directory_classification import vote_directory_classifications

        samples = [
            [{"directoryName": "x", "classification": "business", "conceptType": "entity", "confidence": 0.9, "description": ""}],
            [{"directoryName": "x", "classification": "technology", "conceptType": "framework", "confidence": 0.9, "description": ""}],
            [{"directoryName": "x", "classification": "skip", "conceptType": "", "confidence": 0.9, "description": ""}],
        ]

        assert vote_directory_classifications(samples, min_votes=2) == []

    def test_names_come_from_the_directory(self):
        from deriva.modules.extraction.directory_classification import build_business_concept_node, build_technology_node

        concept = build_business_concept_node({"directoryName": "claims_handling", "conceptType": "process"}, "dir::r::claims_handling", "r")
        tech = build_technology_node({"directoryName": "kafka", "conceptType": "infrastructure"}, "dir::r::kafka", "r")

        assert (concept["properties"]["conceptName"], concept["id"]) == ("ClaimsHandling", "concept::r::claimshandling")
        assert tech["properties"]["technologyName"] == "Kafka"

    def test_module_schema_matches_the_enforced_model(self):
        from deriva.adapters.llm.schemas import DirectoryClassificationItem
        from deriva.modules.extraction.directory_classification import DIRECTORY_CLASSIFICATION_SCHEMA

        items = DIRECTORY_CLASSIFICATION_SCHEMA["schema"]["properties"]["classifications"]["items"]["properties"]
        assert set(items) == set(DirectoryClassificationItem.model_fields)
        assert "conceptName" not in items
