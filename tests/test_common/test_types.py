"""Tests for common.types module."""


from deriva.common.types import (
    BaseResult,
    DerivationData,
    ExtractionData,
    LLMDetails,
    ValidationData,
    ValidationIssue,
)


class TestBaseResult:
    """Tests for BaseResult TypedDict."""

    def test_base_result_structure(self):
        """BaseResult should have success, errors, and stats."""
        result: BaseResult = {
            "success": True,
            "errors": [],
            "stats": {"count": 1},
        }
        assert result["success"] is True
        assert result["errors"] == []
        assert result["stats"]["count"] == 1

    def test_base_result_with_errors(self):
        """BaseResult should handle error lists."""
        result: BaseResult = {
            "success": False,
            "errors": ["Error 1", "Error 2"],
            "stats": {},
        }
        assert result["success"] is False
        assert len(result["errors"]) == 2


class TestLLMDetails:
    """Tests for LLMDetails TypedDict."""

    def test_llm_details_structure(self):
        """LLMDetails should track LLM call metadata."""
        details: LLMDetails = {
            "prompt": "Test prompt",
            "response": '{"result": "ok"}',
            "tokens_in": 100,
            "tokens_out": 50,
            "cache_used": False,
        }
        assert details["tokens_in"] == 100
        assert details["cache_used"] is False


class TestExtractionTypes:
    """Tests for extraction-related types."""

    def test_extraction_data_structure(self):
        """ExtractionData should have nodes and edges."""
        data: ExtractionData = {
            "nodes": [{"id": "node1", "label": "Test"}],
            "edges": [{"from": "node1", "to": "node2"}],
        }
        assert len(data["nodes"]) == 1
        assert len(data["edges"]) == 1


class TestDerivationTypes:
    """Tests for derivation-related types."""

    def test_derivation_data_structure(self):
        """DerivationData should have elements_created."""
        data: DerivationData = {
            "elements_created": [{"id": "elem1", "name": "Test Element"}],
        }
        assert len(data["elements_created"]) == 1


class TestValidationTypes:
    """Tests for validation-related types."""

    def test_validation_issue_structure(self):
        """ValidationIssue should capture issue details."""
        issue: ValidationIssue = {
            "type": "error",
            "rule": "relationship_validity",
            "message": "Invalid relationship",
            "element_id": "elem1",
            "severity": "major",
        }
        assert issue["severity"] == "major"

    def test_validation_data_structure(self):
        """ValidationData should have issues, passed, and failed."""
        data: ValidationData = {
            "issues": [],
            "passed": ["elem1", "elem2"],
            "failed": ["elem3"],
        }
        assert len(data["passed"]) == 2
        assert len(data["failed"]) == 1
