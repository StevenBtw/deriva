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
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_graph = mock_graph.return_value
            session._mock_archimate = mock_archimate.return_value
            yield session

    def test_clear_graph(self, connected_session):
        """Should clear graph and return success."""
        result = connected_session.clear_graph()

        connected_session._mock_graph.clear_graph.assert_called_once()
        assert result["success"] is True

    def test_clear_graph_error(self, connected_session):
        """Should return error on failure."""
        connected_session._mock_graph.clear_graph.side_effect = Exception("Graph error")

        result = connected_session.clear_graph()

        assert result["success"] is False
        assert "Graph error" in result["error"]

    def test_clear_model(self, connected_session):
        """Should clear model and return success."""
        result = connected_session.clear_model()

        connected_session._mock_archimate.clear_model.assert_called_once()
        assert result["success"] is True

    def test_get_graph_db_status(self, connected_session):
        """Should return graph database status (grafeo embedded, always running)."""
        status = connected_session.get_graph_db_status()

        assert status["running"] is True
        assert status["engine"] == "grafeo_embedded"


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
            patch("deriva.services.session.extraction") as mock_extraction,
            patch("deriva.services.session.derivation") as mock_derivation,
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_extraction = mock_extraction  # type: ignore[attr-defined]
            session._mock_derivation = mock_derivation  # type: ignore[attr-defined]
            session._mock_config = mock_config  # type: ignore[attr-defined]
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
        """Should return sum of prep and generate config counts."""
        # Mock configs: 2 prep steps + 3 generate steps = 5 total
        connected_session._mock_config.get_derivation_configs.side_effect = lambda engine, enabled_only, phase: (
            [MagicMock(), MagicMock()] if phase == "prep" else [MagicMock(), MagicMock(), MagicMock()]
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


class TestPipelineSessionGraphDbControl:
    """Tests for graph database control methods (grafeo embedded)."""

    def test_start_graph_db(self):
        """Should return success (grafeo is embedded, always available)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            result = session.start_graph_db()

            assert result["success"] is True
            assert "embedded" in result["message"].lower()

    def test_stop_graph_db(self):
        """Should return success (grafeo is embedded, no container to stop)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            result = session.stop_graph_db()

            assert result["success"] is True
            assert "embedded" in result["message"].lower()


class TestPipelineSessionDerivationNoLLM:
    """Tests for derivation with no LLM configured."""

    @pytest.fixture
    def connected_session(self):
        """Create connected session with mocked services."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            yield session

    def test_run_derivation_returns_error_when_no_llm(self, connected_session):
        """Should return error when LLM not configured."""
        with patch.object(connected_session, "_get_llm_query_fn", return_value=None):
            result = connected_session.run_derivation()

        assert result["success"] is False
        assert "LLM not configured" in result["errors"][0]

    def test_run_derivation_iter_yields_error_when_no_llm(self, connected_session):
        """Should yield error update when LLM not configured."""
        with patch.object(connected_session, "_get_llm_query_fn", return_value=None):
            updates = list(connected_session.run_derivation_iter())

        assert len(updates) == 1
        assert updates[0].status == "error"
        assert "LLM not configured" in updates[0].message


class TestPipelineSessionExport:
    """Tests for export methods."""

    @pytest.fixture
    def connected_session(self):
        """Create connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_archimate = mock_archimate.return_value
            yield session

    def test_export_model_success(self, connected_session, tmp_path):
        """Should export model successfully."""
        mock_element = MagicMock()
        mock_element.identifier = "elem1"
        mock_rel = MagicMock()
        mock_rel.source = "elem1"
        mock_rel.target = "elem1"

        connected_session._mock_archimate.get_elements.return_value = [mock_element]
        connected_session._mock_archimate.get_relationships.return_value = [mock_rel]

        output_path = str(tmp_path / "model.xml")
        with patch("deriva.services.session.ArchiMateXMLExporter"):
            result = connected_session.export_model(output_path=output_path)

        assert result["success"] is True
        assert result["elements_exported"] == 1

    def test_export_model_no_elements(self, connected_session, tmp_path):
        """Should return error when no elements found."""
        connected_session._mock_archimate.get_elements.return_value = []

        result = connected_session.export_model(output_path=str(tmp_path / "model.xml"))

        assert result["success"] is False
        assert "No ArchiMate elements" in result["error"]


class TestPipelineSessionConfigMethods:
    """Tests for config passthrough methods."""

    @pytest.fixture
    def connected_session(self):
        """Create connected session with mocked engine."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_engine = mock_db.return_value  # type: ignore[attr-defined]
            session._mock_config = mock_config  # type: ignore[attr-defined]
            yield session

    def test_list_steps_delegates_to_config(self, connected_session):
        """Should delegate list_steps to config service."""
        connected_session._mock_config.list_steps.return_value = [{"name": "step1"}]

        result = connected_session.list_steps("extraction")

        assert len(result) == 1
        assert result[0]["name"] == "step1"

    def test_enable_step_delegates_to_config(self, connected_session):
        """Should delegate enable_step to config service."""
        connected_session._mock_config.enable_step.return_value = True

        result = connected_session.enable_step("extraction", "BusinessConcept")

        assert result is True

    def test_disable_step_delegates_to_config(self, connected_session):
        """Should delegate disable_step to config service."""
        connected_session._mock_config.disable_step.return_value = True

        result = connected_session.disable_step("extraction", "BusinessConcept")

        assert result is True

    def test_get_file_types_returns_list(self, connected_session):
        """Should return file types as dicts."""

        # Use a simple object with __dict__ instead of MagicMock
        class MockFileType:
            def __init__(self):
                self.extension = ".py"
                self.file_type = "source"

        connected_session._mock_config.get_file_types.return_value = [MockFileType()]

        result = connected_session.get_file_types()

        assert len(result) == 1

    def test_get_extraction_configs_returns_list(self, connected_session):
        """Should return extraction configs as dicts."""
        mock_config = MagicMock()
        mock_config.node_type = "BusinessConcept"
        mock_config.sequence = 1
        mock_config.enabled = True
        mock_config.input_sources = None
        mock_config.instruction = "Test"
        mock_config.example = "{}"
        connected_session._mock_config.get_extraction_configs.return_value = [mock_config]

        result = connected_session.get_extraction_configs()

        assert len(result) == 1
        assert result[0]["node_type"] == "BusinessConcept"

    def test_update_extraction_config(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.update_extraction_config.return_value = True

        result = connected_session.update_extraction_config("BusinessConcept", enabled=True)

        assert result is True

    def test_save_extraction_config(self, connected_session):
        """Should delegate to config service for versioned update."""
        connected_session._mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "new_version": 2,
        }

        result = connected_session.save_extraction_config("BusinessConcept", enabled=True)

        assert result["success"] is True

    def test_get_derivation_configs(self, connected_session):
        """Should return derivation configs as dicts."""
        mock_config = MagicMock()
        mock_config.element_type = "ApplicationComponent"
        mock_config.sequence = 1
        mock_config.enabled = True
        mock_config.input_graph_query = "MATCH (n)"
        mock_config.instruction = "Test"
        mock_config.example = "{}"
        connected_session._mock_config.get_derivation_configs.return_value = [mock_config]

        result = connected_session.get_derivation_configs()

        assert len(result) == 1
        assert result[0]["element_type"] == "ApplicationComponent"

    def test_update_derivation_config(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.update_derivation_config.return_value = True

        result = connected_session.update_derivation_config("ApplicationComponent", enabled=True)

        assert result is True

    def test_save_derivation_config(self, connected_session):
        """Should delegate to config service for versioned update."""
        connected_session._mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "new_version": 2,
        }

        result = connected_session.save_derivation_config("ApplicationComponent", enabled=True)

        assert result["success"] is True

    def test_get_config_versions(self, connected_session):
        """Should return config versions."""
        connected_session._mock_config.get_active_config_versions.return_value = {
            "extraction": {"BusinessConcept": 1},
            "derivation": {"ApplicationComponent": 2},
        }

        result = connected_session.get_config_versions()

        assert result["extraction"]["BusinessConcept"] == 1
        assert result["derivation"]["ApplicationComponent"] == 2

    def test_add_file_type(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.add_file_type.return_value = True

        result = connected_session.add_file_type(".rs", "source", "rust")

        assert result is True

    def test_update_file_type(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.update_file_type.return_value = True

        result = connected_session.update_file_type(".py", "source", "python3")

        assert result is True

    def test_delete_file_type(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.delete_file_type.return_value = True

        result = connected_session.delete_file_type(".xyz")

        assert result is True


class TestPipelineSessionFileTypeStats:
    """Tests for file type stats method."""

    def test_get_file_type_stats(self):
        """Should return file type statistics."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_db.return_value.execute.return_value.fetchone.side_effect = [
                (5,),  # types
                (10,),  # subtypes
                (20,),  # total
            ]

            result = session.get_file_type_stats()

            assert result["types"] == 5
            assert result["subtypes"] == 10
            assert result["total"] == 20


class TestPipelineSessionLLMManagement:
    """Tests for LLM management methods."""

    def test_toggle_llm_cache_enabled(self):
        """Should enable LLM cache."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._llm_manager = MagicMock()

            result = session.toggle_llm_cache(True)

            assert result["success"] is True
            assert result["cache_enabled"] is True

    def test_toggle_llm_cache_no_manager(self):
        """Should return error when no LLM manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            # Force _llm_manager to None
            with patch.object(session, "_get_llm_query_fn", return_value=None):
                session._llm_manager = None

                result = session.toggle_llm_cache(True)

                assert result["success"] is False

    def test_list_benchmark_models(self):
        """Should return benchmark models dict."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.benchmarking"),
        ):
            session = PipelineSession(auto_connect=True)

            with patch("deriva.adapters.llm.manager.load_benchmark_models", return_value={"model1": {}}):
                result = session.list_benchmark_models()

            assert "model1" in result


class TestPipelineSessionMiscMethods:
    """Tests for miscellaneous session methods."""

    @pytest.fixture
    def connected_session(self):
        """Create connected session."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.pipeline") as mock_pipeline,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_engine = mock_db.return_value
            session._mock_pipeline = mock_pipeline
            yield session

    def test_run_classification(self, connected_session):
        """Should delegate to pipeline service."""
        connected_session._mock_pipeline.run_classification.return_value = {"success": True}

        result = connected_session.run_classification(repo_name="test-repo")

        assert result["success"] is True

    def test_get_database_path(self, connected_session):
        """Should return database path."""
        with patch("deriva.adapters.database.DB_PATH", "test/path/db.duckdb"):
            result = connected_session.get_database_path()

            assert "db" in result.lower() or "path" in result.lower()

    def test_execute_sql_with_params(self, connected_session):
        """Should execute SQL with parameters."""
        connected_session._mock_engine.execute.return_value.fetchall.return_value = [(1, "test")]

        result = connected_session.execute_sql("SELECT * FROM test WHERE id = ?", [1])

        assert len(result) == 1
        assert result[0] == (1, "test")

    def test_execute_sql_without_params(self, connected_session):
        """Should execute SQL without parameters."""
        connected_session._mock_engine.execute.return_value.fetchall.return_value = [(1,), (2,)]

        result = connected_session.execute_sql("SELECT COUNT(*) FROM test")

        assert len(result) == 2

    def test_workspace_dir_property(self, connected_session):
        """Should return workspace directory."""
        result = connected_session.workspace_dir

        assert result is not None


class TestPipelineSessionRepositoryInfo:
    """Tests for repository info method."""

    @pytest.fixture
    def connected_session(self):
        """Create connected session with mocked repo manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_repo = mock_repo.return_value
            yield session

    def test_get_repository_info_found(self, connected_session):
        """Should return repository info when found."""
        mock_info = MagicMock()
        mock_info.to_dict.return_value = {"name": "test-repo", "path": "/path/to/repo"}
        connected_session._mock_repo.get_repository_info.return_value = mock_info

        result = connected_session.get_repository_info("test-repo")

        assert result is not None
        assert result["name"] == "test-repo"

    def test_get_repository_info_not_found(self, connected_session):
        """Should return None when not found."""
        connected_session._mock_repo.get_repository_info.return_value = None

        result = connected_session.get_repository_info("unknown-repo")

        assert result is None

    def test_get_repository_info_error(self, connected_session):
        """Should return None on error."""
        connected_session._mock_repo.get_repository_info.side_effect = Exception("Error")

        result = connected_session.get_repository_info("test-repo")

        assert result is None

    def test_delete_repository_error(self, connected_session):
        """Should return error on delete failure."""
        connected_session._mock_repo.delete_repository.side_effect = Exception("Delete failed")

        result = connected_session.delete_repository("test-repo")

        assert result["success"] is False
        assert "Delete failed" in result["error"]


class TestPipelineSessionExtractionStepCount:
    """Tests for get_extraction_step_count method."""

    def test_get_extraction_step_count(self):
        """Should return extraction step count."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)

            # 3 configs * 2 repos = 6 steps
            mock_config.get_extraction_configs.return_value = [MagicMock(), MagicMock(), MagicMock()]
            mock_repo.return_value.list_repositories.return_value = [MagicMock(name="repo1"), MagicMock(name="repo2")]

            count = session.get_extraction_step_count()

            assert count == 6


class TestPipelineSessionCypherQueries:
    """Tests for Cypher query methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_graph = mock_graph.return_value
            session._mock_archimate = mock_archimate.return_value
            yield session

    def test_query_graph_executes_cypher(self, connected_session):
        """Should execute Cypher query on Graph namespace."""
        connected_session._mock_graph.query.return_value = [{"n.name": "TestNode", "n.type": "File"}]

        result = connected_session.query_graph("MATCH (n:File) RETURN n.name, n.type")

        connected_session._mock_graph.query.assert_called_once_with("MATCH (n:File) RETURN n.name, n.type")
        assert len(result) == 1
        assert result[0]["n.name"] == "TestNode"

    def test_query_model_executes_cypher(self, connected_session):
        """Should execute Cypher query on Model namespace."""
        connected_session._mock_archimate.query.return_value = [{"e.name": "MyComponent", "e.type": "ApplicationComponent"}]

        result = connected_session.query_model("MATCH (e:Element) RETURN e.name, e.type")

        connected_session._mock_archimate.query.assert_called_once_with("MATCH (e:Element) RETURN e.name, e.type")
        assert len(result) == 1
        assert result[0]["e.name"] == "MyComponent"

    def test_query_graph_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.query_graph("MATCH (n) RETURN n")

    def test_query_model_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.query_model("MATCH (n) RETURN n")


class TestPipelineSessionArchimateElements:
    """Tests for ArchiMate element/relationship retrieval."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked archimate manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_archimate = mock_archimate.return_value
            yield session

    def test_get_archimate_elements_with_to_dict(self, connected_session):
        """Should convert elements using to_dict if available."""
        mock_element = MagicMock()
        mock_element.to_dict.return_value = {
            "identifier": "elem1",
            "type": "ApplicationComponent",
            "name": "TestComponent",
        }
        connected_session._mock_archimate.get_elements.return_value = [mock_element]

        result = connected_session.get_archimate_elements()

        assert len(result) == 1
        assert result[0]["identifier"] == "elem1"
        assert result[0]["type"] == "ApplicationComponent"

    def test_get_archimate_elements_without_to_dict(self, connected_session):
        """Should convert elements using dict() if no to_dict."""
        # Create an element without to_dict
        mock_element = {"identifier": "elem2", "type": "DataObject"}
        connected_session._mock_archimate.get_elements.return_value = [mock_element]

        result = connected_session.get_archimate_elements()

        assert len(result) == 1
        assert result[0]["identifier"] == "elem2"

    def test_get_archimate_relationships_with_to_dict(self, connected_session):
        """Should convert relationships using to_dict if available."""
        mock_rel = MagicMock()
        mock_rel.to_dict.return_value = {
            "identifier": "rel1",
            "type": "AccessRelationship",
            "source": "elem1",
            "target": "elem2",
        }
        connected_session._mock_archimate.get_relationships.return_value = [mock_rel]

        result = connected_session.get_archimate_relationships()

        assert len(result) == 1
        assert result[0]["identifier"] == "rel1"
        assert result[0]["type"] == "AccessRelationship"

    def test_get_archimate_relationships_without_to_dict(self, connected_session):
        """Should convert relationships using dict() if no to_dict."""
        mock_rel = {"identifier": "rel2", "type": "CompositionRelationship"}
        connected_session._mock_archimate.get_relationships.return_value = [mock_rel]

        result = connected_session.get_archimate_relationships()

        assert len(result) == 1
        assert result[0]["identifier"] == "rel2"

    def test_get_archimate_elements_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.get_archimate_elements()

    def test_get_archimate_relationships_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.get_archimate_relationships()


class TestPipelineSessionBenchmarking:
    """Tests for benchmarking methods."""

    @pytest.fixture
    def connected_session(self):
        """Create a connected session with mocked managers."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._mock_engine = mock_db.return_value
            session._mock_graph = mock_graph.return_value
            session._mock_archimate = mock_archimate.return_value
            yield session

    def test_run_benchmark(self, connected_session):
        """Should run benchmark with given config."""
        # Patch the internal import inside run_benchmark method
        with patch("deriva.services.benchmarking.BenchmarkConfig") as mock_config, patch("deriva.services.benchmarking.BenchmarkOrchestrator") as mock_orch:
            mock_result = MagicMock()
            mock_result.session_id = "bench_123"
            mock_orch.return_value.run.return_value = mock_result

            result = connected_session.run_benchmark(
                repositories=["repo1"],
                models=["model1"],
                runs=2,
                description="Test benchmark",
            )

            mock_config.assert_called_once()
            assert result.session_id == "bench_123"

    def test_run_benchmark_with_all_options(self, connected_session):
        """Should pass all options to benchmark config."""
        with patch("deriva.services.benchmarking.BenchmarkConfig") as mock_config, patch("deriva.services.benchmarking.BenchmarkOrchestrator") as mock_orch:
            mock_result = MagicMock()
            mock_orch.return_value.run.return_value = mock_result

            connected_session.run_benchmark(
                repositories=["repo1", "repo2"],
                models=["model1", "model2"],
                runs=5,
                stages=["extraction", "derivation"],
                description="Full benchmark",
                use_cache=False,
                nocache_configs=["ApplicationComponent"],
                export_models=False,
                clear_between_runs=False,
                bench_hash=True,
                defer_relationships=True,
                per_repo=True,
                use_enrichment_cache=False,
                nocache_enrichment_configs=["SomeConfig"],
            )

            config_call = mock_config.call_args
            assert config_call.kwargs["repositories"] == ["repo1", "repo2"]
            assert config_call.kwargs["models"] == ["model1", "model2"]
            assert config_call.kwargs["runs_per_combination"] == 5
            assert config_call.kwargs["use_cache"] is False

    def test_analyze_benchmark(self, connected_session):
        """Should create and return BenchmarkAnalyzer."""
        with patch("deriva.services.session.benchmarking") as mock_bench:
            mock_analyzer = MagicMock()
            mock_bench.BenchmarkAnalyzer.return_value = mock_analyzer

            result = connected_session.analyze_benchmark("bench_123")

            mock_bench.BenchmarkAnalyzer.assert_called_once_with("bench_123", connected_session._engine)
            assert result is mock_analyzer

    def test_analyze_config_deviations(self, connected_session):
        """Should create and return ConfigDeviationAnalyzer."""
        with patch("deriva.services.config_deviation.ConfigDeviationAnalyzer") as mock_analyzer_cls:
            mock_analyzer = MagicMock()
            mock_analyzer_cls.return_value = mock_analyzer

            result = connected_session.analyze_config_deviations("bench_123")

            mock_analyzer_cls.assert_called_once_with("bench_123", connected_session._engine)
            assert result is mock_analyzer

    def test_list_benchmarks(self, connected_session):
        """Should list benchmark sessions."""
        with patch("deriva.services.benchmarking.list_benchmark_sessions") as mock_list:
            mock_list.return_value = [
                {"session_id": "bench_1", "description": "Test 1"},
                {"session_id": "bench_2", "description": "Test 2"},
            ]

            result = connected_session.list_benchmarks(limit=5)

            mock_list.assert_called_once_with(connected_session._engine, 5)
            assert len(result) == 2

    def test_list_benchmarks_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            session.list_benchmarks()


class TestPipelineSessionLLMQueryFn:
    """Tests for _get_llm_query_fn method."""

    def test_get_llm_query_fn_lazy_loads_manager(self):
        """Should lazy load LLM manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            assert session._llm_manager is None

            with patch("deriva.adapters.llm.LLMManager") as mock_llm:
                mock_llm.return_value = MagicMock()
                fn = session._get_llm_query_fn()

                mock_llm.assert_called_once()
                assert fn is not None

    def test_get_llm_query_fn_returns_none_on_error(self):
        """Should return None if LLM manager fails to initialize."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            with patch("deriva.adapters.llm.LLMManager", side_effect=Exception("No API key")):
                fn = session._get_llm_query_fn()

                assert fn is None

    def test_get_llm_query_fn_sets_nocache(self):
        """Should set nocache flag on LLM manager when requested."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_manager = MagicMock()
            session._llm_manager = mock_manager

            session._get_llm_query_fn(no_cache=True)

            assert mock_manager.nocache is True

    def test_get_llm_query_fn_reuses_existing_manager(self):
        """Should reuse existing LLM manager."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_manager = MagicMock()
            session._llm_manager = mock_manager

            with patch("deriva.adapters.llm.LLMManager") as mock_llm:
                session._get_llm_query_fn()

                # Should not create new manager
                mock_llm.assert_not_called()


class TestPipelineSessionLLMInfo:
    """Tests for llm_info property."""

    def test_llm_info_returns_provider_and_model(self):
        """Should return dict with provider and model."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_manager = MagicMock()
            mock_manager.provider_name = "openai"
            mock_manager.model = "gpt-4"
            session._llm_manager = mock_manager

            result = session.llm_info

            assert result == {"provider": "openai", "model": "gpt-4"}

    def test_llm_info_returns_none_when_no_manager(self):
        """Should return None when LLM manager not configured."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            with patch.object(session, "_get_llm_query_fn", return_value=None):
                session._llm_manager = None
                result = session.llm_info

                assert result is None

    def test_llm_info_lazy_loads_manager(self):
        """Should attempt to load manager if not present."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            session._llm_manager = None

            with patch.object(session, "_get_llm_query_fn") as mock_get:
                _ = session.llm_info

                mock_get.assert_called_once()


class TestPipelineSessionDisconnect:
    """Additional disconnect tests."""

    def test_disconnect_idempotent(self):
        """Disconnect should be idempotent."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession()
            # Disconnect without connecting should not error
            session.disconnect()
            session.disconnect()

            assert not session.is_connected()


class TestPipelineSessionClearModelError:
    """Test clear_model error handling."""

    def test_clear_model_error(self):
        """Should return error on failure."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_archimate.return_value.clear_model.side_effect = Exception("Model error")

            result = session.clear_model()

            assert result["success"] is False
            assert "Model error" in result["error"]


class TestPipelineSessionGraphDbNotConnected:
    """Tests for graph database control stubs (grafeo embedded, always available)."""

    def test_get_graph_db_status_always_running(self):
        """Should return running status even without full connection (grafeo is embedded)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            result = session.get_graph_db_status()

            assert result["running"] is True
            assert result["engine"] == "grafeo_embedded"

    def test_start_graph_db_always_succeeds(self):
        """Should return success (grafeo is embedded, no container to start)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            result = session.start_graph_db()

            assert result["success"] is True

    def test_stop_graph_db_always_succeeds(self):
        """Should return success (grafeo is embedded, no container to stop)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            result = session.stop_graph_db()

            assert result["success"] is True


class TestPipelineSessionGetRepositoriesStringReturn:
    """Tests for get_repositories with string returns."""

    def test_get_repositories_string_result(self):
        """Should handle string repository names."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
        ):
            session = PipelineSession(auto_connect=True)
            mock_repo.return_value.list_repositories.return_value = ["repo1", "repo2"]

            result = session.get_repositories(detailed=False)

            assert len(result) == 2
            assert result[0] == {"name": "repo1"}
            assert result[1] == {"name": "repo2"}

    def test_get_repositories_mixed_results(self):
        """Should handle mixed return types (objects without to_dict)."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
        ):
            session = PipelineSession(auto_connect=True)
            # Create object without to_dict
            mock_obj = object()
            mock_repo.return_value.list_repositories.return_value = [mock_obj]

            result = session.get_repositories()

            assert len(result) == 1
            # Should convert to string


class TestPipelineSessionArchimateStatsEdgeCases:
    """Tests for get_archimate_stats edge cases."""

    def test_get_archimate_stats_with_object_type(self):
        """Should handle elements with type attribute instead of dict."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            # Create element object with type attribute
            class MockElement:
                type = "ApplicationService"

            mock_archimate.return_value.get_elements.return_value = [MockElement(), MockElement()]
            mock_archimate.return_value.get_relationships.return_value = []

            result = session.get_archimate_stats()

            assert result["total_elements"] == 2
            assert result["by_type"]["ApplicationService"] == 2

    def test_get_archimate_stats_with_unknown_type(self):
        """Should handle elements without type."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

            # Create element without type
            class MockElement:
                pass

            mock_archimate.return_value.get_elements.return_value = [MockElement()]
            mock_archimate.return_value.get_relationships.return_value = []

            result = session.get_archimate_stats()

            assert result["total_elements"] == 1
            assert result["by_type"]["Unknown"] == 1


class TestPipelineSessionExportEdgeCases:
    """Tests for export edge cases."""

    def test_export_model_filters_disabled_relationships(self):
        """Should filter relationships to only enabled elements."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.ArchiMateXMLExporter") as mock_exporter,
        ):
            session = PipelineSession(auto_connect=True)

            # Two enabled elements
            elem1 = MagicMock()
            elem1.identifier = "elem1"
            elem2 = MagicMock()
            elem2.identifier = "elem2"

            # Three relationships - one points to disabled element
            rel1 = MagicMock()
            rel1.source = "elem1"
            rel1.target = "elem2"  # Both enabled
            rel2 = MagicMock()
            rel2.source = "elem1"
            rel2.target = "elem3"  # elem3 is disabled

            mock_archimate.return_value.get_elements.return_value = [elem1, elem2]
            mock_archimate.return_value.get_relationships.return_value = [rel1, rel2]

            session.export_model()

            # Should only export rel1
            export_call = mock_exporter.return_value.export.call_args
            exported_rels = export_call.kwargs["relationships"]
            assert len(exported_rels) == 1
            assert exported_rels[0].target == "elem2"

    def test_export_model_handles_exception(self):
        """Should handle export exceptions."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.ArchiMateXMLExporter") as mock_exporter,
        ):
            session = PipelineSession(auto_connect=True)

            elem = MagicMock()
            elem.identifier = "elem1"
            mock_archimate.return_value.get_elements.return_value = [elem]
            mock_archimate.return_value.get_relationships.return_value = []
            mock_exporter.return_value.export.side_effect = Exception("Write failed")

            result = session.export_model()

            assert result["success"] is False
            assert "Write failed" in result["error"]


class TestPipelineSessionCreateRunError:
    """Tests for create_run error handling."""

    def test_create_run_handles_error(self):
        """Should return error on failure."""
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_db.return_value.execute.side_effect = Exception("DB error")

            result = session.create_run("Test run")

            assert result["success"] is False
            assert "DB error" in result["error"]


class TestPipelineSessionExtractionStepCountFiltered:
    """Tests for get_extraction_step_count with repo filter."""

    def test_get_extraction_step_count_filters_by_repo(self):
        """Should filter repos by name."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager") as mock_repo,
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)

            mock_config.get_extraction_configs.return_value = [MagicMock(), MagicMock()]
            repo1 = MagicMock()
            repo1.name = "repo1"
            repo2 = MagicMock()
            repo2.name = "repo2"
            mock_repo.return_value.list_repositories.return_value = [repo1, repo2]

            # Filter to repo1 only: 2 configs * 1 repo = 2 steps
            count = session.get_extraction_step_count(repo_name="repo1")

            assert count == 2


class TestPipelineSessionFileTypesEdgeCases:
    """Tests for get_file_types edge cases."""

    def test_get_file_types_with_has_to_dict(self):
        """Should use HasToDict protocol."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.config") as mock_config,
        ):
            from deriva.common.types import HasToDict

            session = PipelineSession(auto_connect=True)

            # Create object implementing HasToDict
            class MockFileType(HasToDict):
                def to_dict(self):
                    return {"extension": ".py", "type": "source"}

            mock_config.get_file_types.return_value = [MockFileType()]

            result = session.get_file_types()

            assert len(result) == 1
            assert result[0]["extension"] == ".py"

    def test_get_file_types_fallback_to_str(self):
        """Should fallback to string conversion."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.config") as mock_config,
        ):
            session = PipelineSession(auto_connect=True)

            # Create basic object without to_dict or __dict__
            mock_config.get_file_types.return_value = ["simple_value"]

            result = session.get_file_types()

            assert len(result) == 1
            assert result[0]["value"] == "simple_value"
