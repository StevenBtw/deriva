"""
Shared data models and exceptions for repository operations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Re-export exceptions for backwards compatibility
from deriva.common.exceptions import CloneError as CloneError
from deriva.common.exceptions import DeleteError as DeleteError
from deriva.common.exceptions import MetadataError as MetadataError
from deriva.common.exceptions import RepositoryError as RepositoryError
from deriva.common.exceptions import ValidationError as ValidationError

__all__ = [
    # Exceptions (re-exported)
    "CloneError",
    "DeleteError",
    "MetadataError",
    "RepositoryError",
    "ValidationError",
    # Models
    "RepositoryInfo",
    "RepositoryMetadata",
    "FileNode",
]


@dataclass
class RepositoryInfo:
    """Information about a repository."""

    name: str
    path: str
    url: str | None = None
    branch: str | None = None
    last_commit: str | None = None
    is_dirty: bool = False
    size_mb: float = 0.0
    cloned_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class RepositoryMetadata:
    """General metadata about a repository."""

    name: str
    url: str
    description: str | None
    total_size_mb: float
    total_files: int
    total_directories: int
    languages: dict[str, int]  # Language -> file count
    created_at: str
    last_updated: str
    default_branch: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class FileNode:
    """Represents a file or directory in the repository structure."""

    name: str
    path: str
    type: str  # 'file' or 'directory'
    size_bytes: int = 0
    children: list | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary recursively."""
        result = {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "size_bytes": self.size_bytes,
        }
        if self.children:
            result["children"] = [
                child.to_dict() if hasattr(child, "to_dict") else child
                for child in self.children
            ]
        return result
