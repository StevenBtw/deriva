"""Tests for device derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(name: str = "test", pagerank: float = 0.5) -> Candidate:
    """Create test candidate."""
    return Candidate(node_id="test_id", name=name, pagerank=pagerank)


class TestIsLikelyDevice:
    """Tests for _is_likely_device helper."""

    def test_empty_name_returns_false(self):
        from deriva.modules.derivation.device import _is_likely_device

        assert _is_likely_device("", {"device"}, set()) is False

    def test_matches_include_pattern(self):
        from deriva.modules.derivation.device import _is_likely_device

        assert _is_likely_device("mobile_device", {"device"}, set()) is True

    def test_exclude_pattern_takes_precedence(self):
        from deriva.modules.derivation.device import _is_likely_device

        assert _is_likely_device("test_device", {"device"}, {"test"}) is False

    def test_no_match_returns_false(self):
        from deriva.modules.derivation.device import _is_likely_device

        assert _is_likely_device("random_func", {"device"}, set()) is False


class TestFilterCandidates:
    """Tests for filter_candidates function."""

    def test_respects_max_candidates(self):
        from deriva.modules.derivation.device import filter_candidates

        candidates = [make_candidate(f"device_{i}") for i in range(20)]
        result = filter_candidates(candidates, {}, {"device"}, set(), 5)
        assert len(result) <= 5

    def test_filters_empty_names(self):
        from deriva.modules.derivation.device import filter_candidates

        candidates = [make_candidate(""), make_candidate("mobile_device")]
        result = filter_candidates(candidates, {}, {"device"}, set(), 10)
        names = [c.name for c in result]
        assert "" not in names

    def test_fills_remaining_slots(self):
        from deriva.modules.derivation.device import filter_candidates

        likely = [make_candidate(f"device_{i}", pagerank=0.9) for i in range(2)]
        others = [make_candidate(f"other_{i}", pagerank=0.5) for i in range(10)]
        result = filter_candidates(likely + others, {}, {"device"}, set(), 8)
        assert len(result) <= 8


class TestGenerate:
    """Tests for generate function."""

    @patch("deriva.modules.derivation.device.config")
    @patch("deriva.modules.derivation.device.get_enrichments")
    @patch("deriva.modules.derivation.device.query_candidates")
    def test_returns_empty_when_no_candidates(self, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.device import generate

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

    @patch("deriva.modules.derivation.device.config")
    @patch("deriva.modules.derivation.device.get_enrichments")
    @patch("deriva.modules.derivation.device.query_candidates")
    @patch("deriva.modules.derivation.device.filter_candidates")
    def test_returns_empty_when_all_filtered(self, mock_filter, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.device import generate

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

    @patch("deriva.modules.derivation.device.config")
    @patch("deriva.modules.derivation.device.get_enrichments")
    @patch("deriva.modules.derivation.device.query_candidates")
    @patch("deriva.modules.derivation.device.filter_candidates")
    @patch("deriva.modules.derivation.device.batch_candidates")
    def test_handles_llm_error(self, mock_batch, mock_filter, mock_query, mock_enrich, mock_config):
        from deriva.modules.derivation.device import generate

        mock_query.return_value = [make_candidate("device")]
        mock_filter.return_value = [make_candidate("device")]
        mock_batch.return_value = [[make_candidate("device")]]
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
