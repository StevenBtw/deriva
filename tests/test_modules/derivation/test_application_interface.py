"""Tests for application_interface derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(name: str = "test", pagerank: float = 0.5) -> Candidate:
    """Create test candidate."""
    return Candidate(node_id="test_id", name=name, pagerank=pagerank)


class TestIsLikelyInterface:
    """Tests for _is_likely_interface helper."""

    def test_empty_name_returns_false(self):
        from deriva.modules.derivation.application_interface import _is_likely_interface

        assert _is_likely_interface("", {"api"}, set()) is False

    def test_matches_include_pattern(self):
        from deriva.modules.derivation.application_interface import _is_likely_interface

        assert _is_likely_interface("get_api_data", {"api"}, set()) is True

    def test_exclude_pattern_takes_precedence(self):
        from deriva.modules.derivation.application_interface import _is_likely_interface

        assert _is_likely_interface("test_api", {"api"}, {"test"}) is False

    def test_no_match_returns_false(self):
        from deriva.modules.derivation.application_interface import _is_likely_interface

        assert _is_likely_interface("random_func", {"api"}, set()) is False


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_filters_private_methods(self):
        from deriva.modules.derivation.application_interface import filter_candidates

        candidates = [make_candidate("_private"), make_candidate("public_api")]
        result = filter_candidates(candidates, {}, {"api"}, set(), 10)
        assert len(result) == 1
        assert result[0].name == "public_api"

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.application_interface import filter_candidates

        candidates = [make_candidate(f"api_{i}") for i in range(20)]
        result = filter_candidates(candidates, {}, {"api"}, set(), 5)
        assert len(result) <= 5


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.application_interface.config")
    @patch("deriva.modules.derivation.application_interface.get_enrichments")
    @patch("deriva.modules.derivation.application_interface.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.application_interface import generate

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

    @patch("deriva.modules.derivation.application_interface.config")
    @patch("deriva.modules.derivation.application_interface.get_enrichments")
    @patch("deriva.modules.derivation.application_interface.query_candidates")
    @patch("deriva.modules.derivation.application_interface.filter_candidates")
    def test_returns_empty_when_all_filtered(self, mock_filter, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.application_interface import generate

        mock_query.return_value = [make_candidate()]
        mock_filter.return_value = []
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

        assert result.elements_created == 0

    @patch("deriva.modules.derivation.application_interface.config")
    @patch("deriva.modules.derivation.application_interface.get_enrichments")
    @patch("deriva.modules.derivation.application_interface.query_candidates")
    @patch("deriva.modules.derivation.application_interface.filter_candidates")
    @patch("deriva.modules.derivation.application_interface.batch_candidates")
    def test_handles_llm_error(self, mock_batch, mock_filter, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.application_interface import generate

        mock_query.return_value = [make_candidate("api_method")]
        mock_filter.return_value = [make_candidate("api_method")]
        mock_batch.return_value = [[make_candidate("api_method")]]
        mock_enrich.return_value = {}
        mock_config.get_derivation_patterns.return_value = {"include": set(), "exclude": set()}

        def error_fn(*args, **kwargs):
            raise Exception("LLM error")

        result = generate(
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            engine="test",
            llm_query_fn=error_fn,
            query="MATCH (n)",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert result.elements_created == 0
        assert any("LLM error" in e for e in result.errors)
