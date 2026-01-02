"""
Input sources parsing utilities for extraction configuration.

This module provides functions to parse and filter files based on the
input_sources JSON configuration format:

{
    "files": [{"type": "source", "subtype": "*"}],
    "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]
}
"""

from __future__ import annotations

import json
from typing import Any


def parse_input_sources(input_sources_json: str | None) -> dict[str, Any]:
    """
    Parse the input_sources JSON string into a structured dict.

    Args:
        input_sources_json: JSON string from database

    Returns:
        Dict with 'files' and 'nodes' lists, or empty lists if parsing fails
    """
    if not input_sources_json:
        return {"files": [], "nodes": []}

    try:
        parsed = json.loads(input_sources_json)
        return {"files": parsed.get("files", []), "nodes": parsed.get("nodes", [])}
    except json.JSONDecodeError:
        return {"files": [], "nodes": []}


def matches_file_spec(
    file_type: str, file_subtype: str | None, file_specs: list[dict[str, str]]
) -> bool:
    """
    Check if a file matches any of the file specifications.

    Args:
        file_type: The file's type (e.g., 'source', 'docs', 'config')
        file_subtype: The file's subtype (e.g., 'python', 'markdown')
        file_specs: List of {"type": "...", "subtype": "..."} specs

    Returns:
        True if the file matches any spec
    """
    if not file_specs:
        return False

    for spec in file_specs:
        spec_type = spec.get("type", "")
        spec_subtype = spec.get("subtype", "*")

        # Type must match exactly
        if spec_type != file_type:
            continue

        # Subtype matches if wildcard or exact match
        if spec_subtype == "*" or spec_subtype == file_subtype:
            return True

    return False


def filter_files_by_input_sources(
    classified_files: list[dict[str, Any]], input_sources: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Filter classified files based on input_sources file specs.

    Args:
        classified_files: List of classified file dicts with 'file_type' and 'subtype'
        input_sources: Parsed input_sources dict with 'files' list

    Returns:
        List of files matching the input_sources file specs
    """
    file_specs = input_sources.get("files", [])

    if not file_specs:
        return []

    return [
        f
        for f in classified_files
        if matches_file_spec(f.get("file_type", ""), f.get("subtype"), file_specs)
    ]


def get_node_sources(input_sources: dict[str, Any]) -> list[dict[str, str]]:
    """
    Get the node source specifications from input_sources.

    Args:
        input_sources: Parsed input_sources dict

    Returns:
        List of node specs: [{"label": "TypeDefinition", "property": "codeSnippet"}]
    """
    return input_sources.get("nodes", [])


def has_file_sources(input_sources: dict[str, Any]) -> bool:
    """Check if input_sources specifies any file sources."""
    return bool(input_sources.get("files", []))


def has_node_sources(input_sources: dict[str, Any]) -> bool:
    """Check if input_sources specifies any node sources."""
    return bool(input_sources.get("nodes", []))
