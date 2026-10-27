"""Repository Manager - Git repository operations and metadata extraction.

This module provides a fully decoupled, modular repository management system.
Handles validation, cloning, listing, deletion, and metadata extraction.

Usage:
    from deriva.adapters.repository import RepoManager

    repo_mgr = RepoManager()

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
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from deriva.common import settings
from deriva.common.file_utils import long_path
from deriva.common.paths import resolve
from deriva.common.settings import RepositorySettings
from deriva.common.urls import redact_credentials

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
                    if not state or "version" not in state or "repositories" not in state:
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


def _git_env() -> dict[str, str]:
    """Git without terminal prompts: a repository that needs credentials fails at once instead of waiting for a username
    on the terminal that started Deriva (a credential helper still answers)."""
    return settings.child_environment(GIT_TERMINAL_PROMPT="0")


def _git_safety(allow_local: bool = False) -> list[str]:
    """Config for git on an untrusted repository, its submodules included (``-c`` reaches every git process it starts):
    network protocols only, so a submodule URL cannot read a local repository or run a command (``ext::``); a local URL
    only where the user gave it (``user``: never a submodule's); symlinks checked out as plain files, so no link in the
    clone reaches outside it."""
    configs = ["protocol.allow=never", *(f"protocol.{p}.allow=always" for p in ("https", "http", "ssh", "git"))]
    configs += [f"protocol.file.allow={'user' if allow_local else 'never'}", "core.symlinks=false"]
    return [part for config in configs for part in ("-c", config)]


def _git_timeout() -> int:
    """Seconds a clone or pull may take (``DERIVA_GIT_TIMEOUT``): a stalled remote must not hold the run lock forever."""
    try:
        return max(1, int(settings.get("DERIVA_GIT_TIMEOUT") or 1800))
    except ValueError:
        return 1800


# The first release of each line with the fixes for the submodule CVEs of July 2025 (CVE-2025-48384 and others)
_GIT_FIXED = {(2, 43): 7, (2, 44): 4, (2, 45): 4, (2, 46): 4, (2, 47): 3, (2, 48): 2, (2, 49): 1, (2, 50): 1}


def git_outdated(version_output: str) -> bool:
    """True for a ``git --version`` before the submodule fixes of its release line (unknown versions are not reported)."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_output)
    if not match:
        return False
    major, minor, patch = (int(g) for g in match.groups())
    if (major, minor) in _GIT_FIXED:
        return patch < _GIT_FIXED[(major, minor)]
    return (major, minor) < (2, 43)


def _warn_if_git_outdated() -> None:
    try:
        output = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=10, check=False).stdout
    except OSError, subprocess.SubprocessError:
        return
    if git_outdated(output):
        logger.warning("%s predates the fixes for git's submodule vulnerabilities (CVE-2025-48384); update git before cloning untrusted repositories", output.strip())


# STATUS_DLL_INIT_FAILED: Windows could not start git or one of its helpers (as git's exit code, unsigned or signed)
_GIT_START_FAILED = (0xC0000142, 0xC0000142 - 2**32)
GIT_COULD_NOT_START = (
    "Git could not start (Windows error 0xC0000142: a library it needs failed to initialize). Run git --version in a "
    "terminal: if that fails too, repair or reinstall Git for Windows; if it works there, an antivirus or the account "
    "Deriva runs under stops git when Deriva starts it: start Deriva from a normal terminal, or exclude the Git folder "
    "from the antivirus"
)

# What a git error means for the user: (pattern in git's output, sentence; {1} is the pattern's first group)
_GIT_ERRORS: list[tuple[str, str]] = [
    (r"(?i)0xc0000142", GIT_COULD_NOT_START),
    (r"Remote branch (\S+) not found", "The repository has no branch {1}"),
    (r"repository '[^']*' not found|Repository not found", "The repository was not found: check the URL. A private repository needs git credentials on this machine"),
    (r"Could not resolve host: (\S+)", "Could not reach {1}: check the URL and the network connection"),
    (r"Authentication failed|Invalid username or password", "The git credentials were refused for this repository"),
    (r"Not possible to fast-forward|divergent branches", "The clone has commits of its own that the remote does not have, so it cannot be updated by fast-forward"),
    (
        r"transport '(\w+)' not allowed",
        "A remote or submodule uses the {1} protocol, which clones do not allow (only https, http, ssh and git; a local URL only as the URL given to clone)",
    ),
    (r"could not read Username|terminal prompts disabled", "This repository needs git credentials: set up a git credential helper or use a URL your git can open"),
]


def explain_git_error(output: str, action: str = "clone") -> str:
    """A git failure as a sentence the user can act on, with git's own last line (``Git <action> failed`` when unknown)."""
    lines = [line.strip() for line in (output or "").strip().splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"
    for pattern, sentence in _GIT_ERRORS:
        match = re.search(pattern, output or "")
        if match:
            return redact_credentials(f"{sentence.replace('{1}', match.group(1) if match.groups() else '')} (git: {last})")
    return redact_credentials(f"Git {action} failed (git: {last})")


def _git_failure(error: subprocess.CalledProcessError, action: str) -> str:
    """Why a git command failed: a git that could not start by its exit code, else from what git said."""
    if error.returncode in _GIT_START_FAILED:
        return GIT_COULD_NOT_START
    return explain_git_error(error.stderr or error.stdout or str(error), action)


def _discard(folder: Path) -> None:
    """Remove a staging folder (best effort: it holds no user files)."""
    if folder.exists():
        try:
            _force_remove_directory(folder)
        except Exception as e:
            logger.warning("Could not remove the staging folder %s: %s", folder, e)


def _move_into_place(staging: Path, target: Path, attempts: int = 3) -> None:
    """Rename a finished clone to its folder; a virus scanner can hold a file for a moment on Windows."""
    for attempt in range(attempts):
        try:
            os.replace(staging, target)
            return
        except OSError as e:
            if attempt == attempts - 1:
                _discard(staging)
                raise CloneError(f"The clone worked but could not be moved to {target.name}: {e}")
            time.sleep(0.5)


def _is_valid_git_url(url: str) -> bool:
    """Check if URL is a valid Git repository URL."""
    patterns = [
        r"^https?://[^\s/$.?#].[^\s]*\.git$",
        r"^https?://[^\s/$.?#].[^\s]*$",
        r"^git@[^\s:]+:[^\s]+\.git$",
        r"^git@[^\s:]+:[^\s]+$",
        r"^ssh://[^\s]+\.git$",
        r"^file://[^\s]+$",  # a bare repository or a working tree
    ]
    return any(re.match(pattern, url) for pattern in patterns)


def _check_remote_exists(repo_url: str) -> bool:
    """Check if remote repository exists and is accessible."""
    try:
        subprocess.run(
            ["git", *_git_safety(), "ls-remote", repo_url],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            env=_git_env(),
        )
        return True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return False


def _extract_repo_name(repo_url: str) -> str:
    """Extract repository name from URL (a local ``.../name/.git`` is named after the folder that holds it)."""
    url = repo_url.rstrip("/")
    if url.endswith("/.git"):
        url = url[:-5]
    elif url.endswith(".git"):
        url = url[:-4]
    return url.split("/")[-1]


def _handle_remove_readonly(func, path, exc):
    """Error handler for Windows readonly files."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _force_remove_directory(path: Path, max_retries: int = 3) -> None:
    """Forcefully remove a directory, handling Windows file locks."""
    target = long_path(path)
    for attempt in range(max_retries):
        try:
            if os.name == "nt":
                shutil.rmtree(target, onexc=_handle_remove_readonly)
            else:
                shutil.rmtree(target)
            return
        except PermissionError as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue
            else:
                raise DeleteError(f"Failed to delete directory after {max_retries} attempts. Some files may be locked by another process: {e}")
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
        for dirpath, dirnames, filenames in os.walk(long_path(path)):
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
    except subprocess.CalledProcessError, OSError:
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
            except OSError, UnicodeDecodeError:
                pass
    return None


def _count_files_and_dirs(path: Path) -> tuple[int, int]:
    """Count total files and directories."""
    file_count = 0
    dir_count = 0
    try:
        for dirpath, dirnames, filenames in os.walk(long_path(path)):
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
    except subprocess.CalledProcessError, OSError:
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
    except subprocess.CalledProcessError, OSError:
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
    except subprocess.CalledProcessError, OSError:
        return "unknown"


def _get_commit_hash(repo_path: Path) -> str | None:
    """Get the full SHA hash of HEAD commit for audit traceability."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError, OSError:
        return None


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
    commit_hash = _get_commit_hash(repo_path)

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
        commit_hash=commit_hash,
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

            dir_size = sum(child.size_bytes for child in children if child.type == "file")

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


# =============================================================================
# Repository Manager
# =============================================================================


def _stale(repo_path: Path) -> str | None:
    """Why a record no longer matches its folder, or None."""
    if not repo_path.exists():
        return "its folder is gone"
    if not (repo_path / ".git").exists():
        return "its folder is no git checkout"
    return None


def _working_tree_dirty(repo_path: Path, stored: bool) -> bool:
    """Whether the checkout has uncommitted changes now (the stored value when git cannot tell)."""
    try:
        result = subprocess.run(["git", "-C", str(repo_path), "status", "--porcelain"], capture_output=True, encoding="utf-8", errors="replace", check=True)
    except subprocess.CalledProcessError, OSError:
        return stored
    return bool(result.stdout.strip())


class RepoManager:
    """Repository Manager for Git operations.

    Provides a clean interface for managing Git repositories with
    validation, cloning, listing, deletion, and metadata extraction.
    """

    def __init__(self, workspace_dir: str | Path | None = None):
        """Initialize the Repository Manager.

        Args:
            workspace_dir: Directory where repositories will be stored. Defaults to the
                          REPOSITORY_WORKSPACE_DIR setting (workspace/repositories), relative
                          to the Deriva home folder, the same folder the session lists.
        """
        if workspace_dir is None:
            workspace_dir = RepositorySettings().workspace_dir

        ws_path = Path(workspace_dir)
        if not ws_path.is_absolute():
            ws_path = resolve(ws_path).resolve()
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
            raise ValidationError(f"Invalid Git URL format: {redact_credentials(repo_url)}")

        if check_remote and not _check_remote_exists(repo_url):
            raise ValidationError(f"Remote repository not accessible: {redact_credentials(repo_url)}")

        return True

    def clone_repository(
        self,
        repo_url: str,
        target_name: str | None = None,
        branch: str | None = None,
        depth: int | None = None,
        overwrite: bool = False,
        submodules: bool = True,
        allow_local: bool = False,
    ) -> RepositoryInfo:
        """Clone a Git repository.

        Args:
            repo_url: The repository URL to clone
            target_name: Custom name for the cloned directory
            branch: Specific branch to clone
            depth: Clone depth for shallow clones
            overwrite: If True, removes existing directory before cloning
            submodules: Clone the submodules too (their URLs limited to network protocols)
            allow_local: Accept a ``file://`` URL (the command line; the studio never clones local repositories)

        Returns:
            RepositoryInfo object with details about the cloned repository

        Raises:
            CloneError: If cloning fails
            ValidationError: If the repository URL is invalid
        """
        self.validate_repository(repo_url)
        if repo_url.startswith("file://") and not allow_local:
            raise ValidationError("Local repositories are cloned from the command line only (deriva-cli repo clone)")

        if target_name is None:
            target_name = _extract_repo_name(repo_url)

        target_path = self._repository_path(target_name)

        if target_path.exists():
            if overwrite:
                try:
                    _force_remove_directory(target_path)
                except Exception as e:
                    raise CloneError(f"Failed to remove existing directory: {e}")
            else:
                raise CloneError(f"A folder named {target_name} already exists in the workspace: give the clone another name, or delete that repository first")

        # Long paths: on Windows a deep home folder plus git's own file names can pass 260 characters
        # Submodules too: a repository that keeps its modules as submodules is nearly empty without them
        cmd = ["git", *_git_safety(allow_local), "clone", "--config", "core.longpaths=true"]
        if submodules:
            cmd.append("--recurse-submodules")
        if branch:
            cmd.extend(["--branch", branch])
        if depth:
            cmd.extend(["--depth", str(depth)])
            if submodules:
                cmd.append("--shallow-submodules")
        # Into a staging folder first: only a clone that worked becomes the repository's folder, and a failed one
        # (a checkout that stopped half way) leaves nothing a retry would find in its way
        staging = self.workspace_dir / f".clone-{uuid.uuid4().hex[:8]}"
        cmd.extend([repo_url, str(staging)])

        timeout = _git_timeout()
        try:
            subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", check=True, env=_git_env(), timeout=timeout)
        except subprocess.TimeoutExpired:
            _discard(staging)
            raise CloneError(f"The clone took longer than {timeout} seconds and was stopped (DERIVA_GIT_TIMEOUT sets the limit)")
        except subprocess.CalledProcessError as e:
            _discard(staging)
            raise CloneError(_git_failure(e, "clone"))
        except FileNotFoundError:
            _discard(staging)
            raise CloneError("Git is not installed or not in PATH. Please install Git to use clone functionality.")
        _move_into_place(staging, target_path)
        if submodules:
            _warn_if_git_outdated()

        result = _get_repository_info_from_path(target_path, redact_credentials(repo_url))
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
                    # Read now: the stored state is from the clone, and edits since must show
                    is_dirty=False if _stale(Path(repo["path"])) else _working_tree_dirty(Path(repo["path"]), repo.get("is_dirty", False)),
                    size_mb=repo.get("size_mb", 0.0),
                    cloned_at=repo.get("cloned_at"),
                    stale=_stale(Path(repo["path"])),
                )
                for repo in repos_data
            ]
        else:
            return [repo["name"] for repo in repos_data]

    def _repository_path(self, name: str) -> Path:
        """The folder of a repository: one name in the workspace (a path could clone, overwrite or delete elsewhere)."""
        if not name or name in (".", "..") or any(sep in name for sep in ("/", "\\", ":")) or Path(name).is_absolute():
            raise RepositoryError(f"A repository name is one folder name, not a path: {name!r}")
        path = self.workspace_dir / name
        if path.resolve().parent != self.workspace_dir.resolve():
            raise RepositoryError(f"A repository name is one folder name, not a path: {name!r}")
        return path

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
        repo_path = self._repository_path(repo_name)

        # A record whose folder is gone or is no git checkout: only the record goes, never files that are no clone
        if self._state_manager.get_repository(repo_name) is not None and _stale(repo_path):
            self._state_manager.remove_repository(repo_name)
            return True

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
                    raise DeleteError(f"Repository has uncommitted changes: {repo_name}. Use force=True to delete anyway.")
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

    def update_repository(self, repo_name: str) -> RepositoryInfo:
        """Pull the clone's branch, fast-forward only, and store its new state (it keeps when it was cloned).

        Raises:
            RepositoryError: unknown repository, uncommitted changes, or a pull git refuses (with git's reason)
        """
        repo_path = self._repository_path(repo_name)
        stored = self._state_manager.get_repository(repo_name)
        if stored is None or not (repo_path / ".git").exists():
            raise RepositoryError(f"Repository not found: {repo_name}")
        if _working_tree_dirty(repo_path, False):
            raise RepositoryError(f"Repository has uncommitted changes: {repo_name}. Commit or discard them before updating.")
        try:
            subprocess.run(
                # From the remote the clone came from (a URL the user gave, so it may be local); submodules never local
                ["git", *_git_safety(allow_local=True), "-C", str(repo_path), "pull", "--ff-only", "--recurse-submodules"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                env=_git_env(),
                timeout=_git_timeout(),
            )
        except subprocess.TimeoutExpired:
            raise RepositoryError(f"The pull took longer than {_git_timeout()} seconds and was stopped (DERIVA_GIT_TIMEOUT sets the limit)")
        except subprocess.CalledProcessError as e:
            raise RepositoryError(_git_failure(e, "pull"))
        except FileNotFoundError:
            raise RepositoryError("Git is not installed or not in PATH. Please install Git to update repositories.")
        result = _get_repository_info_from_path(repo_path, stored.get("url") or "")
        result.cloned_at = stored.get("cloned_at")
        self._state_manager.add_repository(result)
        return result

    def unregistered(self) -> list[str]:
        """Git folders in the workspace without a record (a clone whose record was lost, a checkout put there by hand)."""
        known = {repo["name"] for repo in self._state_manager.list_repositories()}
        return sorted(p.name for p in self.workspace_dir.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / ".git").exists() and p.name not in known)

    def register_repository(self, repo_name: str) -> RepositoryInfo:
        """Record a git folder that is in the workspace but not in the registry.

        Raises:
            RepositoryError: the name is registered already, or its folder is no git checkout
        """
        repo_path = self._repository_path(repo_name)
        if self._state_manager.get_repository(repo_name) is not None:
            raise RepositoryError(f"{repo_name} is registered already")
        if not (repo_path / ".git").exists():
            raise RepositoryError(f"{repo_name} has no git checkout in the workspace")
        result = _get_repository_info_from_path(repo_path, redact_credentials(_get_git_remote_url(repo_path) or ""))
        self._state_manager.add_repository(result)
        return result

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

    def extract_metadata(self, repo_name: str, output_dir: Path | None = None) -> tuple[Path, Path]:
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
