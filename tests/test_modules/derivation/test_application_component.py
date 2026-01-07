"""Tests for application_component derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(name: str = "test", pagerank: float = 0.5) -> Candidate:
    """Create test candidate."""
    return Candidate(node_id="test_id", name=name, pagerank=pagerank)


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_empty_input_returns_empty(self):
        from deriva.modules.derivation.application_component import filter_candidates

        result = filter_candidates([], {}, 10)
        assert result == []

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.application_component import filter_candidates

        candidates = [make_candidate(f"comp_{i}", pagerank=0.1 * i) for i in range(20)]
        result = filter_candidates(candidates, {}, 5)
        assert len(result) <= 5


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich):
        from deriva.modules.derivation.application_component import generate

        mock_query.return_value = []
        mock_enrich.return_value = {}

        result = generate(
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            engine="test",
            llm_query_fn=Mock(),
            query="MATCH (n)",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert isinstance(result, GenerationResult)
        assert result.elements_created == 0
