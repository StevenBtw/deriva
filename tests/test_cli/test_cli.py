"""Tests for cli.cli module (typer-based)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from deriva.cli.cli import app, main
from deriva.cli.commands.benchmark import _get_run_stats_from_ocel
from deriva.cli.commands.run import (
    _print_derivation_result,
    _print_extraction_result,
    _print_pipeline_result,
)
from deriva.cli.commands.run import (
    app as run_app,
)

runner = CliRunner()


class TestCLIHelp:
    """Tests for CLI help commands."""

    def test_main_help(self):
        """Should show main help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Deriva CLI" in result.stdout

    def test_run_help(self):
        """Should show run command help."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "Pipeline stage" in result.stdout

    def test_config_help(self):
        """Should show config command help."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "list" in result.stdout
        assert "enable" in result.stdout

    def test_repo_help(self):
        """Should show repo command help."""
        result = runner.invoke(app, ["repo", "--help"])
        assert result.exit_code == 0
        assert "clone" in result.stdout
        assert "list" in result.stdout

    def test_benchmark_help(self):
        """Should show benchmark command help."""
        result = runner.invoke(app, ["benchmark", "--help"])
        assert result.exit_code == 0
        assert "run" in result.stdout
        assert "analyze" in result.stdout


class TestPrintExtractionResult:
    """Tests for _print_extraction_result helper."""

    def test_prints_stats(self, capsys):
        """Should print extraction statistics."""
        result = {
            "stats": {
                "repos_processed": 2,
                "nodes_created": 100,
                "edges_created": 50,
                "steps_completed": 5,
                "steps_skipped": 1,
            }
        }
        _print_extraction_result(result)
        output = capsys.readouterr().out

        assert "EXTRACTION RESULTS" in output
        assert "Repos processed:  2" in output
        assert "Nodes created:    100" in output

    def test_prints_errors(self, capsys):
        """Should print errors when present."""
        result = {
            "stats": {},
            "errors": ["Error 1", "Error 2"],
        }
        _print_extraction_result(result)
        output = capsys.readouterr().out

        assert "Errors (2)" in output
        assert "Error 1" in output

    def test_prints_warnings(self, capsys):
        """Should print warnings when present."""
        result = {
            "stats": {},
            "warnings": ["Warning 1", "Warning 2", "Warning 3"],
        }
        _print_extraction_result(result)
        output = capsys.readouterr().out

        assert "Warnings (3)" in output
        assert "Warning 1" in output

    def test_truncates_many_warnings(self, capsys):
        """Should truncate when more than 5 warnings."""
        result = {
            "stats": {},
            "warnings": [f"Warning {i}" for i in range(10)],
        }
        _print_extraction_result(result)
        output = capsys.readouterr().out

        assert "... and 5 more" in output

    def test_truncates_many_errors(self, capsys):
        """Should truncate when more than 5 errors."""
        result = {
            "stats": {},
            "errors": [f"Error {i}" for i in range(10)],
        }
        _print_extraction_result(result)
        output = capsys.readouterr().out

        assert "... and 5 more" in output


class TestPrintDerivationResult:
    """Tests for _print_derivation_result helper."""

    def test_prints_stats(self, capsys):
        """Should print derivation statistics."""
        result = {
            "stats": {
                "elements_created": 10,
                "relationships_created": 20,
                "elements_validated": 30,
                "issues_found": 2,
                "steps_completed": 5,
            }
        }
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "DERIVATION RESULTS" in output
        assert "Elements created:      10" in output
        assert "Relationships created: 20" in output

    def test_prints_issues(self, capsys):
        """Should print issues when present."""
        result = {
            "stats": {},
            "issues": [
                {"severity": "warning", "message": "Missing relationship"},
            ],
        }
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "Issues (1)" in output
        assert "[WARNING]" in output

    def test_prints_errors(self, capsys):
        """Should print errors when present."""
        result = {
            "stats": {},
            "errors": ["Error 1", "Error 2"],
        }
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "Errors (2)" in output

    def test_truncates_many_issues(self, capsys):
        """Should truncate when more than 10 issues."""
        result = {
            "stats": {},
            "issues": [{"severity": "warning", "message": f"Issue {i}"} for i in range(15)],
        }
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "... and 5 more" in output


class TestPrintPipelineResult:
    """Tests for _print_pipeline_result helper."""

    def test_prints_pipeline_summary(self, capsys):
        """Should print pipeline summary."""
        result = {
            "results": {
                "extraction": {"stats": {"nodes_created": 50}},
                "derivation": {"stats": {"elements_created": 10, "issues_found": 1}},
            }
        }
        _print_pipeline_result(result)
        output = capsys.readouterr().out

        assert "PIPELINE COMPLETE" in output
        assert "Extraction:" in output
        assert "Nodes created: 50" in output
        assert "Derivation:" in output
        assert "Elements created: 10" in output

    def test_prints_classification_results(self, capsys):
        """Should print classification results when present."""
        result = {
            "results": {
                "classification": {"stats": {"files_classified": 100, "files_undefined": 5}},
            }
        }
        _print_pipeline_result(result)
        output = capsys.readouterr().out

        assert "Classification:" in output
        assert "Files classified: 100" in output

    def test_prints_total_errors(self, capsys):
        """Should print total errors when present."""
        result = {
            "results": {},
            "errors": ["err1", "err2", "err3"],
        }
        _print_pipeline_result(result)
        output = capsys.readouterr().out

        assert "Total errors: 3" in output


class TestMain:
    """Tests for main entry point."""

    def test_main_returns_zero_on_success(self):
        """Should return 0 on success."""
        with patch("deriva.cli.cli.app") as mock_app:
            mock_app.return_value = None
            result = main()
        assert result == 0

    def test_main_returns_exit_code(self):
        """Should return exit code on SystemExit."""
        with patch("deriva.cli.cli.app") as mock_app:
            mock_app.side_effect = SystemExit(1)
            result = main()
        assert result == 1


class TestConfigListCommand:
    """Tests for config list command."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_lists_extraction_configs(self, mock_session_class):
        """Should list extraction configurations."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = [
            {"name": "BusinessConcept", "enabled": True, "sequence": 1},
            {"name": "TypeDefinition", "enabled": False, "sequence": 2},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "list", "extraction"])

        assert result.exit_code == 0
        assert "EXTRACTION CONFIGURATIONS" in result.stdout
        assert "BusinessConcept" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_shows_message_when_no_configs(self, mock_session_class):
        """Should show message when no configurations found."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "list", "derivation"])

        assert result.exit_code == 0
        assert "No derivation configurations found" in result.stdout

    def test_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "list", "invalid"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestConfigEnableDisableCommand:
    """Tests for config enable and disable commands."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_enable_step_success(self, mock_session_class):
        """Should enable step successfully."""
        mock_session = MagicMock()
        mock_session.enable_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "enable", "extraction", "BusinessConcept"])

        assert result.exit_code == 0
        assert "Enabled" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_enable_step_not_found(self, mock_session_class):
        """Should return error when step not found."""
        mock_session = MagicMock()
        mock_session.enable_step.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "enable", "extraction", "NonExistent"])

        assert result.exit_code == 1
        assert "not found" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_disable_step_success(self, mock_session_class):
        """Should disable step successfully."""
        mock_session = MagicMock()
        mock_session.disable_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "disable", "derivation", "ApplicationComponent"])

        assert result.exit_code == 0
        assert "Disabled" in result.stdout


class TestClearCommand:
    """Tests for clear command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_graph_success(self, mock_session_class):
        """Should clear graph successfully."""
        mock_session = MagicMock()
        mock_session.clear_graph.return_value = {"success": True, "message": "Graph cleared"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["clear", "graph"])

        assert result.exit_code == 0
        assert "Graph cleared" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_model_success(self, mock_session_class):
        """Should clear model successfully."""
        mock_session = MagicMock()
        mock_session.clear_model.return_value = {"success": True, "message": "Model cleared"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["clear", "model"])

        assert result.exit_code == 0

    def test_clear_invalid_target(self):
        """Should reject invalid target."""
        result = runner.invoke(app, ["clear", "invalid"])
        assert result.exit_code == 1
        assert "Error" in result.output


class TestStatusCommand:
    """Tests for status command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_status(self, mock_session_class):
        """Should show pipeline status."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = [{"enabled": True}, {"enabled": False}]
        mock_session.get_file_types.return_value = ["py", "js", "ts"]
        mock_session.get_graph_stats.return_value = {"total_nodes": 100}
        mock_session.get_archimate_stats.return_value = {"total_elements": 50}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "DERIVA STATUS" in result.stdout
        assert "1/2 steps enabled" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_handles_graph_connection_error(self, mock_session_class):
        """Should handle graph connection error gracefully."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = []
        mock_session.get_file_types.return_value = []
        mock_session.get_graph_stats.side_effect = Exception("Not connected")
        mock_session.get_archimate_stats.side_effect = Exception("Not connected")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "(not connected)" in result.stdout


class TestExportCommand:
    """Tests for export command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_success(self, mock_session_class):
        """Should export model successfully."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {
            "success": True,
            "elements_exported": 50,
            "relationships_exported": 30,
            "output_path": "/path/to/model.xml",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["export", "-o", "out.xml", "-n", "MyModel"])

        assert result.exit_code == 0
        assert "Elements exported: 50" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_failure(self, mock_session_class):
        """Should return error on export failure."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {"success": False, "error": "No elements"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["export"])

        assert result.exit_code == 1


class TestRepoCommands:
    """Tests for repo commands."""

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_clone_success(self, mock_session_class):
        """Should clone repository successfully."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "my_repo",
            "path": "/workspace/repos/my_repo",
            "url": "https://github.com/user/repo",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "clone", "https://github.com/user/repo"])

        assert result.exit_code == 0
        assert "cloned successfully" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_list(self, mock_session_class):
        """Should list repositories."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = [
            {"name": "repo1"},
            {"name": "repo2"},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "list"])

        assert result.exit_code == 0
        assert "REPOSITORIES" in result.stdout
        assert "repo1" in result.stdout
        assert "Total: 2 repositories" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_delete_success(self, mock_session_class):
        """Should delete repository successfully."""
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {"success": True}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "delete", "my_repo"])

        assert result.exit_code == 0
        assert "deleted successfully" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_info(self, mock_session_class):
        """Should show repository info."""
        mock_session = MagicMock()
        mock_session.get_repository_info.return_value = {
            "name": "my_repo",
            "path": "/workspace/repos/my_repo",
            "url": "https://github.com/user/repo",
            "branch": "main",
            "last_commit": "abc123",
            "is_dirty": False,
            "size_mb": 15.5,
            "cloned_at": "2024-01-01",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "info", "my_repo"])

        assert result.exit_code == 0
        assert "REPOSITORY: my_repo" in result.stdout


class TestRunCommand:
    """Tests for run command."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction(self, mock_session_class, mock_progress):
        """Should run extraction stage."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 100, "edges_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction"])

        assert result.exit_code == 0
        assert "EXTRACTION" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_without_llm(self, mock_session_class):
        """Should return error when running derivation without LLM."""
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["run", "derivation"])

        assert result.exit_code == 1
        assert "Error" in result.output

    def test_run_invalid_stage(self):
        """Should reject invalid stage."""
        result = runner.invoke(app, ["run", "invalid"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_run_invalid_phase_for_extraction(self):
        """Should reject invalid phase for extraction."""
        result = runner.invoke(app, ["run", "extraction", "--phase", "generate"])
        assert result.exit_code == 1
        assert "not valid for extraction" in result.output

    def test_run_invalid_phase_for_derivation(self):
        """Should reject invalid phase for derivation."""
        result = runner.invoke(app, ["run", "derivation", "--phase", "classify"])
        assert result.exit_code == 1
        assert "not valid for derivation" in result.output


class TestBenchmarkCommands:
    """Tests for benchmark commands."""

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_benchmark_models_empty(self, mock_session_class):
        """Should show message when no models configured."""
        mock_session = MagicMock()
        mock_session.list_benchmark_models.return_value = {}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "models"])

        assert result.exit_code == 0
        assert "No benchmark model" in result.stdout


class TestGetRunStatsFromOcel:
    """Tests for _get_run_stats_from_ocel helper."""

    def test_extracts_stats_from_complete_run_events(self):
        """Should extract node/edge counts from CompleteRun events."""
        mock_analyzer = MagicMock()

        event1 = MagicMock()
        event1.activity = "CompleteRun"
        event1.objects = {"Model": ["gpt4"]}
        event1.attributes = {"stats": {"extraction": {"nodes_created": 100, "edges_created": 50}}}

        event2 = MagicMock()
        event2.activity = "CompleteRun"
        event2.objects = {"Model": ["gpt4"]}
        event2.attributes = {"stats": {"extraction": {"nodes_created": 110, "edges_created": 55}}}

        event3 = MagicMock()
        event3.activity = "StartRun"  # Not CompleteRun - should be ignored
        event3.objects = {"Model": ["gpt4"]}

        mock_analyzer.ocel_log.events = [event1, event2, event3]

        result = _get_run_stats_from_ocel(mock_analyzer)

        assert "gpt4" in result
        assert len(result["gpt4"]) == 2
        assert result["gpt4"][0] == (100, 50)
        assert result["gpt4"][1] == (110, 55)

    def test_returns_empty_for_no_complete_run_events(self):
        """Should return empty dict when no CompleteRun events."""
        mock_analyzer = MagicMock()

        event = MagicMock()
        event.activity = "StartRun"
        event.objects = {}

        mock_analyzer.ocel_log.events = [event]

        result = _get_run_stats_from_ocel(mock_analyzer)

        assert result == {}

    def test_skips_events_without_model(self):
        """Should skip events without Model object."""
        mock_analyzer = MagicMock()

        event = MagicMock()
        event.activity = "CompleteRun"
        event.objects = {"Model": [None]}

        mock_analyzer.ocel_log.events = [event]

        result = _get_run_stats_from_ocel(mock_analyzer)

        assert result == {}


class TestFiletypeCommands:
    """Tests for filetype commands."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_list_success(self, mock_session_class):
        """Should list file types."""
        mock_session = MagicMock()
        mock_session.get_file_types.return_value = [
            {"extension": ".py", "file_type": "code", "subtype": "python"},
            {"extension": ".js", "file_type": "code", "subtype": "javascript"},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "list"])

        assert result.exit_code == 0
        assert "FILE TYPE REGISTRY" in result.stdout
        assert ".py" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_add_success(self, mock_session_class):
        """Should add file type successfully."""
        mock_session = MagicMock()
        mock_session.add_file_type.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "add", ".rs", "code", "rust"])

        assert result.exit_code == 0
        assert "Added file type" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_delete_success(self, mock_session_class):
        """Should delete file type successfully."""
        mock_session = MagicMock()
        mock_session.delete_file_type.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "delete", ".rs"])

        assert result.exit_code == 0
        assert "Deleted file type" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_stats(self, mock_session_class):
        """Should show file type statistics."""
        mock_session = MagicMock()
        mock_session.get_file_type_stats.return_value = {
            "code": 50,
            "config": 10,
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "stats"])

        assert result.exit_code == 0
        assert "FILE TYPE STATISTICS" in result.stdout


class TestBenchmarkAnalyzeCommand:
    """Tests for benchmark analyze command."""

    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_invalid_format(self, mock_session_class):
        """Should reject invalid format."""
        result = runner.invoke(app, ["benchmark", "analyze", "session_123", "-f", "xml"])

        assert result.exit_code == 1
        assert "format must be" in result.output

    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_session_not_found(self, mock_session_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session.analyze_benchmark.side_effect = ValueError("Session not found")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "analyze", "nonexistent"])

        assert result.exit_code == 1
        assert "Session not found" in result.output

    @patch("deriva.cli.commands.benchmark._get_run_stats_from_ocel")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_success(self, mock_session_class, mock_get_stats):
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
        mock_get_stats.return_value = {}

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "ANALYZING BENCHMARK" in result.stdout

    @patch("deriva.cli.commands.benchmark._get_run_stats_from_ocel")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_with_intra_model_data(self, mock_session_class, mock_get_stats):
        """Should display intra-model consistency data."""
        mock_session = MagicMock()
        mock_analyzer = MagicMock()

        # Mock intra-model data
        mock_intra = MagicMock()
        mock_intra.model = "gpt4"
        mock_intra.stable_edges = ["e1", "e2"]
        mock_intra.unstable_edges = ["e3"]

        mock_summary = MagicMock()
        mock_summary.intra_model = [mock_intra]
        mock_summary.inter_model = []
        mock_summary.localization.hotspots = []

        mock_analyzer.compute_full_analysis.return_value = mock_summary
        mock_analyzer.export_summary.return_value = "output.json"
        mock_session.analyze_benchmark.return_value = mock_analyzer
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_get_stats.return_value = {"gpt4": [(100, 50), (110, 55)]}

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INTRA-MODEL CONSISTENCY" in result.stdout


class TestBenchmarkDeviationsCommand:
    """Tests for benchmark deviations command."""

    def test_deviations_invalid_sort(self):
        """Should reject invalid sort-by value."""
        result = runner.invoke(app, ["benchmark", "deviations", "session_123", "--sort-by", "invalid"])

        assert result.exit_code == 1
        assert "sort-by must be" in result.output

    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_deviations_session_not_found(self, mock_session_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session.analyze_config_deviations.side_effect = ValueError("Not found")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "deviations", "nonexistent"])

        assert result.exit_code == 1
        assert "Not found" in result.output

    @patch("deriva.modules.analysis.generate_recommendations")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.services.analysis.BenchmarkAnalyzer")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_comprehensive_session_not_found(self, mock_session_class, mock_analyzer_class):
        """Should handle session not found error."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_analyzer_class.side_effect = ValueError("Session not found")

        result = runner.invoke(app, ["benchmark", "comprehensive-analysis", "bad_session"])

        assert result.exit_code == 1
        assert "Session not found" in result.output

    @patch("deriva.services.analysis.BenchmarkAnalyzer")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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


class TestConfigShowCommand:
    """Tests for config show command."""

    def test_show_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "show", "invalid", "Test"])

        assert result.exit_code == 1
        assert "Error" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_show_extraction_config(self, mock_session_class, mock_config):
        """Should show extraction config details."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        mock_cfg.sequence = 1
        mock_cfg.enabled = True
        mock_cfg.input_sources = None
        mock_cfg.instruction = "Extract business concepts"
        mock_cfg.example = '{"concepts": []}'
        mock_config.get_extraction_config.return_value = mock_cfg

        result = runner.invoke(app, ["config", "show", "extraction", "BusinessConcept"])

        assert result.exit_code == 0
        assert "EXTRACTION CONFIG: BusinessConcept" in result.stdout
        assert "Sequence: 1" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_show_extraction_not_found(self, mock_session_class, mock_config):
        """Should handle extraction config not found."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_config.get_extraction_config.return_value = None

        result = runner.invoke(app, ["config", "show", "extraction", "NotFound"])

        assert result.exit_code == 1
        assert "not found" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_show_derivation_config(self, mock_session_class, mock_config):
        """Should show derivation config details."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_cfg = MagicMock()
        mock_cfg.element_type = "ApplicationComponent"
        mock_cfg.sequence = 1
        mock_cfg.enabled = True
        mock_cfg.input_graph_query = "MATCH (n) RETURN n"
        mock_cfg.instruction = "Derive application components"
        mock_config.get_derivation_config.return_value = mock_cfg

        result = runner.invoke(app, ["config", "show", "derivation", "ApplicationComponent"])

        assert result.exit_code == 0
        assert "DERIVATION CONFIG: ApplicationComponent" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_show_derivation_not_found(self, mock_session_class, mock_config):
        """Should handle derivation config not found."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_config.get_derivation_config.return_value = None

        result = runner.invoke(app, ["config", "show", "derivation", "NotFound"])

        assert result.exit_code == 1
        assert "not found" in result.stdout


class TestConfigUpdateCommand:
    """Tests for config update command."""

    def test_update_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "update", "invalid", "Test"])

        assert result.exit_code == 1
        assert "Error" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_derivation_success(self, mock_session_class, mock_config):
        """Should update derivation config successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            ["config", "update", "derivation", "AppComp", "-i", "New instruction"],
        )

        assert result.exit_code == 0
        assert "Updated derivation config" in result.stdout
        assert "Version: 1 -> 2" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_extraction_success(self, mock_session_class, mock_config):
        """Should update extraction config successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            ["config", "update", "extraction", "Concept", "-i", "New instruction"],
        )

        assert result.exit_code == 0
        assert "Updated extraction config" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_with_params(self, mock_session_class, mock_config):
        """Should update config with params successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            ["config", "update", "derivation", "AppComp", "-p", '{"key": "value"}'],
        )

        assert result.exit_code == 0
        assert "Params: updated" in result.stdout

    def test_update_invalid_params_json(self):
        """Should reject invalid params JSON."""
        result = runner.invoke(
            app,
            ["config", "update", "derivation", "AppComp", "-p", "not valid json"],
        )

        assert result.exit_code == 1
        assert "params must be valid JSON" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_failure(self, mock_session_class, mock_config):
        """Should handle update failure."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": False,
            "error": "Config not found",
        }

        result = runner.invoke(
            app,
            ["config", "update", "derivation", "NotFound", "-i", "test"],
        )

        assert result.exit_code == 1
        assert "Config not found" in result.output


class TestConfigVersionsCommand:
    """Tests for config versions command."""

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_versions_success(self, mock_session_class, mock_config):
        """Should show config versions."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.get_active_config_versions.return_value = {
            "extraction": {"BusinessConcept": 3, "TypeDefinition": 1},
            "derivation": {"ApplicationComponent": 2},
        }

        result = runner.invoke(app, ["config", "versions"])

        assert result.exit_code == 0
        assert "ACTIVE CONFIG VERSIONS" in result.stdout
        assert "BusinessConcept" in result.stdout
        assert "v3" in result.stdout


class TestFiletypeListEmpty:
    """Tests for filetype list when empty."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_list_empty(self, mock_session_class):
        """Should show message when no file types."""
        mock_session = MagicMock()
        mock_session.get_file_types.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "list"])

        assert result.exit_code == 0
        assert "No file types registered" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_add_failure(self, mock_session_class):
        """Should handle add file type failure."""
        mock_session = MagicMock()
        mock_session.add_file_type.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "add", ".py", "code", "python"])

        assert result.exit_code == 1
        assert "Failed to add" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_filetype_delete_failure(self, mock_session_class):
        """Should handle delete file type failure."""
        mock_session = MagicMock()
        mock_session.delete_file_type.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "filetype", "delete", ".unknown"])

        assert result.exit_code == 1
        assert "not found" in result.output


class TestBenchmarkListEmpty:
    """Tests for benchmark list when empty."""

    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_benchmark_list_empty(self, mock_session_class):
        """Should show message when no sessions."""
        mock_session = MagicMock()
        mock_session.list_benchmarks.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["benchmark", "list"])

        assert result.exit_code == 0
        assert "No benchmark sessions found" in result.stdout


class TestRunCommandOnlyStep:
    """Tests for run command --only-step option."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_with_only_step(self, mock_session_class, mock_progress):
        """Should enable only specified extraction step."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.get_extraction_configs.return_value = [
            {"node_type": "BusinessConcept"},
            {"node_type": "TypeDefinition"},
        ]
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction", "--only-step", "BusinessConcept"])

        assert result.exit_code == 0
        assert "Enabling only extraction step: BusinessConcept" in result.stdout
        mock_session.enable_step.assert_called_with("extraction", "BusinessConcept")
        mock_session.disable_step.assert_called_with("extraction", "TypeDefinition")

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_with_only_step(self, mock_session_class, mock_progress):
        """Should enable only specified derivation step."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.get_derivation_configs.return_value = [
            {"step_name": "ApplicationComponent"},
            {"step_name": "BusinessProcess"},
        ]
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 10},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "derivation", "--only-step", "ApplicationComponent"])

        assert result.exit_code == 0
        assert "Enabling only derivation step: ApplicationComponent" in result.stdout
        mock_session.enable_step.assert_called_with("derivation", "ApplicationComponent")
        mock_session.disable_step.assert_called_with("derivation", "BusinessProcess")


class TestRunCommandDerivationSuccess:
    """Tests for run derivation command success path."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_success(self, mock_session_class, mock_progress):
        """Should run derivation successfully."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 15, "relationships_created": 25},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "derivation"])

        assert result.exit_code == 0
        assert "DERIVATION" in result.stdout
        mock_session.run_derivation.assert_called_once()

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_with_phase(self, mock_session_class, mock_progress):
        """Should run derivation with specified phase."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 5},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "derivation", "--phase", "generate"])

        assert result.exit_code == 0
        assert "Phase: generate" in result.stdout
        mock_session.run_derivation.assert_called_once()
        call_kwargs = mock_session.run_derivation.call_args[1]
        assert call_kwargs["phases"] == ["generate"]


class TestRunCommandAllStage:
    """Tests for run command with 'all' stage."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_all_stages(self, mock_session_class, mock_progress):
        """Should run full pipeline."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "results": {
                "extraction": {"stats": {"nodes_created": 100}},
                "derivation": {"stats": {"elements_created": 20}},
            },
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "all"])

        assert result.exit_code == 0
        assert "Running ALL pipeline" in result.stdout
        mock_session.run_pipeline.assert_called_once()

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_all_with_repo(self, mock_session_class, mock_progress):
        """Should run full pipeline with specific repo."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "results": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "all", "--repo", "my_repo"])

        assert result.exit_code == 0
        assert "Repository: my_repo" in result.stdout
        call_kwargs = mock_session.run_pipeline.call_args[1]
        assert call_kwargs["repo_name"] == "my_repo"


class TestRunCommandFailure:
    """Tests for run command failure paths."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_failure_exits_with_error(self, mock_session_class, mock_progress):
        """Should exit with error code when extraction fails."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": False,
            "stats": {},
            "errors": ["Processing failed"],
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction"])

        assert result.exit_code == 1

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_failure_exits_with_error(self, mock_session_class, mock_progress):
        """Should exit with error code when derivation fails."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": False,
            "stats": {},
            "errors": ["LLM error"],
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "derivation"])

        assert result.exit_code == 1


class TestRunCommandNoLLM:
    """Tests for run command with --no-llm flag."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_with_no_llm_flag(self, mock_session_class, mock_progress):
        """Should run extraction with --no-llm flag."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction", "--no-llm"])

        assert result.exit_code == 0
        assert "LLM disabled (--no-llm)" in result.stdout
        call_kwargs = mock_session.run_extraction.call_args[1]
        assert call_kwargs["no_llm"] is True


class TestRunCommandVerbose:
    """Tests for run command verbose output."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_verbose(self, mock_session_class, mock_progress):
        """Should pass verbose flag to extraction."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction", "-v"])

        assert result.exit_code == 0
        call_kwargs = mock_session.run_extraction.call_args[1]
        assert call_kwargs["verbose"] is True


class TestRunCommandLLMNotConfigured:
    """Tests for run command when LLM is not configured."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_without_llm_shows_warning(self, mock_session_class, mock_progress):
        """Should show warning when LLM not configured for extraction."""
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 30},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction"])

        assert result.exit_code == 0
        assert "Warning: LLM not configured" in result.stdout


class TestClearCommandFailure:
    """Tests for clear command failure paths."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_graph_failure(self, mock_session_class):
        """Should handle graph clear failure."""
        mock_session = MagicMock()
        mock_session.clear_graph.return_value = {
            "success": False,
            "error": "Database connection failed",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["clear", "graph"])

        assert result.exit_code == 1
        assert "Database connection failed" in result.output

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_model_failure(self, mock_session_class):
        """Should handle model clear failure."""
        mock_session = MagicMock()
        mock_session.clear_model.return_value = {
            "success": False,
            "error": "Permission denied",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["clear", "model"])

        assert result.exit_code == 1
        assert "Permission denied" in result.output


class TestMainExitCodes:
    """Tests for main entry point exit codes."""

    def test_main_handles_non_integer_exit_code(self):
        """Should return 1 when exit code is not an integer."""
        with patch("deriva.cli.cli.app") as mock_app:
            mock_app.side_effect = SystemExit("error string")
            result = main()
        assert result == 1

    def test_main_handles_none_exit_code(self):
        """Should return 1 when exit code is None."""
        with patch("deriva.cli.cli.app") as mock_app:
            mock_app.side_effect = SystemExit(None)
            result = main()
        assert result == 1


class TestExportCommandVerbose:
    """Tests for export command verbose mode."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_verbose_shows_connection(self, mock_session_class):
        """Should show connection message when verbose."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {
            "success": True,
            "elements_exported": 10,
            "relationships_exported": 5,
            "output_path": "/out/model.xml",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["export", "-v"])

        assert result.exit_code == 0
        assert "Connected to grafeo" in result.stdout


class TestExportCommandDefaultName:
    """Tests for export command default model name."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_uses_default_name(self, mock_session_class):
        """Should use default model name when not specified."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {
            "success": True,
            "elements_exported": 10,
            "relationships_exported": 5,
            "output_path": "/out/model.xml",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["export"])

        assert result.exit_code == 0
        call_kwargs = mock_session.export_model.call_args[1]
        assert call_kwargs["model_name"] == "Deriva Model"


class TestRunCommandExtractionWithPhase:
    """Tests for run extraction with phase option."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_with_classify_phase(self, mock_session_class, mock_progress):
        """Should run extraction with classify phase."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 20},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction", "--phase", "classify"])

        assert result.exit_code == 0
        assert "Phase: classify" in result.stdout
        call_kwargs = mock_session.run_extraction.call_args[1]
        assert call_kwargs["phases"] == ["classify"]

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction_with_parse_phase(self, mock_session_class, mock_progress):
        """Should run extraction with parse phase."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 30},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction", "--phase", "parse"])

        assert result.exit_code == 0
        call_kwargs = mock_session.run_extraction.call_args[1]
        assert call_kwargs["phases"] == ["parse"]


class TestBenchmarkRunOptions:
    """Tests for benchmark run command options."""

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_run_with_no_enrichment_cache(self, mock_session_class, mock_progress):
        """Should disable enrichment cache."""
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
                "--no-enrichment-cache",
            ],
        )

        assert result.exit_code == 0
        assert "Enrichment cache: disabled" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["use_enrichment_cache"] is False

    @patch("deriva.cli.commands.benchmark.create_benchmark_progress_reporter")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_run_with_nocache_enrichment_configs(self, mock_session_class, mock_progress):
        """Should pass nocache-enrichment-configs option."""
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
                "--nocache-enrichment-configs",
                "ApplicationComponent",
            ],
        )

        assert result.exit_code == 0
        assert "No-cache enrichment configs: ['ApplicationComponent']" in result.stdout
        call_kwargs = mock_session.run_benchmark.call_args[1]
        assert call_kwargs["nocache_enrichment_configs"] == ["ApplicationComponent"]


class TestBenchmarkListOptions:
    """Tests for benchmark list with limit option."""

    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.cli.commands.benchmark._get_run_stats_from_ocel")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_with_inter_model_data(self, mock_session_class, mock_get_stats):
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
        mock_get_stats.return_value = {}

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INTER-MODEL CONSISTENCY" in result.stdout
        assert "test_repo:" in result.stdout

    @patch("deriva.cli.commands.benchmark._get_run_stats_from_ocel")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
    def test_analyze_with_hotspots(self, mock_session_class, mock_get_stats):
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
        mock_get_stats.return_value = {}

        result = runner.invoke(app, ["benchmark", "analyze", "session_123"])

        assert result.exit_code == 0
        assert "INCONSISTENCY HOTSPOTS" in result.stdout
        assert "[HIGH] element: BusinessProcess" in result.stdout


class TestBenchmarkDeviationsDetails:
    """Tests for benchmark deviations with detailed output."""

    @patch("deriva.modules.analysis.generate_recommendations")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.modules.analysis.generate_recommendations")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.services.analysis.BenchmarkAnalyzer")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.services.analysis.BenchmarkAnalyzer")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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

    @patch("deriva.services.analysis.BenchmarkAnalyzer")
    @patch("deriva.cli.commands.benchmark.PipelineSession")
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


class TestConfigListOptions:
    """Tests for config list with options."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_list_with_enabled_only(self, mock_session_class):
        """Should filter to enabled only."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = [
            {"name": "BusinessConcept", "enabled": True, "sequence": 1},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "list", "extraction", "--enabled"])

        assert result.exit_code == 0
        mock_session.list_steps.assert_called_once_with("extraction", enabled_only=True)


class TestConfigSequenceCommand:
    """Tests for config sequence command."""

    def test_sequence_rejects_non_derivation(self):
        """Should reject non-derivation step types."""
        result = runner.invoke(app, ["config", "sequence", "extraction", "--order", "Step1,Step2"])

        assert result.exit_code == 1
        assert "Only 'derivation'" in result.output

    def test_sequence_requires_order(self):
        """Should require at least one step in order."""
        result = runner.invoke(app, ["config", "sequence", "derivation", "--order", ""])

        assert result.exit_code == 1
        assert "at least one step name" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_sequence_success(self, mock_session_class, mock_config):
        """Should update sequence successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.update_derivation_sequence.return_value = {
            "success": True,
            "total_updated": 2,
            "updated": [
                {"step_name": "Step1", "sequence": 1},
                {"step_name": "Step2", "sequence": 2},
            ],
            "errors": [],
        }

        result = runner.invoke(app, ["config", "sequence", "derivation", "--order", "Step1,Step2"])

        assert result.exit_code == 0
        assert "Updated 2 steps" in result.stdout
        assert "[1] Step1" in result.stdout
        assert "[2] Step2" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_sequence_with_phase_filter(self, mock_session_class, mock_config):
        """Should pass phase filter."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.update_derivation_sequence.return_value = {
            "success": True,
            "total_updated": 1,
            "updated": [{"step_name": "Step1", "sequence": 1}],
            "errors": [],
        }

        result = runner.invoke(
            app,
            [
                "config",
                "sequence",
                "derivation",
                "--order",
                "Step1",
                "--phase",
                "generate",
            ],
        )

        assert result.exit_code == 0
        assert "Phase filter: generate" in result.stdout
        mock_config.update_derivation_sequence.assert_called_once()
        call_kwargs = mock_config.update_derivation_sequence.call_args
        assert call_kwargs[1]["phase"] == "generate"

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_sequence_partial_failure(self, mock_session_class, mock_config):
        """Should handle partial failures."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.update_derivation_sequence.return_value = {
            "success": False,
            "total_updated": 1,
            "updated": [{"step_name": "Step1", "sequence": 1}],
            "errors": ["Step2 not found"],
        }

        result = runner.invoke(app, ["config", "sequence", "derivation", "--order", "Step1,Step2"])

        assert result.exit_code == 1
        assert "Partially updated 1 steps" in result.stdout
        assert "Step2 not found" in result.stdout


class TestConfigQueryCommand:
    """Tests for config query command."""

    def test_query_rejects_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "query", "invalid"])

        assert result.exit_code == 1
        assert "extraction' or 'derivation'" in result.output

    @patch("deriva.adapters.database.get_connection")
    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_list(self, mock_config, mock_get_conn):
        """Should list extraction configs."""
        mock_engine = MagicMock()
        mock_get_conn.return_value = mock_engine

        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        mock_cfg.enabled = True
        mock_cfg.sequence = 1
        mock_config.get_extraction_configs.return_value = [mock_cfg]

        result = runner.invoke(app, ["config", "query", "extraction"])

        assert result.exit_code == 0
        assert "EXTRACTION CONFIGS (1)" in result.stdout
        assert "BusinessConcept" in result.stdout
        mock_get_conn.assert_called_once_with(read_only=True)
        mock_engine.close.assert_called_once()

    @patch("deriva.adapters.database.get_connection")
    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_single(self, mock_config, mock_get_conn):
        """Should query single extraction config."""
        mock_engine = MagicMock()
        mock_get_conn.return_value = mock_engine

        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        mock_cfg.enabled = True
        mock_cfg.sequence = 1
        mock_cfg.extraction_method = "llm"
        mock_config.get_extraction_config.return_value = mock_cfg

        result = runner.invoke(app, ["config", "query", "extraction", "BusinessConcept"])

        assert result.exit_code == 0
        assert "EXTRACTION: BusinessConcept" in result.stdout
        assert "Enabled: True" in result.stdout

    @patch("deriva.adapters.database.get_connection")
    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_not_found(self, mock_config, mock_get_conn):
        """Should handle config not found."""
        mock_engine = MagicMock()
        mock_get_conn.return_value = mock_engine
        mock_config.get_extraction_config.return_value = None

        result = runner.invoke(app, ["config", "query", "extraction", "NotFound"])

        assert result.exit_code == 0
        assert "Config not found: NotFound" in result.stdout

    @patch("deriva.adapters.database.get_connection")
    @patch("deriva.cli.commands.config.config")
    def test_query_derivation_list(self, mock_config, mock_get_conn):
        """Should list derivation configs."""
        mock_engine = MagicMock()
        mock_get_conn.return_value = mock_engine

        mock_cfg = MagicMock()
        mock_cfg.step_name = "ApplicationComponent"
        mock_cfg.enabled = True
        mock_cfg.sequence = 1
        mock_cfg.phase = "generate"
        mock_config.get_derivation_configs.return_value = [mock_cfg]

        result = runner.invoke(app, ["config", "query", "derivation"])

        assert result.exit_code == 0
        assert "DERIVATION CONFIGS (1)" in result.stdout
        assert "ApplicationComponent" in result.stdout

    @patch("deriva.adapters.database.get_connection")
    @patch("deriva.cli.commands.config.config")
    def test_query_derivation_single(self, mock_config, mock_get_conn):
        """Should query single derivation config."""
        mock_engine = MagicMock()
        mock_get_conn.return_value = mock_engine

        mock_cfg = MagicMock()
        mock_cfg.step_name = "ApplicationComponent"
        mock_cfg.phase = "generate"
        mock_cfg.enabled = True
        mock_cfg.sequence = 1
        mock_cfg.llm = True
        mock_config.get_derivation_config.return_value = mock_cfg

        result = runner.invoke(app, ["config", "query", "derivation", "ApplicationComponent"])

        assert result.exit_code == 0
        assert "DERIVATION: ApplicationComponent" in result.stdout
        assert "Phase: generate" in result.stdout


class TestConfigSnapshotCommand:
    """Tests for config snapshot command."""

    @patch("deriva.adapters.database.get_connection")
    def test_snapshot_session_not_found(self, mock_get_conn):
        """Should handle session not found."""
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = None
        mock_get_conn.return_value = mock_engine

        result = runner.invoke(app, ["config", "snapshot", "nonexistent"])

        assert result.exit_code == 1
        assert "Session not found" in result.stdout

    @patch("deriva.adapters.database.get_connection")
    def test_snapshot_no_snapshot_data(self, mock_get_conn):
        """Should handle no snapshot data."""
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = (None,)
        mock_get_conn.return_value = mock_engine

        result = runner.invoke(app, ["config", "snapshot", "old_session"])

        assert result.exit_code == 1
        assert "No config snapshot found" in result.stdout

    @patch("deriva.adapters.database.get_connection")
    def test_snapshot_success(self, mock_get_conn):
        """Should display snapshot data."""
        mock_engine = MagicMock()
        snapshot_data = {
            "extraction": {"BusinessConcept": 2, "TypeDefinition": 1},
            "derivation": {"ApplicationComponent": 3},
        }
        mock_engine.execute.return_value.fetchone.return_value = (json.dumps(snapshot_data),)
        mock_get_conn.return_value = mock_engine

        result = runner.invoke(app, ["config", "snapshot", "session_123"])

        assert result.exit_code == 0
        assert "CONFIG SNAPSHOT: session_123" in result.stdout
        assert "EXTRACTION:" in result.stdout
        assert "BusinessConcept" in result.stdout
        assert "v2" in result.stdout
        assert "DERIVATION:" in result.stdout
        assert "ApplicationComponent" in result.stdout


class TestConfigUpdateFileOptions:
    """Tests for config update with file options."""

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_with_instruction_file(self, mock_session_class, mock_config, tmp_path):
        """Should read instruction from file."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Create temp instruction file
        instruction_file = tmp_path / "instruction.txt"
        instruction_file.write_text("New instruction from file")

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "derivation",
                "AppComp",
                "--instruction-file",
                str(instruction_file),
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_derivation_config_version.call_args[1]
        assert call_kwargs["instruction"] == "New instruction from file"

    def test_update_with_invalid_instruction_file(self):
        """Should handle missing instruction file."""
        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "derivation",
                "AppComp",
                "--instruction-file",
                "/nonexistent/file.txt",
            ],
        )

        assert result.exit_code == 1
        assert "Error reading instruction file" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_with_example_file(self, mock_session_class, mock_config, tmp_path):
        """Should read example from file."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Create temp example file
        example_file = tmp_path / "example.json"
        example_file.write_text('{"example": "data"}')

        mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "extraction",
                "Concept",
                "--example-file",
                str(example_file),
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_extraction_config_version.call_args[1]
        assert call_kwargs["example"] == '{"example": "data"}'

    def test_update_with_invalid_example_file(self):
        """Should handle missing example file."""
        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "extraction",
                "Concept",
                "--example-file",
                "/nonexistent/file.txt",
            ],
        )

        assert result.exit_code == 1
        assert "Error reading example file" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_with_params_file(self, mock_session_class, mock_config, tmp_path):
        """Should read params from file."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        # Create temp params file
        params_file = tmp_path / "params.json"
        params_file.write_text('{"key": "value"}')

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "derivation",
                "AppComp",
                "--params-file",
                str(params_file),
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_derivation_config_version.call_args[1]
        assert call_kwargs["params"] == '{"key": "value"}'

    def test_update_with_invalid_params_file(self):
        """Should handle missing params file."""
        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "derivation",
                "AppComp",
                "--params-file",
                "/nonexistent/file.txt",
            ],
        )

        assert result.exit_code == 1
        assert "Error reading params file" in result.output

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_extraction_with_sources(self, mock_session_class, mock_config):
        """Should update extraction with sources option."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "extraction",
                "Concept",
                "--sources",
                "File,Directory",
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_extraction_config_version.call_args[1]
        assert call_kwargs["input_sources"] == "File,Directory"

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_extraction_with_batch_size(self, mock_session_class, mock_config):
        """Should update extraction with batch_size option."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            ["config", "update", "extraction", "Concept", "--batch-size", "5"],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_extraction_config_version.call_args[1]
        assert call_kwargs["batch_size"] == 5

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_derivation_with_query(self, mock_session_class, mock_config):
        """Should update derivation with query option."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        result = runner.invoke(
            app,
            [
                "config",
                "update",
                "derivation",
                "AppComp",
                "-q",
                "MATCH (n) RETURN n",
            ],
        )

        assert result.exit_code == 0
        call_kwargs = mock_config.create_derivation_config_version.call_args[1]
        assert call_kwargs["input_graph_query"] == "MATCH (n) RETURN n"


class TestConfigDisableInvalidType:
    """Tests for config disable with invalid type."""

    def test_disable_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "disable", "invalid", "TestStep"])

        assert result.exit_code == 1
        assert "extraction' or 'derivation'" in result.output

    def test_enable_invalid_step_type(self):
        """Should reject invalid step type."""
        result = runner.invoke(app, ["config", "enable", "invalid", "TestStep"])

        assert result.exit_code == 1
        assert "extraction' or 'derivation'" in result.output


class TestRepoCloneOptions:
    """Tests for repo clone command options."""

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_clone_with_custom_name(self, mock_session_class):
        """Should pass custom name option."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "my_custom_name",
            "path": "/workspace/repos/my_custom_name",
            "url": "https://github.com/user/repo",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(
            app,
            ["repo", "clone", "https://github.com/user/repo", "-n", "my_custom_name"],
        )

        assert result.exit_code == 0
        assert "Name: my_custom_name" in result.stdout
        call_kwargs = mock_session.clone_repository.call_args[1]
        assert call_kwargs["name"] == "my_custom_name"

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_clone_with_branch(self, mock_session_class):
        """Should pass branch option."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "repo",
            "path": "/workspace/repos/repo",
            "url": "https://github.com/user/repo",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(
            app,
            ["repo", "clone", "https://github.com/user/repo", "-b", "develop"],
        )

        assert result.exit_code == 0
        assert "Branch: develop" in result.stdout
        call_kwargs = mock_session.clone_repository.call_args[1]
        assert call_kwargs["branch"] == "develop"

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_clone_with_overwrite(self, mock_session_class):
        """Should pass overwrite option."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "repo",
            "path": "/workspace/repos/repo",
            "url": "https://github.com/user/repo",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(
            app,
            ["repo", "clone", "https://github.com/user/repo", "--overwrite"],
        )

        assert result.exit_code == 0
        call_kwargs = mock_session.clone_repository.call_args[1]
        assert call_kwargs["overwrite"] is True

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_clone_failure(self, mock_session_class):
        """Should handle clone failure."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": False,
            "error": "Repository already exists",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "clone", "https://github.com/user/repo"])

        assert result.exit_code == 1
        assert "Repository already exists" in result.output


class TestRepoListOptions:
    """Tests for repo list command options."""

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_list_empty(self, mock_session_class):
        """Should show message when no repositories."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "list"])

        assert result.exit_code == 0
        assert "No repositories found" in result.stdout
        assert "Clone a repository with" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_list_detailed(self, mock_session_class):
        """Should show detailed information."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = [
            {
                "name": "my_repo",
                "url": "https://github.com/user/repo",
                "branch": "main",
                "size_mb": 15.5,
                "cloned_at": "2024-01-01",
                "is_dirty": True,
            }
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "list", "-d"])

        assert result.exit_code == 0
        assert "my_repo (dirty)" in result.stdout
        assert "URL:    https://github.com/user/repo" in result.stdout
        assert "Branch: main" in result.stdout
        assert "Size:   15.50 MB" in result.stdout
        mock_session.get_repositories.assert_called_with(detailed=True)


class TestRepoDeleteOptions:
    """Tests for repo delete command options."""

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_delete_with_force(self, mock_session_class):
        """Should pass force option."""
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {"success": True}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "delete", "my_repo", "-f"])

        assert result.exit_code == 0
        call_kwargs = mock_session.delete_repository.call_args[1]
        assert call_kwargs["force"] is True

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_delete_failure(self, mock_session_class):
        """Should handle delete failure."""
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {
            "success": False,
            "error": "Repository not found",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "delete", "nonexistent"])

        assert result.exit_code == 1
        assert "Repository not found" in result.output

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_delete_uncommitted_changes_exception(self, mock_session_class):
        """Should show force hint for uncommitted changes."""
        mock_session = MagicMock()
        mock_session.delete_repository.side_effect = Exception("Repository has uncommitted changes")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "delete", "my_repo"])

        assert result.exit_code == 1
        assert "uncommitted changes" in result.output
        assert "Use --force to delete anyway" in result.stdout


class TestRepoInfoOptions:
    """Tests for repo info command options."""

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_info_not_found(self, mock_session_class):
        """Should handle repository not found."""
        mock_session = MagicMock()
        mock_session.get_repository_info.return_value = None
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "info", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_info_exception(self, mock_session_class):
        """Should handle exception."""
        mock_session = MagicMock()
        mock_session.get_repository_info.side_effect = Exception("Connection error")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "info", "my_repo"])

        assert result.exit_code == 1
        assert "Connection error" in result.output


class TestPrintExtractionResultExtended:
    """Extended tests for _print_extraction_result helper."""

    def test_prints_truncated_warnings(self, capsys):
        """Should truncate warnings when more than 5."""
        result = {
            "success": True,
            "stats": {"nodes_created": 10},
            "warnings": [f"Warning {i}" for i in range(10)],
        }

        _print_extraction_result(result)

        captured = capsys.readouterr()
        assert "Warning 0" in captured.out
        assert "Warning 4" in captured.out
        assert "Warning 5" not in captured.out
        assert "... and 5 more" in captured.out

    def test_prints_truncated_errors(self, capsys):
        """Should truncate errors when more than 5."""
        result = {
            "success": False,
            "stats": {"nodes_created": 0},
            "errors": [f"Error {i}" for i in range(8)],
        }

        _print_extraction_result(result)

        captured = capsys.readouterr()
        assert "Error 0" in captured.out
        assert "Error 4" in captured.out
        assert "Error 5" not in captured.out
        assert "... and 3 more" in captured.out


class TestPrintDerivationResultExtended:
    """Extended tests for _print_derivation_result helper."""

    def test_prints_issues_with_severity(self, capsys):
        """Should print issues with severity."""
        result = {
            "success": True,
            "stats": {"elements_created": 5},
            "issues": [
                {"severity": "warning", "message": "Minor issue"},
                {"severity": "error", "message": "Major issue"},
            ],
        }

        _print_derivation_result(result)

        captured = capsys.readouterr()
        assert "[WARNING] Minor issue" in captured.out
        assert "[ERROR] Major issue" in captured.out

    def test_prints_truncated_issues(self, capsys):
        """Should truncate issues when more than 10."""
        result = {
            "success": True,
            "stats": {"elements_created": 5},
            "issues": [{"severity": "warning", "message": f"Issue {i}"} for i in range(15)],
        }

        _print_derivation_result(result)

        captured = capsys.readouterr()
        assert "Issue 0" in captured.out
        assert "Issue 9" in captured.out
        assert "Issue 10" not in captured.out
        assert "... and 5 more" in captured.out

    def test_prints_errors(self, capsys):
        """Should print errors."""
        result = {
            "success": False,
            "stats": {"elements_created": 0},
            "errors": ["LLM error 1", "LLM error 2"],
        }

        _print_derivation_result(result)

        captured = capsys.readouterr()
        assert "Errors (2)" in captured.out
        assert "LLM error 1" in captured.out
        assert "LLM error 2" in captured.out


class TestPrintPipelineResultExtended:
    """Extended tests for _print_pipeline_result helper."""

    def test_prints_classification_results(self, capsys):
        """Should print classification results."""
        result = {
            "success": True,
            "results": {"classification": {"stats": {"files_classified": 100, "files_undefined": 5}}},
        }

        _print_pipeline_result(result)

        captured = capsys.readouterr()
        assert "Classification:" in captured.out
        assert "Files classified: 100" in captured.out
        assert "Files undefined:  5" in captured.out

    def test_prints_extraction_results(self, capsys):
        """Should print extraction results."""
        result = {
            "success": True,
            "results": {"extraction": {"stats": {"nodes_created": 250}}},
        }

        _print_pipeline_result(result)

        captured = capsys.readouterr()
        assert "Extraction:" in captured.out
        assert "Nodes created: 250" in captured.out

    def test_prints_derivation_results(self, capsys):
        """Should print derivation results."""
        result = {
            "success": True,
            "results": {"derivation": {"stats": {"elements_created": 50, "issues_found": 3}}},
        }

        _print_pipeline_result(result)

        captured = capsys.readouterr()
        assert "Derivation:" in captured.out
        assert "Elements created: 50" in captured.out
        assert "Issues found: 3" in captured.out

    def test_prints_total_errors(self, capsys):
        """Should print total errors."""
        result = {
            "success": False,
            "results": {},
            "errors": ["Error 1", "Error 2", "Error 3"],
        }

        _print_pipeline_result(result)

        captured = capsys.readouterr()
        assert "Total errors: 3" in captured.out

    def test_prints_all_sections(self, capsys):
        """Should print all result sections."""
        result = {
            "success": True,
            "results": {
                "classification": {"stats": {"files_classified": 100, "files_undefined": 5}},
                "extraction": {"stats": {"nodes_created": 250}},
                "derivation": {"stats": {"elements_created": 50, "issues_found": 3}},
            },
            "errors": ["Minor error"],
        }

        _print_pipeline_result(result)

        captured = capsys.readouterr()
        assert "Classification:" in captured.out
        assert "Extraction:" in captured.out
        assert "Derivation:" in captured.out
        assert "Total errors: 1" in captured.out


# =============================================================================
# Tests for run.py run_stage function (direct invocation of run.app)
# =============================================================================


class TestRunAppInvalidStage:
    """Tests for run.py app with invalid stage."""

    def test_invalid_stage_errors(self):
        """Should reject invalid stage."""
        result = runner.invoke(run_app, ["invalid"])
        assert result.exit_code == 1
        assert "Error: stage must be" in result.output


class TestRunAppInvalidPhases:
    """Tests for run.py app with invalid phases."""

    def test_invalid_extraction_phase(self):
        """Should reject invalid phase for extraction."""
        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--phase", "generate", "extraction"])
        assert result.exit_code == 1
        assert "not valid for extraction" in result.output
        assert "classify, parse" in result.output

    def test_invalid_derivation_phase(self):
        """Should reject invalid phase for derivation."""
        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--phase", "classify", "derivation"])
        assert result.exit_code == 1
        assert "not valid for derivation" in result.output
        assert "generate, prep, refine" in result.output


class TestRunAppExtraction:
    """Tests for run.py app extraction stage."""

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_extraction_success(self, mock_session_class, mock_progress):
        """Should run extraction successfully."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 100, "edges_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["extraction"])

        assert result.exit_code == 0
        assert "EXTRACTION" in result.stdout
        assert "Connected to grafeo" in result.stdout
        mock_session.run_extraction.assert_called_once()

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_extraction_with_repo(self, mock_session_class, mock_progress):
        """Should run extraction with repo specified."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 100},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--repo", "myrepo", "extraction"])

        assert result.exit_code == 0
        assert "Repository: myrepo" in result.stdout

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_extraction_with_phase(self, mock_session_class, mock_progress):
        """Should run extraction with phase specified."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 100},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--phase", "classify", "extraction"])

        assert result.exit_code == 0
        assert "Phase: classify" in result.stdout

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_extraction_failure(self, mock_session_class, mock_progress):
        """Should exit with error code on failure."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": False,
            "errors": ["Failed"],
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["extraction"])

        assert result.exit_code == 1


class TestRunAppDerivation:
    """Tests for run.py app derivation stage."""

    @patch("deriva.cli.commands.run.PipelineSession")
    def test_derivation_no_llm(self, mock_session_class):
        """Should error when LLM not configured."""
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(run_app, ["derivation"])

        assert result.exit_code == 1
        assert "Error: Derivation requires LLM" in result.output

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_derivation_success(self, mock_session_class, mock_progress):
        """Should run derivation successfully."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["derivation"])

        assert result.exit_code == 0
        assert "DERIVATION" in result.stdout
        mock_session.run_derivation.assert_called_once()

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_derivation_with_phase(self, mock_session_class, mock_progress):
        """Should run derivation with phase specified."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 50},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--phase", "generate", "derivation"])

        assert result.exit_code == 0
        assert "Phase: generate" in result.stdout


class TestRunAppAllStage:
    """Tests for run.py app all stage."""

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_all_stage_success(self, mock_session_class, mock_progress):
        """Should run all stages successfully."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "results": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["all"])

        assert result.exit_code == 0
        assert "ALL" in result.stdout
        mock_session.run_pipeline.assert_called_once()

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_all_stage_with_repo(self, mock_session_class, mock_progress):
        """Should run all stages with repo specified."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "results": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--repo", "myrepo", "all"])

        assert result.exit_code == 0
        assert "Repository: myrepo" in result.stdout


class TestRunAppOnlyStep:
    """Tests for run.py app --only-step option."""

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_only_step_extraction(self, mock_session_class, mock_progress):
        """Should enable only specified extraction step."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.get_extraction_configs.return_value = [
            {"node_type": "File"},
            {"node_type": "Method"},
            {"node_type": "BusinessConcept"},
        ]
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 10},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--only-step", "File", "extraction"])

        assert result.exit_code == 0
        assert "Enabling only extraction step: File" in result.stdout
        mock_session.enable_step.assert_called_with("extraction", "File")
        assert mock_session.disable_step.call_count == 2

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_only_step_derivation(self, mock_session_class, mock_progress):
        """Should enable only specified derivation step."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.get_derivation_configs.return_value = [
            {"step_name": "ApplicationComponent"},
            {"step_name": "ApplicationService"},
        ]
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 5},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--only-step", "ApplicationComponent", "derivation"])

        assert result.exit_code == 0
        assert "Enabling only derivation step: ApplicationComponent" in result.stdout
        mock_session.enable_step.assert_called_with("derivation", "ApplicationComponent")


class TestRunAppLLMStatus:
    """Tests for run.py app LLM status messages."""

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_llm_configured_message(self, mock_session_class, mock_progress):
        """Should show LLM configured message."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["extraction"])

        assert result.exit_code == 0
        assert "LLM configured: anthropic/claude-3" in result.stdout

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_no_llm_flag(self, mock_session_class, mock_progress):
        """Should show LLM disabled message with --no-llm flag."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        result = runner.invoke(run_app, ["--no-llm", "extraction"])

        assert result.exit_code == 0
        assert "LLM disabled (--no-llm)" in result.stdout

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_no_llm_warning(self, mock_session_class, mock_progress):
        """Should show warning when LLM not configured."""
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(run_app, ["extraction"])

        assert result.exit_code == 0
        assert "Warning: LLM not configured" in result.stdout


class TestRunAppVerboseQuiet:
    """Tests for run.py app verbose and quiet options."""

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_verbose_option(self, mock_session_class, mock_progress):
        """Should pass verbose option."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        runner.invoke(run_app, ["-v", "extraction"])

        mock_session.run_extraction.assert_called_once()
        call_kwargs = mock_session.run_extraction.call_args[1]
        assert call_kwargs["verbose"] is True

    @patch("deriva.cli.commands.run.create_progress_reporter")
    @patch("deriva.cli.commands.run.PipelineSession")
    def test_quiet_option(self, mock_session_class, mock_progress):
        """Should pass quiet option to progress reporter."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        # Options must come before positional args with typer callback
        runner.invoke(run_app, ["-q", "extraction"])

        mock_progress.assert_called_once_with(quiet=True)
