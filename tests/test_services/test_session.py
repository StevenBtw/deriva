"""Tests for deriva.services.session module (PipelineSession)."""

from unittest.mock import MagicMock, patch

import pytest

from deriva.services.session import PipelineSession


class TestPipelineSessionLifecycle:
    """Tests for PipelineSession lifecycle methods."""

    def test_init_not_connected_by_default(self):
        """Session should not be connected on init by default."""
        with patch("deriva.services.session.get_connection"):
            session = PipelineSession()
            assert not session.is_connected()

    def test_init_auto_connect(self):
        """Session should connect on init if auto_connect=True."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager") as mock_repo,
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)
            assert session.is_connected()
            mock_db.assert_called_once()
            mock_graph.assert_called_once()
            mock_archimate.assert_called_once()
            mock_repo.assert_called_once()

    def test_connect_creates_managers(self):
        """Connect should create all managers."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession()
            session.connect()

            assert session.is_connected()
            mock_db.assert_called_once()
            mock_graph.return_value.connect.assert_called_once()
            mock_archimate.return_value.connect.assert_called_once()

    def test_connect_idempotent(self):
        """Connect should be idempotent."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession()
            session.connect()
            session.connect()  # Should not error

            # Should only be called once
            mock_db.assert_called_once()

    def test_disconnect_clears_managers(self):
        """Disconnect should clear all managers."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)
            session.disconnect()

            assert not session.is_connected()
            mock_graph.return_value.disconnect.assert_called_once()
            mock_archimate.return_value.disconnect.assert_called_once()

    def test_context_manager(self):
        """Should work as context manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            with PipelineSession() as session:
                assert session.is_connected()

            mock_graph.return_value.disconnect.assert_called_once()
            mock_archimate.return_value.disconnect.assert_called_once()


class TestPipelineSessionEnsureConnected:
    """Tests for _ensure_connected behavior."""

    def test_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.get_graph_stats()

    def test_no_error_when_connected(self):
        """Should not raise when connected."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            mock_graph.return_value.get_nodes_by_type.return_value = []

            session = PipelineSession(auto_connect=True)
            # Should not raise
            session.get_graph_stats()


class TestPipelineSessionQueries:
    """Tests for PipelineSession query methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager") as mock_repo,
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)

            # Store mocks for assertions
            session._mock_db = mock_db
            session._mock_graph = mock_graph.return_value
            session._mock_archimate = mock_archimate.return_value
            session._mock_repo = mock_repo.return_value

            yield session

    def test_get_graph_stats(self, connected_session):
        """Should aggregate node counts by type."""
        connected_session._mock_graph.get_nodes_by_type.side_effect = lambda t: ([{"id": "1"}] if t == "Repository" else [])

        stats = connected_session.get_graph_stats()

        assert stats["total_nodes"] == 1
        assert stats["by_type"]["Repository"] == 1
        assert stats["by_type"]["File"] == 0

    def test_get_graph_nodes(self, connected_session):
        """Should return nodes of specific type."""
        connected_session._mock_graph.get_nodes_by_type.return_value = [{"id": "1", "name": "test"}]

        nodes = connected_session.get_graph_nodes("File")

        connected_session._mock_graph.get_nodes_by_type.assert_called_with("File")
        assert len(nodes) == 1

    def test_get_archimate_stats(self, connected_session):
        """Should return element and relationship counts."""
        connected_session._mock_archimate.get_elements.return_value = [
            {"type": "ApplicationComponent"},
            {"type": "ApplicationComponent"},
            {"type": "DataObject"},
        ]
        connected_session._mock_archimate.get_relationships.return_value = [{"id": "1"}]

        stats = connected_session.get_archimate_stats()

        assert stats["total_elements"] == 3
        assert stats["total_relationships"] == 1
        assert stats["by_type"]["ApplicationComponent"] == 2
        assert stats["by_type"]["DataObject"] == 1

    def test_get_repositories(self, connected_session):
        """Should delegate to repo manager."""
        connected_session._mock_repo.list_repositories.return_value = [MagicMock(name="repo1")]

        repos = connected_session.get_repositories(detailed=True)

        connected_session._mock_repo.list_repositories.assert_called_with(detailed=True)
        assert len(repos) == 1


class TestPipelineSessionInfrastructure:
    """Tests for infrastructure control methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection") as mock_neo4j,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_graph = mock_graph.return_value
            session._mock_archimate = mock_archimate.return_value
            session._mock_neo4j = mock_neo4j.return_value
            yield session

    def test_clear_graph(self, connected_session):
        """Should clear graph and return success."""
        result = connected_session.clear_graph()

        connected_session._mock_graph.clear_graph.assert_called_once()
        assert result["success"] is True

    def test_clear_graph_error(self, connected_session):
        """Should return error on failure."""
        connected_session._mock_graph.clear_graph.side_effect = Exception("Neo4j error")

        result = connected_session.clear_graph()

        assert result["success"] is False
        assert "Neo4j error" in result["error"]

    def test_clear_model(self, connected_session):
        """Should clear model and return success."""
        result = connected_session.clear_model()

        connected_session._mock_archimate.clear_model.assert_called_once()
        assert result["success"] is True

    def test_get_neo4j_status(self, connected_session):
        """Should return container status."""
        connected_session._mock_neo4j.get_container_status.return_value = {"running": True}

        status = connected_session.get_neo4j_status()

        assert status["running"] is True


class TestPipelineSessionRepositoryManagement:
    """Tests for repository management methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_repo = mock_repo.return_value
            yield session

    def test_clone_repository_success(self, connected_session):
        """Should clone and return success dict."""
        mock_result = MagicMock()
        mock_result.name = "my-repo"
        mock_result.path = "/path/to/repo"
        mock_result.url = "https://github.com/test/repo"
        connected_session._mock_repo.clone_repository.return_value = mock_result

        result = connected_session.clone_repository("https://github.com/test/repo")

        assert result["success"] is True
        assert result["name"] == "my-repo"

    def test_clone_repository_error(self, connected_session):
        """Should return error on failure."""
        connected_session._mock_repo.clone_repository.side_effect = Exception("Clone failed")

        result = connected_session.clone_repository("https://bad-url")

        assert result["success"] is False
        assert "Clone failed" in result["error"]

    def test_delete_repository_success(self, connected_session):
        """Should delete and return success."""
        result = connected_session.delete_repository("my-repo")

        connected_session._mock_repo.delete_repository.assert_called_with("my-repo", force=False)
        assert result["success"] is True


class TestPipelineSessionRunManagement:
    """Tests for run management methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked database."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_engine = mock_db.return_value
            yield session

    def test_get_runs(self, connected_session):
        """Should return list of runs."""
        connected_session._mock_engine.execute.return_value.fetchall.return_value = [
            (1, "Test run", True, "2024-01-01", None),
            (2, "Old run", False, "2024-01-01", "2024-01-02"),
        ]

        runs = connected_session.get_runs(limit=5)

        assert len(runs) == 2
        assert runs[0]["run_id"] == 1
        assert runs[0]["is_active"] is True

    def test_get_active_run(self, connected_session):
        """Should return active run or None."""
        connected_session._mock_engine.execute.return_value.fetchone.return_value = (
            1,
            "Active run",
            "2024-01-01",
        )

        run = connected_session.get_active_run()

        assert run["run_id"] == 1
        assert run["description"] == "Active run"

    def test_get_active_run_none(self, connected_session):
        """Should return None when no active run."""
        connected_session._mock_engine.execute.return_value.fetchone.return_value = None

        run = connected_session.get_active_run()

        assert run is None

    def test_create_run(self, connected_session):
        """Should create a new run."""
        connected_session._mock_engine.execute.return_value.fetchone.return_value = (5,)

        result = connected_session.create_run("New test run")

        assert result["success"] is True
        assert result["run_id"] == 6
        assert result["description"] == "New test run"


class TestPipelineSessionLLM:
    """Tests for LLM-related methods."""

    def test_get_llm_status_configured(self):
        """Should return configured status with provider info."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)

            # Mock llm_info property
            with patch.object(PipelineSession, "llm_info", new_callable=lambda: property(lambda self: {"provider": "openai", "model": "gpt-4"})):
                status = session.get_llm_status()

            assert status["configured"] is True
            assert status["provider"] == "openai"

    def test_get_llm_status_not_configured(self):
        """Should return not configured when no LLM."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
        ):
            session = PipelineSession(auto_connect=True)

            with patch.object(PipelineSession, "llm_info", new_callable=lambda: property(lambda self: None)):
                status = session.get_llm_status()

            assert status["configured"] is False


class TestPipelineSessionOrchestration:
    """Tests for pipeline orchestration methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked services."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
            patch("deriva.services.session.extraction") as mock_extraction,
            patch("deriva.services.session.derivation") as mock_derivation,
            patch("deriva.services.session.pipeline") as mock_pipeline,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_extraction = mock_extraction
            session._mock_derivation = mock_derivation
            session._mock_pipeline = mock_pipeline
            yield session

    def test_run_extraction(self, connected_session):
        """Should delegate to extraction service."""
        connected_session._mock_extraction.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 10},
        }

        result = connected_session.run_extraction(repo_name="test-repo", verbose=True)

        connected_session._mock_extraction.run_extraction.assert_called_once()
        assert result["success"] is True

    def test_run_derivation(self, connected_session):
        """Should delegate to derivation service."""
        connected_session._mock_derivation.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 5},
        }

        # Mock LLM query function
        with patch.object(connected_session, "_get_llm_query_fn", return_value=lambda p, s: None):
            result = connected_session.run_derivation(verbose=True)

        assert result["success"] is True

    def test_run_pipeline(self, connected_session):
        """Should delegate to pipeline service."""
        connected_session._mock_pipeline.run_full_pipeline.return_value = {
            "success": True,
            "stats": {},
        }

        with patch.object(connected_session, "_get_llm_query_fn", return_value=lambda p, s: None):
            result = connected_session.run_pipeline(verbose=True)

        connected_session._mock_pipeline.run_full_pipeline.assert_called_once()
        assert result["success"] is True


class TestPipelineSessionIterators:
    """Tests for PipelineSession iterator methods (progress bar support)."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked services."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.Neo4jConnection"),
            patch("deriva.services.session.extraction") as mock_extraction,
            patch("deriva.services.session.derivation") as mock_derivation,
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_extraction = mock_extraction
            session._mock_derivation = mock_derivation
            session._mock_config = mock_config
            yield session

    def test_run_extraction_iter_yields_progress_updates(self, connected_session):
        """Should yield ProgressUpdate objects from extraction iterator."""
        from deriva.common.types import ProgressUpdate

        # Mock the extraction iterator to yield some updates
        mock_updates = [
            ProgressUpdate(phase="extraction", step="File", status="processing", current=1, total=2),
            ProgressUpdate(phase="extraction", step="TypeDefinition", status="complete", current=2, total=2),
        ]
        connected_session._mock_extraction.run_extraction_iter.return_value = iter(mock_updates)

        updates = list(connected_session.run_extraction_iter())

        assert len(updates) == 2
        assert all(isinstance(u, ProgressUpdate) for u in updates)
        assert updates[0].step == "File"
        assert updates[1].step == "TypeDefinition"

    def test_run_extraction_iter_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            list(session.run_extraction_iter())

    def test_run_derivation_iter_yields_progress_updates(self, connected_session):
        """Should yield ProgressUpdate objects from derivation iterator."""
        from deriva.common.types import ProgressUpdate

        # Mock the derivation iterator to yield some updates
        mock_updates = [
            ProgressUpdate(phase="derivation", step="PageRank", status="processing", current=1, total=3),
            ProgressUpdate(phase="derivation", step="ApplicationComponent", status="complete", current=2, total=3),
        ]
        connected_session._mock_derivation.run_derivation_iter.return_value = iter(mock_updates)

        with patch.object(connected_session, "_get_llm_query_fn", return_value=lambda p, s: None):
            updates = list(connected_session.run_derivation_iter())

        assert len(updates) == 2
        assert all(isinstance(u, ProgressUpdate) for u in updates)
        assert updates[0].step == "PageRank"
        assert updates[1].step == "ApplicationComponent"

    def test_run_derivation_iter_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            list(session.run_derivation_iter())

    def test_get_derivation_step_count_returns_count(self, connected_session):
        """Should return sum of enrich and generate config counts."""
        # Mock configs: 2 enrich steps + 3 generate steps = 5 total
        connected_session._mock_config.get_derivation_configs.side_effect = lambda engine, enabled_only, phase: (
            [MagicMock(), MagicMock()] if phase == "enrich" else [MagicMock(), MagicMock(), MagicMock()]
        )

        count = connected_session.get_derivation_step_count()

        assert count == 5

    def test_get_derivation_step_count_with_enabled_only_false(self, connected_session):
        """Should pass enabled_only flag to config query."""
        connected_session._mock_config.get_derivation_configs.return_value = []

        connected_session.get_derivation_step_count(enabled_only=False)

        # Verify enabled_only=False was passed
        calls = connected_session._mock_config.get_derivation_configs.call_args_list
        assert all(call.kwargs.get("enabled_only") is False for call in calls)


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
