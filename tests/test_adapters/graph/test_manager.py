"""Tests for adapters.graph.manager module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deriva.adapters.graph.manager import GraphManager


class TestGraphManagerInit:
    """Tests for GraphManager initialization."""

    @patch.dict("os.environ", {}, clear=True)
    def test_initializes_with_default_namespace(self):
        """Should initialize with default namespace."""
        manager = GraphManager()
        assert manager.namespace == "Graph"
        assert manager.db is None

    @patch.dict("os.environ", {"GRAPH_NAMESPACE": "CustomGraph"}, clear=True)
    def test_uses_env_namespace(self):
        """Should use namespace from environment."""
        manager = GraphManager()
        assert manager.namespace == "CustomGraph"


class TestGraphManagerConnection:
    """Tests for GraphManager connection handling."""

    @patch("deriva.adapters.graph.manager.GrafeoConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_connect_creates_grafeo_connection(self, mock_grafeo_class):
        """Should create grafeo connection on connect."""
        mock_conn = MagicMock()
        mock_grafeo_class.return_value = mock_conn

        manager = GraphManager()
        manager.connect()

        mock_grafeo_class.assert_called_once_with(namespace="Graph")
        mock_conn.connect.assert_called_once()
        assert manager.db is mock_conn

    @patch("deriva.adapters.graph.manager.GrafeoConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_disconnect_closes_connection(self, mock_grafeo_class):
        """Should close connection on disconnect."""
        mock_conn = MagicMock()
        mock_grafeo_class.return_value = mock_conn

        manager = GraphManager()
        manager.connect()
        manager.disconnect()

        mock_conn.disconnect.assert_called_once()
        assert manager.db is None

    @patch("deriva.adapters.graph.manager.GrafeoConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_context_manager(self, mock_grafeo_class):
        """Should work as context manager."""
        mock_conn = MagicMock()
        mock_grafeo_class.return_value = mock_conn

        with GraphManager() as manager:
            assert manager.db is mock_conn

        mock_conn.disconnect.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    def test_connect_twice_warns(self):
        """Should warn when already connected."""
        manager = GraphManager()
        manager.db = MagicMock()  # Simulate existing connection

        # Should not raise, just warn
        manager.connect()


class TestGraphManagerOperations:
    """Tests for GraphManager operations."""

    @patch.dict("os.environ", {}, clear=True)
    def test_add_node_requires_connection(self):
        """Should raise error if not connected."""
        manager = GraphManager()
        mock_node = MagicMock()

        with pytest.raises(RuntimeError, match="Not connected"):
            manager.add_node(mock_node)


class TestRecording:
    """The ids of the nodes and edges written inside a block, for the run log."""

    def test_records_the_nodes_and_edges_written_in_the_block(self):
        from deriva.adapters.graph.models import DirectoryNode

        manager = GraphManager()
        manager.db = MagicMock()
        node = DirectoryNode(name="a", path="a", repository_name="r")
        manager.add_node(node, node_id="dir::r::before")

        with manager.recording() as written:
            manager.add_node(node, node_id="dir::r::a")
            manager.add_node(node, node_id="dir::r::b")
            manager.add_edge("dir::r::a", "dir::r::b", "CONTAINS")
        manager.add_node(node, node_id="dir::r::after")

        assert written.nodes == ["dir::r::a", "dir::r::b"]
        # Edges by relationship, source and target: the edge ids of the benchmark's event log
        assert written.edges == ["CONTAINS_dir::r::a_dir::r::b"]

    def test_a_failed_write_is_not_recorded(self):
        from deriva.adapters.graph.models import DirectoryNode

        manager = GraphManager()
        manager.db = MagicMock()
        manager.db.merge_node.side_effect = RuntimeError("disk full")
        manager.db.merge_edge.return_value = False  # an endpoint is missing

        with manager.recording() as written:
            with pytest.raises(RuntimeError):
                manager.add_node(DirectoryNode(name="a", path="a", repository_name="r"), node_id="dir::r::a")
            with pytest.raises(RuntimeError):
                manager.add_edge("dir::r::a", "dir::r::b", "CONTAINS")

        assert (written.nodes, written.edges) == ([], [])


class TestNodesByType:
    def test_a_node_type_that_is_no_label_is_refused_before_the_query(self):
        manager = GraphManager()
        manager.db = MagicMock()

        with pytest.raises(ValueError, match="node type"):
            manager.get_nodes_by_type("File`) DETACH DELETE n //")

        manager.db.execute_read.assert_not_called()

    def test_a_limit_goes_into_the_query(self):
        manager = GraphManager()
        manager.db = MagicMock()
        manager.db.execute_read.return_value = []

        manager.get_nodes_by_type("File", limit=5)

        assert "LIMIT 5" in manager.db.execute_read.call_args.args[0]
