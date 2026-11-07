"""
Utility functions for the extraction pipeline.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .types import LLMDetails, PipelineResult

__all__ = [
    "describe_os_error",
    "is_inside",
    "long_path",
    "read_file_with_encoding",
    "create_pipeline_result",
]

_EXTENDED = "\\\\?\\"


def is_inside(path: Path, root: Path) -> bool:
    """True when ``path`` is no symlink and resolves inside ``root``. A link in a cloned repository (a symlink, or a
    junction on Windows) must never reach files outside it, such as the user's ``.env`` or SSH keys."""
    try:
        return not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def long_path(path: Path) -> Path:
    """The path in Windows' extended form (``\\\\?\\C:\\...``), which opens paths over 260 characters even where long
    paths are off in the registry; a walk from such a root yields such paths. Other systems keep the path."""
    if sys.platform != "win32" or str(path).startswith(_EXTENDED):
        return path
    # The extended form takes no "..", "." or forward slashes: the absolute, normalised path goes in
    absolute = os.path.abspath(path)
    if absolute.startswith("\\\\"):
        return Path(_EXTENDED + "UNC\\" + absolute[2:])
    return Path(_EXTENDED + absolute)


def describe_os_error(error: BaseException) -> str:
    """An error without the file name an OSError carries ("[Errno 13] Permission denied"): the message names the
    repository-relative path itself, not the absolute one (on Windows in its extended form)."""
    if isinstance(error, OSError) and error.strerror:
        winerror = getattr(error, "winerror", None)
        return f"[WinError {winerror}] {error.strerror}" if winerror else f"[Errno {error.errno}] {error.strerror}"
    return str(error)


def read_file_with_encoding(file_path: Path) -> str | None:
    """
    Read a file with automatic encoding detection.

    Handles common encodings including:
    - UTF-8 (with and without BOM)
    - UTF-16 LE/BE (with BOM)
    - Latin-1 fallback

    Args:
        file_path: Path to the file

    Returns:
        File content as string, or None if reading fails
    """
    try:
        # Read raw bytes to detect encoding
        with open(long_path(file_path), "rb") as f:
            raw = f.read()

        # Check for BOM markers and decode accordingly
        if raw.startswith(b"\xff\xfe"):
            # UTF-16 LE with BOM - decode and strip BOM
            content = raw.decode("utf-16-le")
            # Remove BOM if present at start
            if content.startswith("\ufeff"):
                content = content[1:]
            return content

        if raw.startswith(b"\xfe\xff"):
            # UTF-16 BE with BOM - decode and strip BOM
            content = raw.decode("utf-16-be")
            if content.startswith("\ufeff"):
                content = content[1:]
            return content

        if raw.startswith(b"\xef\xbb\xbf"):
            # UTF-8 with BOM - skip BOM bytes
            return raw[3:].decode("utf-8")

        # Try UTF-8 first
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # Try Latin-1 as fallback (accepts all byte values)
        return raw.decode("latin-1")

    except OSError, UnicodeDecodeError:
        return None


def create_pipeline_result(
    stage: str,
    success: bool = True,
    elements: list[dict[str, Any]] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    stats: dict[str, Any] | None = None,
    issues: list[dict[str, Any]] | None = None,
    llm_details: LLMDetails | None = None,
    start_time: datetime | None = None,
) -> PipelineResult:
    """
    Create a standardized pipeline result.

    Args:
        stage: Pipeline stage ('extraction', 'derivation', 'validation')
        success: Whether the operation succeeded
        elements: List of created/processed elements
        relationships: List of created/processed relationships
        errors: List of error messages
        warnings: List of warning messages
        stats: Statistics about the operation
        issues: Validation issues (for validation stage)
        llm_details: LLM call details
        start_time: Start time for duration calculation

    Returns:
        Standardized PipelineResult
    """
    now = datetime.now(UTC)
    timestamp = now.isoformat().replace("+00:00", "Z")

    duration_ms = 0
    if start_time:
        delta = now - start_time
        duration_ms = int(delta.total_seconds() * 1000)

    result: PipelineResult = {
        "success": success,
        "errors": errors or [],
        "warnings": warnings or [],
        "stats": stats or {},
        "elements": elements or [],
        "relationships": relationships or [],
        "stage": stage,
        "timestamp": timestamp,
        "duration_ms": duration_ms,
    }

    if llm_details:
        result["llm_details"] = llm_details

    if issues:
        result["issues"] = issues

    return result
