"""Repository Manager - Git repository operations and metadata extraction.

This package provides a modular repository management system for
validation, cloning, listing, deletion, and metadata extraction.
"""

from __future__ import annotations

from .manager import (
    RepoManager,
    clone_repo,
    delete_repo,
    extract_repo_metadata,
    list_repos,
    sync_repos,
    validate_repo,
)
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

__all__ = [
    # Manager
    "RepoManager",
    # Convenience functions
    "validate_repo",
    "clone_repo",
    "list_repos",
    "delete_repo",
    "extract_repo_metadata",
    "sync_repos",
    # Models
    "RepositoryInfo",
    "RepositoryMetadata",
    "FileNode",
    # Exceptions
    "CloneError",
    "DeleteError",
    "MetadataError",
    "RepositoryError",
    "ValidationError",
]

__version__ = "2.0.0"
