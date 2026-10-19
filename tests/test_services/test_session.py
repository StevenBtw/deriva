"""Tests for deriva.services.session module (PipelineSession)."""

import json
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

    def test_connect_opens_the_repository_database(self):
        """A session for a repository works in that repository's own graph database."""
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.use_database") as use_database,
        ):
            PipelineSession(repository="bigfarm").connect()
            PipelineSession().connect()

        assert [c.args[0] for c in use_database.call_args_list] == ["bigfarm", "default"]

    def test_use_repository_switches_database(self):
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.use_database") as use_database,
        ):
            session = PipelineSession()
            session.connect()
            session.use_repository("darkgreen")

        assert use_database.call_args.args[0] == "darkgreen"
        assert session.repository == "darkgreen"

    def test_a_cancelled_run_makes_no_further_llm_call(self):
        from deriva.services.session import RunCancelled

        session = PipelineSession()
        session._llm_manager = MagicMock()
        query = session._get_llm_query_fn()
        assert query is not None

        session.set_cancel_check(lambda: True)
        with pytest.raises(RunCancelled):
            query("prompt")
        session._llm_manager.query.assert_not_called()

        session.set_cancel_check(None)
        query("prompt")
        session._llm_manager.query.assert_called_once()

    def test_check_repository_refuses_a_name_without_repository_or_graph(self, tmp_path, monkeypatch):
        from deriva.services.session import UnknownRepository

        monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path))
        (tmp_path / "alpha_beta.grafeo").write_bytes(b"")
        with patch("deriva.services.session.RepoManager") as repos:
            repos.return_value.list_repositories.return_value = ["beta", "alpha"]
            for known in (None, "default", "alpha", "alpha_beta"):
                PipelineSession.check_repository(known)
            with pytest.raises(UnknownRepository) as refused:
                PipelineSession.check_repository("typo")

        assert refused.value.available == ["alpha", "beta"]
        assert str(refused.value) == "Unknown repository: typo (known: alpha, beta)"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["alpha_beta.grafeo"]

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
        connected_session._mock_graph.get_nodes_by_type.side_effect = lambda t: [{"id": "1"}] if t == "Repository" else []

        stats = connected_session.get_graph_stats()

        assert stats["total_nodes"] == 1
        assert stats["by_type"]["Repository"] == 1
        assert stats["by_type"]["File"] == 0

    def test_get_graph_nodes(self, connected_session):
        """Should return nodes of specific type."""
        connected_session._mock_graph.get_nodes_by_type.return_value = [{"id": "1", "name": "test"}]

        nodes = connected_session.get_graph_nodes("File")

        connected_session._mock_graph.get_nodes_by_type.assert_called_with("File", limit=None)
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

        mock_result.branch, mock_result.last_commit, mock_result.size_mb = "main", "f112fce workshop", 0.7

        result = connected_session.clone_repository("https://github.com/test/repo")

        assert result["success"] is True
        assert result["name"] == "my-repo"
        # What the studio tells the user it cloned
        assert (result["branch"], result["last_commit"], result["size_mb"]) == ("main", "f112fce workshop", 0.7)

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

    def test_run_pipeline_without_llm_makes_no_llm_calls(self, connected_session):
        """--no-llm: extraction without an LLM, derivation only its structural prep phase."""
        from deriva.services import derivation

        connected_session._mock_pipeline.run_full_pipeline.return_value = {"success": True, "stats": {}}
        connected_session._mock_derivation.STRUCTURAL_PHASES = derivation.STRUCTURAL_PHASES  # the fixture mocks the module

        with patch.object(connected_session, "_get_llm_query_fn") as get_llm:
            connected_session.run_pipeline(no_llm=True)

        get_llm.assert_not_called()
        kwargs = connected_session._mock_pipeline.run_full_pipeline.call_args.kwargs
        assert kwargs["llm_query_fn"] is None
        assert kwargs["derivation_phases"] == ["prep"]


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

    def test_model_levels_hold_both_levels_and_the_views(self, connected_session):
        """The studio's model: the enabled elements (architect), their members (detail) and the views per level."""
        from deriva.adapters.archimate.models import Element

        connected_session._mock_archimate.get_elements.return_value = [
            Element(name="Order Data", element_type="DataObject", identifier="do_order", properties={"source": "domain::r::order"}),
        ]
        connected_session._mock_archimate.get_relationships.return_value = []
        connected_session._graph_manager.query.side_effect = lambda q, p=None: [{"d": "domain::r::order", "e": "entity::r::line", "n": "Order Line"}] if "DataEntity" in q else []

        levels = connected_session.get_model_levels()

        assert [(e["name"], e["level"], e["layer"]) for e in levels["elements"]] == [("Order Data", "enterprise", "Application"), ("Order Line", "detail", "Application")]
        assert len(levels["relationships"]) == 1
        views = {v["name"]: v for v in levels["views"]}
        assert views["Information Structure (enterprise)"] == {
            "name": "Information Structure (enterprise)",
            "viewpoint": "Information Structure",
            "level": "enterprise",
            "elements": ["do_order"],
            "relationships": [],
        }

    def test_model_views_name_their_relationships(self, connected_session):
        """A view lists the relationships it shows: a relationship of another level between two of its elements is not
        among them (an enterprise-only lift between components that are on both levels)."""
        from deriva.adapters.archimate.models import Element, Relationship

        both = {"levels": ["enterprise", "solution"]}
        connected_session._mock_archimate.get_elements.return_value = [
            Element(name="A", element_type="ApplicationComponent", identifier="ac_a", properties=both),
            Element(name="B", element_type="ApplicationComponent", identifier="ac_b", properties=both),
        ]
        connected_session._mock_archimate.get_relationships.return_value = [
            Relationship(source="ac_a", target="ac_b", relationship_type="Serving", identifier="r1", properties={"levels": ["enterprise"], "derived_from": "lifted"}),
        ]
        connected_session._graph_manager.query.return_value = []

        levels = connected_session.get_model_levels()

        (relationship,) = levels["relationships"]
        assert relationship["level"] == "enterprise"  # the exported level, as the exchange file carries it
        views = {v["name"]: v for v in levels["views"]}
        assert views["Application Cooperation (enterprise)"]["relationships"] == [relationship["identifier"]]
        assert views["Application Structure (solution)"]["elements"] == ["ac_a", "ac_b"]
        assert views["Application Structure (solution)"]["relationships"] == []

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

    def test_later_steps_of_a_disabled_target_are_the_enabled_later_ones(self, connected_session):
        """--only-step enables a disabled step for the run: its later steps are found all the same."""
        from types import SimpleNamespace

        configs = [
            SimpleNamespace(node_type="A", sequence=1, enabled=True),
            SimpleNamespace(node_type="B", sequence=2, enabled=False),
            SimpleNamespace(node_type="C", sequence=3, enabled=True),
            SimpleNamespace(node_type="D", sequence=4, enabled=False),
        ]
        connected_session._mock_config.get_extraction_configs.side_effect = lambda engine, enabled_only=False: [c for c in configs if c.enabled or not enabled_only]

        assert connected_session.later_extraction_steps("B") == ["C"]
        assert connected_session.later_extraction_steps("A") == ["C"]

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

    def test_save_extraction_config_passes_the_example(self, connected_session):
        connected_session._mock_config.create_extraction_config_version.return_value = {"success": True, "new_version": 3}

        connected_session.save_extraction_config("BusinessConcept", instruction="i", example="e")

        kwargs = connected_session._mock_config.create_extraction_config_version.call_args.kwargs
        assert kwargs["instruction"] == "i"
        assert kwargs["example"] == "e"

    def test_save_derivation_config_passes_the_example(self, connected_session):
        connected_session._mock_config.create_derivation_config_version.return_value = {"success": True, "new_version": 3}

        connected_session.save_derivation_config("Node", instruction="i", example="e")

        kwargs = connected_session._mock_config.create_derivation_config_version.call_args.kwargs
        assert kwargs["example"] == "e"

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

    def test_get_setting(self, connected_session):
        """Should delegate to config service."""
        connected_session._mock_config.get_setting.return_value = '[".git"]'

        assert connected_session.get_setting("excluded_directories") == '[".git"]'

    def test_set_setting(self, connected_session):
        """Should delegate to config service."""
        connected_session.set_setting("excluded_directories", '[".git"]')

        connected_session._mock_config.set_setting.assert_called_once_with(connected_session._engine, "excluded_directories", '[".git"]')

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

    def test_query_graph_read_only_uses_the_rolled_back_path(self, connected_session):
        connected_session._mock_graph.query_read_only.return_value = [{"id": "d1"}]

        rows = connected_session.query_graph_read_only("MATCH (n) RETURN n.id AS id", {"x": 1})

        assert rows == [{"id": "d1"}]
        connected_session._mock_graph.query_read_only.assert_called_once_with("MATCH (n) RETURN n.id AS id", {"x": 1})
        connected_session._mock_graph.query.assert_not_called()

    def test_query_model_read_only_uses_the_rolled_back_path(self, connected_session):
        connected_session._mock_archimate.query_read_only.return_value = []

        connected_session.query_model_read_only("MATCH (e) RETURN e")

        connected_session._mock_archimate.query_read_only.assert_called_once_with("MATCH (e) RETURN e", None)

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


class TestPipelineSessionCallLog:
    """The session's LLM calls go to an attached per-run call log (prompt, answer, metrics)."""

    @pytest.fixture
    def session(self):
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            manager = MagicMock()
            manager.query.return_value = MagicMock(content='{"roles": {"jboss": "application_server"}}', error=None)
            manager.last_call = {"cache_key": "k1", "cache_hit": False, "latency_ms": 12.5, "input_tokens": 100, "output_tokens": 20, "error_type": None}
            session._llm_manager = manager
            yield session

    def test_calls_are_recorded_with_prompt_answer_and_metrics(self, session, tmp_path):
        from deriva.services.llm_log import LlmCallLog

        log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")
        session.attach_call_log(log)
        query = session._get_llm_query_fn()

        query("Choose a role for jboss", {"name": "role_classification", "strict": True, "schema": {"type": "object"}}, system_prompt="You classify.")
        log.assign_step("Node")

        call = LlmCallLog.read(tmp_path / "llm.jsonl")[0]
        assert call["step"] == "Node"
        assert call["prompt"] == "Choose a role for jboss"
        assert call["system_prompt"] == "You classify."
        assert call["schema"] == "role_classification"
        assert call["response"] == '{"roles": {"jboss": "application_server"}}'
        assert (call["cache_key"], call["cache_hit"], call["latency_ms"], call["tokens_in"], call["tokens_out"]) == ("k1", False, 12.5, 100, 20)

    def test_failing_calls_are_recorded_and_raised(self, session, tmp_path):
        from deriva.services.llm_log import LlmCallLog

        session._llm_manager.query.side_effect = RuntimeError("provider down")
        log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")
        session.attach_call_log(log)
        query = session._get_llm_query_fn()

        with pytest.raises(RuntimeError):
            query("p", None)
        log.close()

        assert LlmCallLog.read(tmp_path / "llm.jsonl")[0]["error"] == "provider down"

    def test_without_a_log_nothing_is_written(self, session, tmp_path):
        from deriva.services.llm_log import LlmCallLog

        log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")
        session.attach_call_log(log)
        session.detach_call_log()
        query = session._get_llm_query_fn()

        query("p", None)
        log.close()

        assert LlmCallLog.read(tmp_path / "llm.jsonl") == []


class TestPipelineSessionTrace:
    def test_trace_element_hands_the_session_and_calls_to_the_trace_service(self):
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
        calls = [{"call_id": "c1", "prompt": "p"}]

        with patch("deriva.services.trace.trace_element", return_value={"element": {}}) as trace:
            assert session.trace_element("e1", calls) == {"element": {}}

        trace.assert_called_once_with(session, "e1", calls)


class TestPipelineSessionModelConfigs:
    """Model configs live in .env; the session reads and writes them without a database connection."""

    def test_models_round_trip_through_the_env_file_in_the_home_folder(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("# keep me\nLLM_TEMPERATURE=0\n", encoding="utf-8")
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
        session = PipelineSession()

        session.save_model_config("mistral-small", provider="mistral", model="mistral-small-latest", key="sk-new-key-0000wxyz")

        assert [(m["name"], m["key"]) for m in session.list_model_configs()] == [("mistral-small", "sk-...wxyz")]
        session.delete_model_config("mistral-small")
        assert session.list_model_configs() == []
        assert (tmp_path / ".env").read_text(encoding="utf-8").startswith("# keep me\nLLM_TEMPERATURE=0\n")


class TestPipelineSessionConfigEditor:
    @pytest.fixture
    def session(self):
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
        session._engine = MagicMock()
        return session

    def test_saves_pass_params_and_batch_size_and_refuse_bad_params(self, session):
        with patch("deriva.services.config.create_derivation_config_version", return_value={"success": True}) as create:
            session.save_derivation_config("Node", params='{"k": 2}', batch_size=5, input_graph_query="MATCH (n) RETURN n")
            with pytest.raises(ValueError):
                session.save_derivation_config("Node", params="[1, 2]")

        assert create.call_count == 1
        assert (create.call_args.kwargs["params"], create.call_args.kwargs["batch_size"], create.call_args.kwargs["input_graph_query"]) == ('{"k": 2}', 5, "MATCH (n) RETURN n")

        with patch("deriva.services.config.create_extraction_config_version", return_value={"success": True}) as create_extraction:
            session.save_extraction_config("Concept", params='{"a": 1}', batch_size=3)
        assert (create_extraction.call_args.kwargs["params"], create_extraction.call_args.kwargs["batch_size"]) == ('{"a": 1}', 3)

    def test_history_scan_and_dry_run(self, session):
        with patch("deriva.services.config.get_config_history", return_value=[{"version": 2}]) as history:
            assert session.get_config_history("derivation", "Node") == [{"version": 2}]
        history.assert_called_once_with(session._engine, "derivation", "Node")

        with patch("deriva.services.overfit.scan_texts", return_value={"available": True, "findings": []}) as scan:
            assert session.scan_prompt_texts({"instruction": "x"}) == {"available": True, "findings": []}
        scan.assert_called_once_with({"instruction": "x"})

        rows = [{"n": {"_id": i, "_labels": ["Graph", "Directory"], "id": f"dir::r::{i}", "name": f"d{i}"}} for i in range(25)]
        with patch.object(session, "query_graph_read_only", return_value=rows) as query:
            result = session.dry_run_graph_query("MATCH (n:Graph:Directory) RETURN n", limit=20)
        query.assert_called_once_with("MATCH (n:Graph:Directory) RETURN n")
        assert result["count"] == 25
        assert len(result["rows"]) == 20
        assert result["rows"][0] == {"n": {"labels": ["Directory"], "id": "dir::r::0", "name": "d0"}}


class TestPipelineSessionOntology:
    def test_ontology_views_are_built_from_the_session(self):
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)

        with (
            patch("deriva.services.ontology.intermediate_ontology", return_value={"node_types": []}) as inner,
            patch("deriva.services.ontology.output_ontology", return_value={"rules": []}) as outer,
        ):
            assert session.intermediate_ontology() == {"node_types": []}
            assert session.output_ontology() == {"rules": []}

        inner.assert_called_once_with(session)
        outer.assert_called_once_with(session)


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

    def test_get_archimate_stats_counts_real_elements_by_their_element_type(self):
        """The archimate manager returns Element objects, whose type is ``element_type``."""
        from deriva.adapters.archimate import Element

        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
            mock_archimate.return_value.get_elements.return_value = [
                Element(name="A", element_type="Node", identifier="n_a"),
                Element(name="B", element_type="Node", identifier="n_b"),
                Element(name="C", element_type="DataObject", identifier="do_c"),
            ]
            mock_archimate.return_value.get_relationships.return_value = []

            result = session.get_archimate_stats()

        assert result["by_type"] == {"Node": 2, "DataObject": 1}

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

            from deriva.adapters.archimate.models import Element, Relationship

            # Two enabled elements
            elem1 = Element(name="One", element_type="ApplicationComponent", identifier="elem1")
            elem2 = Element(name="Two", element_type="ApplicationComponent", identifier="elem2")

            # Two relationships - one points to a disabled element
            rel1 = Relationship(source="elem1", target="elem2", relationship_type="Serving", identifier="rel1")  # Both enabled
            rel2 = Relationship(source="elem1", target="elem3", relationship_type="Serving", identifier="rel2")  # elem3 is disabled

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


class TestOnlyStep:
    """session.only_step enables a single step for a block and restores the exact prior state."""

    @staticmethod
    def _session_with(step_type: str, states: dict[str, bool]) -> PipelineSession:
        session = PipelineSession()
        key = "node_type" if step_type == "extraction" else "element_type"
        getter = "get_extraction_configs" if step_type == "extraction" else "get_derivation_configs"
        setattr(session, getter, lambda enabled_only=False: [{key: n, "enabled": e} for n, e in states.items()])
        session.enable_step = lambda t, n: states.__setitem__(n, True) or True  # type: ignore[method-assign]
        session.disable_step = lambda t, n: states.__setitem__(n, False) or True  # type: ignore[method-assign]
        return session

    def test_enables_only_target_inside_block_and_restores_after(self):
        states = {"File": True, "BusinessConcept": True, "Technology": True, "Test": False}
        session = self._session_with("extraction", states)
        with session.only_step("extraction", "BusinessConcept"):
            assert states == {"File": False, "BusinessConcept": True, "Technology": False, "Test": False}
        assert states == {"File": True, "BusinessConcept": True, "Technology": True, "Test": False}

    def test_restores_when_block_raises(self):
        states = {"pagerank": True, "ApplicationComponent": True, "Completeness": False}
        session = self._session_with("derivation", states)
        with pytest.raises(RuntimeError), session.only_step("derivation", "ApplicationComponent"):
            raise RuntimeError("boom")
        assert states == {"pagerank": True, "ApplicationComponent": True, "Completeness": False}

    def test_derivation_matches_on_element_type(self):
        states = {"pagerank": True, "Node": False}
        session = self._session_with("derivation", states)
        with session.only_step("derivation", "Node"):
            assert states == {"pagerank": False, "Node": True}

    def test_unknown_step_raises_without_changing_anything(self):
        states = {"File": True, "Technology": True}
        session = self._session_with("extraction", states)
        with pytest.raises(ValueError, match="Unknown extraction step"):
            with session.only_step("extraction", "Typo"):
                pass
        assert states == {"File": True, "Technology": True}

    def test_unknown_step_type_raises_without_changing_anything(self):
        states = {"pagerank": True, "Node": False}
        session = self._session_with("derivation", states)
        with pytest.raises(ValueError, match="step_type"):
            with session.only_step("derivations", "Node"):
                pass
        assert states == {"pagerank": True, "Node": False}


def test_connect_applies_pending_migrations():
    """Opening a session brings an older config database up to the current schema."""
    from unittest.mock import MagicMock, patch

    from deriva.services.session import PipelineSession

    engine = MagicMock()
    with (
        patch("deriva.services.session.get_connection", return_value=engine),
        patch("deriva.services.session.run_migrations") as migrate,
        patch("deriva.services.session.use_database"),
        patch("deriva.services.session.GraphManager"),
        patch("deriva.services.session.ArchimateManager"),
        patch("deriva.services.session.RepoManager"),
    ):
        PipelineSession(auto_connect=True)

    migrate.assert_called_once_with(engine)


class TestRunInputs:
    """A studio run records what it ran on in its folder, in the format of a benchmark session's inputs."""

    def test_a_run_folder_records_what_the_run_ran_on(self, tmp_path):
        from types import SimpleNamespace

        import duckdb

        from deriva.adapters.database.manager import SCRIPTS_DIR
        from deriva.services import config as config_service

        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.GraphManager"),
            patch("deriva.services.session.ArchimateManager"),
            patch("deriva.services.session.RepoManager"),
        ):
            session = PipelineSession(auto_connect=True)
        engine = duckdb.connect(":memory:")
        engine.execute((SCRIPTS_DIR / "schema.sql").read_text(encoding="utf-8"))
        engine.execute("INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('license', 'meta', 'license')")
        engine.execute(
            "INSERT INTO extraction_config (id, node_type, version, sequence, enabled, instruction, example, is_active) VALUES (1, 'BusinessConcept', 20, 1, TRUE, 'i', 'e', TRUE)"
        )
        session._engine = engine
        session._llm_manager = SimpleNamespace(provider_name="mistral", model="devstral", temperature=0.6, max_tokens=4000, api_key="sk-secret")

        path = session.write_run_inputs(tmp_path / "r1", "r1")

        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert (path.name, recorded["run_id"]) == ("inputs.json", "r1")
        assert recorded["config_versions"] == {"extraction": {"BusinessConcept": 20}, "derivation": {}}
        assert recorded["inputs"] == config_service.input_snapshot(engine)
        assert recorded["environment"]["models"] == {"session": {"provider": "mistral", "model": "devstral", "temperature": 0.6, "max_tokens": 4000}}
        assert {"git", "source", "grafeo", "python"} <= set(recorded["environment"])
        assert "sk-secret" not in path.read_text(encoding="utf-8")


class TestPipelineSessionManagers:
    def test_managers_need_a_connection(self):
        with pytest.raises(RuntimeError, match="not connected"):
            PipelineSession().managers()

    def test_managers_return_the_engine_and_graph_managers(self):
        with (
            patch("deriva.services.session.get_connection") as mock_db,
            patch("deriva.services.session.GraphManager") as mock_graph,
            patch("deriva.services.session.ArchimateManager") as mock_archimate,
            patch("deriva.services.session.RepoManager"),
            patch("deriva.services.session.run_migrations"),
        ):
            session = PipelineSession(auto_connect=True)

            assert session.managers() == (mock_db.return_value, mock_graph.return_value, mock_archimate.return_value)


class TestConfinedModelExport:
    """The studio exports the model into <home>/workspace/output only (a request names the file)."""

    def test_a_path_outside_the_output_folder_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
        session = PipelineSession()
        session._ensure_connected = lambda: None  # type: ignore[method-assign]
        session._archimate_manager = MagicMock()

        with pytest.raises(ValueError, match="workspace"):
            session.export_model(output_path="workspace/output/../../evil.xml", confined=True)
        with pytest.raises(ValueError, match="workspace"):
            session.export_model(output_path=str(tmp_path.parent / "evil.xml"), confined=True)

    def test_a_relative_path_is_read_from_the_home_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
        session = PipelineSession()
        session._ensure_connected = lambda: None  # type: ignore[method-assign]
        session._archimate_manager = MagicMock()
        session._archimate_manager.get_elements.return_value = []

        result = session.export_model(output_path="workspace/output/model.xml", confined=True)

        assert result["success"] is False  # no elements; the path was accepted


def test_deleting_the_session_repository_leaves_it_for_the_default_graph():
    session = PipelineSession(repository="deriva")
    session._ensure_connected = lambda: None  # type: ignore[method-assign]
    session._repo_manager = MagicMock()

    with patch("deriva.services.session.use_database") as use:
        assert session.delete_repository("deriva")["success"] is True

    assert session.repository == "default"
    use.assert_called_with("default")


class TestRepositoryData:
    """Each repository's own graph database: counts and clears without moving the session off the repository it reads."""

    @pytest.fixture
    def session(self, tmp_path, monkeypatch):
        from deriva.adapters.grafeo.manager import close_database, use_database

        monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path))
        monkeypatch.setenv("GRAFEO_DB_PATH", "")
        close_database()
        with (
            patch("deriva.services.session.get_connection"),
            patch("deriva.services.session.run_migrations"),
            patch("deriva.services.session.RepoManager") as repos,
        ):
            repos.return_value.list_repositories.return_value = ["alpha", "beta"]
            s = PipelineSession(repository="alpha")
            s.connect()
            self._fill(s, "beta")
            yield s
            s.disconnect()
        close_database()
        use_database("default")

    @staticmethod
    def _fill(session, repository):
        from deriva.adapters.archimate.models import Element, Relationship
        from deriva.adapters.graph.models import DirectoryNode, FileNode

        with session.in_repository(repository):
            session._graph_manager.add_node(DirectoryNode(name="src", path="src", repository_name=repository), node_id="dir::src")
            session._graph_manager.add_node(FileNode(name="a.py", path="src/a.py", file_type="source", repository_name=repository), node_id="file::a")
            session._graph_manager.add_edge("dir::src", "file::a", "CONTAINS")
            session._archimate_manager.add_element(Element(name="App", element_type="ApplicationComponent", identifier="app"), validate=False)
            session._archimate_manager.add_element(Element(name="Api", element_type="ApplicationInterface", identifier="api"), validate=False)
            session._archimate_manager.add_relationship(Relationship(source="app", target="api", relationship_type="Composition"), validate=False)

    def test_data_counts_the_named_repository_and_keeps_the_session_where_it_was(self, session):
        data = session.repository_data("beta")

        assert (data["graph"], data["model"]) == ({"nodes": 2, "edges": 1}, {"elements": 2, "relationships": 1})
        assert data["database_bytes"] > 0
        assert session.repository == "alpha"
        assert session.repository_data("alpha")["graph"] == {"nodes": 0, "edges": 0}

    def test_counting_a_repository_without_a_database_creates_none(self, session, tmp_path):
        """A repository not extracted yet (or a stale record) has nothing to count; opening its database would create one."""
        data = session.repository_data("gamma")

        assert (data["graph"], data["model"], data["database_bytes"]) == ({"nodes": 0, "edges": 0}, {"elements": 0, "relationships": 0}, 0)
        assert not (tmp_path / "gamma.grafeo").exists()

    def test_coverage_reads_the_named_repository_and_keeps_the_session_where_it_was(self, session, tmp_path):
        from types import SimpleNamespace

        checkout = tmp_path / "beta-checkout"
        (checkout / "src").mkdir(parents=True)
        (checkout / "src" / "a.py").write_text("x = 1", encoding="utf-8")
        session._repo_manager.get_repository_info.return_value = SimpleNamespace(name="beta", path=str(checkout))
        with patch("deriva.services.session.extraction.extraction_coverage", return_value={"complete": True}) as coverage:
            report = session.extraction_coverage("beta")

        assert report == {"complete": True}
        assert coverage.call_args.args[2].name == "beta"
        assert session.repository == "alpha"

    def test_coverage_of_a_repository_without_a_database_creates_none(self, session, tmp_path):
        from types import SimpleNamespace

        session._repo_manager.get_repository_info.return_value = SimpleNamespace(name="gamma", path=str(tmp_path / "gamma-checkout"))
        with patch("deriva.services.session.extraction.extraction_coverage", return_value={"complete": False}) as coverage:
            session.extraction_coverage("gamma")

        assert coverage.call_args.args[1] is None
        assert not (tmp_path / "gamma.grafeo").exists()

    def test_clearing_the_model_keeps_the_graph(self, session):
        session.clear_repository_model("beta")

        data = session.repository_data("beta")
        assert (data["graph"]["nodes"], data["model"]["elements"]) == (2, 0)
        assert session.repository == "alpha"

    def test_clearing_the_data_clears_graph_and_model(self, session):
        session.clear_repository_data("beta")

        data = session.repository_data("beta")
        assert (data["graph"], data["model"]) == ({"nodes": 0, "edges": 0}, {"elements": 0, "relationships": 0})

    def test_deleting_with_its_data_removes_the_database_file(self, session, tmp_path):
        assert (tmp_path / "beta.grafeo").exists()

        result = session.delete_repository("beta", with_data=True)

        assert result["success"] and result["data_deleted"] is True
        assert not (tmp_path / "beta.grafeo").exists()
        session._repo_manager.delete_repository.assert_called_once_with("beta", force=False)
        assert session.repository == "alpha"

    def test_deleting_the_repository_the_session_reads_moves_it_to_the_shared_graph_first(self, session, tmp_path):
        session.use_repository("beta")

        result = session.delete_repository("beta", with_data=True)

        assert result["data_deleted"] is True and session.repository == "default"
        assert not (tmp_path / "beta.grafeo").exists()

    def test_deleting_without_data_keeps_the_database(self, session, tmp_path):
        session.delete_repository("beta")

        assert (tmp_path / "beta.grafeo").exists()

    def test_update_pulls_the_clone(self, session):
        from types import SimpleNamespace

        session._repo_manager.update_repository.return_value = SimpleNamespace(to_dict=lambda: {"name": "beta", "last_commit": "abc new"})

        assert session.update_repository("beta") == {"success": True, "repository": {"name": "beta", "last_commit": "abc new"}}


class TestStorage:
    """The session hands the storage service its repositories and the database it reads."""

    def _session(self):
        session = PipelineSession(repository="alpha")
        session._repo_manager = MagicMock()
        session._repo_manager.list_repositories.return_value = ["alpha", "beta"]
        session._connected = True
        session._engine = MagicMock()
        return session

    def test_the_overview_and_graph_delete_know_the_repositories_and_the_open_database(self):
        session = self._session()
        with patch("deriva.services.session.storage") as storage:
            session.storage_overview()
            session.delete_graph("gone")

        storage.overview.assert_called_once_with(repositories={"alpha", "beta"}, active="alpha")
        storage.delete_graph.assert_called_once_with("gone", repositories={"alpha", "beta"}, active="alpha")

    def test_clearing_the_llm_cache_closes_the_session_s_own_cache_first(self):
        session = self._session()
        manager = MagicMock()
        session._llm_manager = manager
        with patch("deriva.services.session.storage") as storage:
            storage.clear_llm_cache.side_effect = lambda: manager.cache.close.assert_called_once() or {"bytes": 9, "files": 1}
            assert session.clear_llm_cache() == {"bytes": 9, "files": 1}

        assert session._llm_manager is None


def test_a_model_config_check_needs_no_connection():
    with patch("deriva.services.session.model_configs.check_model", return_value={"ok": True}) as check:
        assert PipelineSession().check_model_config("mistral-small4") == {"ok": True}

    check.assert_called_once_with("mistral-small4")


def test_a_clone_needs_no_database_connection(tmp_path):
    from types import SimpleNamespace

    info = SimpleNamespace(name="x", path=tmp_path / "x", url="u", branch="main", last_commit="abc", size_mb=1.0)
    with patch("deriva.services.session.RepoManager") as repos, patch("deriva.services.session.get_connection") as connect:
        repos.return_value.clone_repository.return_value = info
        result = PipelineSession(workspace_dir=str(tmp_path)).clone_repository("https://example.org/x.git")

    assert result["success"] and result["name"] == "x"
    connect.assert_not_called()


def test_unregistered_folders_and_register_need_no_database_connection(tmp_path):
    from types import SimpleNamespace

    info = SimpleNamespace(name="orphan", path=tmp_path / "orphan", url="u", branch="main", last_commit="abc", size_mb=1.0)
    with patch("deriva.services.session.RepoManager") as repos, patch("deriva.services.session.get_connection") as connect:
        repos.return_value.unregistered.return_value = ["orphan"]
        repos.return_value.register_repository.return_value = info
        session = PipelineSession(workspace_dir=str(tmp_path))
        names = session.unregistered_repositories()
        result = session.register_repository("orphan")

    assert names == ["orphan"]
    assert result == {"success": True, "name": "orphan", "path": str(tmp_path / "orphan"), "url": "u", "branch": "main", "last_commit": "abc", "size_mb": 1.0}
    connect.assert_not_called()


def test_a_failed_register_answers_the_reason(tmp_path):
    from deriva.adapters.repository import RepositoryError

    with patch("deriva.services.session.RepoManager") as repos:
        repos.return_value.register_repository.side_effect = RepositoryError("notes has no git checkout in the workspace")
        result = PipelineSession(workspace_dir=str(tmp_path)).register_repository("notes")

    assert result == {"success": False, "error": "notes has no git checkout in the workspace"}


def test_a_derivation_without_an_llm_says_why():
    """The manager's reason (which key variable is missing, which .env is read) reaches the run, not only the log."""
    from deriva.adapters.llm import ConfigurationError

    session = PipelineSession()
    session._connected = True
    session._engine = session._graph_manager = session._archimate_manager = MagicMock()
    with patch("deriva.adapters.llm.LLMManager", side_effect=ConfigurationError("The model mini has no API key: set AZURE_OPENAI_API_KEY")):
        result = session.run_derivation()
        updates = list(session.run_derivation_iter())

    assert result["errors"] == ["LLM not configured: The model mini has no API key: set AZURE_OPENAI_API_KEY"]
    assert updates[-1].message == "LLM not configured: The model mini has no API key: set AZURE_OPENAI_API_KEY"


def test_model_quality_reads_the_session_s_model_and_graph():
    session = PipelineSession()
    session._connected = True
    session._engine, session._graph_manager, session._archimate_manager = MagicMock(), MagicMock(), MagicMock()
    with patch("deriva.services.session.quality.model_quality", return_value={"verdict": "ok"}) as quality:
        report = session.model_quality()

    assert report == {"verdict": "ok"}
    quality.assert_called_once_with(session._engine, session._graph_manager, session._archimate_manager)
