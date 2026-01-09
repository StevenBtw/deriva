"""Tests for business_object derivation module."""

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


class TestIsLikelyBusinessObject:
    """Tests for _is_likely_business_object helper."""

    def test_empty_name_returns_false(self):
        from deriva.modules.derivation.business_object import _is_likely_business_object

        assert _is_likely_business_object("", {"entity"}, set()) is False

    def test_matches_include_pattern(self):
        from deriva.modules.derivation.business_object import _is_likely_business_object

        assert _is_likely_business_object("customer_entity", {"entity"}, set()) is True

    def test_exclude_pattern_takes_precedence(self):
        from deriva.modules.derivation.business_object import _is_likely_business_object

        assert _is_likely_business_object("test_entity", {"entity"}, {"test"}) is False

    def test_no_match_returns_false(self):
        from deriva.modules.derivation.business_object import _is_likely_business_object

        assert _is_likely_business_object("user_service", {"entity", "model"}, set()) is False


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.business_object import filter_candidates

        candidates = [make_candidate(f"obj_{i}") for i in range(20)]
        result = filter_candidates(candidates, {}, {"entity"}, set(), 5)
        assert len(result) <= 5

    def test_empty_input_returns_empty(self):
        from deriva.modules.derivation.business_object import filter_candidates

        result = filter_candidates([], {}, {"entity"}, set(), 10)
        assert result == []

    def test_filters_by_include_pattern(self):
        from deriva.modules.derivation.business_object import filter_candidates

        candidates = [make_candidate("user_entity"), make_candidate("utils")]
        result = filter_candidates(candidates, {}, {"entity"}, set(), 10)
        # Entity pattern matches should be prioritized
        names = [c.name for c in result]
        assert "user_entity" in names

    def test_sorts_by_pagerank(self):
        from deriva.modules.derivation.business_object import filter_candidates

        candidates = [
            make_candidate("low_entity", pagerank=0.1),
            make_candidate("high_entity", pagerank=0.9),
            make_candidate("med_entity", pagerank=0.5),
        ]
        result = filter_candidates(candidates, {}, {"entity"}, set(), 10)
        pageranks = [c.pagerank for c in result]
        assert pageranks == sorted(pageranks, reverse=True)


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.business_object.config")
    @patch("deriva.modules.derivation.business_object.get_enrichments")
    @patch("deriva.modules.derivation.business_object.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.business_object import generate

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

    @patch("deriva.modules.derivation.business_object.config")
    @patch("deriva.modules.derivation.business_object.get_enrichments")
    @patch("deriva.modules.derivation.business_object.query_candidates")
    @patch("deriva.modules.derivation.business_object.filter_candidates")
    def test_returns_empty_when_filter_removes_all(
        self, mock_filter, mock_query, mock_enrich, mock_config
    ):
        from deriva.modules.derivation.business_object import generate

        mock_query.return_value = [make_candidate("test_entity")]
        mock_enrich.return_value = {}
        mock_config.get_derivation_patterns.return_value = {"include": {"entity"}, "exclude": set()}
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
        from deriva.modules.derivation.business_object import ELEMENT_TYPE

        assert ELEMENT_TYPE == "BusinessObject"

    def test_exports_filter_candidates(self):
        from deriva.modules.derivation.business_object import filter_candidates

        assert callable(filter_candidates)

    def test_exports_generate(self):
        from deriva.modules.derivation.business_object import generate

        assert callable(generate)
