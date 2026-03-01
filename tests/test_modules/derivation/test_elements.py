"""Generic tests for all derivation element modules.

Tests the common interface and behavior across all 13 derivation element modules.
Individual element-specific tests are in their respective test files.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import deriva.services.config as config_module
from deriva.modules.derivation.base import clear_enrichment_cache
from deriva.services.derivation import DERIVATION_REGISTRY


@pytest.fixture(autouse=True)
def reset_enrichment_cache():
    """Clear the module-level enrichment cache before each test."""
    clear_enrichment_cache()
    yield
    clear_enrichment_cache()


# All derivation element types
DERIVATION_ELEMENT_TYPES = list(DERIVATION_REGISTRY.keys())


def get_derivation(element_type: str):
    """Get a derivation class instance for an element type."""
    cls = DERIVATION_REGISTRY.get(element_type)
    return cls() if cls else None


class TestDerivationClasses:
    """Tests that all derivation classes have required interface."""

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_has_element_type(self, element_type):
        """All derivation classes should have ELEMENT_TYPE attribute."""
        derivation = get_derivation(element_type)
        assert hasattr(derivation, "ELEMENT_TYPE")
        assert isinstance(derivation.ELEMENT_TYPE, str)
        assert derivation.ELEMENT_TYPE == element_type

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_has_generate_method(self, element_type):
        """All derivation classes should have generate() method."""
        derivation = get_derivation(element_type)
        assert hasattr(derivation, "generate")
        assert callable(derivation.generate)

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_has_filter_candidates_method(self, element_type):
        """All derivation classes should have filter_candidates() method."""
        derivation = get_derivation(element_type)
        assert hasattr(derivation, "filter_candidates")
        assert callable(derivation.filter_candidates)


class TestGenerateMethod:
    """Tests for generate() method across all derivation classes."""

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_returns_generation_result(self, element_type):
        """All derivation classes should return GenerationResult from generate()."""
        from deriva.modules.derivation.base import GenerationResult

        derivation = get_derivation(element_type)

        # Mock the graph manager to return empty results (simplest path)
        mock_manager = MagicMock()
        mock_manager.query.return_value = []

        result = derivation.generate(
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
        """ApplicationComponent handles query exceptions."""
        derivation = get_derivation("ApplicationComponent")

        # First call (enrichments) succeeds, second call (candidates) fails
        failing_manager = MagicMock()
        failing_manager.query.side_effect = [
            [],  # Empty enrichments
            Exception("DB connection error"),  # Candidate query fails
        ]

        result = derivation.generate(
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

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_creates_elements_with_valid_llm_response(self, element_type, monkeypatch):
        """All derivation classes should create elements when LLM returns valid response."""
        derivation = get_derivation(element_type)

        # Mock config.get_derivation_patterns to return patterns matching "TestElement"
        # This ensures PatternBasedDerivation modules don't filter out all candidates
        def mock_patterns(_engine, _element_type):
            return {"include": {"test"}, "exclude": set()}

        monkeypatch.setattr(config_module, "get_derivation_patterns", mock_patterns)

        # Setup graph manager with stats, enrichment and candidate results
        mock_manager = MagicMock()
        # Stats for compute_graph_hash (called for cache lookup and cache store)
        stats_results = [{"node_count": 10, "edge_count": 20}]
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
                "labels": ["TypeDefinition"],
                "properties": {"path": "/src/test"},
            },
        ]
        # Order: stats (cache lookup) -> enrichments -> stats (cache store) -> candidates
        mock_manager.query.side_effect = [stats_results, enrichment_results, stats_results, candidate_results]

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

        result = derivation.generate(
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

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_handles_llm_exception(self, element_type, monkeypatch):
        """All derivation classes should handle LLM exceptions gracefully."""
        derivation = get_derivation(element_type)

        # Mock config.get_derivation_patterns to return patterns matching "Test"
        # This ensures PatternBasedDerivation modules don't filter out all candidates
        def mock_patterns(_engine, _element_type):
            return {"include": {"test"}, "exclude": set()}

        monkeypatch.setattr(config_module, "get_derivation_patterns", mock_patterns)

        # Setup graph manager with valid results
        mock_manager = MagicMock()
        # Stats for compute_graph_hash (called for cache lookup and cache store)
        stats_results = [{"node_count": 10, "edge_count": 20}]
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
        # Order: stats (cache lookup) -> enrichments -> stats (cache store) -> candidates
        mock_manager.query.side_effect = [stats_results, enrichment_results, stats_results, candidate_results]

        # LLM throws exception
        failing_llm = MagicMock()
        failing_llm.side_effect = Exception("LLM API error")

        result = derivation.generate(
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

        # Should either have errors (if LLM was called) or success with no elements
        # (if candidates were filtered out before LLM call)
        if result.errors:
            assert any("llm" in e.lower() or "error" in e.lower() for e in result.errors)
        else:
            # If no errors, means no candidates reached LLM (filtered out)
            assert result.success is True
            assert result.elements_created == 0

    @pytest.mark.parametrize("element_type", DERIVATION_ELEMENT_TYPES)
    def test_handles_invalid_llm_json(self, element_type, monkeypatch):
        """All derivation classes should handle invalid JSON from LLM."""
        derivation = get_derivation(element_type)

        # Mock config.get_derivation_patterns to return patterns matching "Test"
        # This ensures PatternBasedDerivation modules don't filter out all candidates
        def mock_patterns(_engine, _element_type):
            return {"include": {"test"}, "exclude": set()}

        monkeypatch.setattr(config_module, "get_derivation_patterns", mock_patterns)

        # Setup graph manager
        mock_manager = MagicMock()
        # Stats for compute_graph_hash (called for cache lookup and cache store)
        stats_results = [{"node_count": 10, "edge_count": 20}]
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
        # Order: stats (cache lookup) -> enrichments -> stats (cache store) -> candidates
        mock_manager.query.side_effect = [stats_results, enrichment_results, stats_results, candidate_results]

        # LLM returns invalid JSON
        invalid_llm = MagicMock()
        invalid_response = MagicMock()
        invalid_response.content = "this is not valid json"
        invalid_llm.return_value = invalid_response

        result = derivation.generate(
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

        # Should have parse errors (if LLM was called) or success with no elements
        if result.errors:
            assert len(result.errors) > 0
        else:
            # If no errors, means no candidates reached LLM (filtered out)
            assert result.success is True
            assert result.elements_created == 0
