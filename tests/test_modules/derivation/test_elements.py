"""Generic tests for all derivation element modules.

Tests the common interface and behavior across all 13 derivation element modules.
Individual element-specific tests are in their respective test files.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

# All derivation element module names
DERIVATION_MODULES = [
    "application_component",
    "application_interface",
    "application_service",
    "business_actor",
    "business_event",
    "business_function",
    "business_object",
    "business_process",
    "data_object",
    "device",
    "node",
    "system_software",
    "technology_service",
]


def get_module(module_name: str):
    """Dynamically import a derivation module."""
    return importlib.import_module(f"deriva.modules.derivation.{module_name}")


class TestModuleExports:
    """Tests that all derivation modules export required interface."""

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_exports_element_type(self, module_name):
        """All derivation modules should export ELEMENT_TYPE constant."""
        module = get_module(module_name)
        assert hasattr(module, "ELEMENT_TYPE")
        assert isinstance(module.ELEMENT_TYPE, str)
        assert len(module.ELEMENT_TYPE) > 0

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_exports_generate_function(self, module_name):
        """All derivation modules should export generate() function."""
        module = get_module(module_name)
        assert hasattr(module, "generate")
        assert callable(module.generate)

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_exports_filter_candidates(self, module_name):
        """All derivation modules should export filter_candidates() function."""
        module = get_module(module_name)
        assert hasattr(module, "filter_candidates")
        assert callable(module.filter_candidates)


class TestGenerateFunction:
    """Tests for generate() function across all modules."""

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_returns_generation_result(self, module_name):
        """All derivation modules should return GenerationResult from generate()."""
        from deriva.modules.derivation.base import GenerationResult

        module = get_module(module_name)

        # Mock the graph manager to return empty results (simplest path)
        mock_manager = MagicMock()
        mock_manager.query.return_value = []

        result = module.generate(
            graph_manager=mock_manager,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test instruction",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        assert isinstance(result, GenerationResult)
        assert result.success is True  # Empty results should succeed

    def test_handles_query_exception_application_component(self):
        """ApplicationComponent handles query exceptions (only module with try/except around query)."""
        module = get_module("application_component")

        # First call (enrichments) succeeds, second call (candidates) fails
        failing_manager = MagicMock()
        failing_manager.query.side_effect = [
            [],  # Empty enrichments
            Exception("DB connection error"),  # Candidate query fails
        ]

        result = module.generate(
            graph_manager=failing_manager,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        assert result.success is False
        assert len(result.errors) > 0
        assert any("error" in e.lower() or "failed" in e.lower() for e in result.errors)

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_creates_elements_with_valid_llm_response(self, module_name):
        """All derivation modules should create elements when LLM returns valid response."""
        module = get_module(module_name)
        element_type = module.ELEMENT_TYPE

        # Setup graph manager with enrichment and candidate results
        mock_manager = MagicMock()
        enrichment_results = [
            {
                "node_id": "node_1",
                "pagerank": 0.8,
                "louvain_community": "node_1",
                "kcore_level": 3,
                "is_articulation_point": False,
                "in_degree": 5,
                "out_degree": 3,
            },
        ]
        candidate_results = [
            {
                "id": "node_1",
                "name": "TestElement",
                "labels": ["Directory"],
                "properties": {"path": "/src/test"},
            },
        ]
        mock_manager.query.side_effect = [enrichment_results, candidate_results]

        # Setup LLM response with valid element
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = f"""{{
            "elements": [
                {{
                    "identifier": "test_{element_type.lower()}_1",
                    "name": "Test {element_type}",
                    "documentation": "Test documentation"
                }}
            ]
        }}"""
        mock_llm.return_value = mock_response

        mock_archimate = MagicMock()

        result = module.generate(
            graph_manager=mock_manager,
            archimate_manager=mock_archimate,
            engine=MagicMock(),
            llm_query_fn=mock_llm,
            query="MATCH (n) RETURN n",
            instruction="Test instruction",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        # Should create at least one element
        assert result.elements_created >= 1
        # Should call add_element on archimate manager
        assert mock_archimate.add_element.called

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_handles_llm_exception(self, module_name):
        """All derivation modules should handle LLM exceptions gracefully."""
        module = get_module(module_name)

        # Setup graph manager with valid results
        mock_manager = MagicMock()
        enrichment_results = [
            {
                "node_id": "n1",
                "pagerank": 0.5,
                "louvain_community": "n1",
                "kcore_level": 1,
                "is_articulation_point": False,
                "in_degree": 1,
                "out_degree": 1,
            }
        ]
        candidate_results = [{"id": "n1", "name": "Test", "labels": [], "properties": {}}]
        mock_manager.query.side_effect = [enrichment_results, candidate_results]

        # LLM throws exception
        failing_llm = MagicMock()
        failing_llm.side_effect = Exception("LLM API error")

        result = module.generate(
            graph_manager=mock_manager,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=failing_llm,
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        # Should have errors but not crash
        assert len(result.errors) > 0
        assert any("llm" in e.lower() or "error" in e.lower() for e in result.errors)

    @pytest.mark.parametrize("module_name", DERIVATION_MODULES)
    def test_handles_invalid_llm_json(self, module_name):
        """All derivation modules should handle invalid JSON from LLM."""
        module = get_module(module_name)

        # Setup graph manager
        mock_manager = MagicMock()
        enrichment_results = [
            {
                "node_id": "n1",
                "pagerank": 0.5,
                "louvain_community": "n1",
                "kcore_level": 1,
                "is_articulation_point": False,
                "in_degree": 1,
                "out_degree": 1,
            }
        ]
        candidate_results = [{"id": "n1", "name": "Test", "labels": [], "properties": {}}]
        mock_manager.query.side_effect = [enrichment_results, candidate_results]

        # LLM returns invalid JSON
        invalid_llm = MagicMock()
        invalid_response = MagicMock()
        invalid_response.content = "this is not valid json"
        invalid_llm.return_value = invalid_response

        result = module.generate(
            graph_manager=mock_manager,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=invalid_llm,
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        # Should have parse errors
        assert len(result.errors) > 0
