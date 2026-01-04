"""Repository Manager - Git repository operations and metadata extraction.

This module provides a fully decoupled, modular repository management system.
Handles validation, cloning, listing, deletion, and metadata extraction.

Usage:
    from deriva.adapters.repository import RepoManager

    repo_mgr = RepoManager(workspace_dir="./workspace/repositories")

    # Validate and clone
    repo_mgr.validate_repository("https://github.com/user/repo.git")
    result = repo_mgr.clone_repository("https://github.com/user/repo.git")

    # List and get info
    repos = repo_mgr.list_repositories()
    info = repo_mgr.get_repository_info("repo-name")

    # Extract metadata
    metadata_file, structure_file = repo_mgr.extract_metadata("repo-name")
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .models import (
    CloneError,
    DeleteError,
    FileNode,
    MetadataError,
    RepositoryError,
    RepositoryInfo,
    RepositoryMetadata,
    ValidationError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# State Manager (YAML persistence)
# =============================================================================


class _StateManager:
    """Manages repository state persistence in YAML format."""

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)
        self.state_file = self.workspace_dir / "workspace.yaml"
        self._ensure_state_file()

    def _ensure_state_file(self) -> None:
        """Ensure the state file exists with proper structure."""
        if not self.state_file.exists():
            self._write_state(self._default_state())
        else:
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    state = yaml.safe_load(f)
                    if (
                        not state
                        or "version" not in state
                        or "repositories" not in state
                    ):
                        self._write_state(self._default_state())
            except Exception:
                self._write_state(self._default_state())

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "repositories": {},
        }

    def _read_state(self) -> dict[str, Any]:
        """Read the current state from YAML file."""
        try:
            with open(self.state_file, encoding="utf-8") as f:
                state = yaml.safe_load(f) or {}
                if "repositories" not in state:
                    state["repositories"] = {}
                return state
        except Exception:
            return self._default_state()

    def _write_state(self, state: dict[str, Any]) -> None:
        """Write state to YAML file."""
        state["last_updated"] = datetime.now().isoformat()
        with open(self.state_file, "w", encoding="utf-8") as f:
            yaml.dump(state, f, default_flow_style=False, sort_keys=False)

    def add_repository(self, repo_info: RepositoryInfo) -> None:
        state = self._read_state()
        state["repositories"][repo_info.name] = repo_info.to_dict()
        self._write_state(state)

    def remove_repository(self, repo_name: str) -> None:
        state = self._read_state()
        if repo_name in state["repositories"]:
            del state["repositories"][repo_name]
            self._write_state(state)

    def get_repository(self, repo_name: str) -> dict[str, Any] | None:
        state = self._read_state()
        return state["repositories"].get(repo_name)

    def list_repositories(self) -> list[dict[str, Any]]:
        state = self._read_state()
        return list(state["repositories"].values())

    def sync_state(self) -> list[str]:
        """Verify repositories exist on filesystem and remove stale entries.

        Returns:
            List of repository names that were removed from state.
        """
        state = self._read_state()
        removed = []

        for repo_name, repo_data in list(state["repositories"].items()):
            repo_path = Path(repo_data.get("path", ""))
            if not repo_path.exists() or not (repo_path / ".git").exists():
                del state["repositories"][repo_name]
                removed.append(repo_name)
                logger.info("Removed stale repository from state: %s", repo_name)

        if removed:
            self._write_state(state)

        return removed


# =============================================================================
# Helper Functions
# =============================================================================


def _is_valid_git_url(url: str) -> bool:
    """Check if URL is a valid Git repository URL."""
    patterns = [
        r"^https?://[^\s/$.?#].[^\s]*\.git$",
        r"^https?://[^\s/$.?#].[^\s]*$",
        r"^git@[^\s:]+:[^\s]+\.git$",
        r"^git@[^\s:]+:[^\s]+$",
        r"^ssh://[^\s]+\.git$",
        r"^file://[^\s]+\.git$",
    ]
    return any(re.match(pattern, url) for pattern in patterns)


def _check_remote_exists(repo_url: str) -> bool:
    """Check if remote repository exists and is accessible."""
    try:
        subprocess.run(
            ["git", "ls-remote", repo_url],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return False


def _extract_repo_name(repo_url: str) -> str:
    """Extract repository name from URL."""
    url = repo_url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url.split("/")[-1]


def _handle_remove_readonly(func, path, exc):
    """Error handler for Windows readonly files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _force_remove_directory(path: Path, max_retries: int = 3) -> None:
    """Forcefully remove a directory, handling Windows file locks."""
    for attempt in range(max_retries):
        try:
            if os.name == "nt":
                shutil.rmtree(path, onerror=_handle_remove_readonly)
            else:
                shutil.rmtree(path)
            return
        except PermissionError as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                raise DeleteError(
                    f"Failed to delete directory after {max_retries} attempts. "
                    f"Some files may be locked by another process: {e}"
                )
        except Exception as e:
            raise DeleteError(f"Failed to delete directory: {e}")


def _get_directory_size(path: Path, exclude_git: bool = False) -> float:
    """Calculate total size of directory in MB.

    Args:
        path: Directory path to calculate size for.
        exclude_git: If True, excludes .git directory from calculation.

    Returns:
        Total size in megabytes.
    """
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            if exclude_git and ".git" in dirnames:
                dirnames.remove(".git")
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total_size += os.path.getsize(filepath)
                except OSError:
                    pass
    except Exception as e:
        logger.debug("Error calculating directory size for %s: %s", path, e)
    return total_size / (1024 * 1024)


def _get_repository_info_from_path(repo_path: Path, repo_url: str) -> RepositoryInfo:
    """Get detailed information about a repository from its path."""
    name = repo_path.name

    # Get current branch
    branch = None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        branch = result.stdout.strip()
    except subprocess.CalledProcessError:
        pass

    # Get last commit
    last_commit = None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%H %s"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        last_commit = result.stdout.strip()
    except subprocess.CalledProcessError:
        pass

    # Check if dirty
    is_dirty = False
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        is_dirty = bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        pass

    return RepositoryInfo(
        name=name,
        path=str(repo_path),
        url=repo_url,
        branch=branch,
        last_commit=last_commit,
        is_dirty=is_dirty,
        size_mb=_get_directory_size(repo_path),
        cloned_at=datetime.now().isoformat(),
    )


# =============================================================================
# Metadata Extraction Helpers
# =============================================================================


def _get_git_remote_url(repo_path: Path) -> str | None:
    """Get the remote URL of the repository."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _get_repository_description(repo_path: Path) -> str | None:
    """Get repository description from README."""
    readme_files = ["README.md", "README.txt", "README.rst", "README"]

    for readme in readme_files:
        readme_path = repo_path / readme
        if readme_path.exists():
            try:
                with open(readme_path, encoding="utf-8", errors="ignore") as f:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= 5:
                            break
                        line = line.strip()
                        if line and not line.startswith("#"):
                            lines.append(line)
                    if lines:
                        return " ".join(lines)[:500]
            except (OSError, UnicodeDecodeError):
                pass
    return None


def _count_files_and_dirs(path: Path) -> tuple[int, int]:
    """Count total files and directories."""
    file_count = 0
    dir_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            if ".git" in dirnames:
                dirnames.remove(".git")
            dir_count += len(dirnames)
            file_count += len(filenames)
    except OSError:
        pass
    return file_count, dir_count


def _get_repository_times(repo_path: Path) -> tuple[str, str]:
    """Get repository creation and last update times."""
    created_at = datetime.now().isoformat()
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                "--reverse",
                "--format=%aI",
                "--max-count=1",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            created_at = result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        pass

    last_updated = datetime.now().isoformat()
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "-1", "--format=%aI"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            last_updated = result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        pass

    return created_at, last_updated


def _get_default_branch(repo_path: Path) -> str:
    """Get the default branch name."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _extract_general_metadata(repo_path: Path) -> RepositoryMetadata:
    """Extract general metadata about the repository."""
    url = _get_git_remote_url(repo_path)
    description = _get_repository_description(repo_path)
    total_size_mb = _get_directory_size(repo_path, exclude_git=True)
    total_files, total_directories = _count_files_and_dirs(repo_path)
    # Language detection delegated to Classification module
    languages: dict[str, int] = {}
    created_at, last_updated = _get_repository_times(repo_path)
    default_branch = _get_default_branch(repo_path)

    return RepositoryMetadata(
        name=repo_path.name,
        url=url or "unknown",
        description=description,
        total_size_mb=total_size_mb,
        total_files=total_files,
        total_directories=total_directories,
        languages=languages,
        created_at=created_at,
        last_updated=last_updated,
        default_branch=default_branch,
    )


def _extract_file_structure(repo_path: Path) -> FileNode:
    """Extract the complete file structure with sizes."""

    def build_tree(path: Path, relative_to: Path) -> FileNode:
        rel_path = path.relative_to(relative_to)

        if path.is_file():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            return FileNode(
                name=path.name,
                path=str(rel_path),
                type="file",
                size_bytes=size,
                children=None,
            )
        else:
            children = []
            try:
                for item in sorted(path.iterdir()):
                    if item.name == ".git":
                        continue
                    children.append(build_tree(item, relative_to))
            except PermissionError:
                pass

            dir_size = sum(
                child.size_bytes for child in children if child.type == "file"
            )

            return FileNode(
                name=path.name if path != relative_to else repo_path.name,
                path=str(rel_path) if path != relative_to else ".",
                type="directory",
                size_bytes=dir_size,
                children=children,
            )

    return build_tree(repo_path, repo_path)


# =============================================================================
# Configuration
# =============================================================================


def _load_config() -> dict:
    """Load configuration from config.yaml file."""
    config_path = Path(__file__).parent / "config.yaml"
    default_config = {"workspace_dir": "workspace/repositories"}

    if not config_path.exists():
        return default_config

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
            return {**default_config, **config}
    except Exception:
        return default_config


# =============================================================================
# Repository Manager
# =============================================================================


class RepoManager:
    """Repository Manager for Git operations.

    Provides a clean interface for managing Git repositories with
    validation, cloning, listing, deletion, and metadata extraction.
    """

    def __init__(self, workspace_dir: str | Path | None = None):
        """Initialize the Repository Manager.

        Args:
            workspace_dir: Directory where repositories will be stored.
                          Defaults to "workspace/repositories".
        """
        if workspace_dir is None:
            config = _load_config()
            workspace_dir = config.get("workspace_dir", "workspace/repositories")

        ws_path = Path(workspace_dir)
        if not ws_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            ws_path = (project_root / ws_path).resolve()
        else:
            ws_path = ws_path.resolve()

        self.workspace_dir = ws_path
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._state_manager = _StateManager(self.workspace_dir)

    def validate_repository(self, repo_url: str, check_remote: bool = False) -> bool:
        """Validate a repository URL.

        Args:
            repo_url: The repository URL to validate
            check_remote: If True, verify the remote repository exists

        Returns:
            True if the repository URL is valid

        Raises:
            ValidationError: If validation fails
        """
        if not repo_url or not isinstance(repo_url, str):
            raise ValidationError("Repository URL must be a non-empty string")

        if not _is_valid_git_url(repo_url):
            raise ValidationError(f"Invalid Git URL format: {repo_url}")

        if check_remote and not _check_remote_exists(repo_url):
            raise ValidationError(f"Remote repository not accessible: {repo_url}")

        return True

    def clone_repository(
        self,
        repo_url: str,
        target_name: str | None = None,
        branch: str | None = None,
        depth: int | None = None,
        overwrite: bool = False,
    ) -> RepositoryInfo:
        """Clone a Git repository.

        Args:
            repo_url: The repository URL to clone
            target_name: Custom name for the cloned directory
            branch: Specific branch to clone
            depth: Clone depth for shallow clones
            overwrite: If True, removes existing directory before cloning

        Returns:
            RepositoryInfo object with details about the cloned repository

        Raises:
            CloneError: If cloning fails
            ValidationError: If the repository URL is invalid
        """
        self.validate_repository(repo_url)

        if target_name is None:
            target_name = _extract_repo_name(repo_url)

        target_path = self.workspace_dir / target_name

        if target_path.exists():
            if overwrite:
                try:
                    shutil.rmtree(target_path)
                except Exception as e:
                    raise CloneError(f"Failed to remove existing directory: {e}")
            else:
                raise CloneError(
                    f"Directory already exists: {target_path}. "
                    "Use overwrite=True to replace it."
                )

        cmd = ["git", "clone"]
        if branch:
            cmd.extend(["--branch", branch])
        if depth:
            cmd.extend(["--depth", str(depth)])
        cmd.extend([repo_url, str(target_path)])

        try:
            subprocess.run(
                cmd, capture_output=True, encoding="utf-8", errors="replace", check=True
            )
        except subprocess.CalledProcessError as e:
            raise CloneError(f"Git clone failed: {e.stderr or e.stdout or str(e)}")
        except FileNotFoundError:
            raise CloneError(
                "Git is not installed or not in PATH. "
                "Please install Git to use clone functionality."
            )

        result = _get_repository_info_from_path(target_path, repo_url)
        self._state_manager.add_repository(result)
        return result

    def list_repositories(self, detailed: bool = True) -> list[str | RepositoryInfo]:
        """List all repositories in the workspace.

        Args:
            detailed: If True, returns RepositoryInfo objects.
                     If False, returns just repository names.

        Returns:
            List of repository names or RepositoryInfo objects
        """
        repos_data = self._state_manager.list_repositories()

        if detailed:
            return [
                RepositoryInfo(
                    name=repo["name"],
                    path=repo["path"],
                    url=repo.get("url"),
                    branch=repo.get("branch"),
                    last_commit=repo.get("last_commit"),
                    is_dirty=repo.get("is_dirty", False),
                    size_mb=repo.get("size_mb", 0.0),
                    cloned_at=repo.get("cloned_at"),
                )
                for repo in repos_data
            ]
        else:
            return [repo["name"] for repo in repos_data]

    def delete_repository(self, repo_name: str, force: bool = False) -> bool:
        """Delete a repository from the workspace.

        Args:
            repo_name: Name of the repository directory to delete
            force: If True, deletes even if repository has uncommitted changes

        Returns:
            True if deletion was successful

        Raises:
            DeleteError: If deletion fails
        """
        repo_path = self.workspace_dir / repo_name

        if not repo_path.exists():
            raise DeleteError(f"Repository not found: {repo_name}")

        if not (repo_path / ".git").exists():
            raise DeleteError(f"Not a Git repository: {repo_name}")

        if not force:
            try:
                result = subprocess.run(
                    ["git", "-C", str(repo_path), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if result.stdout.strip():
                    raise DeleteError(
                        f"Repository has uncommitted changes: {repo_name}. "
                        "Use force=True to delete anyway."
                    )
            except subprocess.CalledProcessError:
                pass

        _force_remove_directory(repo_path)

        # Delete associated metadata files
        for suffix in ["_metadata.json", "_structure.json"]:
            meta_file = self.workspace_dir / f"{repo_name}{suffix}"
            if meta_file.exists():
                try:
                    meta_file.unlink()
                except Exception as e:
                    logger.debug("Failed to delete %s: %s", meta_file, e)

        self._state_manager.remove_repository(repo_name)
        return True

    def get_repository_info(self, repo_name: str) -> RepositoryInfo:
        """Get detailed information about a specific repository.

        Args:
            repo_name: Name of the repository

        Returns:
            RepositoryInfo object with repository details

        Raises:
            RepositoryError: If repository not found
        """
        repo_data = self._state_manager.get_repository(repo_name)

        if not repo_data:
            raise RepositoryError(f"Repository not found: {repo_name}")

        return RepositoryInfo(
            name=repo_data["name"],
            path=repo_data["path"],
            url=repo_data.get("url"),
            branch=repo_data.get("branch"),
            last_commit=repo_data.get("last_commit"),
            is_dirty=repo_data.get("is_dirty", False),
            size_mb=repo_data.get("size_mb", 0.0),
            cloned_at=repo_data.get("cloned_at"),
        )

    def sync_repositories(self) -> list[str]:
        """Synchronize state with filesystem.

        Verifies that all repositories in the state file actually exist
        on disk. Removes entries for repositories that no longer exist.

        Returns:
            List of repository names that were removed from state.
        """
        return self._state_manager.sync_state()

    def extract_metadata(
        self, repo_name: str, output_dir: Path | None = None
    ) -> tuple[Path, Path]:
        """Extract metadata from a repository.

        Creates two JSON files:
        1. {repo_name}_metadata.json - General metadata
        2. {repo_name}_structure.json - Full file structure

        Args:
            repo_name: Name of the repository
            output_dir: Directory to save JSON files (defaults to workspace)

        Returns:
            Tuple of (metadata_file_path, structure_file_path)

        Raises:
            MetadataError: If metadata extraction fails
            RepositoryError: If repository not found
        """
        repo_path = self.workspace_dir / repo_name

        if not repo_path.exists():
            raise RepositoryError(f"Repository not found: {repo_name}")

        if not (repo_path / ".git").exists():
            raise MetadataError(f"Not a Git repository: {repo_path}")

        if output_dir is None:
            output_dir = self.workspace_dir

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        metadata = _extract_general_metadata(repo_path)
        structure = _extract_file_structure(repo_path)

        metadata_file = output_dir / f"{repo_name}_metadata.json"
        structure_file = output_dir / f"{repo_name}_structure.json"

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)

        with open(structure_file, "w", encoding="utf-8") as f:
            json.dump(structure.to_dict(), f, indent=2, ensure_ascii=False)

        return metadata_file, structure_file


# =============================================================================
# Convenience Functions
# =============================================================================


def validate_repo(repo_url: str, check_remote: bool = False) -> bool:
    """Quick validation of a repository URL."""
    try:
        manager = RepoManager()
        return manager.validate_repository(repo_url, check_remote)
    except ValidationError:
        return False


def clone_repo(repo_url: str, **kwargs) -> RepositoryInfo:
    """Quick clone of a repository."""
    manager = RepoManager()
    return manager.clone_repository(repo_url, **kwargs)


def list_repos(detailed: bool = True) -> list[str | RepositoryInfo]:
    """Quick list of all repositories."""
    manager = RepoManager()
    return manager.list_repositories(detailed)


def delete_repo(repo_name: str, force: bool = False) -> bool:
    """Quick deletion of a repository."""
    manager = RepoManager()
    return manager.delete_repository(repo_name, force)


def extract_repo_metadata(repo_name: str) -> tuple[Path, Path]:
    """Quick metadata extraction from a repository."""
    manager = RepoManager()
    return manager.extract_metadata(repo_name)


def sync_repos() -> list[str]:
    """Quick sync of repository state with filesystem."""
    manager = RepoManager()
    return manager.sync_repositories()
