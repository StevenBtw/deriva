"""Tests for cli.cli module (typer-based)."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from typer.testing import CliRunner

from deriva.cli.cli import app, main
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

    def test_prints_the_errors_themselves(self, capsys):
        """A failed run says what failed (the first ten), not only how many errors there were."""
        result = {"results": {}, "errors": ["No repositories found"] + [f"err{i}" for i in range(11)]}

        _print_pipeline_result(result)
        output = capsys.readouterr().out

        assert "  - No repositories found" in output
        assert "  - err8" in output and "err9" not in output
        assert "... and 2 more" in output


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

    def test_main_names_a_busy_config_database_in_one_line(self, capsys):
        """With the studio open the config database is locked: one line saying so, not a traceback."""
        from deriva.services import ConfigDatabaseBusy

        with patch("deriva.cli.cli.app", side_effect=ConfigDatabaseBusy("The config database x is open in another Deriva process")):
            assert main() == 1
        assert capsys.readouterr().err.strip() == "Error: The config database x is open in another Deriva process"

    def test_main_names_an_unknown_repository_in_one_line(self, capsys):
        from deriva.services import UnknownRepository

        with patch("deriva.cli.cli.app", side_effect=UnknownRepository("typo", ["alpha"])):
            assert main() == 1
        assert capsys.readouterr().err.strip() == "Error: Unknown repository: typo (known: alpha)"

    @pytest.mark.parametrize(
        "args",
        [
            ["status", "--repo", "typo"],
            ["export", "--repo", "typo"],
            ["clear", "model", "--repo", "typo"],
            ["run", "extraction", "--repo", "typo"],
            ["graph", "tag-steps", "--repo", "typo"],
        ],
    )
    def test_an_unknown_repository_is_refused_before_a_database_opens(self, args):
        from deriva.services import UnknownRepository

        session_class = MagicMock()
        session_class.check_repository.side_effect = UnknownRepository("typo", [])
        with patch("deriva.cli.cli.PipelineSession", session_class), patch("deriva.cli.commands.graph.PipelineSession", session_class):
            result = runner.invoke(app, args)

        assert isinstance(result.exception, UnknownRepository)
        session_class.check_repository.assert_called_once_with("typo")
        session_class.assert_not_called()

    def test_the_no_llm_help_says_derivation_runs_only_its_prep_phase(self):
        result = runner.invoke(app, ["run", "--help"], env={"COLUMNS": "300", "NO_COLOR": "1"})

        assert "No LLM call: extraction runs its parsers, derivation only its prep phase (no elements)" in result.output

    def test_main_makes_stdout_line_buffered(self):
        """Progress lines must appear live, also when stdout is piped to a file."""
        with patch("deriva.cli.cli.app"), patch("deriva.cli.cli.sys.stdout") as stdout:
            main()
        stdout.reconfigure.assert_called_once_with(line_buffering=True)

    def test_main_runs_with_a_stdout_that_cannot_reconfigure(self):
        """Redirected streams such as io.StringIO have no reconfigure()."""
        import io

        with patch("deriva.cli.cli.app"), patch("deriva.cli.cli.sys.stdout", io.StringIO()):
            assert main() == 0


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


class TestCoverageCommand:
    """deriva-cli coverage: what of a repository's checkout reached its graph."""

    REPORT = {
        "files": 4,
        "in_graph": 3,
        "extensions": [{"extension": ".java", "files": 3, "in_graph": 3, "file_type": "source", "subtype": "java", "reader": "parser", "with_symbols": 0, "unreadable": 1}],
        "missing": ["gone.xsd"],
        "unreadable": [{"path": "deep/A.java", "reason": "path over 260 characters: [WinError 3]"}],
        "nodes": {"File": 3},
        "complete": False,
        "reasons": ["1 file is not in the graph (gone.xsd)"],
        "notes": ["1 source file is read by no extraction step: .kt (1)"],
    }

    @patch("deriva.cli.cli.PipelineSession")
    def test_coverage_prints_the_verdict_reasons_and_extensions(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.extraction_coverage.return_value = self.REPORT
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["coverage", "--repo", "x"])

        assert result.exit_code == 0
        mock_session.extraction_coverage.assert_called_once_with("x")
        assert "Files: 4 in the checkout, 3 in the graph" in result.stdout
        assert "Incomplete" in result.stdout and "1 file is not in the graph (gone.xsd)" in result.stdout
        assert "1 source file is read by no extraction step: .kt (1)" in result.stdout
        assert ".java" in result.stdout and "deep/A.java: path over 260 characters" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_coverage_as_json_has_the_full_lists(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.extraction_coverage.return_value = self.REPORT
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["coverage", "--repo", "x", "--json"])

        assert json.loads(result.stdout) == self.REPORT


class TestQualityCommand:
    """deriva-cli quality: the verdict on a repository's model from its structure."""

    REPORT = {
        "elements": 7,
        "relationships": 3,
        "orphans": [{"id": "c3", "name": "C3", "type": "ApplicationComponent"}],
        "orphan_share": 0.43,
        "structural_share": 1.0,
        "relationship_types": {"Composition": 3},
        "layers": {"Business": 0, "Application": 6, "Technology": 1},
        "unsupported": [{"id": "in", "name": "Inbound", "type": "ApplicationComponent", "sources": ["repo/In"]}],
        "verdict": "weak",
        "reasons": ["3 of 7 elements (43%) have no relationship (above 25%)"],
    }

    @patch("deriva.cli.cli.PipelineSession")
    def test_quality_prints_the_verdict_its_reasons_and_the_elements_without_evidence(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.model_quality.return_value = self.REPORT
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["quality", "--repo", "x"])

        assert result.exit_code == 0
        mock_session_class.assert_called_once_with(repository="x")
        assert "Weak: 7 elements, 3 relationships" in result.stdout
        assert "3 of 7 elements (43%) have no relationship (above 25%)" in result.stdout
        assert "Inbound (ApplicationComponent) <- repo/In" in result.stdout

    @patch("deriva.cli.cli.PipelineSession")
    def test_quality_as_json(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.model_quality.return_value = self.REPORT
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["quality", "--repo", "x", "--json"])

        assert json.loads(result.stdout) == self.REPORT


class TestStatusCommand:
    """Tests for status command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_status_shows_home_folder_and_version(self, mock_session_class):
        from deriva.services import about

        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.list_steps.return_value = []
        mock_session.get_file_types.return_value = []

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert f"Home: {about.home()}" in result.output
        assert f"Version: {about.version()}" in result.output

    @patch("deriva.cli.cli.PipelineSession")
    def test_status_names_the_graph_it_reads(self, mock_session_class):
        """Without --repo the counts are those of the shared graph, not of the repository run last."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.list_steps.return_value = []
        mock_session.get_file_types.return_value = []

        shared = runner.invoke(app, ["status"])
        repository = runner.invoke(app, ["status", "--repo", "deriva"])

        assert "  Graph: default (shared; use --repo <name> for a repository's graph)" in shared.output
        assert "  Graph: deriva\n" in repository.output

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

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_without_output_uses_the_session_default(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.export_model.return_value = {"success": True, "elements_exported": 1, "relationships_exported": 0, "output_path": "x"}

        result = runner.invoke(app, ["export"])

        assert result.exit_code == 0
        assert mock_session.export_model.call_args.kwargs["output_path"] is None


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
    def test_run_extraction_no_llm_does_not_load_the_llm(self, mock_session_class):
        """--no-llm prints no LLM warnings: the session's LLM is never asked for."""
        mock_session = MagicMock()
        llm_info = PropertyMock(return_value=None)
        type(mock_session).llm_info = llm_info
        mock_session.run_extraction.return_value = {"success": True, "stats": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["run", "extraction", "--no-llm"])

        assert result.exit_code == 0
        assert "LLM disabled (--no-llm)" in result.output
        llm_info.assert_not_called()

    @patch("deriva.cli.cli.derivation.start_full_derivation")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_all_no_llm_passes_the_flag_and_keeps_the_model(self, mock_session_class, clear):
        mock_session = MagicMock()
        mock_session.run_pipeline.return_value = {"success": True, "results": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["run", "all", "--no-llm"])

        assert result.exit_code == 0
        assert mock_session.run_pipeline.call_args.kwargs["no_llm"] is True
        clear.assert_not_called()

    @patch("deriva.cli.cli.derivation.start_full_derivation")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_no_llm_runs_the_prep_phase_only(self, mock_session_class, clear):
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session.run_derivation.return_value = {"success": True, "stats": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["run", "derivation", "--no-llm"])

        assert result.exit_code == 0
        assert mock_session.run_derivation.call_args.kwargs["phases"] == ["prep"]
        clear.assert_not_called()

    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_no_llm_refuses_the_generate_phase(self, mock_session_class):
        mock_session_class.return_value.__enter__.return_value = MagicMock()

        result = runner.invoke(app, ["run", "derivation", "--no-llm", "--phase", "generate"])

        assert result.exit_code == 1
        assert "--no-llm" in result.output

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

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_moves_a_derivation_step_with_sequence(self, mock_session_class, mock_config):
        """--sequence makes a new version at another place in the phase."""
        mock_session_class.return_value.__enter__.return_value = MagicMock()
        mock_config.create_derivation_config_version.return_value = {"success": True, "old_version": 3, "new_version": 4}

        result = runner.invoke(app, ["config", "update", "derivation", "joint_consistency", "--sequence", "8"])

        assert result.exit_code == 0
        assert mock_config.create_derivation_config_version.call_args.kwargs["sequence"] == 8
        assert "Sequence: 8" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_sets_whether_a_derivation_step_calls_the_llm(self, mock_session_class, mock_config):
        """--llm/--no-llm makes a new version with the flag set; without either the flag is kept."""
        mock_session_class.return_value.__enter__.return_value = MagicMock()
        mock_config.create_derivation_config_version.return_value = {"success": True, "old_version": 1, "new_version": 2}

        result = runner.invoke(app, ["config", "update", "derivation", "ApplicationGrouping", "--llm"])
        kept = runner.invoke(app, ["config", "update", "derivation", "ApplicationGrouping", "--sequence", "3"])

        assert result.exit_code == 0 and "LLM: True" in result.stdout
        calls = mock_config.create_derivation_config_version.call_args_list
        assert calls[0].kwargs["llm"] is True and kept.exit_code == 0 and calls[1].kwargs["llm"] is None

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_update_refuses_sequence_for_an_extraction_step(self, mock_session_class, mock_config):
        """--sequence moves derivation steps only: for an extraction step it is refused, not silently dropped."""
        mock_session_class.return_value.__enter__.return_value = MagicMock()

        result = runner.invoke(app, ["config", "update", "extraction", "BuildModule", "--sequence", "3"])

        assert result.exit_code == 1
        assert "--sequence" in result.output
        mock_config.create_extraction_config_version.assert_not_called()

    def test_update_invalid_params_json(self):
        """Should reject invalid params JSON."""
        result = runner.invoke(
            app,
            ["config", "update", "derivation", "AppComp", "-p", "not valid json"],
        )

        assert result.exit_code == 1
        assert "params must be valid JSON" in result.output

    def test_update_rejects_params_that_are_not_an_object(self):
        """Params are read with .get(), so an array or scalar is rejected up front."""
        result = runner.invoke(app, ["config", "update", "derivation", "AppComp", "-p", "[1, 2]"])

        assert result.exit_code == 1
        assert "params must be a JSON object" in result.output

    def test_update_rejects_temperature_out_of_range(self):
        result = runner.invoke(app, ["config", "update", "derivation", "AppComp", "--temperature", "3"])

        assert result.exit_code != 0
        assert "temperature" in result.output.lower()

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
        mock_session.only_step.assert_called_once_with("extraction", "BusinessConcept")
        mock_session.only_step.return_value.__exit__.assert_called_once()

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
        mock_session.only_step.assert_called_once_with("derivation", "ApplicationComponent")
        mock_session.only_step.return_value.__exit__.assert_called_once()

    @patch("deriva.cli.cli.PipelineSession")
    def test_run_with_unknown_only_step_exits_with_error(self, mock_session_class):
        """Should exit 1 without running when the step name is unknown."""
        mock_session = MagicMock()
        mock_session.only_step.side_effect = ValueError("Unknown extraction step: Typo")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["run", "extraction", "--only-step", "Typo"])

        assert result.exit_code == 1
        assert "Unknown extraction step: Typo" in result.output
        mock_session.run_extraction.assert_not_called()


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

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_the_warning_says_why_the_llm_is_not_configured(self, mock_session_class, mock_progress):
        mock_session = MagicMock()
        mock_session.llm_info = None
        mock_session.llm_error = "The model config mini has no API key: set AZURE_OPENAI_API_KEY"
        mock_session.run_extraction.return_value = {"success": True, "stats": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_progress.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_progress.return_value.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(app, ["run", "extraction"])

        assert "Warning: LLM not configured: The model config mini has no API key: set AZURE_OPENAI_API_KEY" in result.stdout


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

    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_list(self, mock_config):
        """Should list extraction configs."""
        mock_engine = MagicMock()
        mock_config.read_only_connection.return_value = mock_engine

        mock_cfg = MagicMock()
        mock_cfg.node_type = "BusinessConcept"
        mock_cfg.enabled = True
        mock_cfg.sequence = 1
        mock_config.get_extraction_configs.return_value = [mock_cfg]

        result = runner.invoke(app, ["config", "query", "extraction"])

        assert result.exit_code == 0
        assert "EXTRACTION CONFIGS (1)" in result.stdout
        assert "BusinessConcept" in result.stdout
        mock_config.read_only_connection.assert_called_once_with()
        mock_engine.close.assert_called_once()

    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_single(self, mock_config):
        """Should query single extraction config."""
        mock_engine = MagicMock()
        mock_config.read_only_connection.return_value = mock_engine

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

    @patch("deriva.cli.commands.config.config")
    def test_query_extraction_not_found(self, mock_config):
        """Should handle config not found."""
        mock_engine = MagicMock()
        mock_config.read_only_connection.return_value = mock_engine
        mock_config.get_extraction_config.return_value = None

        result = runner.invoke(app, ["config", "query", "extraction", "NotFound"])

        assert result.exit_code == 0
        assert "Config not found: NotFound" in result.stdout

    @patch("deriva.cli.commands.config.config")
    def test_query_derivation_list(self, mock_config):
        """Should list derivation configs."""
        mock_engine = MagicMock()
        mock_config.read_only_connection.return_value = mock_engine

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

    @patch("deriva.cli.commands.config.config")
    def test_query_derivation_single(self, mock_config):
        """Should query single derivation config."""
        mock_engine = MagicMock()
        mock_config.read_only_connection.return_value = mock_engine

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

    @patch("deriva.services.config.read_only_connection")
    def test_snapshot_session_not_found(self, mock_get_conn):
        """Should handle session not found."""
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = None
        mock_get_conn.return_value = mock_engine

        result = runner.invoke(app, ["config", "snapshot", "nonexistent"])

        assert result.exit_code == 1
        assert "Session not found" in result.stdout

    @patch("deriva.services.config.read_only_connection")
    def test_snapshot_no_snapshot_data(self, mock_get_conn):
        """Should handle no snapshot data."""
        mock_engine = MagicMock()
        mock_engine.execute.return_value.fetchone.return_value = (None,)
        mock_get_conn.return_value = mock_engine

        result = runner.invoke(app, ["config", "snapshot", "old_session"])

        assert result.exit_code == 1
        assert "No config snapshot found" in result.stdout

    @patch("deriva.services.config.read_only_connection")
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
    def test_update_extraction_with_params(self, mock_session_class, mock_config):
        """Extraction steps take versioned params too."""
        mock_session_class.return_value.__enter__.return_value = MagicMock()
        mock_config.create_extraction_config_version.return_value = {"success": True, "old_version": 1, "new_version": 2}

        result = runner.invoke(app, ["config", "update", "extraction", "Technology", "-p", '{"prompt": {}}'])

        assert result.exit_code == 0
        assert mock_config.create_extraction_config_version.call_args.kwargs["params"] == '{"prompt": {}}'

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
        assert "  deriva-cli repo clone <url>" in result.stdout

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
        assert call_kwargs["with_data"] is False

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_delete_with_data_says_the_graph_went_too(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {"success": True, "data_deleted": True}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "delete", "my_repo", "--with-data"])

        assert result.exit_code == 0
        assert mock_session.delete_repository.call_args[1]["with_data"] is True
        assert "Its graph and model were deleted too." in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_update_pulls_and_names_the_commit(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.update_repository.return_value = {"success": True, "repository": {"name": "my_repo", "last_commit": "abc1234 newer"}}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "update", "my_repo"])

        assert result.exit_code == 0
        mock_session.update_repository.assert_called_once_with("my_repo")
        assert "Commit: abc1234 newer" in result.stdout
        assert "run extraction" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_update_failure_exits_1_with_git_s_reason(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.update_repository.return_value = {"success": False, "error": "Repository has uncommitted changes: my_repo"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "update", "my_repo"])

        assert result.exit_code == 1
        assert "Repository has uncommitted changes: my_repo" in result.output

    @patch("deriva.cli.commands.repo.PipelineSession.__enter__")
    def test_repo_clone_never_prints_the_credentials_in_its_url(self, mock_enter):
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {"success": False, "error": "The git credentials were refused for this repository"}
        mock_enter.return_value = mock_session

        result = runner.invoke(app, ["repo", "clone", "https://user:s3cret@github.com/org/repo.git"])

        assert "s3cret" not in result.output
        assert "URL: https://github.com/org/repo.git" in result.output
        # The clone still gets the URL as given: the credentials are git's to use
        assert mock_session.clone_repository.call_args.kwargs["url"] == "https://user:s3cret@github.com/org/repo.git"

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_register_records_a_folder(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.register_repository.return_value = {"success": True, "name": "orphan", "branch": "main", "last_commit": "abc1234 first"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "register", "orphan"])

        assert result.exit_code == 0
        mock_session.register_repository.assert_called_once_with("orphan")
        assert "Repository 'orphan' registered" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_register_without_a_name_lists_the_unregistered_folders(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.unregistered_repositories.return_value = ["orphan"]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "register"])

        assert result.exit_code == 0
        mock_session.register_repository.assert_not_called()
        assert "orphan" in result.stdout

    @patch("deriva.cli.commands.repo.PipelineSession")
    def test_repo_list_marks_a_stale_record(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.get_repositories.return_value = [{"name": "gone", "stale": "its folder is gone"}]
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["repo", "list", "--detailed"])

        assert "gone (stale: its folder is gone; delete removes the record only)" in result.stdout

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


class TestConfigAddCommand:
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_adds_step(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.add_derivation_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "add", "derivation", "joint_consistency", "--phase", "refine", "--sequence", "4", "--params", '{"dry_run": true}'])

        assert result.exit_code == 0
        mock_session.add_derivation_step.assert_called_once_with("joint_consistency", "refine", 4, params='{"dry_run": true}')
        assert "Added derivation step: joint_consistency (disabled)" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_existing_step_exits_1(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.add_derivation_step.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "add", "derivation", "graph_relationships", "--phase", "refine", "--sequence", "4"])

        assert result.exit_code == 1

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_invalid_values_exit_1_with_the_reason(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.add_derivation_step.side_effect = ValueError("phase must be one of prep, generate, refine, relationship")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "add", "derivation", "x", "--phase", "refnie", "--sequence", "4"])

        assert result.exit_code == 1
        assert "phase must be one of" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_config_add_extraction_step(self, mock_session_class, tmp_path):
        mock_session = MagicMock()
        mock_session.add_extraction_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session
        params = tmp_path / "params.json"
        params.write_text('{"code_subtypes": ["python"]}', encoding="utf-8")

        result = runner.invoke(app, ["config", "add", "extraction", "DeployableUnit", "--sequence", "15", "--params-file", str(params)])

        assert result.exit_code == 0, result.output
        mock_session.add_extraction_step.assert_called_once_with("DeployableUnit", 15, extraction_method="structural", params='{"code_subtypes": ["python"]}')
        assert "Added extraction step: DeployableUnit (disabled)" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_config_add_derivation_step_needs_a_phase(self, mock_session_class):
        result = runner.invoke(app, ["config", "add", "derivation", "x", "--sequence", "4"])

        assert result.exit_code == 1 and "--phase" in result.output
        mock_session_class.assert_not_called()

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_a_missing_params_file_exits_1_with_the_reason(self, mock_session_class, tmp_path):
        result = runner.invoke(app, ["config", "add", "extraction", "X", "--sequence", "1", "--params-file", str(tmp_path / "missing.json")])

        assert result.exit_code == 1 and "Error reading params file" in result.output
        mock_session_class.assert_not_called()

    @pytest.mark.parametrize(
        ("args", "reason"),
        [
            (["extraction", "X", "--sequence", "1", "--phase", "refine"], "--phase"),
            (["derivation", "X", "--sequence", "1", "--phase", "refine", "--method", "llm"], "--method"),
            (["derivation", "X", "--sequence", "1", "--phase", "refine", "--params", "{}", "--params-file", "p.json"], "--params-file"),
        ],
    )
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_options_that_do_not_apply_or_conflict_exit_1(self, mock_session_class, args, reason):
        result = runner.invoke(app, ["config", "add", *args])

        assert result.exit_code == 1 and reason in result.output
        mock_session_class.assert_not_called()


class TestRepositoryDatabaseSelection:
    """Commands with --repo work in that repository's graph database."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_run_opens_repo_database(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.run_extraction.return_value = {"success": True, "stats": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session

        runner.invoke(app, ["run", "extraction", "--repo", "bigfarm", "-q"])

        assert mock_session_class.call_args.kwargs["repository"] == "bigfarm"

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_and_clear_open_repo_database(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.export_model.return_value = {"success": True, "elements_exported": 0, "relationships_exported": 0, "output_path": "x"}
        mock_session.clear_model.return_value = {"success": True}
        mock_session_class.return_value.__enter__.return_value = mock_session

        runner.invoke(app, ["export", "--repo", "bigfarm", "-o", "x.xml"])
        runner.invoke(app, ["clear", "model", "--repo", "darkgreen"])

        assert [c.kwargs["repository"] for c in mock_session_class.call_args_list] == ["bigfarm", "darkgreen"]


class TestModelConfigCommands:
    """`config model list|set|delete` edit the model configs in .env (keys shown masked)."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_list(self, mock_session_class):
        mock_session_class.return_value.list_model_configs.return_value = [
            {"name": "anthropic-haiku", "provider": "anthropic", "model": "claude-haiku", "url": None, "key": "sk-...abcd", "key_env": None}
        ]

        result = runner.invoke(app, ["config", "model", "list"])

        assert result.exit_code == 0
        assert "anthropic-haiku" in result.stdout
        assert "sk-...abcd" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_set(self, mock_session_class):
        """--key asks for the key (hidden, or from stdin): an argument would land in the shell history and the process list."""
        result = runner.invoke(app, ["config", "model", "set", "mistral-small", "--provider", "mistral", "--model", "mistral-small-latest", "--key"], input="sk-x\n")

        assert result.exit_code == 0, result.output
        mock_session_class.return_value.save_model_config.assert_called_once_with(
            "mistral-small", provider="mistral", model="mistral-small-latest", url=None, key="sk-x", key_env=None, sampling=None, reasoning=None, temperature=None, context=None
        )
        assert "sk-x" not in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_set_with_a_context_size(self, mock_session_class):
        result = runner.invoke(app, ["config", "model", "set", "ollama-qwen", "--provider", "ollama", "--model", "qwen3:8b", "--context", "8192"])

        assert result.exit_code == 0, result.output
        assert mock_session_class.return_value.save_model_config.call_args.kwargs["context"] == "8192"

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_set_takes_no_key_as_an_argument(self, mock_session_class):
        result = runner.invoke(app, ["config", "model", "set", "mistral-small", "--provider", "mistral", "--model", "mistral-small-latest", "--key", "sk-x"])

        assert result.exit_code != 0
        mock_session_class.return_value.save_model_config.assert_not_called()

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_set_without_sampling_and_with_a_reasoning_level(self, mock_session_class):
        result = runner.invoke(
            app, ["config", "model", "set", "anthropic-haiku55", "--provider", "anthropic", "--model", "claude-haiku-5-5", "--sampling", "false", "--reasoning", "none"]
        )

        assert result.exit_code == 0, result.output
        kwargs = mock_session_class.return_value.save_model_config.call_args.kwargs
        assert (kwargs["sampling"], kwargs["reasoning"]) == ("false", "none")

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_set_refused(self, mock_session_class):
        mock_session_class.return_value.save_model_config.side_effect = ValueError("Unknown provider 'nope'")

        result = runner.invoke(app, ["config", "model", "set", "m", "--provider", "nope", "--model", "x"])

        assert result.exit_code == 1
        assert "Unknown provider" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_model_delete_unknown(self, mock_session_class):
        mock_session_class.return_value.delete_model_config.side_effect = KeyError("No model config named 'm'")

        result = runner.invoke(app, ["config", "model", "delete", "m"])

        assert result.exit_code == 1


class TestSettingCommands:
    """`config setting show|set` read and write system settings through the session."""

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_setting_show(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.get_setting.return_value = '[".git", "node_modules"]'
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "setting", "show", "excluded_directories"])

        assert result.exit_code == 0
        assert "node_modules" in result.stdout
        mock_session.get_setting.assert_called_once_with("excluded_directories")

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_setting_show_missing(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.get_setting.return_value = None
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "setting", "show", "nope"])

        assert result.exit_code == 1

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_setting_set(self, mock_session_class):
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "setting", "set", "excluded_directories", '[".git"]'])

        assert result.exit_code == 0
        mock_session.set_setting.assert_called_once_with("excluded_directories", '[".git"]')

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_setting_set_invalid_value_exits_1(self, mock_session_class):
        mock_session = MagicMock()
        mock_session.set_setting.side_effect = ValueError("excluded_directories must be a JSON list of directory names")
        mock_session_class.return_value.__enter__.return_value = mock_session

        result = runner.invoke(app, ["config", "setting", "set", "excluded_directories", "node_modules"])

        assert result.exit_code == 1
        assert "JSON list" in result.output


class TestUpdateTemperature:
    """The LLM temperature of a step is a versioned column, settable from the CLI."""

    @pytest.mark.parametrize("step_type", ["derivation", "extraction"])
    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_temperature_is_passed_to_the_new_version(self, mock_session_class, mock_config, step_type):
        mock_session_class.return_value.__enter__.return_value = MagicMock()
        for fn in (mock_config.create_derivation_config_version, mock_config.create_extraction_config_version):
            fn.return_value = {"success": True, "old_version": 1, "new_version": 2}

        result = runner.invoke(app, ["config", "update", step_type, "Step", "--temperature", "0"])

        assert result.exit_code == 0
        fn = mock_config.create_derivation_config_version if step_type == "derivation" else mock_config.create_extraction_config_version
        assert fn.call_args.kwargs["temperature"] == 0.0


class TestConfigPatternCommands:
    """``config pattern`` lists, adds and removes a derivation step's name patterns."""

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_list_prints_the_rows(self, mock_session_class, mock_config):
        mock_config.list_derivation_patterns.return_value = [{"step_name": "Alpha", "pattern_type": "include", "pattern_category": "first", "patterns": ["a", "b"]}]

        result = runner.invoke(app, ["config", "pattern", "list", "Alpha"])

        assert result.exit_code == 0
        mock_config.list_derivation_patterns.assert_called_once_with(mock_session_class.return_value.__enter__.return_value._engine, "Alpha")
        assert "Alpha" in result.stdout and "include" in result.stdout and "first" in result.stdout and "a, b" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_add_merges_into_the_category(self, mock_session_class, mock_config):
        mock_config.list_derivation_patterns.return_value = [{"step_name": "Alpha", "pattern_type": "include", "pattern_category": "first", "patterns": ["a"]}]

        result = runner.invoke(app, ["config", "pattern", "add", "Alpha", "include", "first", "b", "a"])

        assert result.exit_code == 0
        engine = mock_session_class.return_value.__enter__.return_value._engine
        mock_config.update_derivation_patterns.assert_called_once_with(engine, "Alpha", "include", "first", ["a", "b"])

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_delete_removes_patterns_or_whole_categories(self, mock_session_class, mock_config):
        mock_config.remove_derivation_patterns.return_value = 2

        result = runner.invoke(app, ["config", "pattern", "delete", "Alpha", "include"])

        assert result.exit_code == 0
        engine = mock_session_class.return_value.__enter__.return_value._engine
        mock_config.remove_derivation_patterns.assert_called_once_with(engine, "Alpha", "include", None, None)
        assert "2" in result.stdout

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_delete_with_category_and_patterns(self, mock_session_class, mock_config):
        mock_config.remove_derivation_patterns.return_value = 1

        result = runner.invoke(app, ["config", "pattern", "delete", "Alpha", "include", "--category", "first", "a"])

        assert result.exit_code == 0
        engine = mock_session_class.return_value.__enter__.return_value._engine
        mock_config.remove_derivation_patterns.assert_called_once_with(engine, "Alpha", "include", "first", ["a"])

    @patch("deriva.cli.commands.config.config")
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_delete_that_changes_nothing_fails(self, mock_session_class, mock_config):
        mock_config.remove_derivation_patterns.return_value = 0

        result = runner.invoke(app, ["config", "pattern", "delete", "Alpha", "include"])

        assert result.exit_code == 1


class TestFullRunsStartEmpty:
    """A full derivation run starts from an empty model (setting derivation_clear_model, default on); partial runs keep it."""

    @staticmethod
    def _session(mock_session_class, mock_progress, setting=None):
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.get_setting.return_value = setting
        mock_session.run_derivation.return_value = {"success": True, "stats": {}}
        mock_session.run_pipeline.return_value = {"success": True, "results": {}}
        mock_session_class.return_value.__enter__.return_value = mock_session
        reporter = MagicMock()
        reporter.__enter__ = MagicMock(return_value=reporter)
        reporter.__exit__ = MagicMock(return_value=False)
        mock_progress.return_value = reporter
        return mock_session

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_a_full_derivation_run_clears_the_model_first(self, mock_session_class, mock_progress):
        session = self._session(mock_session_class, mock_progress)

        result = runner.invoke(app, ["run", "derivation"])

        assert result.exit_code == 0
        session.clear_model.assert_called_once()
        assert "Model cleared" in result.stdout
        names = [c[0] for c in session.method_calls]
        assert names.index("clear_model") < names.index("run_derivation")

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_a_full_pipeline_run_clears_the_model_first(self, mock_session_class, mock_progress):
        session = self._session(mock_session_class, mock_progress)

        result = runner.invoke(app, ["run", "all"])

        assert result.exit_code == 0
        names = [c[0] for c in session.method_calls]
        assert names.index("clear_model") < names.index("run_pipeline")

    @pytest.mark.parametrize("args", [["run", "derivation", "--phase", "refine"], ["run", "derivation", "--only-step", "ApplicationComponent"], ["run", "extraction"]])
    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_partial_and_extraction_runs_keep_the_model(self, mock_session_class, mock_progress, args):
        session = self._session(mock_session_class, mock_progress)
        session.run_extraction.return_value = {"success": True, "stats": {}}

        result = runner.invoke(app, args)

        assert result.exit_code == 0
        session.clear_model.assert_not_called()

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_a_full_run_keeps_the_model_when_the_setting_is_off(self, mock_session_class, mock_progress):
        session = self._session(mock_session_class, mock_progress, setting="false")

        result = runner.invoke(app, ["run", "derivation"])

        assert result.exit_code == 0
        session.clear_model.assert_not_called()


class TestModelDefaultCommand:
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_sets_the_default_model(self, mock_session_class):
        result = runner.invoke(app, ["config", "model", "default", "mistral-small4"])

        assert result.exit_code == 0, result.output
        mock_session_class.return_value.set_default_model.assert_called_once_with("mistral-small4")
        assert "mistral-small4" in result.stdout

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_an_unknown_model_is_refused(self, mock_session_class):
        mock_session_class.return_value.set_default_model.side_effect = KeyError("No model config named 'nope'")

        result = runner.invoke(app, ["config", "model", "default", "nope"])

        assert result.exit_code == 1

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_the_list_marks_the_default(self, mock_session_class):
        mock_session_class.return_value.list_model_configs.return_value = [
            {"name": "mistral-small4", "provider": "mistral", "model": "mistral-small-2603", "url": None, "key": None, "key_env": "MISTRAL_API_KEY", "default": True},
            {"name": "openai-gpt6luna", "provider": "openai", "model": "gpt-6-luna", "url": None, "key": None, "key_env": None, "default": False},
        ]

        result = runner.invoke(app, ["config", "model", "list"])

        assert result.exit_code == 0
        (marked,) = [line for line in result.stdout.splitlines() if "(default)" in line]
        assert "mistral-small4" in marked


@patch("deriva.cli.cli.derivation.start_full_derivation")
@patch("deriva.cli.cli.PipelineSession")
def test_run_all_without_a_configured_model_keeps_the_model(mock_session_class, clear):
    """Without a model nothing can be derived again, so the full run does not start from an empty model."""
    mock_session = MagicMock()
    mock_session.llm_info = None
    mock_session.run_pipeline.return_value = {"success": True, "results": {}}
    mock_session_class.return_value.__enter__.return_value = mock_session

    result = runner.invoke(app, ["run", "all"])

    assert result.exit_code == 0, result.output
    clear.assert_not_called()


@patch("deriva.cli.commands.config.PipelineSession")
def test_model_set_refuses_an_empty_key(mock_session_class):
    result = runner.invoke(app, ["config", "model", "set", "mistral-small", "--provider", "mistral", "--model", "mistral-small-latest", "--key"], input="\n")

    assert result.exit_code != 0
    mock_session_class.return_value.save_model_config.assert_not_called()


class TestDisabledCountSummary:
    """The run summaries show how many elements refine disabled."""

    def test_derivation_result_prints_disabled_count(self, capsys):
        result = {
            "stats": {
                "elements_created": 9,
                "relationships_created": 3,
                "elements_disabled": 4,
            }
        }
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "Elements disabled by refine: 4" in output

    def test_derivation_result_omits_disabled_count_when_zero(self, capsys):
        result = {"stats": {"elements_created": 5, "elements_disabled": 0}}
        _print_derivation_result(result)
        output = capsys.readouterr().out

        assert "disabled" not in output

    def test_pipeline_result_prints_disabled_count(self, capsys):
        result = {
            "results": {
                "derivation": {"stats": {"elements_created": 9, "elements_disabled": 4}},
            }
        }
        _print_pipeline_result(result)
        output = capsys.readouterr().out

        assert "Elements disabled by refine: 4" in output


class TestMainEntryPoint:
    """Tests for the main() entry point."""

    def test_main_keeps_the_pydantic_ai_banner_out(self, monkeypatch):
        """The CLI sets PYDANTIC_AI_NO_BANNER so the banner stays out of its output."""
        monkeypatch.delenv("PYDANTIC_AI_NO_BANNER", raising=False)
        with patch("deriva.cli.cli.app") as app_mock:
            assert main() == 0

        assert os.environ["PYDANTIC_AI_NO_BANNER"] == "1"
        app_mock.assert_called_once_with()

    def test_main_keeps_a_user_set_value(self, monkeypatch):
        """A value the user set themselves wins (setdefault, not overwrite)."""
        monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "0")
        with patch("deriva.cli.cli.app"):
            assert main() == 0

        assert os.environ["PYDANTIC_AI_NO_BANNER"] == "0"


class TestConfigRestore:
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_restore_names_the_new_version(self, mock_session_class):
        session = mock_session_class.return_value.__enter__.return_value
        session.restore_config_version.return_value = {"success": True, "old_version": 9, "new_version": 10, "restored": 7}

        result = runner.invoke(app, ["config", "restore", "derivation", "Node", "7"])

        assert result.exit_code == 0, result.output
        session.restore_config_version.assert_called_once_with("derivation", "Node", 7)
        assert "Node: version 7 restored as v10 (was v9)" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_restore_failure_exits_1(self, mock_session_class):
        session = mock_session_class.return_value.__enter__.return_value
        session.restore_config_version.return_value = {"success": False, "error": "Node has no version 9"}

        result = runner.invoke(app, ["config", "restore", "derivation", "Node", "9"])

        assert result.exit_code == 1
        assert "Node has no version 9" in result.output


class TestConfigModelTest:
    @patch("deriva.cli.commands.config.PipelineSession")
    def test_a_working_model_prints_its_latency(self, mock_session_class):
        mock_session_class.return_value.check_model_config.return_value = {
            "ok": True,
            "model": "mistral-small4",
            "provider": "mistral",
            "model_id": "mistral-small-2603",
            "served_model": "mistral-small-2603",
            "latency_ms": 812.4,
            "answer": "OK",
        }

        result = runner.invoke(app, ["config", "model", "test", "mistral-small4"])

        assert result.exit_code == 0, result.output
        assert "mistral-small4 works: mistral-small-2603 answered in 0.8 s" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_a_failing_model_says_what_to_fix_and_exits_1(self, mock_session_class):
        mock_session_class.return_value.check_model_config.return_value = {
            "ok": False,
            "model": "m",
            "provider": "mistral",
            "model_id": "x",
            "error": "The provider refused the API key: check the key (ModelHTTPError)",
            "detail": "401",
        }

        result = runner.invoke(app, ["config", "model", "test", "m"])

        assert result.exit_code == 1
        assert "The provider refused the API key" in result.output

    @patch("deriva.cli.commands.config.PipelineSession")
    def test_an_unknown_model_exits_1(self, mock_session_class):
        mock_session_class.return_value.check_model_config.side_effect = KeyError("nope")

        result = runner.invoke(app, ["config", "model", "test", "nope"])

        assert result.exit_code == 1
        assert "No model config named nope" in result.output
