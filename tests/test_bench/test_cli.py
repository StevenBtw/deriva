"""The benchmark CLI commands (deriva.bench.cli, mounted as deriva-cli benchmark)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from deriva.cli.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _the_mocked_session_is_its_own_benchmark_session(monkeypatch):
    """The commands wrap the PipelineSession in a BenchmarkSession; with a mocked session the mock serves as both."""
    from deriva.bench import cli as bench_cli

    monkeypatch.setattr(bench_cli, "BenchmarkSession", lambda session: session)


class TestBenchmarkCommands:
    """Tests for benchmark commands."""

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_run_success(self, mock_session_class, mock_progress):
        """Should run benchmark successfully."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 120.5
        mock_result.ocel_path = "workspace/benchmarks/bench_123/ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["benchmark", "run", "--repos", "repo1", "--models", "gpt4"])

        assert result.exit_code == 0
        assert "BENCHMARK COMPLETE" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_list(self, mock_session_class):
        """Should list benchmark sessions."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = [
            {
                "session_id": "bench_001",
                "status": "completed",
                "started_at": "2024-01-01T10:00:00",
                "description": "Test run",
            },
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list"])

        assert result.exit_code == 0
        assert "bench_001" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_export(self, mock_session_class):
        """Should write the session bundle and say how many files it holds."""
        mock_session = MagicMock()
        mock_session.export_benchmark.return_value = {"session_id": "bench_001", "files": [{}, {}, {}]}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "export", "bench_001", "-o", "out/bench_001.zip"])

        assert result.exit_code == 0
        mock_session.export_benchmark.assert_called_once_with("bench_001", "out/bench_001.zip")
        assert "3 files" in result.stdout
        assert "out/bench_001.zip" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_export_unknown_session(self, mock_session_class):
        """Should fail with the reason when the session folder does not exist."""
        mock_session = MagicMock()
        mock_session.export_benchmark.side_effect = FileNotFoundError("Benchmark session not found: bench_404")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "export", "bench_404", "-o", "x.zip"])

        assert result.exit_code == 1
        assert "bench_404" in result.output

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_models_empty(self, mock_session_class):
        """Should show message when no models configured."""
        mock_session = MagicMock()
        mock_session.list_benchmark_models.return_value = {}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "models"])

        assert result.exit_code == 0
        assert "No benchmark model" in result.stdout
        # Benchmark models are the LLM_{NAME}_* models of .env
        assert "LLM_{NAME}_PROVIDER" in result.stdout
        assert "LLM_BENCH" not in result.stdout


class TestBenchmarkAnalyzeCommand:
    """Tests for benchmark analyze command."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_invalid_format(self, mock_session_class):
        """Should reject invalid format."""
        result = runner.invoke(app, ["benchmark", "analyze", "session_123", "-f", "xml"])

        assert result.exit_code == 1
        assert "format must be" in result.output

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_session_not_found(self, mock_session_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session.analyze_benchmark.side_effect = ValueError("Session not found")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "nonexistent"])

        assert result.exit_code == 1
        assert "Session not found" in result.output

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_success(self, mock_session_class):
        """Should analyze benchmark successfully."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        # Mock summary with all required attributes
        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = []

        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "ANALYZING BENCHMARK" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_a_single_run_says_consistency_needs_two_runs(self, mock_session_class):
        """One run per repository and model: no 0-0 table, no hotspot, the reason instead."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()
        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = []
        mock_summary.model_quality = []
        mock_summary.localization.hotspots = []
        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "needs at least 2 runs" in result.stdout
        assert "INTRA-MODEL CONSISTENCY" not in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_with_intra_model_data(self, mock_session_class):
        """Should display intra-model consistency data."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        # Mock intra-model data
        mock_intra = MagicMock()
        mock_intra.model = "gpt4"
        mock_intra.repository = "repo1"
        mock_intra.runs = 2
        mock_intra.stable_elements, mock_intra.unstable_elements = ["a1"], {}
        mock_intra.stable_relationships, mock_intra.unstable_relationships = [], {}
        mock_intra.stable_edges = ["e1", "e2"]
        mock_intra.unstable_edges = {"e3": 1}

        mock_summary = MagicMock()
        mock_summary.intra_model = [mock_intra]
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = []

        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INTRA-MODEL CONSISTENCY" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_shows_model_quality(self, mock_session_class):
        """Should display the structural quality of each exported model."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()
        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = []
        mock_summary.model_quality = [
            {
                "repository": "repo1",
                "model": "gpt4",
                "run": 1,
                "elements": 30,
                "relationships": 45,
                "relationships_per_element": 1.5,
                "orphan_share": 0.2,
                "composition_violations": 2,
                "duplicate_pairs": 1,
                "duplicate_elements": 4,
                "chains": {"ApplicationService-ApplicationComponent": (3, 4)},
                "reference": {"precision": 0.4, "recall": 0.6},
            }
        ]
        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "MODEL QUALITY" in result.stdout
        assert "Orphan%" in result.stdout and "Dupl.el" in result.stdout
        assert "repo1" in result.stdout and "1.50" in result.stdout and "20%" in result.stdout
        assert "ApplicationService-ApplicationComponent 3/4" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_shows_the_milp_solve_per_run(self, mock_session_class):
        """The joint_consistency report of each run (the MILP as a safety net) is printed."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()
        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = []
        row = {
            "repository": "repo1",
            "model": "gpt4",
            "run": 2,
            "elements": 3,
            "relationships": 4,
            "relationships_per_element": 1.3,
            "orphan_share": 0.0,
            "composition_violations": 0,
            "duplicate_pairs": 0,
            "duplicate_elements": 0,
            "chains": {},
            "reference": None,
        }
        solve = {
            "status": "optimal",
            "seconds": 0.012,
            "proposals": 4,
            "merge_candidates": 1,
            "rows": {"H1": 2, "H5": 1},
            "cycle_cuts": 1,
            "kept": 3,
            "dropped": 1,
            "merges": 0,
            "redirects": 0,
        }
        mock_summary.model_quality = [{**row, "solve": solve}, {**row, "run": 3, "solve": None}]
        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "MILP SAFETY NET" in result.stdout
        assert "H1 2, H5 1" in result.stdout and "optimal" in result.stdout and "0.012" in result.stdout


class TestBenchmarkDeviationsCommand:
    """Tests for benchmark deviations command."""

    def test_deviations_invalid_sort(self):
        """Should reject invalid sort-by value."""
        result = runner.invoke(app, ["benchmark", "deviations", "session_123", "--sort-by", "invalid"])

        assert result.exit_code == 1
        assert "sort-by must be" in result.output

    @patch("deriva.bench.cli.PipelineSession")
    def test_deviations_session_not_found(self, mock_session_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session.analyze_config_deviations.side_effect = ValueError("Not found")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "deviations", "nonexistent"])

        assert result.exit_code == 1
        assert "Not found" in result.output

    @patch("deriva.bench.config_deviation.generate_recommendations")
    @patch("deriva.bench.cli.PipelineSession")
    def test_deviations_success(self, mock_session_class, mock_recommendations):
        """Should analyze deviations successfully."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        mock_report = MagicMock()
        mock_report.total_runs = 5
        mock_report.total_deviations = 10
        mock_report.overall_consistency = 0.85
        mock_report.config_deviations = []

        mock_analyzer.analyze.return_value = mock_report
        mock_analyzer.export_json.return_value = "deviations.json"
        mock_session.analyze_config_deviations.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_recommendations.return_value = []

        result = runner.invoke(app, ["benchmark", "deviations", "session_123"])

        assert result.exit_code == 0
        assert "Total runs analyzed: 5" in result.stdout


class TestBenchmarkComprehensiveCommand:
    """Tests for benchmark comprehensive-analysis command."""

    def test_comprehensive_invalid_format(self):
        """Should reject invalid format."""
        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "session_1", "-f", "csv"])

        assert result.exit_code == 1
        assert "format must be" in result.output

    @patch("deriva.bench.analysis.BenchmarkAnalyzer")
    @patch("deriva.bench.cli.PipelineSession")
    def test_comprehensive_session_not_found(self, mock_session_class, mock_analyzer_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_analyzer_class.side_effect = ValueError("Session not found")

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "bad_session"])

        assert result.exit_code == 1
        assert "Session not found" in result.output

    @patch("deriva.bench.analysis.BenchmarkAnalyzer")
    @patch("deriva.bench.cli.PipelineSession")
    def test_comprehensive_success(self, mock_session_class, mock_analyzer_class):
        """Should run comprehensive analysis successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_analyzer = MagicMock()
        mock_report = MagicMock()
        mock_report.repositories = ["repo1"]
        mock_report.models = ["gpt4"]
        mock_report.overall_consistency = 0.9
        mock_report.overall_precision = 0.85
        mock_report.overall_recall = 0.88
        mock_report.stability_reports = {}
        mock_report.semantic_reports = {}
        mock_report.cross_repo = None
        mock_report.recommendations = ["Improve consistency"]

        mock_analyzer.generate_report.return_value = mock_report
        mock_analyzer.export_all.return_value = {"json": "out.json", "markdown": "out.md"}
        mock_analyzer_class.return_value = mock_analyzer

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "session_1"])

        assert result.exit_code == 0
        assert "BENCHMARK ANALYSIS" in result.stdout
        assert "Consistency:" in result.stdout


class TestBenchmarkModelsCommand:
    """Tests for benchmark models command."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_models_with_data(self, mock_session_class):
        """Should list available benchmark models."""
        mock_session = MagicMock()

        mock_config = MagicMock()
        mock_config.provider = "openai"
        mock_config.model = "gpt-4"
        mock_config.api_url = "https://api.openai.com/v1/very-long-url-that-should-be-truncated"

        mock_session.list_benchmark_models.return_value = {"gpt4": mock_config}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "models"])

        assert result.exit_code == 0
        assert "AVAILABLE BENCHMARK MODELS" in result.stdout
        assert "gpt4" in result.stdout
        assert "Provider: openai" in result.stdout


class TestBenchmarkRunWithErrors:
    """Tests for benchmark run command error scenarios."""

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_run_with_errors(self, mock_session_class, mock_progress):
        """Should display errors from benchmark run."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 2
        mock_result.runs_failed = 1
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = False
        mock_result.errors = ["Error 1", "Error 2", "Error 3", "Error 4", "Error 5", "Error 6"]
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["benchmark", "run", "--repos", "repo1", "--models", "gpt4"])

        assert result.exit_code == 1
        assert "Errors (6)" in result.stdout
        assert "... and 1 more" in result.stdout


class TestBenchmarkListEmpty:
    """Tests for benchmark list when empty."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_benchmark_list_empty(self, mock_session_class):
        """Should show message when no sessions."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list"])

        assert result.exit_code == 0
        assert "No benchmark sessions found" in result.stdout


class TestBenchmarkRunOptions:
    """Tests for benchmark run command options."""

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_only_extraction_step(self, mock_session_class, mock_progress):
        """Should enable only specified extraction step."""
        mock_session = MagicMock()
        mock_session.get_extraction_configs.return_value = [
            {"node_type": "BusinessConcept"},
            {"node_type": "TypeDefinition"},
        ]
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--only-extraction-step",
                "BusinessConcept",
            ],
        )

        assert result.exit_code == 0
        assert "Enabling only extraction step: BusinessConcept" in result.stdout
        mock_session.enable_step.assert_called_with("extraction", "BusinessConcept")
        mock_session.disable_step.assert_called_with("extraction", "TypeDefinition")

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_only_derivation_step(self, mock_session_class, mock_progress):
        """Should enable only specified derivation step."""
        mock_session = MagicMock()
        mock_session.get_derivation_configs.return_value = [
            {"step_name": "ApplicationComponent"},
            {"step_name": "BusinessProcess"},
        ]
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--only-derivation-step",
                "ApplicationComponent",
            ],
        )

        assert result.exit_code == 0
        assert "Enabling only derivation step: ApplicationComponent" in result.stdout
        mock_session.enable_step.assert_called_with("derivation", "ApplicationComponent")
        mock_session.disable_step.assert_called_with("derivation", "BusinessProcess")

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_stages(self, mock_session_class, mock_progress):
        """Should pass stages option."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--stages",
                "extraction,derivation",
            ],
        )

        assert result.exit_code == 0
        assert "Stages: ['extraction', 'derivation']" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["stages"] == ["extraction", "derivation"]

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_no_cache(self, mock_session_class, mock_progress):
        """Should disable cache when --no-cache specified."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            ["benchmark", "run", "--repos", "repo1", "--models", "gpt4", "--no-cache"],
        )

        assert result.exit_code == 0
        assert "Cache: disabled" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["use_cache"] is False

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_nocache_configs(self, mock_session_class, mock_progress):
        """Should pass nocache-configs option."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--nocache-configs",
                "BusinessConcept,Technology",
            ],
        )

        assert result.exit_code == 0
        assert "No-cache configs: ['BusinessConcept', 'Technology']" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["nocache_configs"] == ["BusinessConcept", "Technology"]

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_per_repo_mode(self, mock_session_class, mock_progress):
        """Should run in per-repo mode."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 6
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 120.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1,repo2",
                "--models",
                "gpt4",
                "--per-repo",
            ],
        )

        assert result.exit_code == 0
        assert "Mode: per-repo" in result.stdout
        assert "Total runs: 6" in result.stdout  # 2 repos * 1 model * 3 runs
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["per_repo"] is True

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_bench_hash(self, mock_session_class, mock_progress):
        """Should enable bench-hash option."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--bench-hash",
            ],
        )

        assert result.exit_code == 0
        assert "Bench hash: enabled" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["bench_hash"] is True

    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_run_with_defer_relationships(self, mock_session_class, mock_progress):
        """Should enable defer-relationships option."""
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.session_id = "bench_123"
        mock_result.runs_completed = 3
        mock_result.runs_failed = 0
        mock_result.duration_seconds = 60.0
        mock_result.ocel_path = "ocel.json"
        mock_result.success = True
        mock_result.errors = []
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(
            app,
            [
                "benchmark",
                "run",
                "--repos",
                "repo1",
                "--models",
                "gpt4",
                "--defer-relationships",
            ],
        )

        assert result.exit_code == 0
        assert "Defer relationships: enabled" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["defer_relationships"] is True

    @pytest.mark.parametrize("flags, deferred", [([], True), (["--no-defer-relationships"], False)])
    @patch("deriva.bench.cli.create_benchmark_progress_reporter")
    @patch("deriva.bench.cli.PipelineSession")
    def test_relationships_are_deferred_by_default(self, mock_session_class, mock_progress, flags, deferred):
        """The CLI follows the service default: elements first, then the relationship pass."""
        mock_session = MagicMock()
        mock_result = MagicMock(session_id="bench_123", runs_completed=1, runs_failed=0, duration_seconds=1.0, ocel_path="ocel.json", success=True, errors=[])
        mock_session.run_benchmark.return_value = mock_result
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["benchmark", "run", "--repos", "repo1", "--models", "gpt4", *flags])

        assert result.exit_code == 0
        assert mock_session.run_benchmark.call_args[1]["defer_relationships"] is deferred

    @pytest.mark.parametrize("flag", [["--no-enrichment-cache"], ["--nocache-enrichment-configs", "ApplicationComponent"]])
    def test_enrichment_cache_flags_are_gone(self, flag):
        """Enrichment values are read once per derivation run, so there is no cache to switch off."""
        result = runner.invoke(app, ["benchmark", "run", "--repos", "repo1", "--models", "model1", *flag])

        assert result.exit_code == 2


class TestBenchmarkListOptions:
    """Tests for benchmark list with limit option."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_list_with_limit(self, mock_session_class):
        """Should pass limit option."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = [
            {
                "session_id": "bench_001",
                "status": "completed",
                "started_at": "2024-01-01",
                "description": "Test",
            }
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list", "-l", "5"])

        assert result.exit_code == 0
        mock_session.list_benchmarks.assert_called_once_with(limit=5)

    @patch("deriva.bench.cli.PipelineSession")
    def test_list_with_description(self, mock_session_class):
        """Should show description when present."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = [
            {
                "session_id": "bench_001",
                "status": "completed",
                "started_at": "2024-01-01",
                "description": "Multi-model test run",
            }
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list"])

        assert result.exit_code == 0
        assert "Description: Multi-model test run" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_list_shows_failed_status(self, mock_session_class):
        """Should display status correctly for failed sessions."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = [
            {
                "session_id": "bench_001",
                "status": "failed",
                "started_at": "2024-01-01",
                "description": "",
            }
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list"])

        assert result.exit_code == 0
        assert "Status: failed" in result.stdout


class TestBenchmarkAnalyzeInterModel:
    """Tests for benchmark analyze with inter-model data."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_with_inter_model_data(self, mock_session_class):
        """Should display inter-model consistency data."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        # Mock inter-model data
        mock_inter = MagicMock()
        mock_inter.repository = "test_repo"
        mock_inter.edges_by_model = {"gpt4": ["e1", "e2"], "claude": ["e1", "e3"]}
        mock_inter.edge_overlap = ["e1"]
        mock_inter.edge_jaccard = 0.33

        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = [mock_inter]
        mock_summary.localization.hotspots = []

        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INTER-MODEL CONSISTENCY" in result.stdout
        assert "test_repo:" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_analyze_with_hotspots(self, mock_session_class):
        """Should display hotspots."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        mock_summary = MagicMock()
        mock_summary.intra_model = []
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = [
            {
                "severity": "high",
                "type": "element",
                "name": "BusinessProcess",
                "consistency": 45.0,
            },
        ]

        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INCONSISTENCY HOTSPOTS" in result.stdout
        assert "[HIGH] element: BusinessProcess" in result.stdout


class TestBenchmarkDeviationsDetails:
    """Tests for benchmark deviations with detailed output."""

    @patch("deriva.bench.config_deviation.generate_recommendations")
    @patch("deriva.bench.cli.PipelineSession")
    def test_deviations_with_recommendations(self, mock_session_class, mock_recommendations):
        """Should display recommendations when available."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        mock_deviation = MagicMock()
        mock_deviation.config_type = "derivation"
        mock_deviation.config_id = "ApplicationComponent"
        mock_deviation.consistency_score = 0.4
        mock_deviation.deviation_count = 5
        mock_deviation.total_objects = 10
        mock_deviation.deviating_objects = ["obj1", "obj2", "obj3", "obj4"]

        mock_report = MagicMock()
        mock_report.total_runs = 5
        mock_report.total_deviations = 5
        mock_report.overall_consistency = 0.6
        mock_report.config_deviations = [mock_deviation]

        mock_analyzer.analyze.return_value = mock_report
        mock_analyzer.export_json.return_value = "deviations.json"
        mock_session.analyze_config_deviations.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_recommendations.return_value = ["Improve instruction clarity for ApplicationComponent"]

        result = runner.invoke(app, ["benchmark", "deviations", "session_123"])

        assert result.exit_code == 0
        assert "[HIGH] derivation: ApplicationComponent" in result.stdout
        assert "Sample: obj1, obj2, obj3" in result.stdout
        assert "RECOMMENDATIONS" in result.stdout
        assert "Improve instruction clarity" in result.stdout

    @patch("deriva.bench.config_deviation.generate_recommendations")
    @patch("deriva.bench.cli.PipelineSession")
    def test_deviations_sorted_by_consistency(self, mock_session_class, mock_recommendations):
        """Should export with different sort order."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        mock_report = MagicMock()
        mock_report.total_runs = 5
        mock_report.total_deviations = 5
        mock_report.overall_consistency = 0.6
        mock_report.config_deviations = []

        mock_analyzer.analyze.return_value = mock_report
        mock_analyzer.export_sorted_json.return_value = "deviations_sorted.json"
        mock_session.analyze_config_deviations.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_recommendations.return_value = []

        result = runner.invoke(
            app,
            ["benchmark", "deviations", "session_123", "--sort-by", "consistency_score"],
        )

        assert result.exit_code == 0
        mock_analyzer.export_sorted_json.assert_called_once()


class TestBenchmarkComprehensiveDetails:
    """Tests for comprehensive analysis with detailed output."""

    @patch("deriva.bench.analysis.BenchmarkAnalyzer")
    @patch("deriva.bench.cli.PipelineSession")
    def test_comprehensive_with_stability_reports(self, mock_session_class, mock_analyzer_class):
        """Should display stability reports."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_analyzer = MagicMock()
        mock_report = MagicMock()
        mock_report.repositories = ["repo1"]
        mock_report.models = ["gpt4"]
        mock_report.overall_consistency = 0.9
        mock_report.overall_precision = 0.85
        mock_report.overall_recall = 0.88

        mock_derivation_stability = MagicMock()
        mock_derivation_stability.overall_consistency = 0.92

        mock_report.stability_reports = {"repo1": {"derivation": mock_derivation_stability}}
        mock_report.semantic_reports = {}
        mock_report.cross_repo = None
        mock_report.recommendations = []

        mock_analyzer.generate_report.return_value = mock_report
        mock_analyzer.export_all.return_value = {"json": "out.json", "markdown": "out.md"}
        mock_analyzer_class.return_value = mock_analyzer

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "session_1"])

        assert result.exit_code == 0
        assert "PER-REPOSITORY STABILITY" in result.stdout
        assert "repo1: 92.0% derivation consistency" in result.stdout

    @patch("deriva.bench.analysis.BenchmarkAnalyzer")
    @patch("deriva.bench.cli.PipelineSession")
    def test_comprehensive_with_semantic_reports(self, mock_session_class, mock_analyzer_class):
        """Should display semantic match summary."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_analyzer = MagicMock()
        mock_report = MagicMock()
        mock_report.repositories = ["repo1"]
        mock_report.models = ["gpt4"]
        mock_report.overall_consistency = 0.9
        mock_report.overall_precision = 0.85
        mock_report.overall_recall = 0.88
        mock_report.stability_reports = {}

        mock_semantic = MagicMock()
        mock_semantic.element_precision = 0.80
        mock_semantic.element_recall = 0.75
        mock_semantic.element_f1 = 0.77

        mock_report.semantic_reports = {"repo1": mock_semantic}
        mock_report.cross_repo = None
        mock_report.recommendations = []

        mock_analyzer.generate_report.return_value = mock_report
        mock_analyzer.export_all.return_value = {"json": "out.json", "markdown": "out.md"}
        mock_analyzer_class.return_value = mock_analyzer

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "session_1"])

        assert result.exit_code == 0
        assert "SEMANTIC MATCH SUMMARY" in result.stdout
        assert "P=80.0%" in result.stdout
        assert "R=75.0%" in result.stdout

    @patch("deriva.bench.analysis.BenchmarkAnalyzer")
    @patch("deriva.bench.cli.PipelineSession")
    def test_comprehensive_with_cross_repo(self, mock_session_class, mock_analyzer_class):
        """Should display cross-repo element types."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_analyzer = MagicMock()
        mock_report = MagicMock()
        mock_report.repositories = ["repo1", "repo2"]
        mock_report.models = ["gpt4"]
        mock_report.overall_consistency = 0.9
        mock_report.overall_precision = 0.85
        mock_report.overall_recall = 0.88
        mock_report.stability_reports = {}
        mock_report.semantic_reports = {}

        mock_cross = MagicMock()
        mock_cross.best_element_types = [
            ("ApplicationComponent", 0.95),
            ("BusinessProcess", 0.90),
        ]
        mock_cross.worst_element_types = [
            ("Technology", 0.45),
            ("DataObject", 0.55),
        ]
        mock_report.cross_repo = mock_cross

        mock_report.recommendations = ["Use more specific naming"]

        mock_analyzer.generate_report.return_value = mock_report
        mock_analyzer.export_all.return_value = {"json": "out.json", "markdown": "out.md"}
        mock_analyzer_class.return_value = mock_analyzer

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "session_1"])

        assert result.exit_code == 0
        assert "BEST ELEMENT TYPES" in result.stdout
        assert "ApplicationComponent: 95.0%" in result.stdout
        assert "WORST ELEMENT TYPES" in result.stdout
        assert "Technology: 45.0%" in result.stdout
        assert "RECOMMENDATIONS" in result.stdout
        assert "Use more specific naming" in result.stdout


class TestBenchmarkStepCommand:
    """``benchmark step`` repeats one step per repository and prints its consistency."""

    @staticmethod
    def _result(errors=None, unscored=None):
        from deriva.bench.step_benchmark import StepBenchmarkResult
        from deriva.modules.analysis import AnswerStability, DecisionStability, compare_step_outputs

        consistency = compare_step_outputs([{("Concept", "a"): {"kind": "x"}, ("Concept", "b"): {}}, {("Concept", "a"): {"kind": "y"}}])
        return StepBenchmarkResult(
            session_id="bench_1",
            step="BusinessConcept",
            repositories={"repo1": consistency},
            answer_stability={"repo1": [AnswerStability(step="BusinessConcept", prompts=4, identical=3)]},
            decision_stability={"repo1": DecisionStability(items=573, stable=549)},
            output_stability={"repo1": DecisionStability(items=573, stable=566)},
            llm_calls={"repo1": [4, 4]},
            errors=errors or [],
            unscored=unscored or [],
        )

    @patch("deriva.bench.cli.PipelineSession")
    def test_properties_that_are_not_scored_are_named(self, mock_session_class):
        session = mock_session_class.return_value.__enter__.return_value
        session.run_step_benchmark.return_value = self._result(unscored=["documentation", "llm_name"])

        result = runner.invoke(app, ["benchmark", "step", "DataObject", "--repos", "repo1", "--model", "m1"])

        assert "not scored in exact: documentation, llm_name" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_runs_the_step_and_prints_its_consistency(self, mock_session_class):
        session = mock_session_class.return_value.__enter__.return_value
        session.run_step_benchmark.return_value = self._result()

        result = runner.invoke(app, ["benchmark", "step", "BusinessConcept", "--repos", "repo1", "--model", "m1", "-n", "2"])

        assert result.exit_code == 0
        session.run_step_benchmark.assert_called_once_with("BusinessConcept", repositories=["repo1"], model="m1", runs=2, verbose=False)
        assert "repo1" in result.stdout and "50.0%" in result.stdout  # presence 1 of 2 objects
        assert "Average" in result.stdout
        assert "kind" in result.stdout  # the property that differs
        assert "3/4" in result.stdout  # answer stability of the step
        assert "549/573" in result.stdout  # decision stability of the step's items
        assert "566/573" in result.stdout  # output stability: labels with the same effect alike
        assert "bench_1" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_errors_exit_with_failure(self, mock_session_class):
        session = mock_session_class.return_value.__enter__.return_value
        session.run_step_benchmark.return_value = self._result(errors=["repo1: run 1 failed"])

        result = runner.invoke(app, ["benchmark", "step", "BusinessConcept", "--repos", "repo1", "--model", "m1"])

        assert result.exit_code == 1
        assert "run 1 failed" in result.stdout

    @pytest.mark.parametrize("command", [["step", "BusinessConcept", "--model", "m1"], ["run", "--models", "m1"]])
    @patch("deriva.bench.cli.PipelineSession")
    def test_a_benchmark_needs_at_least_one_run(self, mock_session_class, command):
        result = runner.invoke(app, ["benchmark", *command, "--repos", "repo1", "-n", "0"])

        assert result.exit_code == 2  # usage error: an empty benchmark would report 100%
        mock_session_class.assert_not_called()


class TestBenchmarkAnalyzeConsistencyTable:
    """benchmark analyze prints the consistency of each repository and model over its runs."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_prints_elements_and_relationships_per_repository_and_model(self, mock_session_class):
        from deriva.bench.benchmarking import IntraModelMetrics

        mock_session = MagicMock()
        mock_analyzer = MagicMock()
        mock_summary = MagicMock()
        mock_summary.intra_model = [
            IntraModelMetrics(
                model="m",
                repository="repo1",
                runs=3,
                element_counts=[2, 2, 3],
                count_variance=0.2,
                name_consistency=200 / 3,
                stable_elements=["a1", "a2"],
                unstable_elements={"a3": 1},
                relationship_consistency=50.0,
                stable_relationships=["r1"],
                unstable_relationships={"r2": 2},
            )
        ]
        mock_summary.inter_model = []
        mock_summary.model_quality = []
        mock_summary.localization.hotspots = []
        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0, result.output
        row = next(line for line in result.stdout.splitlines() if line.strip().startswith("repo1"))
        assert row.split()[:3] == ["repo1", "m", "3"]
        assert "2/3 (66.7%)" in row  # elements in every run
        assert "1/2 (50.0%)" in row  # relationships in every run
        assert "STRUCTURAL EDGE CONSISTENCY" not in result.stdout
        # The runs of a session share one extraction: its edges are not compared here
        assert "Edges are not compared" in result.stdout


class TestBenchmarkOcelCommand:
    """benchmark ocel writes the OCEL 2.0 log and the case log of chosen sessions."""

    @patch("deriva.bench.cli.PipelineSession")
    def test_writes_the_logs_of_the_sessions(self, mock_session_class, tmp_path):
        mock_session = MagicMock()
        mock_session.export_process_logs.return_value = [tmp_path / "ocel.json", tmp_path / "cases.csv", tmp_path / "cases.xes"]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "ocel", "bench_1,bench_2", "-o", str(tmp_path)])

        assert result.exit_code == 0, result.output
        mock_session.export_process_logs.assert_called_once_with(["bench_1", "bench_2"], str(tmp_path))
        assert "2 sessions" in result.stdout
        assert "cases.xes" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_an_unknown_session_fails_with_the_reason(self, mock_session_class, tmp_path):
        mock_session = MagicMock()
        mock_session.export_process_logs.side_effect = FileNotFoundError("Benchmark session not found: bench_404")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "ocel", "bench_404", "-o", str(tmp_path)])

        assert result.exit_code == 1
        assert "bench_404" in result.output


class TestBenchmarkMarkFailed:
    @patch("deriva.bench.cli.PipelineSession")
    def test_marks_the_session_failed(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.mark_benchmark_failed.return_value = 1
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "mark-failed", "bench_1"])

        assert result.exit_code == 0, result.output
        mock_session.mark_benchmark_failed.assert_called_once_with("bench_1")
        assert "bench_1" in result.stdout and "1 unfinished run" in result.stdout

    @patch("deriva.bench.cli.PipelineSession")
    def test_a_finished_session_is_refused_with_the_reason(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.mark_benchmark_failed.side_effect = ValueError("Session bench_1 is completed, not running")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "mark-failed", "bench_1"])

        assert result.exit_code == 1
        assert "completed, not running" in result.output


def test_conventions_writes_a_review_per_repository_and_a_summary(tmp_path, monkeypatch):
    """The command reads the run snapshots of a session and writes the checklist views."""
    import json as _json

    from typer.testing import CliRunner as _Runner

    from deriva.bench import conventions_report
    from deriva.bench.cli import app as bench_app

    models = tmp_path / "benchmarks" / "bench_1" / "models"
    models.mkdir(parents=True)
    snapshot = {"elements": [{"identifier": "ac_shop", "type": "ApplicationComponent", "name": "Shop", "source": "dir::r::shop"}], "relationships": [], "disabled": []}
    for n in (1, 2):
        (models / f"shop_m_run{n}.json").write_text(_json.dumps(snapshot), encoding="utf-8")
    (models / "other-repo_m_run1.json").write_text(_json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(conventions_report, "workspace", lambda: tmp_path)

    result = _Runner().invoke(bench_app, ["conventions", "bench_1", "-o", str(tmp_path / "out")])

    assert result.exit_code == 0, result.output
    review = (tmp_path / "out" / "shop_m.md").read_text(encoding="utf-8")
    assert "| check | run1 | run2 | target |" in review and "| unconnected elements | fail 1 | fail 1 | 0 |" in review
    assert (tmp_path / "out" / "other-repo_m.md").is_file()
    summary = (tmp_path / "out" / "summary.md").read_text(encoding="utf-8")
    assert "| shop |" in summary and "| other-repo |" in summary


def test_conventions_with_a_run_no_snapshot_has_exits_1(tmp_path, monkeypatch):
    """A --run that matches no snapshot is an error, not an empty report."""
    import json as _json

    from typer.testing import CliRunner as _Runner

    from deriva.bench import conventions_report
    from deriva.bench.cli import app as bench_app

    models = tmp_path / "benchmarks" / "bench_1" / "models"
    models.mkdir(parents=True)
    (models / "shop_m_run1.json").write_text(_json.dumps({"elements": [], "relationships": [], "disabled": []}), encoding="utf-8")
    monkeypatch.setattr(conventions_report, "workspace", lambda: tmp_path)

    out = tmp_path / "out"
    out.mkdir()
    (out / "summary.md").write_text("an earlier report", encoding="utf-8")

    result = _Runner().invoke(bench_app, ["conventions", "bench_1", "-o", str(out), "--run", "7"])

    assert result.exit_code == 1 and "no run snapshots" in result.output
    # Nothing is written: an earlier report in the folder stays as it was
    assert (out / "summary.md").read_text(encoding="utf-8") == "an earlier report" and not (out / "conventions.json").exists()


def test_gate_compares_a_candidate_with_a_baseline_and_writes_markdown_and_json(tmp_path):
    """Sessions by id under --benchmarks; the verdict on the console, gate.md and gate.json in the output folder."""
    import json as _json

    from typer.testing import CliRunner as _Runner

    from deriva.bench.cli import app as bench_app

    benchmarks, goldens = tmp_path / "benchmarks", tmp_path / "goldens"
    goldens.mkdir()
    reference = {"repository": "shop", "elements": [{"key": "a", "type": "ApplicationComponent", "name": "Core"}, {"key": "b", "type": "ApplicationComponent", "name": "Web"}]}
    (goldens / "shop.json").write_text(_json.dumps(reference), encoding="utf-8")
    for session, names in (("bench_base", ["Core"]), ("bench_new", ["Core", "Web"])):
        models = benchmarks / session / "models"
        models.mkdir(parents=True)
        (benchmarks / session / "session_metadata.json").write_text(_json.dumps({"config": {"repositories": ["shop"], "models": ["m"]}}), encoding="utf-8")
        snapshot = {"elements": [{"identifier": n, "type": "ApplicationComponent", "name": n, "source": n} for n in names], "relationships": []}
        for n in (1, 2):
            (models / f"shop_m_run{n}.json").write_text(_json.dumps(snapshot), encoding="utf-8")
    args = ["gate", "--baseline", "bench_base", "--candidate", "bench_new", "--benchmarks", str(benchmarks), "--goldens", str(goldens)]

    result = _Runner().invoke(bench_app, [*args, "--reference", str(tmp_path / "none"), "-o", str(tmp_path / "out")])

    assert result.exit_code == 0, result.output
    assert "**PASS**: 1/1 measured repositories better" in result.output
    payload = _json.loads((tmp_path / "out" / "gate.json").read_text(encoding="utf-8"))
    assert payload["verdict"]["verdict"] == "PASS" and payload["baseline"]["shop"]["recall"] == 0.5
    assert "| shop | reference | 50.0% | 100.0% |" in (tmp_path / "out" / "gate.md").read_text(encoding="utf-8")

    # The baseline alone: its table, no verdict
    alone = _Runner().invoke(bench_app, ["gate", "--baseline", "bench_base", "--benchmarks", str(benchmarks), "--goldens", str(goldens), "-o", str(tmp_path / "alone")])
    assert alone.exit_code == 0, alone.output
    assert "| shop | reference | 2 | 50.0% | 100.0% |" in alone.output and "Verdict" not in alone.output
