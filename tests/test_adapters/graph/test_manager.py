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
        assert manager.neo4j is None

    @patch.dict("os.environ", {"NEO4J_GRAPH_NAMESPACE": "CustomGraph"}, clear=True)
    def test_uses_env_namespace(self):
        """Should use namespace from environment."""
        manager = GraphManager()
        assert manager.namespace == "CustomGraph"


class TestGraphManagerConnection:
    """Tests for GraphManager connection handling."""

    @patch("deriva.adapters.graph.manager.Neo4jConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_connect_creates_neo4j_connection(self, mock_neo4j_class):
        """Should create Neo4j connection on connect."""
        mock_conn = MagicMock()
        mock_neo4j_class.return_value = mock_conn

        manager = GraphManager()
        manager.connect()

        mock_neo4j_class.assert_called_once_with(namespace="Graph")
        mock_conn.connect.assert_called_once()
        assert manager.neo4j is mock_conn

    @patch("deriva.adapters.graph.manager.Neo4jConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_disconnect_closes_connection(self, mock_neo4j_class):
        """Should close connection on disconnect."""
        mock_conn = MagicMock()
        mock_neo4j_class.return_value = mock_conn

        manager = GraphManager()
        manager.connect()
        manager.disconnect()

        mock_conn.disconnect.assert_called_once()
        assert manager.neo4j is None

    @patch("deriva.adapters.graph.manager.Neo4jConnection")
    @patch.dict("os.environ", {}, clear=True)
    def test_context_manager(self, mock_neo4j_class):
        """Should work as context manager."""
        mock_conn = MagicMock()
        mock_neo4j_class.return_value = mock_conn

        with GraphManager() as manager:
            assert manager.neo4j is mock_conn

        mock_conn.disconnect.assert_called_once()

    @patch.dict("os.environ", {}, clear=True)
    def test_connect_twice_warns(self):
        """Should warn when already connected."""
        manager = GraphManager()
        manager.neo4j = MagicMock()  # Simulate existing connection

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
