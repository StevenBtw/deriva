"""Tests for application_component derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult


def make_candidate(
    name: str = "test",
    pagerank: float = 0.5,
    node_id: str | None = None,
    louvain_community: str | None = None,
) -> Candidate:
    """Create test candidate.

    Args:
        name: Candidate name
        pagerank: PageRank value
        node_id: Node ID (defaults to id_{name})
        louvain_community: Community ID. Set equal to node_id to make it a community root.
    """
    nid = node_id or f"id_{name}"
    return Candidate(
        node_id=nid,
        name=name,
        pagerank=pagerank,
        louvain_community=louvain_community,
    )


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

    def test_prioritizes_community_roots(self):
        from deriva.modules.derivation.application_component import filter_candidates

        # Community roots have node_id == louvain_community
        candidates = [
            make_candidate("root1", pagerank=0.1, node_id="r1", louvain_community="r1"),
            make_candidate("non_root", pagerank=0.9, node_id="nr", louvain_community="r1"),
            make_candidate("root2", pagerank=0.2, node_id="r2", louvain_community="r2"),
        ]
        result = filter_candidates(candidates, {}, 10)
        # Both roots should be included
        root_names = [c.name for c in result if c.node_id == c.louvain_community]
        assert "root1" in root_names
        assert "root2" in root_names

    def test_includes_high_pagerank_non_roots(self):
        from deriva.modules.derivation.application_component import filter_candidates

        candidates = [
            make_candidate("root", pagerank=0.1, node_id="r1", louvain_community="r1"),
            make_candidate("high_pr", pagerank=0.9, node_id="hp", louvain_community="r1"),
        ]
        result = filter_candidates(candidates, {}, 10)
        names = [c.name for c in result]
        assert "high_pr" in names

    def test_sorts_by_pagerank(self):
        from deriva.modules.derivation.application_component import filter_candidates

        candidates = [
            make_candidate("low", pagerank=0.1),
            make_candidate("high", pagerank=0.9),
            make_candidate("med", pagerank=0.5),
        ]
        result = filter_candidates(candidates, {}, 10)
        # Should be sorted by pagerank descending
        pageranks = [c.pagerank for c in result]
        assert pageranks == sorted(pageranks, reverse=True)


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

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    def test_handles_query_exception(self, mock_query, mock_enrich):
        from deriva.modules.derivation.application_component import generate

        mock_query.side_effect = Exception("Database error")
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

        assert result.success is False
        assert "Query failed" in result.errors[0]

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    @patch("deriva.modules.derivation.application_component.filter_candidates")
    def test_returns_empty_when_filter_removes_all(self, mock_filter, mock_query, mock_enrich):
        from deriva.modules.derivation.application_component import generate

        mock_query.return_value = [make_candidate("test")]
        mock_enrich.return_value = {}
        mock_filter.return_value = []  # All filtered out

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

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    @patch("deriva.modules.derivation.application_component.filter_candidates")
    @patch("deriva.modules.derivation.application_component.batch_candidates")
    @patch("deriva.modules.derivation.application_component.build_derivation_prompt")
    @patch("deriva.modules.derivation.application_component.parse_derivation_response")
    @patch("deriva.modules.derivation.application_component.build_element")
    def test_successful_element_creation(
        self, mock_build, mock_parse, mock_prompt, mock_batch, mock_filter, mock_query, mock_enrich
    ):
        from deriva.modules.derivation.application_component import generate

        mock_query.return_value = [make_candidate("component1")]
        mock_enrich.return_value = {}
        mock_filter.return_value = [make_candidate("component1")]
        mock_batch.return_value = [[make_candidate("component1")]]
        mock_prompt.return_value = "prompt"

        mock_llm = Mock()
        mock_llm.return_value = Mock(content='{"elements": []}')

        mock_parse.return_value = {
            "success": True,
            "data": [{"name": "TestComponent", "source_node_id": "id_1"}],
        }
        mock_build.return_value = {
            "success": True,
            "data": {
                "identifier": "elem_1",
                "name": "TestComponent",
                "element_type": "ApplicationComponent",
                "documentation": "Test doc",
                "properties": {"source": "id_1"},
            },
        }

        mock_archimate = MagicMock()

        result = generate(
            graph_manager=MagicMock(),
            archimate_manager=mock_archimate,
            engine="test",
            llm_query_fn=mock_llm,
            query="MATCH (n)",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert result.success is True
        assert result.elements_created == 1
        mock_archimate.add_element.assert_called_once()

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    @patch("deriva.modules.derivation.application_component.filter_candidates")
    @patch("deriva.modules.derivation.application_component.batch_candidates")
    @patch("deriva.modules.derivation.application_component.build_derivation_prompt")
    def test_handles_llm_exception(
        self, mock_prompt, mock_batch, mock_filter, mock_query, mock_enrich
    ):
        from deriva.modules.derivation.application_component import generate

        mock_query.return_value = [make_candidate("test")]
        mock_enrich.return_value = {}
        mock_filter.return_value = [make_candidate("test")]
        mock_batch.return_value = [[make_candidate("test")]]
        mock_prompt.return_value = "prompt"

        mock_llm = Mock(side_effect=Exception("LLM timeout"))

        result = generate(
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            engine="test",
            llm_query_fn=mock_llm,
            query="MATCH (n)",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert "LLM error" in result.errors[0]

    @patch("deriva.modules.derivation.application_component.get_enrichments")
    @patch("deriva.modules.derivation.application_component.query_candidates")
    @patch("deriva.modules.derivation.application_component.filter_candidates")
    @patch("deriva.modules.derivation.application_component.batch_candidates")
    @patch("deriva.modules.derivation.application_component.build_derivation_prompt")
    @patch("deriva.modules.derivation.application_component.parse_derivation_response")
    def test_handles_parse_failure(
        self, mock_parse, mock_prompt, mock_batch, mock_filter, mock_query, mock_enrich
    ):
        from deriva.modules.derivation.application_component import generate

        mock_query.return_value = [make_candidate("test")]
        mock_enrich.return_value = {}
        mock_filter.return_value = [make_candidate("test")]
        mock_batch.return_value = [[make_candidate("test")]]
        mock_prompt.return_value = "prompt"

        mock_llm = Mock(return_value=Mock(content="invalid json"))
        mock_parse.return_value = {"success": False, "errors": ["Parse error"]}

        result = generate(
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            engine="test",
            llm_query_fn=mock_llm,
            query="MATCH (n)",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert "Parse error" in result.errors


class TestModuleExports:
    """Tests for module exports."""

    def test_element_type_constant(self):
        from deriva.modules.derivation.application_component import ELEMENT_TYPE

        assert ELEMENT_TYPE == "ApplicationComponent"

    def test_exports_filter_candidates(self):
        from deriva.modules.derivation.application_component import filter_candidates

        assert callable(filter_candidates)

    def test_exports_generate(self):
        from deriva.modules.derivation.application_component import generate

        assert callable(generate)
