"""Tests for adapters.neo4j.manager module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.adapters.neo4j.manager import Neo4jConnection


class TestNeo4jConnectionInit:
    """Tests for Neo4jConnection initialization."""

    @patch.dict("os.environ", {}, clear=True)
    def test_stores_namespace(self):
        """Should store namespace parameter."""
        conn = Neo4jConnection(namespace="Graph")
        assert conn.namespace == "Graph"

    @patch.dict("os.environ", {"NEO4J_URI": "bolt://custom:7687"}, clear=True)
    def test_loads_config_from_env(self):
        """Should load configuration from environment."""
        conn = Neo4jConnection(namespace="Test")
        assert conn.config["neo4j"]["uri"] == "bolt://custom:7687"

    @patch.dict("os.environ", {}, clear=True)
    def test_uses_default_values(self):
        """Should use default values when env vars not set."""
        conn = Neo4jConnection(namespace="Test")
        assert conn.config["neo4j"]["uri"] == "bolt://localhost:7687"
        assert conn.config["neo4j"]["database"] == "neo4j"


class TestNeo4jConnectionLifecycle:
    """Tests for Neo4jConnection connect/disconnect."""

    @patch("deriva.adapters.neo4j.manager.GraphDatabase")
    @patch.dict("os.environ", {}, clear=True)
    def test_connect_creates_driver(self, mock_graph_db):
        """Should create driver on connect."""
        mock_driver = MagicMock()
        mock_graph_db.driver.return_value = mock_driver

        conn = Neo4jConnection(namespace="Test")
        conn.connect()

        mock_graph_db.driver.assert_called_once()
        assert conn.driver is mock_driver

    @patch("deriva.adapters.neo4j.manager.GraphDatabase")
    @patch.dict("os.environ", {}, clear=True)
    def test_disconnect_closes_driver(self, mock_graph_db):
        """Should close driver on disconnect."""
        mock_driver = MagicMock()
        mock_graph_db.driver.return_value = mock_driver

        conn = Neo4jConnection(namespace="Test")
        conn.connect()
        conn.disconnect()

        mock_driver.close.assert_called_once()

    @patch("deriva.adapters.neo4j.manager.GraphDatabase")
    @patch.dict("os.environ", {}, clear=True)
    def test_context_manager(self, mock_graph_db):
        """Should work as context manager."""
        mock_driver = MagicMock()
        mock_graph_db.driver.return_value = mock_driver

        with Neo4jConnection(namespace="Test") as conn:
            assert conn.driver is mock_driver

        mock_driver.close.assert_called_once()
