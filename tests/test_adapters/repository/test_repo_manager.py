"""Tests for repository adapter with mock filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        assert "github.com" in retrieved["url"]

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

    def test_clone_existing_without_overwrite(self, tmp_path):
        """Should fail when directory exists and overwrite=False."""
        manager = RepoManager(workspace_dir=tmp_path)
        (tmp_path / "existing-repo").mkdir()

        with pytest.raises(CloneError, match="already exists"):
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
