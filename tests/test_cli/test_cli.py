"""Tests for cli.cli module."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from deriva.cli.cli import (
    _get_run_stats_from_ocel,
    _print_derivation_result,
    _print_extraction_result,
    _print_pipeline_result,
    cmd_clear,
    cmd_config_disable,
    cmd_config_enable,
    cmd_config_list,
    cmd_config_show,
    cmd_config_versions,
    cmd_export,
    cmd_repo_clone,
    cmd_repo_delete,
    cmd_repo_info,
    cmd_repo_list,
    cmd_status,
    create_parser,
    main,
)


class TestCreateParser:
    """Tests for argument parser creation."""

    def test_creates_parser(self):
        """Should create argument parser."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_run_command_exists(self):
        """Should parse run command."""
        parser = create_parser()
        args = parser.parse_args(["run", "extraction"])
        assert args.command == "run"
        assert args.stage == "extraction"

    def test_run_command_with_options(self):
        """Should parse run command with options."""
        parser = create_parser()
        args = parser.parse_args(["run", "derivation", "--phase", "enrich", "-v"])
        assert args.stage == "derivation"
        assert args.phase == "enrich"
        assert args.verbose is True

    def test_config_list_command(self):
        """Should parse config list command."""
        parser = create_parser()
        args = parser.parse_args(["config", "list", "extraction"])
        assert args.command == "config"
        assert args.config_action == "list"
        assert args.step_type == "extraction"

    def test_repo_clone_command(self):
        """Should parse repo clone command."""
        parser = create_parser()
        args = parser.parse_args(["repo", "clone", "https://github.com/user/repo"])
        assert args.command == "repo"
        assert args.repo_action == "clone"
        assert args.url == "https://github.com/user/repo"

    def test_clear_command(self):
        """Should parse clear command."""
        parser = create_parser()
        args = parser.parse_args(["clear", "graph"])
        assert args.command == "clear"
        assert args.target == "graph"

    def test_export_command_with_options(self):
        """Should parse export command with options."""
        parser = create_parser()
        args = parser.parse_args(["export", "-o", "out.archimate", "-n", "MyModel"])
        assert args.command == "export"
        assert args.output == "out.archimate"
        assert args.name == "MyModel"

    def test_benchmark_run_command(self):
        """Should parse benchmark run command."""
        parser = create_parser()
        args = parser.parse_args(["benchmark", "run", "--repos", "repo1,repo2", "--models", "gpt4,claude"])
        assert args.command == "benchmark"
        assert args.benchmark_action == "run"
        assert args.repos == "repo1,repo2"
        assert args.models == "gpt4,claude"


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


class TestPrintExtractionResultAdditional:
    """Additional tests for _print_extraction_result helper."""

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


class TestPrintDerivationResultAdditional:
    """Additional tests for _print_derivation_result helper."""

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


class TestMain:
    """Tests for main entry point."""

    def test_no_command_shows_help(self, capsys):
        """Should show help when no command provided."""
        with patch("sys.argv", ["deriva"]):
            result = main()
        assert result == 0


class TestCmdConfigList:
    """Tests for cmd_config_list command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_lists_extraction_configs(self, mock_session_class, capsys):
        """Should list extraction configurations."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = [
            {"name": "BusinessConcept", "enabled": True, "sequence": 1},
            {"name": "TypeDefinition", "enabled": False, "sequence": 2},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="extraction", enabled=False)
        result = cmd_config_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "EXTRACTION CONFIGURATIONS" in output
        assert "BusinessConcept" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_message_when_no_configs(self, mock_session_class, capsys):
        """Should show message when no configurations found."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="derivation", enabled=False)
        result = cmd_config_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "No derivation configurations found" in output


class TestCmdConfigShow:
    """Tests for cmd_config_show command."""

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_extraction_config(self, mock_session_class, mock_config, capsys):
        """Should show extraction config details."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.get_extraction_config.return_value = MagicMock(
            node_type="BusinessConcept",
            sequence=1,
            enabled=True,
            input_sources="*.py",
            instruction="Extract business concepts",
            example="{}",
        )

        args = argparse.Namespace(step_type="extraction", name="BusinessConcept")
        result = cmd_config_show(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "EXTRACTION CONFIG: BusinessConcept" in output

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_derivation_config(self, mock_session_class, mock_config, capsys):
        """Should show derivation config details."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.get_derivation_config.return_value = MagicMock(
            element_type="ApplicationComponent",
            sequence=1,
            enabled=True,
            input_graph_query="MATCH (n) RETURN n",
            instruction="Derive components",
        )

        args = argparse.Namespace(step_type="derivation", name="ApplicationComponent")
        result = cmd_config_show(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "DERIVATION CONFIG: ApplicationComponent" in output

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_returns_error_when_config_not_found(self, mock_session_class, mock_config, capsys):
        """Should return error when config not found."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.get_extraction_config.return_value = None

        args = argparse.Namespace(step_type="extraction", name="NonExistent")
        result = cmd_config_show(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "not found" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_returns_error_for_unknown_step_type(self, mock_session_class, capsys):
        """Should return error for unknown step type."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="unknown", name="test")
        result = cmd_config_show(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "Unknown step type" in output


class TestCmdConfigEnableDisable:
    """Tests for cmd_config_enable and cmd_config_disable commands."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_enable_step_success(self, mock_session_class, capsys):
        """Should enable step successfully."""
        mock_session = MagicMock()
        mock_session.enable_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="extraction", name="BusinessConcept")
        result = cmd_config_enable(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Enabled" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_enable_step_not_found(self, mock_session_class, capsys):
        """Should return error when step not found."""
        mock_session = MagicMock()
        mock_session.enable_step.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="extraction", name="NonExistent")
        result = cmd_config_enable(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "not found" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_disable_step_success(self, mock_session_class, capsys):
        """Should disable step successfully."""
        mock_session = MagicMock()
        mock_session.disable_step.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(step_type="derivation", name="ApplicationComponent")
        result = cmd_config_disable(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Disabled" in output


class TestCmdConfigVersions:
    """Tests for cmd_config_versions command."""

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_active_versions(self, mock_session_class, mock_config, capsys):
        """Should show active config versions."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.get_active_config_versions.return_value = {
            "extraction": {"BusinessConcept": 2, "TypeDefinition": 1},
            "derivation": {"ApplicationComponent": 3},
        }

        args = argparse.Namespace()
        result = cmd_config_versions(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "ACTIVE CONFIG VERSIONS" in output


class TestCmdClear:
    """Tests for cmd_clear command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_graph_success(self, mock_session_class, capsys):
        """Should clear graph successfully."""
        mock_session = MagicMock()
        mock_session.clear_graph.return_value = {"success": True, "message": "Graph cleared"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(target="graph")
        result = cmd_clear(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Graph cleared" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_model_success(self, mock_session_class, capsys):
        """Should clear model successfully."""
        mock_session = MagicMock()
        mock_session.clear_model.return_value = {"success": True, "message": "Model cleared"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(target="model")
        result = cmd_clear(args)

        assert result == 0

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_unknown_target(self, mock_session_class, capsys):
        """Should return error for unknown target."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(target="unknown")
        result = cmd_clear(args)

        assert result == 1

    @patch("deriva.cli.cli.PipelineSession")
    def test_clear_failure(self, mock_session_class, capsys):
        """Should return error on failure."""
        mock_session = MagicMock()
        mock_session.clear_graph.return_value = {"success": False, "error": "Connection failed"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(target="graph")
        result = cmd_clear(args)

        assert result == 1


class TestCmdStatus:
    """Tests for cmd_status command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_status(self, mock_session_class, capsys):
        """Should show pipeline status."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = [{"enabled": True}, {"enabled": False}]
        mock_session.get_file_types.return_value = ["py", "js", "ts"]
        mock_session.get_graph_stats.return_value = {"total_nodes": 100}
        mock_session.get_archimate_stats.return_value = {"total_elements": 50}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace()
        result = cmd_status(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "DERIVA STATUS" in output
        assert "1/2 steps enabled" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_handles_graph_connection_error(self, mock_session_class, capsys):
        """Should handle graph connection error gracefully."""
        mock_session = MagicMock()
        mock_session.list_steps.return_value = []
        mock_session.get_file_types.return_value = []
        mock_session.get_graph_stats.side_effect = Exception("Not connected")
        mock_session.get_archimate_stats.side_effect = Exception("Not connected")
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace()
        result = cmd_status(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "(not connected)" in output


class TestCmdExport:
    """Tests for cmd_export command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_success(self, mock_session_class, capsys):
        """Should export model successfully."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {
            "success": True,
            "elements_exported": 50,
            "relationships_exported": 30,
            "output_path": "/path/to/model.archimate",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(output="out.archimate", name="MyModel", verbose=False)
        result = cmd_export(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Elements exported: 50" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_export_failure(self, mock_session_class, capsys):
        """Should return error on export failure."""
        mock_session = MagicMock()
        mock_session.export_model.return_value = {"success": False, "error": "No elements to export"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(output="out.archimate", name="MyModel", verbose=False)
        result = cmd_export(args)

        assert result == 1


class TestCmdRepoClone:
    """Tests for cmd_repo_clone command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_clone_success(self, mock_session_class, capsys):
        """Should clone repository successfully."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "my_repo",
            "path": "/workspace/repos/my_repo",
            "url": "https://github.com/user/repo",
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            url="https://github.com/user/repo",
            name=None,
            branch=None,
            overwrite=False,
        )
        result = cmd_repo_clone(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "cloned successfully" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_clone_failure(self, mock_session_class, capsys):
        """Should return error on clone failure."""
        mock_session = MagicMock()
        mock_session.clone_repository.return_value = {"success": False, "error": "Repository not found"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            url="https://github.com/user/nonexistent",
            name=None,
            branch=None,
            overwrite=False,
        )
        result = cmd_repo_clone(args)

        assert result == 1


class TestCmdRepoList:
    """Tests for cmd_repo_list command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_lists_repositories(self, mock_session_class, capsys):
        """Should list repositories."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = [
            {"name": "repo1"},
            {"name": "repo2"},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(detailed=False)
        result = cmd_repo_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "REPOSITORIES" in output
        assert "repo1" in output
        assert "Total: 2 repositories" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_lists_detailed_repositories(self, mock_session_class, capsys):
        """Should list repositories with details."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = [
            {
                "name": "repo1",
                "url": "https://github.com/user/repo1",
                "branch": "main",
                "size_mb": 10.5,
                "cloned_at": "2024-01-01",
                "is_dirty": False,
            },
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(detailed=True)
        result = cmd_repo_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "URL:" in output
        assert "Branch:" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_message_when_no_repos(self, mock_session_class, capsys):
        """Should show message when no repositories."""
        mock_session = MagicMock()
        mock_session.workspace_dir = "/workspace"
        mock_session.get_repositories.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(detailed=False)
        result = cmd_repo_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "No repositories found" in output


class TestCmdRepoDelete:
    """Tests for cmd_repo_delete command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_delete_success(self, mock_session_class, capsys):
        """Should delete repository successfully."""
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {"success": True}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(name="my_repo", force=False)
        result = cmd_repo_delete(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "deleted successfully" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_delete_failure(self, mock_session_class, capsys):
        """Should return error on delete failure."""
        mock_session = MagicMock()
        mock_session.delete_repository.return_value = {"success": False, "error": "Not found"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(name="nonexistent", force=False)
        result = cmd_repo_delete(args)

        assert result == 1

    @patch("deriva.cli.cli.PipelineSession")
    def test_delete_exception(self, mock_session_class, capsys):
        """Should handle exception during delete."""
        mock_session = MagicMock()
        mock_session.delete_repository.side_effect = Exception("uncommitted changes detected")
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(name="dirty_repo", force=False)
        result = cmd_repo_delete(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "--force" in output


class TestCmdRepoInfo:
    """Tests for cmd_repo_info command."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_shows_repo_info(self, mock_session_class, capsys):
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

        args = argparse.Namespace(name="my_repo")
        result = cmd_repo_info(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "REPOSITORY: my_repo" in output
        assert "Path:" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_repo_not_found(self, mock_session_class, capsys):
        """Should return error when repo not found."""
        mock_session = MagicMock()
        mock_session.get_repository_info.return_value = None
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(name="nonexistent")
        result = cmd_repo_info(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "not found" in output


class TestGetRunStatsFromOcel:
    """Tests for _get_run_stats_from_ocel helper."""

    def test_extracts_stats_from_complete_run_events(self):
        """Should extract node/edge counts from CompleteRun events."""
        mock_analyzer = MagicMock()

        # Create mock events
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


class TestCreateParserAdditional:
    """Additional tests for argument parser creation."""

    def test_status_command(self):
        """Should parse status command."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_config_enable_command(self):
        """Should parse config enable command."""
        parser = create_parser()
        args = parser.parse_args(["config", "enable", "extraction", "BusinessConcept"])
        assert args.config_action == "enable"
        assert args.step_type == "extraction"
        assert args.name == "BusinessConcept"

    def test_config_disable_command(self):
        """Should parse config disable command."""
        parser = create_parser()
        args = parser.parse_args(["config", "disable", "derivation", "ApplicationComponent"])
        assert args.config_action == "disable"
        assert args.name == "ApplicationComponent"

    def test_config_show_command(self):
        """Should parse config show command."""
        parser = create_parser()
        args = parser.parse_args(["config", "show", "extraction", "TypeDefinition"])
        assert args.config_action == "show"
        assert args.name == "TypeDefinition"

    def test_config_update_command(self):
        """Should parse config update command."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "config",
                "update",
                "derivation",
                "ApplicationComponent",
                "-i",
                "New instruction",
            ]
        )
        assert args.config_action == "update"
        assert args.instruction == "New instruction"

    def test_config_versions_command(self):
        """Should parse config versions command."""
        parser = create_parser()
        args = parser.parse_args(["config", "versions"])
        assert args.config_action == "versions"

    def test_repo_list_detailed(self):
        """Should parse repo list with detailed flag."""
        parser = create_parser()
        args = parser.parse_args(["repo", "list", "-d"])
        assert args.detailed is True

    def test_repo_delete_force(self):
        """Should parse repo delete with force flag."""
        parser = create_parser()
        args = parser.parse_args(["repo", "delete", "my_repo", "-f"])
        assert args.force is True

    def test_benchmark_list_command(self):
        """Should parse benchmark list command."""
        parser = create_parser()
        args = parser.parse_args(["benchmark", "list", "-l", "20"])
        assert args.benchmark_action == "list"
        assert args.limit == 20

    def test_benchmark_analyze_command(self):
        """Should parse benchmark analyze command."""
        parser = create_parser()
        args = parser.parse_args(["benchmark", "analyze", "session_123", "-f", "markdown"])
        assert args.benchmark_action == "analyze"
        assert args.session_id == "session_123"
        assert args.format == "markdown"

    def test_benchmark_models_command(self):
        """Should parse benchmark models command."""
        parser = create_parser()
        args = parser.parse_args(["benchmark", "models"])
        assert args.benchmark_action == "models"

    def test_benchmark_deviations_command(self):
        """Should parse benchmark deviations command."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "benchmark",
                "deviations",
                "session_123",
                "-s",
                "consistency_score",
            ]
        )
        assert args.benchmark_action == "deviations"
        assert args.sort_by == "consistency_score"

    def test_run_with_quiet_flag(self):
        """Should parse run with quiet flag."""
        parser = create_parser()
        args = parser.parse_args(["run", "extraction", "-q"])
        assert args.quiet is True

    def test_run_with_no_llm_flag(self):
        """Should parse run with no-llm flag."""
        parser = create_parser()
        args = parser.parse_args(["run", "extraction", "--no-llm"])
        assert args.no_llm is True

    def test_benchmark_run_with_all_options(self):
        """Should parse benchmark run with all options."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "benchmark",
                "run",
                "--repos",
                "repo1,repo2",
                "--models",
                "gpt4,claude",
                "-n",
                "5",
                "--stages",
                "extraction,derivation",
                "-d",
                "Test benchmark",
                "--no-cache",
                "--nocache-configs",
                "ApplicationComponent,DataObject",
            ]
        )
        assert args.runs == 5
        assert args.stages == "extraction,derivation"
        assert args.description == "Test benchmark"
        assert args.no_cache is True
        assert args.nocache_configs == "ApplicationComponent,DataObject"


# Additional CLI imports for new tests
from deriva.cli.cli import (
    cmd_config_update,
    cmd_filetype_add,
    cmd_filetype_delete,
    cmd_filetype_list,
    cmd_filetype_stats,
    cmd_run,
)


class TestCmdConfigUpdate:
    """Tests for cmd_config_update command."""

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_update_derivation_config_success(self, mock_session_class, mock_config, capsys):
        """Should update derivation config successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        args = argparse.Namespace(
            step_type="derivation",
            name="ApplicationComponent",
            instruction="New instruction",
            example=None,
            instruction_file=None,
            example_file=None,
            query=None,
            sources=None,
        )
        result = cmd_config_update(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Updated" in output
        assert "Version: 1 -> 2" in output

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_update_extraction_config_success(self, mock_session_class, mock_config, capsys):
        """Should update extraction config successfully."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_extraction_config_version.return_value = {
            "success": True,
            "old_version": 1,
            "new_version": 2,
        }

        args = argparse.Namespace(
            step_type="extraction",
            name="BusinessConcept",
            instruction="New instruction",
            example=None,
            instruction_file=None,
            example_file=None,
            query=None,
            sources="*.py",
        )
        result = cmd_config_update(args)

        assert result == 0

    @patch("deriva.cli.cli.config")
    @patch("deriva.cli.cli.PipelineSession")
    def test_update_config_failure(self, mock_session_class, mock_config, capsys):
        """Should return error on update failure."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_config.create_derivation_config_version.return_value = {
            "success": False,
            "error": "Config not found",
        }

        args = argparse.Namespace(
            step_type="derivation",
            name="Unknown",
            instruction="New instruction",
            example=None,
            instruction_file=None,
            example_file=None,
            query=None,
            sources=None,
        )
        result = cmd_config_update(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "Error" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_update_unknown_step_type(self, mock_session_class, capsys):
        """Should return error for unknown step type."""
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            step_type="unknown",
            name="test",
            instruction="New instruction",
            example=None,
            instruction_file=None,
            example_file=None,
            query=None,
            sources=None,
        )
        result = cmd_config_update(args)

        assert result == 1


class TestCmdFiletype:
    """Tests for file type commands."""

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_list_success(self, mock_session_class, capsys):
        """Should list file types."""
        mock_session = MagicMock()
        mock_session.get_file_types.return_value = [
            {"extension": ".py", "file_type": "code", "subtype": "python"},
            {"extension": ".js", "file_type": "code", "subtype": "javascript"},
        ]
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace()
        result = cmd_filetype_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "FILE TYPE REGISTRY" in output
        assert ".py" in output
        assert "python" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_list_empty(self, mock_session_class, capsys):
        """Should show message when no file types."""
        mock_session = MagicMock()
        mock_session.get_file_types.return_value = []
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace()
        result = cmd_filetype_list(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "No file types registered" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_add_success(self, mock_session_class, capsys):
        """Should add file type successfully."""
        mock_session = MagicMock()
        mock_session.add_file_type.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            extension=".rs",
            file_type="code",
            subtype="rust",
        )
        result = cmd_filetype_add(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Added file type" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_add_failure(self, mock_session_class, capsys):
        """Should return error when add fails."""
        mock_session = MagicMock()
        mock_session.add_file_type.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            extension=".py",
            file_type="code",
            subtype="python",
        )
        result = cmd_filetype_add(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "Failed to add" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_delete_success(self, mock_session_class, capsys):
        """Should delete file type successfully."""
        mock_session = MagicMock()
        mock_session.delete_file_type.return_value = True
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(extension=".rs")
        result = cmd_filetype_delete(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Deleted file type" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_delete_not_found(self, mock_session_class, capsys):
        """Should return error when file type not found."""
        mock_session = MagicMock()
        mock_session.delete_file_type.return_value = False
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(extension=".xyz")
        result = cmd_filetype_delete(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "not found" in output

    @patch("deriva.cli.cli.PipelineSession")
    def test_filetype_stats(self, mock_session_class, capsys):
        """Should show file type statistics."""
        mock_session = MagicMock()
        mock_session.get_file_type_stats.return_value = {
            "code": 50,
            "config": 10,
            "docs": 5,
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace()
        result = cmd_filetype_stats(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "FILE TYPE STATISTICS" in output
        assert "code" in output
        assert "Total" in output


class TestCmdRun:
    """Tests for cmd_run command."""

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_extraction(self, mock_session_class, mock_progress, capsys):
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

        args = argparse.Namespace(
            stage="extraction",
            repo=None,
            verbose=False,
            no_llm=False,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "EXTRACTION" in output

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation(self, mock_session_class, mock_progress, capsys):
        """Should run derivation stage."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 10, "relationships_created": 5},
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        args = argparse.Namespace(
            stage="derivation",
            repo=None,
            verbose=False,
            no_llm=False,
            phase="enrich",
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 0

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_derivation_without_llm(self, mock_session_class, mock_progress, capsys):
        """Should return error when running derivation without LLM."""
        mock_session = MagicMock()
        mock_session.llm_info = None  # No LLM configured
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            stage="derivation",
            repo=None,
            verbose=False,
            no_llm=False,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "Error" in output

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_all_stages(self, mock_session_class, mock_progress, capsys):
        """Should run all pipeline stages."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "results": {
                "extraction": {"stats": {"nodes_created": 100}},
                "derivation": {"stats": {"elements_created": 10}},
            },
        }
        mock_session_class.return_value.__enter__.return_value = mock_session

        mock_reporter = MagicMock()
        mock_progress.return_value = mock_reporter
        mock_reporter.__enter__ = MagicMock(return_value=mock_reporter)
        mock_reporter.__exit__ = MagicMock(return_value=False)

        args = argparse.Namespace(
            stage="all",
            repo=None,
            verbose=False,
            no_llm=False,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 0

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_unknown_stage(self, mock_session_class, mock_progress, capsys):
        """Should return error for unknown stage."""
        mock_session = MagicMock()
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session_class.return_value.__enter__.return_value = mock_session

        args = argparse.Namespace(
            stage="unknown",
            repo=None,
            verbose=False,
            no_llm=False,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 1
        output = capsys.readouterr().out
        assert "Unknown stage" in output

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_with_repo_name(self, mock_session_class, mock_progress, capsys):
        """Should run extraction with specific repository."""
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

        args = argparse.Namespace(
            stage="extraction",
            repo="my_repo",
            verbose=False,
            no_llm=False,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "Repository: my_repo" in output

    @patch("deriva.cli.cli.create_progress_reporter")
    @patch("deriva.cli.cli.PipelineSession")
    def test_run_with_no_llm_flag(self, mock_session_class, mock_progress, capsys):
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

        args = argparse.Namespace(
            stage="extraction",
            repo=None,
            verbose=False,
            no_llm=True,
            phase=None,
            quiet=False,
        )
        result = cmd_run(args)

        assert result == 0
        output = capsys.readouterr().out
        assert "LLM disabled" in output
