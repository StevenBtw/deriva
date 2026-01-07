"""Integration tests for CLI with mock repository.

These tests create a small mock repository and test CLI commands
against it, with database connections mocked.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from deriva.cli.cli import (
    cmd_clear,
    cmd_config_disable,
    cmd_config_enable,
    cmd_config_list,
    cmd_config_show,
    cmd_config_versions,
    cmd_export,
    cmd_repo_list,
    cmd_run,
    cmd_status,
    create_parser,
    main,
)


class MockRepository:
    """Creates a mock repository structure for testing."""

    def __init__(self, root_path: Path):
        self.root = root_path
        self.name = "mock_project"
        self._create_structure()

    def _create_structure(self):
        """Create a minimal Python project structure."""
        # Create directory structure
        (self.root / "src").mkdir()
        (self.root / "src" / "models").mkdir()
        (self.root / "src" / "api").mkdir()
        (self.root / "tests").mkdir()

        # Create Python files
        (self.root / "src" / "__init__.py").write_text("")
        (self.root / "src" / "main.py").write_text('''"""Main entry point."""

def main():
    """Run the application."""
    print("Hello, World!")

if __name__ == "__main__":
    main()
''')
        (self.root / "src" / "models" / "__init__.py").write_text("")
        (self.root / "src" / "models" / "user.py").write_text('''"""User model."""

class User:
    """Represents a user in the system."""

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    def validate(self) -> bool:
        """Validate user data."""
        return bool(self.name and "@" in self.email)
''')
        (self.root / "src" / "api" / "__init__.py").write_text("")
        (self.root / "src" / "api" / "routes.py").write_text('''"""API routes."""

from models.user import User

def get_user(user_id: int) -> User:
    """Get a user by ID."""
    return User("test", "test@example.com")
''')
        (self.root / "tests" / "__init__.py").write_text("")
        (self.root / "tests" / "test_user.py").write_text('''"""Tests for User model."""

import pytest
from src.models.user import User

def test_user_creation():
    """Test user creation."""
    user = User("John", "john@example.com")
    assert user.name == "John"

def test_user_validation():
    """Test user validation."""
    user = User("John", "john@example.com")
    assert user.validate() is True
''')

        # Create config files
        (self.root / "pyproject.toml").write_text("""[project]
name = "mock_project"
version = "0.1.0"
description = "A mock project for testing"
dependencies = ["fastapi>=0.100.0", "pydantic>=2.0.0"]

[project.optional-dependencies]
dev = ["pytest>=7.0.0", "black>=23.0.0"]
""")
        (self.root / "README.md").write_text("""# Mock Project

A simple mock project for testing the Deriva CLI.

## Features
- User management
- API endpoints
""")

        # Initialize git
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("[core]\n\trepositoryformatversion = 0")


class TestCreateParser:
    """Tests for CLI argument parser creation."""

    def test_creates_parser(self):
        """Should create argument parser."""
        parser = create_parser()

        assert parser is not None
        assert parser.prog == "deriva"

    def test_parser_has_config_command(self):
        """Should have config subcommand."""
        parser = create_parser()
        args = parser.parse_args(["config", "list", "extraction"])

        assert args.command == "config"
        assert args.config_action == "list"

    def test_parser_has_run_command(self):
        """Should have run subcommand."""
        parser = create_parser()
        args = parser.parse_args(["run", "extraction"])

        assert args.command == "run"
        assert args.stage == "extraction"

    def test_parser_has_repo_command(self):
        """Should have repo subcommand."""
        parser = create_parser()
        args = parser.parse_args(["repo", "list"])

        assert args.command == "repo"
        assert args.repo_action == "list"

    def test_parser_run_with_options(self):
        """Should parse run options."""
        parser = create_parser()
        args = parser.parse_args(["run", "extraction", "--repo", "myrepo", "-v"])

        assert args.stage == "extraction"
        assert args.repo == "myrepo"
        assert args.verbose is True

    def test_parser_clear_command(self):
        """Should have clear subcommand."""
        parser = create_parser()
        args = parser.parse_args(["clear", "graph"])

        assert args.command == "clear"
        assert args.target == "graph"

    def test_parser_status_command(self):
        """Should have status subcommand."""
        parser = create_parser()
        args = parser.parse_args(["status"])

        assert args.command == "status"

    def test_parser_export_command(self):
        """Should have export subcommand."""
        parser = create_parser()
        args = parser.parse_args(["export", "-o", "output.archimate"])

        assert args.command == "export"
        assert args.output == "output.archimate"


class TestCmdConfigList:
    """Tests for config list command."""

    def test_lists_extraction_steps(self):
        """Should list extraction configurations."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_steps.return_value = [
            {"name": "TypeDefinition", "enabled": True, "sequence": 1},
            {"name": "BusinessConcept", "enabled": False, "sequence": 2},
        ]

        args = argparse.Namespace(step_type="extraction", enabled=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_list(args)

        assert result == 0
        mock_session.list_steps.assert_called_once_with("extraction", enabled_only=False)

    def test_lists_only_enabled_steps(self):
        """Should filter to enabled steps only."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_steps.return_value = [
            {"name": "TypeDefinition", "enabled": True, "sequence": 1},
        ]

        args = argparse.Namespace(step_type="extraction", enabled=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_list(args)

        assert result == 0
        mock_session.list_steps.assert_called_once_with("extraction", enabled_only=True)

    def test_handles_empty_list(self):
        """Should handle no configurations found."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_steps.return_value = []

        args = argparse.Namespace(step_type="extraction", enabled=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_list(args)

        assert result == 0


class TestCmdConfigEnable:
    """Tests for config enable command."""

    def test_enables_extraction_step(self):
        """Should enable an extraction step."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.enable_step.return_value = True

        args = argparse.Namespace(step_type="extraction", name="TypeDefinition")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_enable(args)

        assert result == 0
        mock_session.enable_step.assert_called_once_with("extraction", "TypeDefinition")

    def test_returns_error_for_nonexistent_step(self):
        """Should return error for unknown step."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.enable_step.return_value = False

        args = argparse.Namespace(step_type="extraction", name="UnknownStep")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_enable(args)

        assert result == 1


class TestCmdConfigDisable:
    """Tests for config disable command."""

    def test_disables_extraction_step(self):
        """Should disable an extraction step."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.disable_step.return_value = True

        args = argparse.Namespace(step_type="extraction", name="TypeDefinition")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_disable(args)

        assert result == 0
        mock_session.disable_step.assert_called_once_with("extraction", "TypeDefinition")

    def test_returns_error_for_nonexistent_step(self):
        """Should return error for unknown step."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.disable_step.return_value = False

        args = argparse.Namespace(step_type="extraction", name="UnknownStep")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_disable(args)

        assert result == 1


class TestCmdConfigShow:
    """Tests for config show command."""

    def test_shows_extraction_config(self):
        """Should show extraction configuration details."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        mock_cfg = MagicMock()
        mock_cfg.node_type = "TypeDefinition"
        mock_cfg.sequence = 1
        mock_cfg.enabled = True
        mock_cfg.input_sources = '{"files": []}'
        mock_cfg.instruction = "Extract types"
        mock_cfg.example = '{"types": []}'

        args = argparse.Namespace(step_type="extraction", name="TypeDefinition")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch("deriva.cli.cli.config.get_extraction_config", return_value=mock_cfg):
                result = cmd_config_show(args)

        assert result == 0

    def test_shows_derivation_config(self):
        """Should show derivation configuration details."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        mock_cfg = MagicMock()
        mock_cfg.element_type = "ApplicationComponent"
        mock_cfg.sequence = 1
        mock_cfg.enabled = True
        mock_cfg.input_graph_query = "MATCH (n) RETURN n"
        mock_cfg.instruction = "Generate components"

        args = argparse.Namespace(step_type="derivation", name="ApplicationComponent")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch("deriva.cli.cli.config.get_derivation_config", return_value=mock_cfg):
                result = cmd_config_show(args)

        assert result == 0

    def test_returns_error_for_nonexistent_extraction(self):
        """Should return error for nonexistent extraction config."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        args = argparse.Namespace(step_type="extraction", name="Unknown")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch("deriva.cli.cli.config.get_extraction_config", return_value=None):
                result = cmd_config_show(args)

        assert result == 1

    def test_returns_error_for_unknown_step_type(self):
        """Should return error for unknown step type."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        args = argparse.Namespace(step_type="unknown", name="Test")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_show(args)

        assert result == 1


class TestCmdConfigVersions:
    """Tests for config versions command."""

    def test_shows_versions(self):
        """Should show active config versions."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        versions = {
            "extraction": {"TypeDefinition": 1, "BusinessConcept": 2},
            "derivation": {"ApplicationComponent": 1},
        }

        args = argparse.Namespace()

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch("deriva.cli.cli.config.get_active_config_versions", return_value=versions):
                result = cmd_config_versions(args)

        assert result == 0


class TestCmdRun:
    """Tests for run command."""

    def test_runs_extraction(self):
        """Should run extraction pipeline."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 10},
        }

        args = argparse.Namespace(stage="extraction", repo=None, verbose=False, no_llm=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0
        mock_session.run_extraction.assert_called_once()

    def test_runs_derivation(self):
        """Should run derivation pipeline."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 5},
        }

        args = argparse.Namespace(stage="derivation", repo=None, verbose=False, no_llm=False, phase=None)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0
        mock_session.run_derivation.assert_called_once()

    def test_runs_all_stages(self):
        """Should run full pipeline."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_pipeline.return_value = {
            "success": True,
            "stats": {},
        }

        args = argparse.Namespace(stage="all", repo="myrepo", verbose=True, no_llm=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0
        mock_session.run_pipeline.assert_called_once()

    def test_derivation_fails_without_llm(self):
        """Should fail derivation when LLM not configured."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = None  # No LLM configured

        args = argparse.Namespace(stage="derivation", repo=None, verbose=False, no_llm=False, phase=None)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 1


class TestCmdExport:
    """Tests for export command."""

    def test_exports_to_file(self):
        """Should export ArchiMate model to file."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.export_model.return_value = {
            "success": True,
            "output_path": "output.archimate",
            "elements_exported": 10,
            "relationships_exported": 5,
        }

        args = argparse.Namespace(output="output.archimate", name=None, verbose=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_export(args)

        assert result == 0
        mock_session.export_model.assert_called_once()

    def test_handles_export_error(self):
        """Should handle export errors."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.export_model.return_value = {"success": False, "error": "Export failed"}

        args = argparse.Namespace(output="output.archimate", name="Test Model", verbose=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_export(args)

        assert result == 1


class TestCmdRepoList:
    """Tests for repo list command."""

    def test_lists_repositories(self):
        """Should list all repositories."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repositories.return_value = [
            {"name": "repo1", "url": "https://github.com/user/repo1.git"},
            {"name": "repo2", "url": "https://github.com/user/repo2.git"},
        ]

        args = argparse.Namespace(detailed=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_list(args)

        assert result == 0
        mock_session.get_repositories.assert_called_once_with(detailed=False)

    def test_handles_no_repositories(self):
        """Should handle empty repository list."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repositories.return_value = []

        args = argparse.Namespace(detailed=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_list(args)

        assert result == 0


class TestCmdStatus:
    """Tests for status command."""

    def test_shows_status(self):
        """Should show pipeline status."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_status.return_value = {
            "neo4j": {"connected": True, "nodes": 100, "relationships": 50},
            "sqlite": {"connected": True, "repositories": 2},
            "archimate": {"elements": 10, "relationships": 5},
        }

        args = argparse.Namespace()

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_status(args)

        assert result == 0


class TestCmdClear:
    """Tests for clear command."""

    def test_clears_graph(self):
        """Should clear graph data."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        args = argparse.Namespace(target="graph")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_clear(args)

        assert result == 0
        mock_session.clear_graph.assert_called_once()

    def test_clears_model(self):
        """Should clear model data."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        args = argparse.Namespace(target="model")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_clear(args)

        assert result == 0
        mock_session.clear_model.assert_called_once()


class TestMain:
    """Tests for main CLI entry point."""

    def test_no_command_shows_help(self):
        """Should show help when no command provided."""
        with patch("sys.argv", ["deriva"]):
            result = main()

        assert result == 0

    def test_config_no_action_shows_help(self):
        """Should show help for config without action."""
        with patch("sys.argv", ["deriva", "config"]):
            with pytest.raises(SystemExit):
                main()

    def test_runs_config_list(self):
        """Should run config list command."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_steps.return_value = []

        with patch("sys.argv", ["deriva", "config", "list", "extraction"]):
            with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
                result = main()

        assert result == 0


class TestCmdRepoClone:
    """Tests for repo clone command."""

    def test_clones_repository_success(self):
        """Should clone repository successfully."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.clone_repository.return_value = {
            "success": True,
            "name": "myrepo",
            "path": "/workspace/myrepo",
            "url": "https://github.com/user/myrepo.git",
        }

        from deriva.cli.cli import cmd_repo_clone

        args = argparse.Namespace(url="https://github.com/user/myrepo.git", name=None, branch=None, overwrite=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_clone(args)

        assert result == 0
        mock_session.clone_repository.assert_called_once()

    def test_clone_with_name_and_branch(self):
        """Should clone with custom name and branch."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.clone_repository.return_value = {"success": True, "name": "custom"}

        from deriva.cli.cli import cmd_repo_clone

        args = argparse.Namespace(url="https://github.com/user/repo.git", name="custom", branch="develop", overwrite=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_clone(args)

        assert result == 0

    def test_clone_failure(self):
        """Should return error on clone failure."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.clone_repository.return_value = {"success": False, "error": "Repository already exists"}

        from deriva.cli.cli import cmd_repo_clone

        args = argparse.Namespace(url="https://github.com/user/repo.git", name=None, branch=None, overwrite=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_clone(args)

        assert result == 1


class TestCmdRepoDelete:
    """Tests for repo delete command."""

    def test_deletes_repository_success(self):
        """Should delete repository successfully."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.delete_repository.return_value = {"success": True}

        from deriva.cli.cli import cmd_repo_delete

        args = argparse.Namespace(name="myrepo", force=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_delete(args)

        assert result == 0

    def test_delete_with_force(self):
        """Should delete with force flag."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.delete_repository.return_value = {"success": True}

        from deriva.cli.cli import cmd_repo_delete

        args = argparse.Namespace(name="myrepo", force=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_delete(args)

        assert result == 0
        mock_session.delete_repository.assert_called_once_with(name="myrepo", force=True)

    def test_delete_failure(self):
        """Should return error on delete failure."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.delete_repository.return_value = {"success": False, "error": "Not found"}

        from deriva.cli.cli import cmd_repo_delete

        args = argparse.Namespace(name="nonexistent", force=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_delete(args)

        assert result == 1

    def test_delete_handles_exception(self):
        """Should handle exceptions during delete."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.delete_repository.side_effect = Exception("uncommitted changes detected")

        from deriva.cli.cli import cmd_repo_delete

        args = argparse.Namespace(name="dirty_repo", force=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_delete(args)

        assert result == 1


class TestCmdRepoInfo:
    """Tests for repo info command."""

    def test_shows_repository_info(self):
        """Should show repository information."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repository_info.return_value = {
            "name": "myrepo",
            "path": "/workspace/myrepo",
            "url": "https://github.com/user/myrepo.git",
            "branch": "main",
            "last_commit": "abc123",
            "is_dirty": False,
            "size_mb": 5.5,
            "cloned_at": "2024-01-01T10:00:00",
        }

        from deriva.cli.cli import cmd_repo_info

        args = argparse.Namespace(name="myrepo")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_info(args)

        assert result == 0

    def test_info_not_found(self):
        """Should return error when repository not found."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repository_info.return_value = None

        from deriva.cli.cli import cmd_repo_info

        args = argparse.Namespace(name="nonexistent")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_info(args)

        assert result == 1


class TestCmdRepoListDetailed:
    """Additional tests for repo list command."""

    def test_lists_repos_detailed(self):
        """Should list repositories with details."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repositories.return_value = [
            {
                "name": "repo1",
                "url": "https://github.com/user/repo1.git",
                "branch": "main",
                "size_mb": 10.5,
                "cloned_at": "2024-01-01",
                "is_dirty": True,
            },
        ]

        args = argparse.Namespace(detailed=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_list(args)

        assert result == 0
        mock_session.get_repositories.assert_called_once_with(detailed=True)


class TestCmdConfigUpdate:
    """Tests for config update command."""

    def test_updates_derivation_config(self, tmp_path):
        """Should update derivation configuration."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        from deriva.cli.cli import cmd_config_update

        args = argparse.Namespace(
            step_type="derivation",
            name="ApplicationComponent",
            instruction="Test instruction",
            example="Test example",
            instruction_file=None,
            example_file=None,
            query=None,
        )

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch(
                "deriva.cli.cli.config.create_derivation_config_version",
                return_value={"success": True, "old_version": 1, "new_version": 2},
            ):
                result = cmd_config_update(args)

        assert result == 0

    def test_updates_from_file(self, tmp_path):
        """Should read instruction from file."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        instruction_file = tmp_path / "instruction.txt"
        instruction_file.write_text("Instruction from file")

        from deriva.cli.cli import cmd_config_update

        args = argparse.Namespace(
            step_type="derivation",
            name="ApplicationComponent",
            instruction=None,
            example="Example",
            instruction_file=str(instruction_file),
            example_file=None,
            query=None,
        )

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch(
                "deriva.cli.cli.config.create_derivation_config_version",
                return_value={"success": True, "old_version": 1, "new_version": 2},
            ):
                result = cmd_config_update(args)

        assert result == 0

    def test_handles_file_read_error(self):
        """Should handle file read errors."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        from deriva.cli.cli import cmd_config_update

        args = argparse.Namespace(
            step_type="derivation",
            name="ApplicationComponent",
            instruction=None,
            example=None,
            instruction_file="/nonexistent/file.txt",
            example_file=None,
            query=None,
        )

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_config_update(args)

        assert result == 1


class TestCmdRunFailure:
    """Tests for run command failure scenarios."""

    def test_run_extraction_failure(self):
        """Should return error on extraction failure."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_extraction.return_value = {
            "success": False,
            "errors": ["Failed to extract"],
        }

        args = argparse.Namespace(stage="extraction", repo=None, verbose=False, no_llm=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 1


class TestCmdConfigShowDerivationNotFound:
    """Test config show for nonexistent derivation config."""

    def test_returns_error_for_nonexistent_derivation(self):
        """Should return error for nonexistent derivation config."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        args = argparse.Namespace(step_type="derivation", name="Unknown")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            with patch("deriva.cli.cli.config.get_derivation_config", return_value=None):
                result = cmd_config_show(args)

        assert result == 1


class TestCmdBenchmarkList:
    """Tests for benchmark list command."""

    def test_lists_benchmarks(self):
        """Should list benchmark sessions."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_benchmarks.return_value = [
            {
                "session_id": "bench_123",
                "status": "completed",
                "started_at": "2024-01-01T10:00:00",
                "description": "Test benchmark",
            },
        ]

        from deriva.cli.cli import cmd_benchmark_list

        args = argparse.Namespace(limit=10)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_benchmark_list(args)

        assert result == 0

    def test_handles_empty_list(self):
        """Should handle no benchmark sessions."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.list_benchmarks.return_value = []

        from deriva.cli.cli import cmd_benchmark_list

        args = argparse.Namespace(limit=10)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_benchmark_list(args)

        assert result == 0


class TestCmdRunWithNoLlm:
    """Tests for run command with --no-llm flag."""

    def test_run_extraction_with_no_llm(self):
        """Should run extraction with LLM disabled."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_extraction.return_value = {"success": True, "stats": {}}

        args = argparse.Namespace(stage="extraction", repo=None, verbose=False, no_llm=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0


class TestCmdRunUnknownStage:
    """Tests for run command with unknown stage."""

    def test_unknown_stage_returns_error(self):
        """Should return error for unknown stage."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}

        args = argparse.Namespace(stage="unknown", repo=None, verbose=False, no_llm=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 1


class TestCmdRunVerbose:
    """Tests for run command with verbose output."""

    def test_run_extraction_verbose(self):
        """Should run extraction with verbose output."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "openai", "model": "gpt-4"}
        mock_session.run_extraction.return_value = {
            "success": True,
            "stats": {"nodes_created": 5},
            "warnings": ["Warning 1"],
            "errors": [],
        }

        args = argparse.Namespace(stage="extraction", repo="myrepo", verbose=True, no_llm=False)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0


class TestCmdRunDerivationWithPhase:
    """Tests for derivation with specific phase."""

    def test_run_derivation_with_phase(self):
        """Should run derivation with specific phase."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.llm_info = {"provider": "anthropic", "model": "claude-3"}
        mock_session.run_derivation.return_value = {
            "success": True,
            "stats": {"elements_created": 3},
        }

        args = argparse.Namespace(
            stage="derivation", repo=None, verbose=False, no_llm=False, phase="generate"
        )

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_run(args)

        assert result == 0
        mock_session.run_derivation.assert_called_once_with(verbose=False, phases=["generate"])


class TestCmdExportWithName:
    """Tests for export command with model name."""

    def test_exports_with_model_name(self):
        """Should export with custom model name."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.export_model.return_value = {
            "success": True,
            "output_path": "output.archimate",
            "elements_exported": 10,
            "relationships_exported": 5,
        }

        args = argparse.Namespace(output="output.archimate", name="My Model", verbose=True)

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_export(args)

        assert result == 0


class TestCmdRepoInfoException:
    """Tests for repo info command exception handling."""

    def test_handles_exception(self):
        """Should handle exceptions during info retrieval."""
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)
        mock_session.get_repository_info.side_effect = Exception("Database error")

        from deriva.cli.cli import cmd_repo_info

        args = argparse.Namespace(name="myrepo")

        with patch("deriva.cli.cli.PipelineSession", return_value=mock_session):
            result = cmd_repo_info(args)

        assert result == 1


class TestMockRepositoryStructure:
    """Tests using the mock repository structure."""

    def test_mock_repo_creation(self):
        """Should create mock repository with expected structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MockRepository(Path(tmpdir))

            # Verify structure
            assert (mock_repo.root / "src").is_dir()
            assert (mock_repo.root / "src" / "main.py").is_file()
            assert (mock_repo.root / "src" / "models" / "user.py").is_file()
            assert (mock_repo.root / "tests" / "test_user.py").is_file()
            assert (mock_repo.root / "pyproject.toml").is_file()
            assert (mock_repo.root / "README.md").is_file()

    def test_mock_repo_has_python_content(self):
        """Should have valid Python content in files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MockRepository(Path(tmpdir))

            main_py = (mock_repo.root / "src" / "main.py").read_text()
            assert "def main()" in main_py
            assert "Hello, World!" in main_py

            user_py = (mock_repo.root / "src" / "models" / "user.py").read_text()
            assert "class User:" in user_py
            assert "def validate" in user_py

    def test_mock_repo_has_dependencies(self):
        """Should have dependencies in pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MockRepository(Path(tmpdir))

            pyproject = (mock_repo.root / "pyproject.toml").read_text()
            assert "fastapi" in pyproject
            assert "pydantic" in pyproject
            assert "pytest" in pyproject

    def test_mock_repo_can_count_files(self):
        """Should be able to count files in mock repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_repo = MockRepository(Path(tmpdir))

            python_files = list(mock_repo.root.rglob("*.py"))
            # __init__.py files + main.py + user.py + routes.py + test_user.py
            assert len(python_files) >= 5
