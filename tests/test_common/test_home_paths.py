"""Every default location resolves through the home folder, never the current folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from deriva.common import paths


@pytest.fixture
def home(monkeypatch, tmp_path):
    """DERIVA_HOME in a temporary folder, the process in another one."""
    root = tmp_path / "home"
    monkeypatch.setenv("DERIVA_HOME", str(root))
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    return root.resolve()


def test_the_config_database_lives_where_paths_says():
    from deriva.adapters.database import db_tool, manager

    assert manager.DB_PATH == paths.config_db()
    assert db_tool.DB_PATH == paths.config_db()


def test_a_fresh_home_gets_its_database_folder(tmp_path):
    from deriva.adapters.database import manager

    target = tmp_path / "new-home" / "sql.db"
    manager.ensure_database(target)

    assert target.is_file()


def test_model_configs_read_and_write_the_home_env_file(home):
    from deriva.services import model_configs

    assert model_configs.default_env_path() == home / ".env"


def test_run_logs_go_to_the_home_workspace(home):
    from deriva.common.logging import RunLogger, read_run_logs

    logger = RunLogger(7)
    assert logger.run_dir == home / "workspace" / "logs" / "run_7"

    run_dir = home / "workspace" / "logs" / "run_9"
    run_dir.mkdir(parents=True)
    (run_dir / "log_20261009.jsonl").write_text('{"level": 20, "message": "x"}\n', encoding="utf-8")
    assert len(read_run_logs(9)) == 1


def test_disk_caches_resolve_relative_folders_against_home(home):
    from deriva.common.cache_utils import BaseDiskCache

    class Probe(BaseDiskCache):
        pass

    cache = Probe("workspace/cache/probe")
    try:
        assert cache.cache_dir == home / "workspace" / "cache" / "probe"
    finally:
        cache._cache.close()


def test_the_llm_cache_folder(home):
    from deriva.adapters.llm.manager import _cache_path

    assert _cache_path(None) == home / "workspace" / "cache" / "llm"
    assert _cache_path("workspace/cache/other") == home / "workspace" / "cache" / "other"


def test_repositories(home):
    from deriva.adapters.repository.manager import RepoManager

    assert RepoManager().workspace_dir == home / "workspace" / "repositories"


def test_graph_databases_from_a_relative_env_value(home, monkeypatch):
    from deriva.adapters.grafeo.manager import database_file

    monkeypatch.setenv("GRAFEO_DB_DIR", "workspace/graphs")
    assert Path(database_file("repo")) == home / "workspace" / "graphs" / "repo.grafeo"


def test_a_fresh_home_keeps_its_graphs(home, monkeypatch):
    """Without a setting the graphs persist in the home folder, so `run` and a later `export` see the same graph."""
    from deriva.adapters.grafeo.manager import database_file

    monkeypatch.delenv("GRAFEO_DB_DIR", raising=False)
    assert Path(database_file("repo")) == home / "workspace" / "graphs" / "repo.grafeo"


def test_an_empty_graph_folder_means_in_memory(home, monkeypatch):
    from deriva.adapters.grafeo.manager import database_file

    monkeypatch.setenv("GRAFEO_DB_DIR", "")
    assert database_file("repo") is None


def test_nlp_models(home, monkeypatch):
    from deriva.adapters.nlp.manager import NlpTool

    monkeypatch.delenv("DERIVA_NLP_MODELS_DIR", raising=False)
    assert NlpTool().models_dir == home / "workspace" / "cache" / "nlp"


def test_session_repositories_folder(home, monkeypatch):
    from deriva.services.session import PipelineSession

    monkeypatch.delenv("REPOSITORY_WORKSPACE_DIR", raising=False)
    assert PipelineSession().workspace_dir == str(home / "workspace" / "repositories")


def test_import_time_folders_sit_in_the_workspace():
    from deriva.adapters.graph import cache
    from deriva.services import about, overfit
    from deriva.studio.runs import RUNS_DIR

    assert Path(cache.GRAPH_CACHE_DIR).is_absolute()
    assert overfit.SCANNER == paths.workspace() / "scripts" / "check_prompt_overfit.py"
    assert RUNS_DIR == paths.workspace() / "runs"
    assert about.home() == paths.home()
    assert about.workspace() == paths.workspace()


def test_reference_models_are_found_in_the_home_folder(tmp_path, monkeypatch):
    from deriva.bench import analysis

    monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
    assert analysis.known_reference_models() == {}
    folder = tmp_path / "workspace" / "reference"
    folder.mkdir(parents=True)
    (folder / "widgets.archimate").write_text("<model/>", encoding="utf-8")

    assert analysis.known_reference_models() == {"widgets": str(folder / "widgets.archimate")}


def test_the_session_exports_to_the_workspace_by_default():
    from unittest.mock import MagicMock, patch

    from deriva.services.session import PipelineSession

    session = PipelineSession()
    session._connected = True
    session._archimate_manager = MagicMock()
    session._archimate_manager.get_elements.return_value = [MagicMock(identifier="e1")]
    session._archimate_manager.get_relationships.return_value = []
    with patch("deriva.services.session.ArchiMateXMLExporter") as exporter:
        result = session.export_model()

    expected = str(paths.workspace() / "output" / "model.xml")
    assert exporter.return_value.export.call_args.kwargs["output_path"] == expected
    assert result["output_path"] == expected
