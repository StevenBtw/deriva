"""Tests for repository adapter with mock filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest

from deriva.adapters.repository.manager import (
    RepoManager,
    _extract_repo_name,
    _get_directory_size,
    _is_valid_git_url,
    _StateManager,
)
from deriva.adapters.repository.models import (
    CloneError,
    DeleteError,
    FileNode,
    MetadataError,
    RepositoryError,
    RepositoryInfo,
    RepositoryMetadata,
    ValidationError,
)


class TestIsValidGitUrl:
    """Tests for _is_valid_git_url helper."""

    def test_https_url_with_git_extension(self):
        """Should accept HTTPS URLs with .git extension."""
        assert _is_valid_git_url("https://github.com/user/repo.git") is True

    def test_https_url_without_git_extension(self):
        """Should accept HTTPS URLs without .git extension."""
        assert _is_valid_git_url("https://github.com/user/repo") is True

    def test_http_url(self):
        """Should accept HTTP URLs."""
        assert _is_valid_git_url("http://github.com/user/repo.git") is True

    def test_ssh_url(self):
        """Should accept SSH URLs."""
        assert _is_valid_git_url("git@github.com:user/repo.git") is True

    def test_ssh_url_without_extension(self):
        """Should accept SSH URLs without .git extension."""
        assert _is_valid_git_url("git@github.com:user/repo") is True

    def test_file_url(self):
        """Should accept file:// URLs."""
        assert _is_valid_git_url("file:///path/to/repo.git") is True

    def test_invalid_url(self):
        """Should reject invalid URLs."""
        assert _is_valid_git_url("not-a-valid-url") is False

    def test_empty_string(self):
        """Should reject empty strings."""
        assert _is_valid_git_url("") is False

    def test_plain_path(self):
        """Should reject plain paths."""
        assert _is_valid_git_url("/home/user/repo") is False


class TestExtractRepoName:
    """Tests for _extract_repo_name helper."""

    def test_https_url_with_git_extension(self):
        """Should extract name from HTTPS URL with .git."""
        assert _extract_repo_name("https://github.com/user/my-repo.git") == "my-repo"

    def test_https_url_without_extension(self):
        """Should extract name from HTTPS URL without .git."""
        assert _extract_repo_name("https://github.com/user/my-repo") == "my-repo"

    def test_ssh_url(self):
        """Should extract name from SSH URL."""
        assert _extract_repo_name("git@github.com:user/my-repo.git") == "my-repo"

    def test_url_with_trailing_slash(self):
        """Should handle trailing slash."""
        assert _extract_repo_name("https://github.com/user/my-repo/") == "my-repo"


class TestGetDirectorySize:
    """Tests for _get_directory_size helper."""

    def test_calculates_size_correctly(self, tmp_path):
        """Should calculate total directory size in MB."""
        # Create some files with known sizes
        (tmp_path / "file1.txt").write_bytes(b"x" * 1024)  # 1 KB
        (tmp_path / "file2.txt").write_bytes(b"y" * 2048)  # 2 KB

        size_mb = _get_directory_size(tmp_path)
        expected_mb = 3072 / (1024 * 1024)  # 3 KB in MB
        assert abs(size_mb - expected_mb) < 0.001

    def test_size_and_counts_walk_from_the_extended_form(self, tmp_path):
        """With long paths off, Windows skips what lies deeper than 260 characters unless the walk starts from \\\\?\\."""
        import os

        from deriva.adapters.repository.manager import _count_files_and_dirs
        from deriva.common.file_utils import long_path

        with patch("deriva.adapters.repository.manager.os.walk", wraps=os.walk) as walk:
            _get_directory_size(tmp_path)
            _count_files_and_dirs(tmp_path)

        assert [c.args[0] for c in walk.call_args_list] == [long_path(tmp_path)] * 2

    def test_handles_empty_directory(self, tmp_path):
        """Should return 0 for empty directory."""
        size_mb = _get_directory_size(tmp_path)
        assert size_mb == 0.0

    def test_handles_nested_directories(self, tmp_path):
        """Should include nested files."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_bytes(b"z" * 512)

        size_mb = _get_directory_size(tmp_path)
        expected_mb = 512 / (1024 * 1024)
        assert abs(size_mb - expected_mb) < 0.001


class TestStateManager:
    """Tests for _StateManager class."""

    def test_creates_state_file_if_missing(self, tmp_path):
        """Should create workspace.yaml if it doesn't exist."""
        _StateManager(tmp_path)  # Creates state file on init
        state_file = tmp_path / "workspace.yaml"
        assert state_file.exists()

    def test_adds_and_retrieves_repository(self, tmp_path):
        """Should add and retrieve repository info."""
        state_mgr = _StateManager(tmp_path)
        repo_info = RepositoryInfo(
            name="test-repo",
            path=str(tmp_path / "test-repo"),
            url="https://github.com/user/test-repo.git",
        )
        state_mgr.add_repository(repo_info)

        retrieved = state_mgr.get_repository("test-repo")
        assert retrieved is not None
        assert retrieved["name"] == "test-repo"
        parsed_url = urlparse(retrieved["url"])
        assert parsed_url.hostname == "github.com"

    def test_removes_repository(self, tmp_path):
        """Should remove repository from state."""
        state_mgr = _StateManager(tmp_path)
        repo_info = RepositoryInfo(
            name="test-repo",
            path=str(tmp_path / "test-repo"),
        )
        state_mgr.add_repository(repo_info)
        state_mgr.remove_repository("test-repo")

        assert state_mgr.get_repository("test-repo") is None

    def test_lists_all_repositories(self, tmp_path):
        """Should list all repositories."""
        state_mgr = _StateManager(tmp_path)
        state_mgr.add_repository(RepositoryInfo(name="repo1", path="/path/repo1"))
        state_mgr.add_repository(RepositoryInfo(name="repo2", path="/path/repo2"))

        repos = state_mgr.list_repositories()
        assert len(repos) == 2
        names = [r["name"] for r in repos]
        assert "repo1" in names
        assert "repo2" in names


class TestRepositoryInfo:
    """Tests for RepositoryInfo model."""

    def test_creates_with_required_fields(self):
        """Should create with minimal required fields."""
        info = RepositoryInfo(name="repo", path="/path/to/repo")
        assert info.name == "repo"
        assert info.path == "/path/to/repo"
        assert info.url is None
        assert info.is_dirty is False

    def test_to_dict(self):
        """Should convert to dictionary."""
        info = RepositoryInfo(
            name="repo",
            path="/path/to/repo",
            url="https://github.com/user/repo.git",
            branch="main",
            is_dirty=True,
            size_mb=10.5,
        )
        d = info.to_dict()
        assert d["name"] == "repo"
        assert d["url"] == "https://github.com/user/repo.git"
        assert d["is_dirty"] is True
        assert d["size_mb"] == 10.5


class TestRepositoryMetadata:
    """Tests for RepositoryMetadata model."""

    def test_creates_with_all_fields(self):
        """Should create with all fields."""
        meta = RepositoryMetadata(
            name="repo",
            url="https://github.com/user/repo.git",
            description="A test repo",
            total_size_mb=5.5,
            total_files=100,
            total_directories=10,
            languages={"Python": 50, "JavaScript": 30},
            created_at="2024-01-01T00:00:00",
            last_updated="2024-12-01T00:00:00",
            default_branch="main",
        )
        assert meta.name == "repo"
        assert meta.languages["Python"] == 50

    def test_to_dict(self):
        """Should convert to dictionary."""
        meta = RepositoryMetadata(
            name="repo",
            url="https://github.com/user/repo.git",
            description=None,
            total_size_mb=0.0,
            total_files=0,
            total_directories=0,
            languages={},
            created_at="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
            default_branch="main",
        )
        d = meta.to_dict()
        assert d["name"] == "repo"
        assert d["default_branch"] == "main"


class TestFileNode:
    """Tests for FileNode model."""

    def test_creates_file_node(self):
        """Should create file node."""
        node = FileNode(name="test.py", path="src/test.py", type="file", size_bytes=1024)
        assert node.name == "test.py"
        assert node.type == "file"
        assert node.size_bytes == 1024
        assert node.children is None

    def test_creates_directory_node(self):
        """Should create directory node with children."""
        child = FileNode(name="file.py", path="src/file.py", type="file", size_bytes=512)
        parent = FileNode(
            name="src",
            path="src",
            type="directory",
            size_bytes=512,
            children=[child],
        )
        assert parent.type == "directory"
        assert parent.children is not None
        assert len(parent.children) == 1

    def test_to_dict_recursive(self):
        """Should convert to dict recursively."""
        child = FileNode(name="file.py", path="src/file.py", type="file", size_bytes=100)
        parent = FileNode(
            name="src",
            path="src",
            type="directory",
            size_bytes=100,
            children=[child],
        )
        d = parent.to_dict()
        assert d["name"] == "src"
        assert len(d["children"]) == 1
        assert d["children"][0]["name"] == "file.py"


class TestRepoManagerValidation:
    """Tests for RepoManager.validate_repository."""

    def test_validates_https_url(self, tmp_path):
        """Should accept valid HTTPS URL."""
        manager = RepoManager(workspace_dir=tmp_path)
        result = manager.validate_repository("https://github.com/user/repo.git")
        assert result is True

    def test_rejects_empty_url(self, tmp_path):
        """Should reject empty URL."""
        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(ValidationError, match="non-empty string"):
            manager.validate_repository("")

    def test_rejects_invalid_format(self, tmp_path):
        """Should reject invalid URL format."""
        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(ValidationError, match="Invalid Git URL"):
            manager.validate_repository("not-a-url")

    def test_check_remote_when_requested(self, tmp_path):
        """Should check remote when check_remote=True."""
        manager = RepoManager(workspace_dir=tmp_path)
        with patch("deriva.adapters.repository.manager._check_remote_exists", return_value=False):
            with pytest.raises(ValidationError, match="not accessible"):
                manager.validate_repository("https://github.com/user/repo.git", check_remote=True)


class TestRepoManagerClone:
    """Tests for RepoManager.clone_repository."""

    def test_clone_success(self, tmp_path):
        """Should clone repository successfully."""
        manager = RepoManager(workspace_dir=tmp_path)

        with patch("deriva.adapters.repository.manager.subprocess.run") as mock_run:

            def handle_subprocess(*args, **kwargs):
                cmd = args[0]
                result = MagicMock()
                result.stdout = "main"
                result.stderr = ""

                # Handle clone command
                if cmd[0] == "git" and "clone" in cmd:
                    target_dir = Path(cmd[-1])
                    target_dir.mkdir(parents=True, exist_ok=True)
                    (target_dir / ".git").mkdir()

                return result

            mock_run.side_effect = handle_subprocess

            result = manager.clone_repository("https://github.com/user/test-repo.git")

            assert result.name == "test-repo"
            assert mock_run.called

    def test_overwrite_removes_read_only_files(self, tmp_path):
        """Git keeps its pack files read-only; overwriting an existing clone must still remove them (Windows)."""
        import stat

        manager = RepoManager(workspace_dir=tmp_path)
        pack = tmp_path / "old-repo" / ".git" / "objects" / "pack" / "pack-1.idx"
        pack.parent.mkdir(parents=True)
        pack.write_text("x")
        pack.chmod(stat.S_IREAD)

        def handle_subprocess(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "git" and "clone" in cmd:
                (Path(cmd[-1]) / ".git").mkdir(parents=True)
            return MagicMock(stdout="main", stderr="")

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=handle_subprocess):
            result = manager.clone_repository("https://github.com/user/old-repo.git", overwrite=True)

        assert result.name == "old-repo"
        assert not pack.exists()

    def test_on_windows_removal_clears_the_read_only_bit(self, tmp_path):
        """The overwrite goes through the removal that handles read-only files, also where CI runs on Linux."""
        from deriva.adapters.repository import manager as repo_manager

        target = tmp_path / "old"
        target.mkdir()
        with patch.object(repo_manager.os, "name", "nt"), patch.object(repo_manager.shutil, "rmtree") as rmtree:
            repo_manager._force_remove_directory(target)

        assert rmtree.call_args.kwargs == {"onexc": repo_manager._handle_remove_readonly}

    def test_the_read_only_handler_removes_a_read_only_file(self, tmp_path):
        import os
        import stat

        from deriva.adapters.repository import manager as repo_manager

        pack = tmp_path / "pack.idx"
        pack.write_text("x")
        pack.chmod(stat.S_IREAD)

        repo_manager._handle_remove_readonly(os.unlink, str(pack), PermissionError())

        assert not pack.exists()

    def test_clone_existing_without_overwrite(self, tmp_path):
        """Should fail when directory exists and overwrite=False."""
        manager = RepoManager(workspace_dir=tmp_path)
        (tmp_path / "existing-repo").mkdir()

        with pytest.raises(CloneError, match="A folder named existing-repo already exists in the workspace: give the clone another name"):
            manager.clone_repository("https://github.com/user/existing-repo.git")

    def test_clone_with_branch(self, tmp_path):
        """Should pass branch to git clone."""
        manager = RepoManager(workspace_dir=tmp_path)

        clone_cmd_args = []

        with patch("deriva.adapters.repository.manager.subprocess.run") as mock_run:

            def handle_subprocess(*args, **kwargs):
                cmd = args[0]
                result = MagicMock()
                result.stdout = "develop"
                result.stderr = ""

                # Capture clone command
                if cmd[0] == "git" and "clone" in cmd:
                    clone_cmd_args.extend(cmd)
                    target_dir = Path(cmd[-1])
                    target_dir.mkdir(parents=True, exist_ok=True)
                    (target_dir / ".git").mkdir()

                return result

            mock_run.side_effect = handle_subprocess
            manager.clone_repository("https://github.com/user/repo.git", branch="develop")

            assert "--branch" in clone_cmd_args
            assert "develop" in clone_cmd_args

    def test_clone_allows_long_paths(self, tmp_path):
        """Windows: a deep home folder plus git's pack file names pass 260 characters; the clone (and the repository) allow long paths."""
        manager = RepoManager(workspace_dir=tmp_path)
        clone_cmd_args = []

        def handle_subprocess(*args, **kwargs):
            cmd = args[0]
            result = MagicMock(stdout="main", stderr="")
            if cmd[0] == "git" and "clone" in cmd:
                clone_cmd_args.extend(cmd)
                (Path(cmd[-1]) / ".git").mkdir(parents=True)
            return result

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=handle_subprocess):
            manager.clone_repository("https://github.com/user/repo.git")

        position = clone_cmd_args.index("core.longpaths=true")
        assert clone_cmd_args[position - 1] == "--config"

    def test_clone_fetches_submodules(self, tmp_path):
        """A repository that keeps its modules as git submodules is empty without them (only the top-level files)."""
        manager = RepoManager(workspace_dir=tmp_path)
        commands = []

        def handle_subprocess(*args, **kwargs):
            cmd = args[0]
            if cmd[0] == "git" and "clone" in cmd:
                commands.append(cmd)
                (Path(cmd[-1]) / ".git").mkdir(parents=True)
            return MagicMock(stdout="main", stderr="")

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=handle_subprocess):
            manager.clone_repository("https://github.com/user/repo.git")
            manager.clone_repository("https://github.com/user/other.git", depth=1)

        assert "--recurse-submodules" in commands[0] and "--shallow-submodules" not in commands[0]
        assert "--recurse-submodules" in commands[1] and "--shallow-submodules" in commands[1]


class TestRepoManagerList:
    """Tests for RepoManager.list_repositories."""

    def test_list_empty_workspace(self, tmp_path):
        """Should return empty list for empty workspace."""
        manager = RepoManager(workspace_dir=tmp_path)
        repos = manager.list_repositories()
        assert repos == []

    def test_list_detailed(self, tmp_path):
        """Should return RepositoryInfo objects when detailed=True."""
        manager = RepoManager(workspace_dir=tmp_path)
        # Add a repo to state
        manager._state_manager.add_repository(RepositoryInfo(name="repo1", path=str(tmp_path / "repo1"), url="https://github.com/u/repo1.git"))

        repos = manager.list_repositories(detailed=True)
        assert len(repos) == 1
        assert isinstance(repos[0], RepositoryInfo)
        assert repos[0].name == "repo1"

    def test_list_names_only(self, tmp_path):
        """Should return names only when detailed=False."""
        manager = RepoManager(workspace_dir=tmp_path)
        manager._state_manager.add_repository(RepositoryInfo(name="repo1", path=str(tmp_path / "repo1")))

        repos = manager.list_repositories(detailed=False)
        assert repos == ["repo1"]


class TestRepoManagerDelete:
    """Tests for RepoManager.delete_repository."""

    def test_delete_nonexistent(self, tmp_path):
        """Should raise error for nonexistent repository."""
        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(DeleteError, match="not found"):
            manager.delete_repository("nonexistent")

    def test_delete_non_git_directory(self, tmp_path):
        """Should raise error for non-git directory."""
        manager = RepoManager(workspace_dir=tmp_path)
        (tmp_path / "not-a-repo").mkdir()

        with pytest.raises(DeleteError, match="Not a Git repository"):
            manager.delete_repository("not-a-repo")

    def test_delete_success(self, tmp_path):
        """Should delete repository successfully."""
        manager = RepoManager(workspace_dir=tmp_path)

        # Create fake repo
        repo_path = tmp_path / "test-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()
        manager._state_manager.add_repository(RepositoryInfo(name="test-repo", path=str(repo_path)))

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            result = manager.delete_repository("test-repo", force=True)
            assert result is True
            assert not repo_path.exists()

    def test_delete_dirty_without_force(self, tmp_path):
        """Should fail when repo has changes and force=False."""
        manager = RepoManager(workspace_dir=tmp_path)

        repo_path = tmp_path / "dirty-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = " M modified_file.py"  # Indicates uncommitted changes
            mock_run.return_value = mock_result

            with pytest.raises(DeleteError, match="uncommitted changes"):
                manager.delete_repository("dirty-repo", force=False)


class TestRepoManagerGetInfo:
    """Tests for RepoManager.get_repository_info."""

    def test_get_existing_repo(self, tmp_path):
        """Should return info for existing repository."""
        manager = RepoManager(workspace_dir=tmp_path)
        manager._state_manager.add_repository(
            RepositoryInfo(
                name="test-repo",
                path=str(tmp_path / "test-repo"),
                url="https://github.com/user/test-repo.git",
                branch="main",
            )
        )

        info = manager.get_repository_info("test-repo")
        assert info.name == "test-repo"
        assert info.branch == "main"

    def test_get_nonexistent_repo(self, tmp_path):
        """Should raise error for nonexistent repository."""
        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(RepositoryError, match="not found"):
            manager.get_repository_info("nonexistent")


class TestRepoManagerExtractMetadata:
    """Tests for RepoManager.extract_metadata."""

    def test_extract_metadata_success(self, tmp_path):
        """Should extract metadata and create JSON files."""
        manager = RepoManager(workspace_dir=tmp_path)

        # Create mock repository structure
        repo_path = tmp_path / "test-repo"
        repo_path.mkdir()
        (repo_path / ".git").mkdir()
        (repo_path / "README.md").write_text("# Test Repo\n\nThis is a test.")
        (repo_path / "main.py").write_text("print('hello')")

        src_dir = repo_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.py").write_text("def foo(): pass")

        # Mock git commands
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = "https://github.com/user/test-repo.git"
            mock_run.return_value = mock_result

            meta_file, struct_file = manager.extract_metadata("test-repo")

            assert meta_file.exists()
            assert struct_file.exists()

            # Check metadata content
            with open(meta_file, encoding="utf-8") as f:
                metadata = json.load(f)
            assert metadata["name"] == "test-repo"

            # Check structure content
            with open(struct_file, encoding="utf-8") as f:
                structure = json.load(f)
            assert structure["name"] == "test-repo"
            assert structure["type"] == "directory"

    def test_extract_metadata_nonexistent_repo(self, tmp_path):
        """Should raise error for nonexistent repository."""
        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(RepositoryError, match="not found"):
            manager.extract_metadata("nonexistent")

    def test_extract_metadata_non_git_directory(self, tmp_path):
        """Should raise error for non-git directory."""
        manager = RepoManager(workspace_dir=tmp_path)
        (tmp_path / "not-a-repo").mkdir()

        with pytest.raises(MetadataError, match="Not a Git repository"):
            manager.extract_metadata("not-a-repo")


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_validate_repo_valid(self):
        """Should return True for valid URL."""
        from deriva.adapters.repository.manager import validate_repo

        result = validate_repo("https://github.com/user/repo.git")
        assert result is True

    def test_validate_repo_invalid(self):
        """Should return False for invalid URL."""
        from deriva.adapters.repository.manager import validate_repo

        result = validate_repo("not-a-url")
        assert result is False


class TestRepositoryNamesStayInTheWorkspace:
    """A repository name is one folder in the workspace: a path could clone, overwrite or delete elsewhere."""

    @pytest.mark.parametrize("name", ["../evil", "..", "a/b", "a\\b", "/tmp/x", "C:\\x", ""])
    def test_clone_refuses_a_name_that_is_no_single_folder(self, tmp_path, name):
        from deriva.adapters.repository.manager import RepositoryError

        manager = RepoManager(workspace_dir=tmp_path / "ws")
        with patch("deriva.adapters.repository.manager.subprocess.run") as run, pytest.raises(RepositoryError):
            manager.clone_repository("https://github.com/user/repo.git", target_name=name, overwrite=True)
        run.assert_not_called()

    def test_delete_refuses_a_path(self, tmp_path):
        from deriva.adapters.repository.manager import RepositoryError

        (tmp_path / "outside" / ".git").mkdir(parents=True)
        manager = RepoManager(workspace_dir=tmp_path / "ws")

        with pytest.raises(RepositoryError):
            manager.delete_repository("../outside", force=True)
        assert (tmp_path / "outside").exists()


def test_the_listing_reads_uncommitted_changes_now(tmp_path):
    """The stored state is from the clone: edits made since must show, or the studio deletes without warning."""
    manager = RepoManager(workspace_dir=tmp_path)
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    manager._state_manager.list_repositories = lambda: [{"name": "repo", "path": str(tmp_path / "repo"), "is_dirty": False}]

    with patch("deriva.adapters.repository.manager.subprocess.run") as run:
        run.return_value = MagicMock(stdout=" M src/app.py\n")
        (info,) = manager.list_repositories(detailed=True)

    assert info.is_dirty is True


class TestUpdateRepository:
    """A clone pulls its branch, fast-forward only, and its stored state follows (real git, local origin)."""

    @staticmethod
    def _git(cwd, *args):
        import subprocess

        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)

    def _commit(self, origin, name, text):
        (origin / name).write_text(text, encoding="utf-8")
        self._git(origin, "add", name)
        self._git(origin, "commit", "-m", f"add {name}")

    def _clone(self, tmp_path):
        from deriva.adapters.repository.manager import RepoManager, _get_repository_info_from_path

        origin = tmp_path / "origin"
        origin.mkdir()
        self._git(origin, "init", "-b", "main")
        self._commit(origin, "a.txt", "one")
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        self._git(tmp_path, "clone", str(origin), str(workspace / "demo"))
        manager = RepoManager(workspace_dir=workspace)
        info = _get_repository_info_from_path(workspace / "demo", "https://example.com/demo.git")
        info.cloned_at = "2026-10-01T10:00:00"
        manager._state_manager.add_repository(info)
        return origin, workspace / "demo", manager

    def test_pulls_new_commits_and_keeps_when_it_was_cloned(self, tmp_path):
        origin, clone, manager = self._clone(tmp_path)
        before = manager.get_repository_info("demo").last_commit
        self._commit(origin, "b.txt", "two")

        info = manager.update_repository("demo")

        assert (clone / "b.txt").exists()
        assert info.last_commit != before and info.last_commit.endswith("add b.txt")
        stored = manager.get_repository_info("demo")
        assert (stored.last_commit, stored.cloned_at, stored.url) == (info.last_commit, "2026-10-01T10:00:00", "https://example.com/demo.git")

    def test_refuses_a_clone_with_uncommitted_changes(self, tmp_path):
        origin, clone, manager = self._clone(tmp_path)
        (clone / "a.txt").write_text("edited", encoding="utf-8")

        with pytest.raises(RepositoryError, match="uncommitted changes"):
            manager.update_repository("demo")

    def test_a_pull_that_cannot_fast_forward_is_an_error_with_git_s_reason(self, tmp_path):
        origin, clone, manager = self._clone(tmp_path)
        self._commit(origin, "b.txt", "origin")
        self._commit(clone, "c.txt", "local")

        with pytest.raises(RepositoryError, match="commits of its own"):
            manager.update_repository("demo")

    def test_an_unknown_repository_is_an_error(self, tmp_path):
        _, _, manager = self._clone(tmp_path)

        with pytest.raises(RepositoryError, match="not found"):
            manager.update_repository("other")


class TestGitFeedback:
    """Git never waits for a terminal prompt, and its errors say what the user can do about them."""

    @staticmethod
    def _failing(stderr):
        import subprocess

        def run(cmd, **kwargs):
            if "clone" in cmd:
                raise subprocess.CalledProcessError(128, cmd, output="", stderr=stderr)
            return MagicMock(stdout="", stderr="")

        return run

    def test_clone_and_pull_never_wait_for_a_terminal_prompt(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)
        seen = []

        def run(cmd, **kwargs):
            seen.append((cmd, kwargs.get("env") or {}))
            if "clone" in cmd:
                (Path(cmd[-1]) / ".git").mkdir(parents=True)
            return MagicMock(stdout="" if "status" in cmd else "main", stderr="")

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=run):
            manager.clone_repository("https://github.com/user/repo.git")
            manager.update_repository("repo")

        for verb in ("clone", "pull"):
            env = next(env for cmd, env in seen if verb in cmd)
            assert env.get("GIT_TERMINAL_PROMPT") == "0", verb

    @pytest.mark.parametrize(
        ("stderr", "expected"),
        [
            (
                "remote: Repository not found.\nfatal: repository 'https://github.com/user/repo.git/' not found",
                "The repository was not found: check the URL. A private repository needs git credentials on this machine",
            ),
            ("fatal: unable to access 'https://git.example.org/repo.git/': Could not resolve host: git.example.org", "Could not reach git.example.org"),
            ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "This repository needs git credentials"),
            ("remote: Invalid username or password.\nfatal: Authentication failed for 'https://github.com/user/repo.git/'", "The git credentials were refused"),
            ("warning: Could not find remote branch nope to clone.\nfatal: Remote branch nope not found in upstream origin", "The repository has no branch nope"),
        ],
    )
    def test_clone_errors_say_what_to_do_and_keep_git_s_own_line(self, tmp_path, stderr, expected):
        manager = RepoManager(workspace_dir=tmp_path)

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._failing(stderr)), pytest.raises(CloneError) as error:
            manager.clone_repository("https://github.com/user/repo.git")

        message = str(error.value)
        assert message.startswith(expected)
        assert f"(git: {stderr.strip().splitlines()[-1]})" in message

    def test_an_unknown_git_error_is_passed_on(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._failing("fatal: something new")), pytest.raises(CloneError) as error:
            manager.clone_repository("https://github.com/user/repo.git")

        assert str(error.value) == "Git clone failed (git: fatal: something new)"


class TestCloneStaging:
    """A clone lands in its folder only when it worked; a failed one leaves nothing a retry would trip over."""

    @staticmethod
    def _run(fail=False):
        import subprocess

        targets = []

        def run(cmd, **kwargs):
            if "clone" in cmd:
                target = Path(cmd[-1])
                targets.append(target)
                (target / ".git").mkdir(parents=True)
                (target / "half-written.txt").write_text("x", encoding="utf-8")
                if fail:
                    raise subprocess.CalledProcessError(128, cmd, output="", stderr="error: unable to create file: Filename too long\nfatal: unable to checkout working tree")
            return MagicMock(stdout="", stderr="")

        return run, targets

    def test_a_clone_is_staged_and_moved_into_its_folder(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)
        run, targets = self._run()

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=run):
            info = manager.clone_repository("https://github.com/user/repo.git")

        assert targets[0].name.startswith(".clone-") and targets[0].parent == tmp_path
        assert Path(info.path) == tmp_path / "repo" and (tmp_path / "repo" / ".git").is_dir()
        assert not any(p.name.startswith(".clone-") for p in tmp_path.iterdir())

    def test_a_failed_clone_leaves_no_folder_behind(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)
        run, _ = self._run(fail=True)

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=run), pytest.raises(CloneError):
            manager.clone_repository("https://github.com/user/repo.git")

        assert sorted(p.name for p in tmp_path.iterdir()) == ["workspace.yaml"]
        assert manager.list_repositories(detailed=False) == []


class TestRegistryRepair:
    """The registry and the workspace folders can disagree; both ways are shown and repaired without losing files."""

    @staticmethod
    def _git_folder(path):
        import subprocess

        path.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "first"], cwd=path, check=True)

    def test_a_git_folder_without_a_record_is_found_and_registered(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)
        self._git_folder(tmp_path / "orphan")
        (tmp_path / "notes").mkdir()

        assert manager.unregistered() == ["orphan"]
        info = manager.register_repository("orphan")

        assert info.name == "orphan" and info.last_commit.endswith("first")
        assert manager.unregistered() == [] and manager.list_repositories(detailed=False) == ["orphan"]
        with pytest.raises(RepositoryError, match="no git checkout"):
            manager.register_repository("notes")

    def test_records_whose_folder_is_gone_or_no_git_checkout_are_stale(self, tmp_path):
        from deriva.adapters.repository.manager import _get_repository_info_from_path

        manager = RepoManager(workspace_dir=tmp_path)
        self._git_folder(tmp_path / "ok")
        for name in ("ok", "gone", "plain"):
            folder = tmp_path / name
            folder.mkdir(exist_ok=True)
            manager._state_manager.add_repository(_get_repository_info_from_path(folder, f"https://example.org/{name}.git"))
        import shutil

        shutil.rmtree(tmp_path / "gone")

        stale = {r.name: r.stale for r in manager.list_repositories(detailed=True)}
        assert stale == {"ok": None, "gone": "its folder is gone", "plain": "its folder is no git checkout"}

    def test_a_stale_record_is_deleted_without_touching_files(self, tmp_path):
        from deriva.adapters.repository.manager import _get_repository_info_from_path

        manager = RepoManager(workspace_dir=tmp_path)
        (tmp_path / "plain").mkdir()
        (tmp_path / "plain" / "keep.txt").write_text("mine", encoding="utf-8")
        manager._state_manager.add_repository(_get_repository_info_from_path(tmp_path / "plain", "u"))

        assert manager.delete_repository("plain") is True

        assert manager.list_repositories(detailed=False) == []
        assert (tmp_path / "plain" / "keep.txt").read_text(encoding="utf-8") == "mine"


class TestGitHardening:
    """Cleanup reaches deep files, a git that cannot start is explained, and no credentials leave a git message."""

    @staticmethod
    def _git(clone=None, pull=None):
        """subprocess.run for git: ``clone``/``pull`` raise the given error; other git calls answer empty."""

        def run(cmd, **kwargs):
            if "clone" in cmd and clone is not None:
                (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
                raise clone
            if "clone" in cmd:
                (Path(cmd[-1]) / ".git").mkdir(parents=True, exist_ok=True)
            if "pull" in cmd and pull is not None:
                raise pull
            return MagicMock(stdout="", stderr="", returncode=0)

        return run

    def test_cleanup_removes_through_the_extended_form(self, tmp_path):
        """With long paths off, Windows deletes nothing deeper than 260 characters unless the path is extended."""
        from deriva.adapters.repository.manager import _force_remove_directory
        from deriva.common.file_utils import long_path

        folder = tmp_path / "staging"
        folder.mkdir()
        with patch("deriva.adapters.repository.manager.shutil.rmtree") as rmtree:
            _force_remove_directory(folder)

        rmtree.assert_called_once()
        assert rmtree.call_args.args[0] == long_path(folder)

    def test_a_staging_folder_with_files_deeper_than_260_characters_is_removed(self, tmp_path):
        from deriva.adapters.repository.manager import _discard
        from deriva.common.file_utils import long_path

        staging = tmp_path / ".clone-deadbeef"
        deep = staging.joinpath(*["nested-folder-name"] * 16)
        long_path(deep).mkdir(parents=True)
        long_path(deep / "file.txt").write_text("x", encoding="utf-8")
        assert len(str(deep / "file.txt")) > 260

        _discard(staging)

        assert not long_path(staging).exists()

    @pytest.mark.parametrize("code", [3221225794, -1073741502], ids=["unsigned", "signed"])
    def test_a_git_that_cannot_start_is_explained_without_the_url(self, tmp_path, code):
        """0xC0000142: Windows could not start git (a DLL failed to initialize); the clone leaves nothing behind."""
        import subprocess

        manager = RepoManager(workspace_dir=tmp_path)
        failure = subprocess.CalledProcessError(code, ["git", "clone"], output="", stderr="")

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git(clone=failure)), pytest.raises(CloneError) as raised:
            manager.clone_repository("https://user:s3cret@github.com/org/private-repo.git")

        message = str(raised.value)
        assert "0xC0000142" in message
        assert "git --version" in message and "Git for Windows" in message and "antivirus" in message
        assert "s3cret" not in message and "github.com" not in message
        assert sorted(p.name for p in tmp_path.iterdir()) == ["workspace.yaml"]

    def test_a_git_helper_that_cannot_start_is_explained_too(self, tmp_path):
        """The https helper failing to start shows up in git's output, not in git's own exit code."""
        import subprocess

        manager = RepoManager(workspace_dir=tmp_path)
        stderr = "error: git-remote-https died of signal 15\nfatal: remote helper 'https' exited with status 0xc0000142"
        failure = subprocess.CalledProcessError(128, ["git", "clone"], output="", stderr=stderr)

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git(clone=failure)), pytest.raises(CloneError) as raised:
            manager.clone_repository("https://github.com/org/repo.git")

        assert "0xC0000142" in str(raised.value) and "git --version" in str(raised.value)

    def test_an_update_whose_git_cannot_start_is_explained(self, tmp_path):
        import subprocess

        manager = RepoManager(workspace_dir=tmp_path)
        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git()):
            manager.clone_repository("https://github.com/org/repo.git")
        failure = subprocess.CalledProcessError(3221225794, ["git", "pull"], output="", stderr="")

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git(pull=failure)), pytest.raises(RepositoryError) as raised:
            manager.update_repository("repo")

        assert "0xC0000142" in str(raised.value) and "git --version" in str(raised.value)

    def test_credentials_never_reach_a_git_error(self, tmp_path):
        import subprocess

        manager = RepoManager(workspace_dir=tmp_path)
        stderr = "Cloning into 'x'...\nfatal: repository 'https://user:s3cret@github.com/org/x.git/' not found"
        failure = subprocess.CalledProcessError(128, ["git", "clone"], output="", stderr=stderr)

        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git(clone=failure)), pytest.raises(CloneError) as raised:
            manager.clone_repository("https://user:s3cret@github.com/org/x.git")

        message = str(raised.value)
        assert "s3cret" not in message and "user:" not in message
        # The repository it was about stays readable
        assert "https://github.com/org/x.git/" in message

    def test_an_invalid_url_error_hides_its_credentials(self, tmp_path):
        from deriva.common.exceptions import ValidationError

        manager = RepoManager(workspace_dir=tmp_path)
        with pytest.raises(ValidationError) as raised:
            manager.validate_repository("https://ghp_token123@github.com/org/repo name")

        assert "ghp_token123" not in str(raised.value)
        assert "https://github.com/org/repo name" in str(raised.value)

    def test_a_cloned_url_is_stored_without_its_credentials(self, tmp_path):
        manager = RepoManager(workspace_dir=tmp_path)
        with patch("deriva.adapters.repository.manager.subprocess.run", side_effect=self._git()):
            info = manager.clone_repository("https://user:s3cret@github.com/org/repo.git")

        assert info.url == "https://github.com/org/repo.git"
        assert "s3cret" not in (tmp_path / "workspace.yaml").read_text(encoding="utf-8")
        assert manager.list_repositories(detailed=True)[0].url == "https://github.com/org/repo.git"
