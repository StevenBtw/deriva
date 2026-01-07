"""Tests for data_object derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(name: str = "test", pagerank: float = 0.5) -> Candidate:
    """Create test candidate."""
    return Candidate(node_id="test_id", name=name, pagerank=pagerank)


class TestIsLikelyDataObject:
    """Tests for _is_likely_data_object helper."""

    def test_empty_name_returns_false(self):
        from deriva.modules.derivation.data_object import _is_likely_data_object

        assert _is_likely_data_object("", {"model"}, set()) is False

    def test_matches_include_pattern(self):
        from deriva.modules.derivation.data_object import _is_likely_data_object

        assert _is_likely_data_object("UserModel", {"model"}, set()) is True

    def test_exclude_pattern_takes_precedence(self):
        from deriva.modules.derivation.data_object import _is_likely_data_object

        assert _is_likely_data_object("test_model", {"model"}, {"test"}) is False


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.data_object import filter_candidates

        candidates = [make_candidate(f"model_{i}") for i in range(20)]
        result = filter_candidates(candidates, {}, {"model"}, set(), 5)
        assert len(result) <= 5


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.data_object.config")
    @patch("deriva.modules.derivation.data_object.get_enrichments")
    @patch("deriva.modules.derivation.data_object.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.data_object import generate

        mock_query.return_value = []
        mock_enrich.return_value = {}
        mock_config.get_derivation_patterns.return_value = {"include": set(), "exclude": set()}

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
