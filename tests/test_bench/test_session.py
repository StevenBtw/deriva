"""BenchmarkSession: the benchmark operations on a connected PipelineSession."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from deriva.bench.session import BenchmarkSession
from deriva.services.session import PipelineSession


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
        with patch("deriva.bench.benchmarking.BenchmarkConfig") as mock_config, patch("deriva.bench.benchmarking.BenchmarkOrchestrator") as mock_orch:
            mock_result = MagicMock()
            mock_result.session_id = "bench_123"
            mock_orch.return_value.run.return_value = mock_result

            result = BenchmarkSession(connected_session).run_benchmark(
                repositories=["repo1"],
                models=["model1"],
                runs=2,
                description="Test benchmark",
            )

            mock_config.assert_called_once()
            assert result.session_id == "bench_123"

    def test_run_benchmark_returns_to_the_session_database(self, connected_session):
        """The benchmark switches to each repository's database; the session gets its own back, also after an error."""
        with (
            patch("deriva.bench.benchmarking.BenchmarkConfig"),
            patch("deriva.bench.benchmarking.BenchmarkOrchestrator") as orchestrator,
            patch("deriva.bench.session.use_database") as use_database,
        ):
            orchestrator.return_value.run.side_effect = RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                BenchmarkSession(connected_session).run_benchmark(repositories=["repo1"], models=["model1"])

        use_database.assert_called_once_with(connected_session.repository)

    def test_run_benchmark_with_all_options(self, connected_session):
        """Should pass all options to benchmark config."""
        with patch("deriva.bench.benchmarking.BenchmarkConfig") as mock_config, patch("deriva.bench.benchmarking.BenchmarkOrchestrator") as mock_orch:
            mock_result = MagicMock()
            mock_orch.return_value.run.return_value = mock_result

            BenchmarkSession(connected_session).run_benchmark(
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
            )

            config_call = mock_config.call_args
            assert config_call.kwargs["repositories"] == ["repo1", "repo2"]
            assert config_call.kwargs["models"] == ["model1", "model2"]
            assert config_call.kwargs["runs_per_combination"] == 5
            assert config_call.kwargs["use_cache"] is False

    def test_run_step_benchmark(self, connected_session):
        """One step, repeated per repository with one model."""
        with patch("deriva.bench.step_benchmark.StepBenchmark") as step_benchmark:
            step_benchmark.return_value.run_step.return_value = "result"

            result = BenchmarkSession(connected_session).run_step_benchmark("BusinessConcept", repositories=["repo1", "repo2"], model="model1", runs=3, verbose=True)

        config = step_benchmark.call_args.kwargs["config"]
        assert (config.repositories, config.models, config.runs_per_combination) == (["repo1", "repo2"], ["model1"], 3)
        step_benchmark.return_value.run_step.assert_called_once_with("BusinessConcept", verbose=True)
        assert result == "result"

    def test_run_step_benchmark_returns_to_the_session_database(self, connected_session):
        """The benchmark works in its own database; the session gets its repository's back, also after an error."""
        with patch("deriva.bench.step_benchmark.StepBenchmark") as step_benchmark, patch("deriva.bench.session.use_database") as use_database:
            step_benchmark.return_value.run_step.side_effect = RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                BenchmarkSession(connected_session).run_step_benchmark("BusinessConcept", repositories=["repo1"], model="model1")

        use_database.assert_called_once_with(connected_session.repository)

    def test_analyze_benchmark(self, connected_session):
        """Should create and return BenchmarkAnalyzer."""
        with patch("deriva.bench.session.benchmarking") as mock_bench:
            mock_analyzer = MagicMock()
            mock_bench.BenchmarkAnalyzer.return_value = mock_analyzer

            result = BenchmarkSession(connected_session).analyze_benchmark("bench_123")

            mock_bench.BenchmarkAnalyzer.assert_called_once_with("bench_123", connected_session._engine)
            assert result is mock_analyzer

    def test_analyze_config_deviations(self, connected_session):
        """Should create and return ConfigDeviationAnalyzer."""
        with patch("deriva.bench.config_deviation.ConfigDeviationAnalyzer") as mock_analyzer_cls:
            mock_analyzer = MagicMock()
            mock_analyzer_cls.return_value = mock_analyzer

            result = BenchmarkSession(connected_session).analyze_config_deviations("bench_123")

            mock_analyzer_cls.assert_called_once_with("bench_123", connected_session._engine)
            assert result is mock_analyzer

    def test_list_benchmarks(self, connected_session):
        """Should list benchmark sessions."""
        with patch("deriva.bench.benchmarking.list_benchmark_sessions") as mock_list:
            mock_list.return_value = [
                {"session_id": "bench_1", "description": "Test 1"},
                {"session_id": "bench_2", "description": "Test 2"},
            ]

            result = BenchmarkSession(connected_session).list_benchmarks(limit=5)

            mock_list.assert_called_once_with(connected_session._engine, 5, offset=0, search=None, repository=None, model=None, status=None)
            assert len(result) == 2

    def test_listed_sessions_carry_the_size_of_their_folder(self, connected_session, tmp_path):
        (tmp_path / "bench_1").mkdir()
        (tmp_path / "bench_1" / "events.jsonl").write_bytes(b"e" * 12)
        with patch("deriva.bench.benchmarking.list_benchmark_sessions", return_value=[{"session_id": "bench_1"}, {"session_id": "bench_2"}]) as mock_list:
            rows = BenchmarkSession(connected_session).list_benchmarks(limit=20, offset=20, search="v35", benchmarks_dir=tmp_path)

        assert [r["bytes"] for r in rows] == [12, 0]
        assert mock_list.call_args.kwargs == {"offset": 20, "search": "v35", "repository": None, "model": None, "status": None}

    def test_deleting_and_pruning_sessions_use_the_benchmarks_folder(self, connected_session, tmp_path):
        with (
            patch("deriva.bench.benchmarking.delete_benchmark_session", return_value={"session_id": "bench_1", "runs": 2, "bytes": 9}) as delete,
            patch("deriva.bench.benchmarking.prune_benchmark_sessions", return_value=["bench_0"]) as prune,
        ):
            session = BenchmarkSession(connected_session)
            assert session.delete_benchmark("bench_1", benchmarks_dir=tmp_path)["runs"] == 2
            assert session.prune_benchmarks(keep=5, benchmarks_dir=tmp_path) == ["bench_0"]

        delete.assert_called_once_with(connected_session._engine, "bench_1", tmp_path)
        prune.assert_called_once_with(connected_session._engine, tmp_path, keep=5, failed=False)

    def test_list_benchmarks_raises_when_not_connected(self):
        """Should raise RuntimeError when not connected."""
        session = PipelineSession()

        with pytest.raises(RuntimeError, match="not connected"):
            BenchmarkSession(session).list_benchmarks()


class TestPipelineSessionExportBenchmark:
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
        session._engine.execute.return_value.fetchone.return_value = (
            json.dumps({"models": ["m"]}),
            json.dumps({"extraction": {"Repository": 2}, "derivation": {"Node": 7}}),
        )
        return BenchmarkSession(session)

    def test_bundle_has_config_texts_at_the_session_versions_and_no_keys(self, session, tmp_path):
        import zipfile

        from deriva.adapters.llm.models import BenchmarkModelConfig
        from deriva.services.config import DerivationConfig, ExtractionConfig
        from deriva.services.export_bundle import verify_bundle

        (tmp_path / "bench_1").mkdir()
        (tmp_path / "bench_1" / "session_metadata.json").write_text("{}", encoding="utf-8")
        extraction = [ExtractionConfig("Repository", 1, True, None, "Describe the repository", None)]
        derivation = [DerivationConfig("Node", "generate", 3, True, True, "MATCH (n) RETURN n", None, "Choose the nodes", None, "{}")]
        model = BenchmarkModelConfig(name="m", provider="azure", model="gpt", api_key="sk-secret")

        with (
            patch("deriva.services.config.get_extraction_configs_by_version", return_value=extraction) as by_version,
            patch("deriva.services.config.get_derivation_configs_by_version", return_value=derivation),
            patch.object(session.session, "list_benchmark_models", return_value={"m": model, "other": model}),
        ):
            manifest = session.export_benchmark("bench_1", tmp_path / "out.zip", benchmarks_dir=tmp_path)

        by_version.assert_called_once_with(session._engine, {"Repository": 2})
        with zipfile.ZipFile(tmp_path / "out.zip") as bundle:
            snapshot = json.loads(bundle.read("config_snapshot.json"))
            environment = bundle.read("environment.json")
        assert (snapshot["extraction"][0]["node_type"], snapshot["extraction"][0]["version"], snapshot["extraction"][0]["instruction"]) == (
            "Repository",
            2,
            "Describe the repository",
        )
        assert (snapshot["derivation"][0]["step_name"], snapshot["derivation"][0]["version"]) == ("Node", 7)
        assert list(json.loads(environment)["models"]) == ["m"]
        assert b"sk-secret" not in environment
        assert manifest["session_id"] == "bench_1"
        assert verify_bundle(tmp_path / "out.zip") == []

    def test_session_ids_cannot_leave_the_benchmarks_folder(self, session, tmp_path):
        with pytest.raises(ValueError, match=r"Not a benchmark session id: \.\./"):
            session.export_benchmark("../outside", tmp_path / "out.zip", benchmarks_dir=tmp_path / "benchmarks")


class TestPipelineSessionBenchmarkViews:
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
        session._engine.execute.return_value.fetchone.return_value = (json.dumps({"models": ["azure-gpt4"]}),)
        return BenchmarkSession(session)

    def test_views_use_the_model_names_of_the_sessions(self, session, tmp_path):
        with (
            patch("deriva.bench.benchmark_views.results", return_value=[{"repository": "r"}]) as results,
            patch("deriva.bench.benchmark_views.flips", return_value=[]) as flips,
            patch("deriva.bench.benchmark_views.inspector", return_value={}) as inspector,
        ):
            assert session.benchmark_results(["s_a", "s_b"], benchmarks_dir=tmp_path) == [{"repository": "r"}]
            session.benchmark_flips(["s_a"], "r", benchmarks_dir=tmp_path)
            session.benchmark_inspector(["s_a"], "r", benchmarks_dir=tmp_path)
        with patch("deriva.bench.benchmark_views.element_trace", return_value=[]) as trace:
            session.benchmark_trace(["s_a"], "r", "Node", "tech::r::queue", benchmarks_dir=tmp_path)

        trace.assert_called_once_with(tmp_path, ["s_a"], ["azure-gpt4"], "r", "Node", "tech::r::queue", None)  # no model: every model's runs
        results.assert_called_once_with(tmp_path, ["s_a", "s_b"], ["azure-gpt4"])
        flips.assert_called_once_with(tmp_path, ["s_a"], ["azure-gpt4"], "r")
        inspector.assert_called_once_with(tmp_path, ["s_a"], ["azure-gpt4"], "r", None)

    def test_steps_report_answer_stability_per_repository(self, session):
        from deriva.modules.analysis.types import AnswerStability

        with patch("deriva.bench.analysis.BenchmarkAnalyzer") as analyzer:
            analyzer.return_value.analyze_answer_stability.return_value = {"r": [AnswerStability(step="Node", prompts=4, identical=3)]}
            steps = session.benchmark_steps(["s_a"])

        analyzer.assert_called_once_with(["s_a"], session._engine)
        assert steps == {"r": [{"step": "Node", "prompts": 4, "identical": 3, "score": 0.75}]}

    def test_steps_come_in_pipeline_order(self, session):
        """Where variance starts is read top down: extraction steps by sequence, then derivation by phase and sequence."""
        from types import SimpleNamespace

        from deriva.modules.analysis.types import AnswerStability

        names = ("ApplicationComponent", "BusinessConcept", "ApplicationComponent.naming", "Unknown", "DirectoryClassification", "Node", "pagerank")
        extraction = [SimpleNamespace(node_type="DirectoryClassification", sequence=11), SimpleNamespace(node_type="BusinessConcept", sequence=12)]
        derivation = [
            SimpleNamespace(step_name="Node", phase="generate", sequence=3),
            SimpleNamespace(step_name="ApplicationComponent", phase="generate", sequence=1),
            SimpleNamespace(step_name="pagerank", phase="prep", sequence=9),
        ]
        with (
            patch("deriva.bench.analysis.BenchmarkAnalyzer") as analyzer,
            patch("deriva.services.config.get_extraction_configs", return_value=extraction),
            patch("deriva.services.config.get_derivation_configs", return_value=derivation),
        ):
            analyzer.return_value.analyze_answer_stability.return_value = {"r": [AnswerStability(step=name, prompts=1, identical=1) for name in names]}
            steps = session.benchmark_steps(["s_a"])

        assert [s["step"] for s in steps["r"]] == [
            "DirectoryClassification",
            "BusinessConcept",
            "pagerank",
            "ApplicationComponent",
            "ApplicationComponent.naming",
            "Node",
            "Unknown",
        ]

    def test_session_ids_are_checked(self, session, tmp_path):
        with pytest.raises(ValueError, match=r"Not a benchmark session id: \.\./"):
            session.benchmark_results(["s_a", "../x"], benchmarks_dir=tmp_path)


def test_process_logs_refuse_ids_that_leave_the_benchmarks_folder(tmp_path):
    from unittest.mock import MagicMock

    from deriva.bench.session import BenchmarkSession

    with pytest.raises(ValueError, match=r"Not a benchmark session id: \.\./"):
        BenchmarkSession(MagicMock()).export_process_logs(["s1", "../outside"], tmp_path / "out", benchmarks_dir=tmp_path)
