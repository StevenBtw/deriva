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

    def test_the_answer_is_a_closed_choice(self):
        """Only decisions: no generated description or confidence, and the type from a fixed list."""
        schema = cast(dict[str, Any], DIRECTORY_CLASSIFICATION_SCHEMA["schema"])
        items = schema["properties"]["classifications"]["items"]

        assert set(items["properties"]) == {"directoryName", "classification", "conceptType"}
        assert items["properties"]["conceptType"]["enum"] == ["entity", "process", "actor", "capability", "infrastructure", "framework", "none"]

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

    def test_languages_are_sorted(self):
        """The language list does not depend on the order the files were stored in."""
        directories = [{"name": "alpha", "path": "r/alpha", "file_count": 2, "source_count": 2, "subtypes": ["yaml", None, "java"]}]

        prompt = build_classification_prompt(directories, "I", "{}")

        assert prompt.index('"java"') < prompt.index('"yaml"')

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
        classification = {"directoryName": "records", "conceptType": "entity"}

        node = build_business_concept_node(classification, "dir_records", "myrepo", 0.9)

        assert "Graph" in node["labels"]
        assert "Graph:BusinessConcept" in node["labels"]

    def test_builds_node_with_correct_properties(self):
        """Name from the directory, type from the answer, confidence from the step's config; no generated text."""
        classification = {"directoryName": "records", "conceptType": "entity"}

        node = build_business_concept_node(classification, "dir_records", "myrepo", 0.9)

        props = node["properties"]
        assert props["conceptName"] == "Records"  # from the directory, not the LLM
        assert props["conceptType"] == "entity"
        assert props["description"] == ""
        assert props["confidence"] == 0.9
        assert props["repositoryName"] == "myrepo"
        assert props["originSource"] == "directory:records/"
        assert props["active"] is True

    def test_generates_deterministic_id(self):
        """Should generate consistent node IDs."""
        classification = {"directoryName": "records", "conceptType": "entity"}

        node = build_business_concept_node(classification, "dir_records", "testrepo", 0.9)

        assert node["id"] == "concept::testrepo::record"  # canonical name key: words singular

    def test_separators_in_directory_name(self):
        """Directory 'user_management' becomes concept 'UserManagement'."""
        classification = {"directoryName": "user_management", "conceptType": "entity"}

        node = build_business_concept_node(classification, "dir_users", "repo", 0.9)

        assert node["id"] == "concept::repo::usermanagement"
        assert node["properties"]["conceptName"] == "UserManagement"


class TestBuildTechnologyNode:
    """Tests for build_technology_node function."""

    def test_builds_node_with_correct_labels(self):
        """Should create node with Graph:Technology label."""
        classification = {"directoryName": "broker", "conceptType": "infrastructure"}

        node = build_technology_node(classification, "dir_broker", "myrepo", 0.9)

        assert "Graph" in node["labels"]
        assert "Graph:Technology" in node["labels"]

    def test_builds_node_with_correct_properties(self):
        """Should populate technology-specific properties."""
        classification = {"directoryName": "store", "conceptType": "infrastructure"}

        node = build_technology_node(classification, "dir_store", "myrepo", 0.9)

        props = node["properties"]
        assert props["technologyName"] == "Store"
        assert props["technologyType"] == "infrastructure"
        assert props["description"] == ""
        assert props["confidence"] == 0.9
        assert props["repositoryName"] == "myrepo"
        assert props["originSource"] == "directory:store/"

    def test_generates_tech_prefixed_id(self):
        """Should generate ID with tech_ prefix."""
        classification = {"directoryName": "search_engine", "conceptType": "infrastructure"}

        node = build_technology_node(classification, "dir_search", "repo", 0.9)

        assert node["id"] == "tech::repo::searchengine"


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

    def test_nodes_and_edges_get_the_configured_confidence(self):
        """The answer carries only decisions; confidence comes from the step's params, not the LLM."""
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.content = '{"classifications": [{"directoryName": "records", "classification": "business", "conceptType": "entity"}]}'
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "live"

        result = classify_directories(
            directories=[{"name": "records", "path": "src/records", "id": "dir_records"}],
            repo_name="test",
            llm_query_fn=MagicMock(return_value=mock_response),
            config={"instruction": "Classify", "example": "{}", "params": {"confidence": 0.9}},
        )

        (node,) = result["data"]["nodes"]
        (edge,) = result["data"]["edges"]
        assert (node["properties"]["confidence"], node["properties"]["description"]) == (0.9, "")
        assert edge["properties"]["confidence"] == 0.9

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
            config={"instruction": "Classify", "example": "{}", "params": {"confidence": 0.9}},
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
        assert set(winner) == {"directoryName", "classification", "conceptType"}

    def test_no_majority_means_skip(self):
        from deriva.modules.extraction.directory_classification import vote_directory_classifications

        samples = [
            [{"directoryName": "x", "classification": "business", "conceptType": "entity", "confidence": 0.9, "description": ""}],
            [{"directoryName": "x", "classification": "technology", "conceptType": "framework", "confidence": 0.9, "description": ""}],
            [{"directoryName": "x", "classification": "skip", "conceptType": "", "confidence": 0.9, "description": ""}],
        ]

        assert vote_directory_classifications(samples, min_votes=2) == []

    def test_directories_without_a_majority_count_as_skipped(self):
        import json
        from types import SimpleNamespace

        from deriva.modules.extraction.directory_classification import classify_directories

        def answer(b_class, b_type):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "classifications": [
                            {"directoryName": "a", "classification": "business", "conceptType": "process", "confidence": 0.9, "description": ""},
                            {"directoryName": "b", "classification": b_class, "conceptType": b_type, "confidence": 0.9, "description": ""},
                        ]
                    }
                )
            )

        llm = MagicMock(side_effect=[answer("business", "entity"), answer("technology", "framework"), answer("skip", "")])
        result = classify_directories(
            directories=[{"name": "a", "path": "a", "id": "dir::r::a"}, {"name": "b", "path": "b", "id": "dir::r::b"}],
            repo_name="r",
            llm_query_fn=llm,
            config={"instruction": "i", "example": "{}", "params": {"samples": 3, "min_votes": 2}},
        )

        assert result["stats"]["business_concepts"] == 1
        assert result["stats"]["skipped"] == 1

    def test_a_failed_sample_does_not_discard_the_others(self):
        import json
        from types import SimpleNamespace

        from deriva.modules.extraction.directory_classification import classify_directories

        good = SimpleNamespace(
            content=json.dumps({"classifications": [{"directoryName": "a", "classification": "business", "conceptType": "process", "confidence": 0.9, "description": ""}]})
        )
        failed = SimpleNamespace(content="", error="Rate limit exceeded")

        result = classify_directories(
            directories=[{"name": "a", "path": "a", "id": "dir::r::a"}],
            repo_name="r",
            llm_query_fn=MagicMock(side_effect=[failed, good, good]),
            config={"instruction": "i", "example": "{}", "params": {"samples": 3, "min_votes": 2}},
        )

        assert result["success"] is True
        assert result["stats"]["business_concepts"] == 1

    def test_same_named_directories_both_get_their_edge(self):
        """The answer names directories by basename; every directory with that name is linked."""
        import json
        from types import SimpleNamespace

        from deriva.modules.extraction.directory_classification import classify_directories

        answer = SimpleNamespace(
            content=json.dumps({"classifications": [{"directoryName": "orders", "classification": "business", "conceptType": "entity", "confidence": 0.9, "description": ""}]})
        )
        result = classify_directories(
            directories=[{"name": "orders", "path": "a/orders", "id": "dir::r::a_orders"}, {"name": "orders", "path": "b/orders", "id": "dir::r::b_orders"}],
            repo_name="r",
            llm_query_fn=MagicMock(return_value=answer),
            config={"instruction": "i", "example": "{}"},
        )

        assert sorted(e["source"] for e in result["data"]["edges"]) == ["dir::r::a_orders", "dir::r::b_orders"]

    def test_names_come_from_the_directory(self):
        from deriva.modules.extraction.directory_classification import build_business_concept_node, build_technology_node

        concept = build_business_concept_node({"directoryName": "claims_handling", "conceptType": "process"}, "dir::r::claims_handling", "r", 0.9)
        tech = build_technology_node({"directoryName": "kafka", "conceptType": "infrastructure"}, "dir::r::kafka", "r", 0.9)

        assert (concept["properties"]["conceptName"], concept["id"]) == ("ClaimsHandling", "concept::r::claimhandling")
        assert tech["properties"]["technologyName"] == "Kafka"

    def test_module_schema_matches_the_enforced_model(self):
        from deriva.adapters.llm.schemas import DirectoryClassificationItem
        from deriva.modules.extraction.directory_classification import DIRECTORY_CLASSIFICATION_SCHEMA

        items = DIRECTORY_CLASSIFICATION_SCHEMA["schema"]["properties"]["classifications"]["items"]["properties"]
        assert set(items) == set(DirectoryClassificationItem.model_fields)
        assert "conceptName" not in items
        concept_types = DirectoryClassificationItem.model_json_schema()["properties"]["conceptType"]["enum"]
        assert concept_types == items["conceptType"]["enum"]


class TestIdentityFromNameKey:
    """Concept and technology ids come from the canonical name key, whatever step or spelling produced them."""

    def test_document_and_directory_concepts_share_an_id(self):
        from deriva.modules.extraction import concept_candidates, directory_classification

        term = {
            "term": "Claims Handling",
            "language": "en",
            "kind": "noun",
            "english": "claims handling",
            "count": 1,
            "occurrences": [{"path": "doc.md", "segment": 0, "start": 0, "snippet": "s"}],
        }
        (candidate,) = concept_candidates.merge_candidates([term], "r")
        (document,), _ = concept_candidates.concept_nodes_and_edges([(candidate, "business_process")], "r", 0.9)
        directory = directory_classification.build_business_concept_node({"directoryName": "claims_handling", "conceptType": "process"}, "dir::r::claims_handling", "r", 0.9)

        assert document["node_id"] == directory["id"] == "concept::r::claimhandling"

    def test_technology_spellings_share_an_id(self):
        from deriva.modules.extraction import directory_classification, technology_candidates

        spaced = technology_candidates.technology_node_id("r", "Message Broker Server")
        joined = technology_candidates.technology_node_id("r", "MessageBrokerServer")
        directory = directory_classification.build_technology_node({"directoryName": "message-broker-server", "conceptType": "infrastructure"}, "dir::r::mbs", "r", 0.9)

        assert spaced == joined == directory["id"] == "tech::r::messagebrokerserver"


class TestStructuralSkip:
    """Directories the structure already decides as skip never reach the LLM (rule 6a)."""

    PARAMS = {"skip_names": ["utils", "tests"], "skip_trees": ["tests"], "skip_pass_through": True}

    @staticmethod
    def _dir(path, file_count=1, subdir_count=0):
        return {"name": path.rsplit("/", 1)[-1], "path": path, "file_count": file_count, "subdir_count": subdir_count}

    def test_names_trees_and_pass_through_directories_are_skipped(self):
        from deriva.modules.extraction.directory_classification import structural_skip

        directories = [
            self._dir("r/records"),
            self._dir("r/Utils"),  # a skip name, any spelling
            self._dir("r/tests/alpha"),  # inside a skipped tree
            self._dir("r/lib/records", file_count=0, subdir_count=1),  # a path step: no files, one subdirectory
            self._dir("r/lib/records/core", file_count=0, subdir_count=2),  # no files but a branch point
        ]

        keep, skipped = structural_skip(directories, self.PARAMS)

        assert [d["path"] for d in keep] == ["r/records", "r/lib/records/core"]
        assert [d["path"] for d in skipped] == ["r/Utils", "r/tests/alpha", "r/lib/records"]

    def test_no_params_skip_nothing(self):
        from deriva.modules.extraction.directory_classification import structural_skip

        directories = [self._dir("r/utils"), self._dir("r/a", file_count=0, subdir_count=1)]

        assert structural_skip(directories, {}) == (directories, [])


class TestOneDecisionPerName:
    """Directories with the same name (by canonical key) are classified once, as one entry, and share the decision."""

    @staticmethod
    def _dir(path, dir_id, file_count=1, subtypes=("java",)):
        return {"name": path.rsplit("/", 1)[-1], "path": path, "id": dir_id, "file_count": file_count, "source_count": file_count, "subtypes": list(subtypes)}

    def test_same_named_directories_become_one_entry(self):
        from deriva.modules.extraction.directory_classification import group_directories_by_name

        directories = [self._dir("r/a/eventLogger", "d1", 2, ["javascript"]), self._dir("r/b/other", "d2"), self._dir("r/c/event_logger", "d3", 1, ["java"])]

        first, second = group_directories_by_name(directories)

        assert (first["name"], first["paths"], first["ids"]) == ("eventLogger", ["r/a/eventLogger", "r/c/event_logger"], ["d1", "d3"])
        assert (first["file_count"], first["source_count"], first["subtypes"]) == (3, 3, ["java", "javascript"])
        assert (second["name"], second["ids"]) == ("other", ["d2"])

    def test_the_prompt_lists_every_path_of_a_name(self):
        from deriva.modules.extraction.directory_classification import group_directories_by_name

        (group,) = group_directories_by_name([self._dir("r/a/records", "d1"), self._dir("r/b/records", "d2")])

        prompt = build_classification_prompt([group], "I", "{}")

        assert prompt.count('"name": "records"') == 1
        assert "r/a/records" in prompt and "r/b/records" in prompt

    def test_every_directory_of_the_name_gets_the_decision(self):
        from deriva.modules.extraction.directory_classification import group_directories_by_name

        (group,) = group_directories_by_name([self._dir("r/a/eventLogger", "d1"), self._dir("r/b/event_logger", "d2")])
        response = MagicMock(error=None, usage={}, response_type="live")
        # The answer echoes the name in another spelling: matched by name key
        response.content = '{"classifications": [{"directoryName": "EventLogger", "classification": "business", "conceptType": "process"}]}'

        result = classify_directories([group], "r", MagicMock(return_value=response), {"instruction": "I", "example": "{}", "params": {"confidence": 0.9}})

        (node,) = result["data"]["nodes"]
        assert node["properties"]["conceptName"] == "EventLogger"  # the directory's name, not the echo
        assert sorted(e["source"] for e in result["data"]["edges"]) == ["d1", "d2"]
