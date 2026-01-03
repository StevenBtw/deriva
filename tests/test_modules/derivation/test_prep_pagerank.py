"""Tests for derivation prep_pagerank module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.modules.derivation.prep_pagerank import run_pagerank


class TestRunPagerank:
    """Tests for run_pagerank function."""

    def test_returns_success_with_no_nodes(self):
        """Should return success with message when no active nodes."""
        graph_manager = MagicMock()
        graph_manager.query.return_value = []

        result = run_pagerank(graph_manager)

        assert result["success"] is True
        assert "No active nodes" in result["errors"]
        assert result["stats"]["nodes"] == 0

    def test_uses_default_params(self):
        """Should use default damping, max_iterations, tolerance."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}, {"id": "node2"}],  # nodes
            [{"src": "node1", "dst": "node2"}],  # edges
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"node1": 0.5, "node2": 0.5}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result) as mock_pr:
            run_pagerank(graph_manager)

        mock_pr.assert_called_once()
        call_kwargs = mock_pr.call_args[1]
        assert call_kwargs["damping"] == 0.85
        assert call_kwargs["max_iter"] == 100
        assert call_kwargs["tol"] == 1e-6

    def test_uses_custom_params(self):
        """Should use custom params when provided."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}],  # nodes
            [],  # edges
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"node1": 1.0}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result) as mock_pr:
            run_pagerank(graph_manager, params={"damping": 0.9, "max_iterations": 50, "tolerance": 1e-8})

        call_kwargs = mock_pr.call_args[1]
        assert call_kwargs["damping"] == 0.9
        assert call_kwargs["max_iter"] == 50
        assert call_kwargs["tol"] == 1e-8

    def test_computes_pagerank_scores(self):
        """Should compute PageRank and update nodes."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}, {"id": "node2"}, {"id": "node3"}],  # nodes
            [{"src": "node1", "dst": "node2"}, {"src": "node2", "dst": "node3"}],  # edges
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"node1": 0.3, "node2": 0.4, "node3": 0.3}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result):
            result = run_pagerank(graph_manager)

        assert result["success"] is True
        assert result["stats"]["nodes"] == 3
        assert result["stats"]["edges"] == 2
        assert result["stats"]["updated"] == 3

    def test_returns_top_nodes(self):
        """Should return top 5 nodes in stats."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": f"node{i}"} for i in range(6)],  # 6 nodes
            [],  # no edges
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {
            "node0": 0.1,
            "node1": 0.2,
            "node2": 0.3,
            "node3": 0.4,
            "node4": 0.5,
            "node5": 0.6,
        }

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result):
            result = run_pagerank(graph_manager)

        top_nodes = result["stats"]["top_nodes"]
        assert len(top_nodes) == 5
        # Top node should be node5 with score 0.6
        assert top_nodes[0]["id"] == "node5"
        assert top_nodes[0]["score"] == 0.6

    def test_handles_pagerank_failure(self):
        """Should return error when PageRank fails."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}],  # nodes
            [],  # edges
        ]

        mock_result = MagicMock()
        mock_result.ok = False
        mock_result.error = "Convergence failed"

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result):
            result = run_pagerank(graph_manager)

        assert result["success"] is False
        assert any("Convergence failed" in e for e in result["errors"])

    def test_handles_node_update_errors(self):
        """Should continue when node update fails."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}, {"id": "node2"}],  # nodes
            [],  # edges
        ]
        graph_manager.update_node_property.side_effect = Exception("DB error")

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"node1": 0.5, "node2": 0.5}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result):
            result = run_pagerank(graph_manager)

        # Should still succeed but with 0 updated
        assert result["success"] is True
        assert result["stats"]["updated"] == 0

    def test_builds_adjacency_correctly(self):
        """Should build adjacency list from edges."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],  # nodes
            [{"src": "a", "dst": "b"}, {"src": "b", "dst": "c"}, {"src": "a", "dst": "c"}],  # edges
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"a": 0.3, "b": 0.3, "c": 0.4}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result) as mock_pr:
            run_pagerank(graph_manager)

        # Verify the neighbors function was built correctly
        call_args = mock_pr.call_args
        node_ids = call_args[0][0]
        neighbors_fn = call_args[0][1]

        assert set(node_ids) == {"a", "b", "c"}
        assert set(neighbors_fn("a")) == {"b", "c"}
        assert neighbors_fn("b") == ["c"]
        assert neighbors_fn("c") == []

    def test_computes_average_and_max_scores(self):
        """Should compute avg and max scores in stats."""
        graph_manager = MagicMock()
        graph_manager.query.side_effect = [
            [{"id": "node1"}, {"id": "node2"}, {"id": "node3"}],
            [],
        ]

        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.solution = {"node1": 0.2, "node2": 0.3, "node3": 0.5}

        with patch("deriva.modules.derivation.prep_pagerank.pagerank", return_value=mock_result):
            result = run_pagerank(graph_manager)

        assert result["stats"]["max_score"] == 0.5
        # Avg = (0.2 + 0.3 + 0.5) / 3 = 0.3333
        assert result["stats"]["avg_score"] == round(1.0 / 3, 4)
