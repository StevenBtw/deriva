"""Tests for application_service derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(
    name: str = "test",
    pagerank: float = 0.5,
    node_id: str | None = None,
) -> Candidate:
    """Create test candidate."""
    return Candidate(node_id=node_id or f"id_{name}", name=name, pagerank=pagerank)


class TestIsLikelyService:
    """Tests for _is_likely_service helper."""

    def test_empty_name_returns_false(self):
        from deriva.modules.derivation.application_service import _is_likely_service

        assert _is_likely_service("", {"service"}, set()) is False

    def test_matches_include_pattern(self):
        from deriva.modules.derivation.application_service import _is_likely_service

        assert _is_likely_service("user_service", {"service"}, set()) is True

    def test_exclude_pattern_takes_precedence(self):
        from deriva.modules.derivation.application_service import _is_likely_service

        assert _is_likely_service("test_service", {"service"}, {"test"}) is False

    def test_matches_api_pattern(self):
        from deriva.modules.derivation.application_service import _is_likely_service

        assert _is_likely_service("user_api", {"api"}, set()) is True

    def test_no_match_returns_false(self):
        from deriva.modules.derivation.application_service import _is_likely_service

        assert _is_likely_service("utils", {"service", "api"}, set()) is False


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_filters_dunder_names(self):
        from deriva.modules.derivation.application_service import filter_candidates

        candidates = [make_candidate("__init__"), make_candidate("user_service")]
        result = filter_candidates(candidates, {}, {"service"}, set(), 10)
        assert len(result) == 1
        assert result[0].name == "user_service"

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.application_service import filter_candidates

        candidates = [make_candidate(f"service_{i}") for i in range(20)]
        result = filter_candidates(candidates, {}, {"service"}, set(), 5)
        assert len(result) <= 5

    def test_empty_input_returns_empty(self):
        from deriva.modules.derivation.application_service import filter_candidates

        result = filter_candidates([], {}, {"service"}, set(), 10)
        assert result == []

    def test_sorts_by_pagerank(self):
        from deriva.modules.derivation.application_service import filter_candidates

        candidates = [
            make_candidate("low_service", pagerank=0.1),
            make_candidate("high_service", pagerank=0.9),
            make_candidate("med_service", pagerank=0.5),
        ]
        result = filter_candidates(candidates, {}, {"service"}, set(), 10)
        pageranks = [c.pagerank for c in result]
        assert pageranks == sorted(pageranks, reverse=True)


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.application_service.config")
    @patch("deriva.modules.derivation.application_service.get_enrichments")
    @patch("deriva.modules.derivation.application_service.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.application_service import generate

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

    @patch("deriva.modules.derivation.application_service.config")
    @patch("deriva.modules.derivation.application_service.get_enrichments")
    @patch("deriva.modules.derivation.application_service.query_candidates")
    @patch("deriva.modules.derivation.application_service.filter_candidates")
    def test_returns_empty_when_filter_removes_all(
        self, mock_filter, mock_query, mock_enrich, mock_config
    ):
        from deriva.modules.derivation.application_service import generate

        mock_query.return_value = [make_candidate("test_service")]
        mock_enrich.return_value = {}
        mock_config.get_derivation_patterns.return_value = {"include": {"service"}, "exclude": set()}
        mock_filter.return_value = []

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

        assert result.success is True
        assert result.elements_created == 0


class TestModuleExports:
    """Tests for module exports."""

    def test_element_type_constant(self):
        from deriva.modules.derivation.application_service import ELEMENT_TYPE

        assert ELEMENT_TYPE == "ApplicationService"

    def test_exports_filter_candidates(self):
        from deriva.modules.derivation.application_service import filter_candidates

        assert callable(filter_candidates)

    def test_exports_generate(self):
        from deriva.modules.derivation.application_service import generate

        assert callable(generate)
