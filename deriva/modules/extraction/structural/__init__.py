"""
Structural extraction module - Pure functions for extracting structural graph nodes.

This package provides extraction functions for structural elements:
- repository: Repository node extraction
- directory: Directory node extraction
- file: File node extraction

These extractors work without LLM - they parse filesystem structure directly.
"""

from __future__ import annotations

from .directory import build_directory_node, extract_directories
from .file import build_file_node, extract_files
from .repository import build_repository_node, extract_repository

__all__ = [
    # Repository
    "build_repository_node",
    "extract_repository",
    # Directory
    "build_directory_node",
    "extract_directories",
    # File
    "build_file_node",
    "extract_files",
]
