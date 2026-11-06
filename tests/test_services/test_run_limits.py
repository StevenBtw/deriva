"""Limits for untrusted repositories: a huge file is not read, and a run stops calling the LLM after its budget."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import duckdb
import pytest

from deriva.services import config
from deriva.services.extraction import _read_documents


@pytest.fixture
def engine():
    db = duckdb.connect(":memory:")
    db.execute("CREATE TABLE system_settings (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP)")
    yield db
    db.close()


class TestSettings:
    def test_defaults(self, engine):
        assert config.get_max_read_bytes(engine) == 50_000_000
        assert config.get_llm_call_budget(engine) == 2000
        assert config.setting_default("max_read_bytes") == "50000000"
        assert config.setting_default("max_llm_calls_per_run") == "2000"

    def test_set_values_apply(self, engine):
        config.set_setting(engine, "max_read_bytes", "1000")
        config.set_setting(engine, "max_llm_calls_per_run", "10")
        assert (config.get_max_read_bytes(engine), config.get_llm_call_budget(engine)) == (1000, 10)

    @pytest.mark.parametrize("value", ["0", "-5", "many", "1.5"])
    def test_a_limit_is_a_positive_whole_number(self, engine, value):
        with pytest.raises(ValueError, match="positive whole number"):
            config.set_setting(engine, "max_llm_calls_per_run", value)

    def test_an_unreadable_stored_value_gives_the_default(self):
        broken = MagicMock()
        broken.execute.return_value.fetchone.return_value = ("lots",)
        assert config.get_max_read_bytes(broken) == 50_000_000


class TestFileSize:
    def test_a_file_over_the_limit_is_not_read(self, tmp_path):
        (tmp_path / "big.md").write_text("x" * 200, encoding="utf-8")
        (tmp_path / "small.md").write_text("small", encoding="utf-8")

        documents, errors = _read_documents(tmp_path, [{"path": "big.md"}, {"path": "small.md"}], "repo", max_bytes=100)

        assert [d["path"] for d in documents] == ["small.md"]
        assert any("big.md" in e and "max_read_bytes" in e for e in errors)


class TestCallBudget:
    def test_a_run_stops_calling_after_its_budget(self):
        from deriva.services.session import LLMBudgetExceeded, PipelineSession

        session = PipelineSession.__new__(PipelineSession)
        session._llm_manager = MagicMock()
        session._llm_error = None
        session._cancel_check = None
        session._engine = MagicMock()
        session._record_call = MagicMock()
        with patch.object(config, "get_llm_call_budget", return_value=2):
            query = session._get_llm_query_fn()
            assert query is not None
            query("a")
            query("b")
            with pytest.raises(LLMBudgetExceeded, match="max_llm_calls_per_run"):
                query("c")
        assert session._llm_manager.query.call_count == 2

    def test_each_run_gets_a_fresh_budget(self):
        from deriva.services.session import PipelineSession

        session = PipelineSession.__new__(PipelineSession)
        session._llm_manager = MagicMock()
        session._llm_error = None
        session._cancel_check = None
        session._engine = MagicMock()
        session._record_call = MagicMock()
        with patch.object(config, "get_llm_call_budget", return_value=1):
            first, second = session._get_llm_query_fn(), session._get_llm_query_fn()
            assert first is not None and second is not None
            first("a")
            second("b")
        assert session._llm_manager.query.call_count == 2


def test_a_failed_model_load_is_logged_once_per_reason(caplog):
    from deriva.services.session import PipelineSession

    session = PipelineSession.__new__(PipelineSession)
    session._llm_manager = None
    session._llm_error = None
    with patch("deriva.adapters.llm.LLMManager", side_effect=RuntimeError("No LLM model is configured")), caplog.at_level("WARNING"):
        session._get_llm_query_fn()
        session._get_llm_query_fn()
    assert caplog.text.count("Failed to initialize LLM manager") == 1


class TestOneBudgetForARun:
    def _session(self, budget):
        from deriva.services.session import PipelineSession

        session = PipelineSession.__new__(PipelineSession)
        session._engine = object()
        session._run_budget = None
        session._cancel_check = None
        session._llm_error = None
        session._llm_no_model = False
        session._llm_manager = MagicMock()
        session._record_call = MagicMock()
        return session

    def test_the_query_functions_of_one_run_share_the_budget(self):
        from deriva.services.session import LLMBudgetExceeded

        session = self._session(3)
        with patch("deriva.services.session.config.get_llm_call_budget", return_value=3), session.one_llm_budget():
            extraction, derivation = session._get_llm_query_fn(), session._get_llm_query_fn()
            for query in (extraction, extraction, derivation):
                query("p")
            with pytest.raises(LLMBudgetExceeded):
                derivation("p")
        assert session._run_budget is None

    def test_threads_cannot_pass_the_limit_together(self):
        from concurrent.futures import ThreadPoolExecutor

        from deriva.services.session import LLMBudgetExceeded, _CallBudget

        budget = _CallBudget(50)

        def take(_):
            try:
                budget.take()
                return 1
            except LLMBudgetExceeded:
                return 0

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(take, range(400))) == 50

    def test_a_broken_model_configuration_fails_the_pipeline_run(self):
        session = self._session(3)
        session._connected = True
        session._graph_manager = session._archimate_manager = object()
        session._llm_manager = None
        session._llm_error = "LLM_X_KEY is not set"
        with patch.object(type(session), "_get_llm_query_fn", return_value=None):
            result = session.run_pipeline(repo_name="r")
        assert result["success"] is False and "LLM_X_KEY" in result["errors"][0]

    def test_no_model_at_all_is_a_structural_run(self):
        session = self._session(3)
        session._connected = True
        session._graph_manager = session._archimate_manager = object()
        session._llm_no_model = True
        finished = {"success": True}
        with patch.object(type(session), "_get_llm_query_fn", return_value=None), patch("deriva.services.session.pipeline.run_full_pipeline", return_value=finished) as run:
            assert session.run_pipeline(repo_name="r")["success"] is True
        assert run.call_args.kwargs["llm_query_fn"] is None


def test_a_model_configured_after_a_start_without_one_clears_the_flag():
    """The studio can add a model after a session started without one: the session then has a model."""
    from deriva.common.exceptions import NoModelConfigured
    from deriva.services.session import PipelineSession

    session = PipelineSession.__new__(PipelineSession)
    session._llm_manager = None
    session._llm_error = None
    session._cancel_check = None
    session._engine = None
    session._record_call = MagicMock()
    with patch("deriva.adapters.llm.LLMManager", side_effect=NoModelConfigured("No LLM model is configured")):
        assert session._get_llm_query_fn() is None
    assert session.llm_no_model is True
    with patch("deriva.adapters.llm.LLMManager", return_value=MagicMock()):
        assert session._get_llm_query_fn() is not None
    assert session.llm_no_model is False and session.llm_error is None
