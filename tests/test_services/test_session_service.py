"""Tests for services.session module (PipelineSession)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.services.session import PipelineSession


class TestPipelineSessionLifecycle:
    """Tests for PipelineSession lifecycle methods."""

    def test_init_defaults(self):
        """Should initialize with default values."""
        session = PipelineSession()

        assert session._connected is False
        assert session._engine is None
        assert session._graph_manager is None

    def test_init_with_auto_connect(self):
        """Should connect on init if auto_connect=True."""
        with patch.object(PipelineSession, "connect") as mock_connect:
            PipelineSession(auto_connect=True)
            mock_connect.assert_called_once()

    def test_connect_creates_managers(self):
        """Should create all managers on connect."""
        with patch("deriva.services.session.get_connection") as mock_get_conn:
            with patch("deriva.services.session.GraphManager") as mock_graph:
                with patch("deriva.services.session.ArchimateManager") as mock_archi:
                    with patch("deriva.services.session.RepoManager") as mock_repo:
                        with patch("deriva.services.session.Neo4jConnection") as mock_neo4j:
                            mock_get_conn.return_value = MagicMock()
                            mock_graph.return_value = MagicMock()
                            mock_archi.return_value = MagicMock()
                            mock_repo.return_value = MagicMock()
                            mock_neo4j.return_value = MagicMock()

                            session = PipelineSession()
                            session.connect()

                            assert session._connected is True
                            mock_graph.return_value.connect.assert_called_once()
                            mock_archi.return_value.connect.assert_called_once()

    def test_connect_skips_if_already_connected(self):
        """Should skip if already connected."""
        session = PipelineSession()
        session._connected = True

        # This should not raise or do anything
        with patch("deriva.services.session.get_connection") as mock_get_conn:
            session.connect()
            mock_get_conn.assert_not_called()

    def test_disconnect_cleans_up(self):
        """Should clean up all managers on disconnect."""
        session = PipelineSession()
        session._connected = True
        session._graph_manager = MagicMock()
        session._archimate_manager = MagicMock()
        session._repo_manager = MagicMock()
        session._neo4j_conn = MagicMock()
        session._engine = MagicMock()

        session.disconnect()

        assert session._connected is False
        assert session._graph_manager is None
        assert session._archimate_manager is None
        assert session._repo_manager is None

    def test_disconnect_skips_if_not_connected(self):
        """Should skip if not connected."""
        session = PipelineSession()
        session._connected = False

        # Should not raise
        session.disconnect()

    def test_context_manager(self):
        """Should support context manager protocol."""
        with patch.object(PipelineSession, "connect") as mock_connect:
            with patch.object(PipelineSession, "disconnect") as mock_disconnect:
                with PipelineSession():
                    mock_connect.assert_called_once()

                mock_disconnect.assert_called_once()

    def test_is_connected(self):
        """Should return connection status."""
        session = PipelineSession()
        assert session.is_connected() is False

        session._connected = True
        assert session.is_connected() is True


class TestPipelineSessionLLM:
    """Tests for PipelineSession LLM methods."""

    def test_get_llm_query_fn_lazy_loads(self):
        """Should lazy load LLM manager."""
        session = PipelineSession()

        with patch("deriva.adapters.llm.LLMManager") as mock_llm:
            mock_manager = MagicMock()
            mock_llm.return_value = mock_manager

            fn = session._get_llm_query_fn()

            assert fn is not None
            mock_llm.assert_called_once()

    def test_get_llm_query_fn_returns_none_on_error(self):
        """Should return None if LLM init fails."""
        session = PipelineSession()

        with patch("deriva.adapters.llm.LLMManager", side_effect=Exception("No API key")):
            fn = session._get_llm_query_fn()

        assert fn is None

    def test_get_llm_query_fn_sets_nocache(self):
        """Should set nocache flag when requested."""
        session = PipelineSession()

        with patch("deriva.adapters.llm.LLMManager") as mock_llm:
            mock_manager = MagicMock()
            mock_llm.return_value = mock_manager

            session._get_llm_query_fn(no_cache=True)

            assert mock_manager.nocache is True

    def test_llm_info_returns_provider_and_model(self):
        """Should return LLM provider info."""
        session = PipelineSession()
        mock_manager = MagicMock()
        mock_manager.provider = "anthropic"
        mock_manager.model = "claude-3"
        session._llm_manager = mock_manager

        info = session.llm_info

        assert info is not None
        assert info["provider"] == "anthropic"
        assert info["model"] == "claude-3"

    def test_llm_info_returns_none_without_manager(self):
        """Should return None if no LLM manager."""
        session = PipelineSession()

        with patch.object(session, "_get_llm_query_fn", return_value=None):
            info = session.llm_info

        assert info is None


class TestPipelineSessionQueries:
    """Tests for PipelineSession query methods."""

    def test_get_graph_stats(self):
        """Should return graph statistics."""
        session = PipelineSession()
        session._connected = True
        mock_graph = MagicMock()
        mock_graph.get_nodes_by_type.return_value = [{"id": "node1"}]
        session._graph_manager = mock_graph

        stats = session.get_graph_stats()

        assert "total_nodes" in stats
        assert "by_type" in stats
        # Should have checked multiple node types
        assert mock_graph.get_nodes_by_type.call_count > 0

    def test_get_graph_nodes(self):
        """Should return nodes of specific type."""
        session = PipelineSession()
        session._connected = True
        mock_graph = MagicMock()
        mock_graph.get_nodes_by_type.return_value = [{"id": "node1"}, {"id": "node2"}]
        session._graph_manager = mock_graph

        nodes = session.get_graph_nodes("Repository")

        assert len(nodes) == 2
        mock_graph.get_nodes_by_type.assert_called_with("Repository")

    def test_get_archimate_stats(self):
        """Should return ArchiMate statistics."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        mock_archi.get_elements.return_value = [
            {"type": "ApplicationComponent"},
            {"type": "ApplicationComponent"},
            {"type": "DataObject"},
        ]
        mock_archi.get_relationships.return_value = [{"id": "rel1"}]
        session._archimate_manager = mock_archi

        stats = session.get_archimate_stats()

        assert stats["total_elements"] == 3
        assert stats["total_relationships"] == 1
        assert stats["by_type"]["ApplicationComponent"] == 2
        assert stats["by_type"]["DataObject"] == 1

    def test_get_archimate_elements(self):
        """Should return ArchiMate elements as dicts."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        mock_elem = MagicMock()
        mock_elem.to_dict.return_value = {"id": "elem1", "name": "Component"}
        mock_archi.get_elements.return_value = [mock_elem]
        session._archimate_manager = mock_archi

        elements = session.get_archimate_elements()

        assert len(elements) == 1
        assert elements[0]["id"] == "elem1"

    def test_get_archimate_relationships(self):
        """Should return ArchiMate relationships as dicts."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        mock_rel = MagicMock()
        mock_rel.to_dict.return_value = {"id": "rel1", "type": "Composition"}
        mock_archi.get_relationships.return_value = [mock_rel]
        session._archimate_manager = mock_archi

        rels = session.get_archimate_relationships()

        assert len(rels) == 1
        assert rels[0]["type"] == "Composition"

    def test_query_graph(self):
        """Should execute Cypher query on graph namespace."""
        session = PipelineSession()
        session._connected = True
        mock_graph = MagicMock()
        mock_graph.query.return_value = [{"n": "result"}]
        session._graph_manager = mock_graph

        result = session.query_graph("MATCH (n) RETURN n")

        assert len(result) == 1
        mock_graph.query.assert_called_with("MATCH (n) RETURN n")

    def test_query_model(self):
        """Should execute Cypher query on model namespace."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        mock_archi.query.return_value = [{"e": "element"}]
        session._archimate_manager = mock_archi

        result = session.query_model("MATCH (e) RETURN e")

        assert len(result) == 1
        mock_archi.query.assert_called_with("MATCH (e) RETURN e")

    def test_get_repositories(self):
        """Should return list of repositories."""
        session = PipelineSession()
        session._connected = True
        mock_repo = MagicMock()
        mock_repo.list_repositories.return_value = ["repo1", "repo2"]
        session._repo_manager = mock_repo

        repos = session.get_repositories()

        assert len(repos) == 2
        assert repos[0]["name"] == "repo1"


class TestPipelineSessionInfrastructure:
    """Tests for PipelineSession infrastructure methods."""

    def test_get_neo4j_status(self):
        """Should get Neo4j container status."""
        session = PipelineSession()
        mock_conn = MagicMock()
        mock_conn.get_container_status.return_value = {"status": "running"}
        session._neo4j_conn = mock_conn

        status = session.get_neo4j_status()

        assert status["status"] == "running"

    def test_get_neo4j_status_creates_connection(self):
        """Should create Neo4j connection if not exists."""
        session = PipelineSession()
        session._neo4j_conn = None

        with patch("deriva.services.session.Neo4jConnection") as mock_neo4j:
            mock_conn = MagicMock()
            mock_conn.get_container_status.return_value = {"status": "stopped"}
            mock_neo4j.return_value = mock_conn

            status = session.get_neo4j_status()

            mock_neo4j.assert_called_with(namespace="Docker")
            assert status["status"] == "stopped"

    def test_start_neo4j(self):
        """Should start Neo4j container."""
        session = PipelineSession()
        mock_conn = MagicMock()
        mock_conn.start_container.return_value = {"success": True}
        session._neo4j_conn = mock_conn

        result = session.start_neo4j()

        assert result["success"] is True

    def test_stop_neo4j(self):
        """Should stop Neo4j container."""
        session = PipelineSession()
        mock_conn = MagicMock()
        mock_conn.stop_container.return_value = {"success": True}
        session._neo4j_conn = mock_conn

        result = session.stop_neo4j()

        assert result["success"] is True

    def test_clear_graph(self):
        """Should clear graph data."""
        session = PipelineSession()
        session._connected = True
        mock_graph = MagicMock()
        session._graph_manager = mock_graph

        result = session.clear_graph()

        assert result["success"] is True
        mock_graph.clear_graph.assert_called_once()

    def test_clear_graph_handles_error(self):
        """Should handle errors when clearing graph."""
        session = PipelineSession()
        session._connected = True
        mock_graph = MagicMock()
        mock_graph.clear_graph.side_effect = Exception("Connection lost")
        session._graph_manager = mock_graph

        result = session.clear_graph()

        assert result["success"] is False
        assert "Connection lost" in result["error"]

    def test_clear_model(self):
        """Should clear ArchiMate model data."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        session._archimate_manager = mock_archi

        result = session.clear_model()

        assert result["success"] is True
        mock_archi.clear_model.assert_called_once()

    def test_clear_model_handles_error(self):
        """Should handle errors when clearing model."""
        session = PipelineSession()
        session._connected = True
        mock_archi = MagicMock()
        mock_archi.clear_model.side_effect = Exception("DB error")
        session._archimate_manager = mock_archi

        result = session.clear_model()

        assert result["success"] is False
        assert "DB error" in result["error"]


class TestPipelineSessionGetRunLogger:
    """Tests for PipelineSession._get_run_logger."""

    def test_returns_none_without_engine(self):
        """Should return None if no engine."""
        session = PipelineSession()
        session._engine = None

        logger = session._get_run_logger()

        assert logger is None

    def test_returns_none_if_no_active_run(self):
        """Should return None if no active run."""
        session = PipelineSession()
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = None
        session._engine = mock_engine

        logger = session._get_run_logger()

        assert logger is None

    def test_returns_run_logger_for_active_run(self):
        """Should return RunLogger for active run."""
        session = PipelineSession()
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = ("run-123",)
        session._engine = mock_engine

        with patch("deriva.services.session.RunLogger") as mock_logger_cls:
            mock_logger = MagicMock()
            mock_logger_cls.return_value = mock_logger

            logger = session._get_run_logger()

            mock_logger_cls.assert_called_with(run_id="run-123")
            assert logger is mock_logger

    def test_handles_query_error(self):
        """Should handle query errors gracefully."""
        session = PipelineSession()
        mock_engine = MagicMock()
        mock_engine.execute.side_effect = Exception("Query failed")
        session._engine = mock_engine

        logger = session._get_run_logger()

        assert logger is None
