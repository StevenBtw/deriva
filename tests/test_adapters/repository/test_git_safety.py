"""Git on untrusted repositories: limited protocols, no symlinks, no API keys in git's environment, a timeout."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deriva.adapters.repository import manager as repo_manager
from deriva.adapters.repository.manager import RepoManager
from deriva.common.exceptions import CloneError, ValidationError

RUN = "deriva.adapters.repository.manager.subprocess.run"


def _configs(cmd: list[str]) -> list[str]:
    """The ``-c`` values of a git command line (before the subcommand)."""
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "-c"]


class _Git:
    """Records git calls; a clone creates its target folder."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if cmd[0] == "git" and "clone" in cmd:
            (Path(cmd[-1]) / ".git").mkdir(parents=True)
        return MagicMock(stdout="main", stderr="")

    def clone(self) -> tuple[list[str], dict]:
        return next(c for c in self.calls if "clone" in c[0])


@pytest.fixture
def git():
    recorder = _Git()
    with patch(RUN, side_effect=recorder):
        yield recorder


class TestClone:
    def test_only_network_protocols_and_no_local_submodules(self, tmp_path, git):
        RepoManager(workspace_dir=tmp_path).clone_repository("https://github.com/user/repo.git")
        configs = _configs(git.clone()[0])
        assert "protocol.allow=never" in configs
        assert {"protocol.https.allow=always", "protocol.ssh.allow=always", "protocol.git.allow=always"} <= set(configs)
        assert "protocol.file.allow=never" in configs

    def test_symlinks_are_checked_out_as_plain_files(self, tmp_path, git):
        RepoManager(workspace_dir=tmp_path).clone_repository("https://github.com/user/repo.git")
        assert "core.symlinks=false" in _configs(git.clone()[0])

    def test_submodules_by_default_and_on_request_none(self, tmp_path, git):
        manager = RepoManager(workspace_dir=tmp_path)
        manager.clone_repository("https://github.com/user/repo.git")
        manager.clone_repository("https://github.com/user/other.git", submodules=False)
        clones = [c for c, _ in git.calls if "clone" in c]
        assert "--recurse-submodules" in clones[0]
        assert "--recurse-submodules" not in clones[1]

    def test_no_api_keys_in_gits_environment(self, tmp_path, git, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
        monkeypatch.setenv("SOME_SERVICE_API_KEY", "secret")
        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent")
        RepoManager(workspace_dir=tmp_path).clone_repository("https://github.com/user/repo.git")
        env = git.clone()[1]["env"]
        assert "OPENAI_API_KEY" not in env and "SOME_SERVICE_API_KEY" not in env
        assert env["SSH_AUTH_SOCK"] == "/tmp/agent"
        assert env["GIT_TERMINAL_PROMPT"] == "0"

    def test_a_clone_that_takes_too_long_is_stopped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DERIVA_GIT_TIMEOUT", "5")
        seen = {}

        def slow(cmd, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            Path(cmd[-1]).mkdir(parents=True)
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

        with patch(RUN, side_effect=slow), pytest.raises(CloneError, match="5 seconds"):
            RepoManager(workspace_dir=tmp_path).clone_repository("https://github.com/user/repo.git")
        assert seen["timeout"] == 5
        assert not any(p.name.startswith(".clone-") for p in tmp_path.iterdir())


class TestLocalClones:
    def test_refused_unless_allowed(self, tmp_path, git):
        with pytest.raises(ValidationError, match="Local repositories"):
            RepoManager(workspace_dir=tmp_path).clone_repository("file:///srv/repos/app.git")
        assert git.calls == []

    def test_allowed_from_the_command_line_but_not_for_submodules(self, tmp_path, git):
        RepoManager(workspace_dir=tmp_path).clone_repository("file:///srv/repos/app.git", allow_local=True)
        configs = _configs(git.clone()[0])
        # "user": the URL the user gave may be local, a submodule's may not (git's own distinction)
        assert "protocol.file.allow=user" in configs


class TestPull:
    def test_pull_has_the_same_limits(self, tmp_path, git):
        manager = RepoManager(workspace_dir=tmp_path)
        manager.clone_repository("https://github.com/user/repo.git")
        with patch.object(repo_manager, "_working_tree_dirty", return_value=False):
            manager.update_repository("repo")
        pull, kwargs = next(c for c in git.calls if "pull" in c[0])
        assert {"protocol.allow=never", "protocol.file.allow=user", "core.symlinks=false"} <= set(_configs(pull))
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert kwargs["timeout"] > 0


class TestGitVersion:
    @pytest.mark.parametrize(
        ("version", "outdated"),
        [("2.43.0", True), ("2.43.7", False), ("2.45.1.windows.1", True), ("2.45.4", False), ("2.49.0", True), ("2.50.1", False), ("2.51.0", False)],
    )
    def test_versions_before_the_submodule_fixes_are_reported(self, version, outdated):
        assert repo_manager.git_outdated(f"git version {version}") is outdated


def _real_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path: Path, file: str) -> Path:
    path.mkdir()
    _real_git(path, "init", "-b", "main")
    (path / file).write_text("x", encoding="utf-8")
    _real_git(path, "add", file)
    _real_git(path, "commit", "-m", "init")
    return path


class TestWithRealGit:
    def test_a_local_clone_works_but_its_local_submodule_is_refused(self, tmp_path):
        library = _repo(tmp_path / "library", "lib.txt")
        app = _repo(tmp_path / "app", "app.txt")
        # Adding a local submodule needs file transport allowed for this one command
        _real_git(app, "-c", "protocol.file.allow=always", "submodule", "add", library.as_uri(), "lib")
        _real_git(app, "commit", "-m", "submodule")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        manager = RepoManager(workspace_dir=workspace)

        info = manager.clone_repository(app.as_uri() + "/.git", target_name="plain", submodules=False, allow_local=True)
        assert (Path(info.path) / "app.txt").exists()

        with pytest.raises(CloneError, match="uses the file protocol"):
            manager.clone_repository(app.as_uri() + "/.git", target_name="with-submodules", allow_local=True)
        assert not (workspace / "with-submodules").exists()


class TestEdges:
    def test_an_unreadable_timeout_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv("DERIVA_GIT_TIMEOUT", "soon")
        assert repo_manager._git_timeout() == 1800

    def test_unknown_and_old_versions(self):
        assert repo_manager.git_outdated("git version unknown") is False
        assert repo_manager.git_outdated("git version 2.39.5") is True

    def test_an_outdated_git_is_logged_after_a_clone(self, tmp_path, caplog):
        def run(cmd, **kwargs):
            if "clone" in cmd:
                (Path(cmd[-1]) / ".git").mkdir(parents=True)
            return MagicMock(stdout="git version 2.43.0" if "--version" in cmd else "main", stderr="")

        with patch(RUN, side_effect=run), caplog.at_level("WARNING"):
            RepoManager(workspace_dir=tmp_path).clone_repository("https://github.com/user/repo.git")
        assert "CVE-2025-48384" in caplog.text

    def test_no_git_to_ask_is_no_warning(self):
        with patch(RUN, side_effect=OSError("no git")):
            repo_manager._warn_if_git_outdated()

    def test_a_pull_that_takes_too_long_is_stopped(self, tmp_path, git):
        manager = RepoManager(workspace_dir=tmp_path)
        manager.clone_repository("https://github.com/user/repo.git")
        with (
            patch(RUN, side_effect=subprocess.TimeoutExpired("git", 1)),
            patch.object(repo_manager, "_working_tree_dirty", return_value=False),
            pytest.raises(repo_manager.RepositoryError, match="seconds"),
        ):
            manager.update_repository("repo")


class TestLocalNames:
    @pytest.mark.parametrize(
        ("url", "name"),
        [
            ("file:///srv/repos/LakesideMutual/.git", "LakesideMutual"),
            ("file:///srv/repos/LakesideMutual", "LakesideMutual"),
            ("file:///srv/repos/app.git", "app"),
            ("https://github.com/user/repo.git", "repo"),
        ],
    )
    def test_the_name_is_the_repository_folder(self, url, name):
        assert repo_manager._extract_repo_name(url) == name

    def test_a_working_tree_url_is_valid(self):
        assert repo_manager._is_valid_git_url("file:///srv/repos/LakesideMutual")
