"""
Base utilities for extraction modules.

This module provides shared functions and patterns used across all extraction modules:
- Prompt building helpers
- Response parsing utilities
- Node ID generation
- Error handling patterns
- Input sources parsing
- Name normalization

All extraction modules should use these utilities to maintain consistency.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from deriva.common import (
    calculate_duration_ms,
    create_empty_llm_details,
    current_timestamp,
    extract_llm_details,
    parse_json_array,
)
from deriva.common.types import LLMDetails, PipelineResult


# =============================================================================
# Node/Edge ID Generation
# =============================================================================


def strip_chunk_suffix(file_path: str) -> str:
    """
    Strip chunk suffix from file path.

    When files are chunked, paths get "(lines X-Y)" suffix. This strips it
    to get the original file path for node ID generation.

    Args:
        file_path: File path potentially with chunk suffix

    Returns:
        Original file path without chunk suffix

    Examples:
        >>> strip_chunk_suffix("src/app.py (lines 1-100)")
        'src/app.py'
        >>> strip_chunk_suffix("src/app.py")
        'src/app.py'
    """
    return re.sub(r"\s*\(lines \d+-\d+\)$", "", file_path)


def generate_node_id(prefix: str, repo_name: str, identifier: str) -> str:
    """
    Generate a consistent node ID.

    Args:
        prefix: Node type prefix (e.g., 'concept', 'type', 'method')
        repo_name: Repository name
        identifier: Unique identifier within the type

    Returns:
        Formatted node ID string
    """
    # Normalize identifier for consistent IDs
    normalized = identifier.lower().replace(" ", "_").replace("-", "_")
    normalized = "".join(c for c in normalized if c.isalnum() or c == "_")
    return f"{prefix}_{repo_name}_{normalized}"


def generate_edge_id(from_node_id: str, to_node_id: str, relationship_type: str) -> str:
    """
    Generate a consistent edge ID.

    Args:
        from_node_id: Source node ID
        to_node_id: Target node ID
        relationship_type: Type of relationship

    Returns:
        Formatted edge ID string
    """
    rel_type = relationship_type.lower()
    return f"{rel_type}_{from_node_id}_to_{to_node_id}"


# =============================================================================
# JSON Response Parsing
# =============================================================================


def parse_json_response(response_content: str, array_key: str) -> dict[str, Any]:
    """
    Parse and validate LLM JSON response with a specific array key.

    Args:
        response_content: Raw JSON string from LLM
        array_key: Expected key containing the array (e.g., 'concepts', 'types')

    Returns:
        Dictionary with:
            - success: bool
            - data: Parsed items list
            - errors: List of parsing errors
    """
    return parse_json_array(response_content, array_key).to_dict()


def validate_required_fields(
    data: dict[str, Any], required_fields: list[str]
) -> list[str]:
    """
    Validate that required fields are present and non-empty.

    Args:
        data: Dictionary to validate
        required_fields: List of required field names

    Returns:
        List of error messages (empty if all valid)
    """
    errors = []
    for field in required_fields:
        if field not in data or not data[field]:
            errors.append(f"Missing required field: {field}")
    return errors


def deduplicate_nodes(
    nodes: list[dict[str, Any]], key: str = "node_id"
) -> list[dict[str, Any]]:
    """
    Deduplicate nodes by a key field, preserving order.

    Used when aggregating results from chunked extraction where the same
    node might be extracted from overlapping chunks.

    Args:
        nodes: List of node dictionaries to deduplicate
        key: Field name to use for deduplication (default: "node_id")

    Returns:
        List of unique nodes, preserving first occurrence order
    """
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for node in nodes:
        node_key = node.get(key, "")
        if node_key and node_key not in seen:
            seen.add(node_key)
            unique.append(node)
    return unique


def create_extraction_result(
    success: bool,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    errors: list[str],
    stats: dict[str, Any],
    llm_details: LLMDetails | None = None,
    warnings: list[str] | None = None,
    start_time: datetime | None = None,
) -> PipelineResult:
    """
    Create a standardized extraction result dictionary.

    Args:
        success: Whether the extraction succeeded
        nodes: List of created nodes (mapped to 'elements')
        edges: List of created edges (mapped to 'relationships')
        errors: List of error messages
        stats: Statistics dictionary
        llm_details: Optional LLM call details
        warnings: Optional list of warning messages
        start_time: Optional start time for duration calculation

    Returns:
        Standardized PipelineResult
    """
    timestamp = current_timestamp()
    duration_ms = calculate_duration_ms(start_time) if start_time else 0

    result: PipelineResult = {
        "success": success,
        "elements": nodes,
        "relationships": edges,
        "errors": errors,
        "warnings": warnings or [],
        "stats": stats,
        "stage": "extraction",
        "timestamp": timestamp,
        "duration_ms": duration_ms,
    }

    if llm_details is not None:
        result["llm_details"] = llm_details

    return result


# Backward compatibility alias
extract_llm_details_from_response = extract_llm_details


# =============================================================================
# Input Sources Parsing
# =============================================================================


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


# =============================================================================
# Name Normalization - Canonical Mappings
# =============================================================================

# Map lowercase variations to official package names
PACKAGE_CANONICAL_NAMES: dict[str, str] = {
    # Python packages (PyPI)
    "flask": "Flask",
    "sqlalchemy": "SQLAlchemy",
    "flask-sqlalchemy": "Flask-SQLAlchemy",
    "flask_sqlalchemy": "Flask-SQLAlchemy",
    "jinja2": "Jinja2",
    "jinja": "Jinja2",
    "wtforms": "WTForms",
    "flask-wtf": "Flask-WTF",
    "flask_wtf": "Flask-WTF",
    "weasyprint": "WeasyPrint",
    "pydantic": "Pydantic",
    "requests": "Requests",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "scipy": "SciPy",
    "matplotlib": "Matplotlib",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "django": "Django",
    "fastapi": "FastAPI",
    "pytest": "pytest",
    "lxml": "lxml",
    "pillow": "Pillow",
    "pil": "Pillow",
    "opencv": "OpenCV",
    "cv2": "OpenCV",
    "beautifulsoup": "BeautifulSoup",
    "beautifulsoup4": "BeautifulSoup",
    "bs4": "BeautifulSoup",
    "celery": "Celery",
    "redis": "Redis",
    "pymongo": "PyMongo",
    "boto3": "Boto3",
    "gunicorn": "Gunicorn",
    "uwsgi": "uWSGI",
    "nginx": "Nginx",
    "apache": "Apache",
    "marimo": "Marimo",
    "duckdb": "DuckDB",
    "neo4j": "Neo4j",
    "sqlite": "SQLite",
    "sqlite3": "SQLite",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "clickhouse": "ClickHouse",
    # JavaScript/npm packages
    "jquery": "jQuery",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "bootstrap": "Bootstrap",
    "popper": "Popper.js",
    "popper.js": "Popper.js",
    "lodash": "Lodash",
    "axios": "Axios",
    "express": "Express",
    "nextjs": "Next.js",
    "next": "Next.js",
    # Infrastructure
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "heroku": "Heroku",
}

# Suffixes to remove from normalized names
REDUNDANT_SUFFIXES = [
    "_orm",
    "_database",
    "_db",
    "_service",
    "_lib",
    "_library",
    "_framework",
    "_package",
    "_module",
    " orm",
    " database",
    " service",
]


# =============================================================================
# Singularization Rules
# =============================================================================

# Words that shouldn't be singularized
UNCOUNTABLE_WORDS = {
    "data",
    "information",
    "software",
    "hardware",
    "middleware",
    "metadata",
    "analytics",
    "logistics",
    "news",
    "status",
}

# Irregular plurals
IRREGULAR_PLURALS: dict[str, str] = {
    "indices": "index",
    "matrices": "matrix",
    "vertices": "vertex",
    "analyses": "analysis",
    "bases": "base",
    "crises": "crisis",
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "data": "data",  # Keep as is
    "media": "medium",
    "children": "child",
    "people": "person",
}


def singularize(word: str) -> str:
    """
    Convert a plural word to singular form.

    Args:
        word: Word to singularize

    Returns:
        Singular form of the word
    """
    lower_word = word.lower()

    # Check uncountable words
    if lower_word in UNCOUNTABLE_WORDS:
        return word

    # Check irregular plurals
    if lower_word in IRREGULAR_PLURALS:
        # Preserve original case pattern
        singular = IRREGULAR_PLURALS[lower_word]
        if word[0].isupper():
            return singular.capitalize()
        return singular

    # Apply regular rules
    if lower_word.endswith("ies") and len(lower_word) > 3:
        # cities -> city, but not "series"
        if lower_word[-4] not in "aeiou":
            return word[:-3] + ("Y" if word[-3].isupper() else "y")

    if lower_word.endswith("es"):
        # Check for -ses, -xes, -zes, -ches, -shes
        if lower_word.endswith(("ses", "xes", "zes", "ches", "shes")):
            return word[:-2]

    if lower_word.endswith("s") and not lower_word.endswith("ss"):
        # Simple plural - remove s
        if len(lower_word) > 2:
            return word[:-1]

    return word


# =============================================================================
# Normalization Functions
# =============================================================================


def normalize_package_name(name: str) -> str:
    """
    Normalize a package/dependency name to its canonical form.

    Args:
        name: Package name to normalize

    Returns:
        Canonical package name with proper capitalization
    """
    if not name:
        return name

    # Remove redundant suffixes first
    normalized = name
    name_lower = name.lower()
    for suffix in REDUNDANT_SUFFIXES:
        if name_lower.endswith(suffix):
            normalized = name[: -len(suffix)]
            name_lower = normalized.lower()
            break

    # Check canonical mapping
    if name_lower in PACKAGE_CANONICAL_NAMES:
        return PACKAGE_CANONICAL_NAMES[name_lower]

    # If no canonical mapping, return with original case
    return normalized


def normalize_concept_name(name: str) -> str:
    """
    Normalize a business concept name.

    Applies:
    - Singularization
    - CamelCase conversion for multi-word names
    - Removal of redundant prefixes/suffixes

    Args:
        name: Concept name to normalize

    Returns:
        Normalized concept name
    """
    if not name:
        return name

    # Split on underscores and spaces
    parts = re.split(r"[_\s]+", name)

    # Singularize the last word (usually the noun)
    if parts:
        parts[-1] = singularize(parts[-1])

    # Convert to CamelCase
    result = "".join(part.capitalize() for part in parts if part)

    return result


def normalize_technology_name(name: str) -> str:
    """
    Normalize a technology name.

    Args:
        name: Technology name to normalize

    Returns:
        Canonical technology name
    """
    # Use package normalization (technologies are often packages)
    return normalize_package_name(name)


def normalize_node(
    node: dict[str, Any], node_type: str, repo_name: str | None = None
) -> dict[str, Any]:
    """
    Normalize names in an extracted node based on its type.

    Args:
        node: Node dictionary with 'properties' containing the name
        node_type: Type of node (ExternalDependency, BusinessConcept, etc.)
        repo_name: Repository name for generating consistent node IDs

    Returns:
        Node with normalized names
    """
    if "properties" not in node:
        return node

    props = node["properties"].copy()

    if node_type == "ExternalDependency":
        if "dependencyName" in props:
            props["dependencyName"] = normalize_package_name(props["dependencyName"])
    elif node_type == "BusinessConcept":
        if "conceptName" in props:
            props["conceptName"] = normalize_concept_name(props["conceptName"])
    elif node_type == "Technology":
        if "techName" in props:
            props["techName"] = normalize_technology_name(props["techName"])

    node_copy = node.copy()
    node_copy["properties"] = props

    # Update node_id if name changed and we have repo_name
    if node_type == "ExternalDependency" and "dependencyName" in props and repo_name:
        name_slug = (
            props["dependencyName"]
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
            .replace("/", "_")
        )
        node_copy["node_id"] = f"extdep_{repo_name}_{name_slug}"

    return node_copy


def normalize_nodes(
    nodes: list[dict[str, Any]], node_type: str, repo_name: str | None = None
) -> list[dict[str, Any]]:
    """
    Normalize names in a list of extracted nodes.

    Args:
        nodes: List of node dictionaries
        node_type: Type of nodes
        repo_name: Repository name for generating consistent node IDs

    Returns:
        List of nodes with normalized names
    """
    return [normalize_node(node, node_type, repo_name) for node in nodes]


def deduplicate_by_normalized_name(
    nodes: list[dict[str, Any]], name_key: str
) -> list[dict[str, Any]]:
    """
    Deduplicate nodes by their normalized name.

    When the same concept is extracted with different variations (e.g.,
    "positions" and "position"), this keeps only the first occurrence.

    Args:
        nodes: List of node dictionaries
        name_key: Key in properties containing the name (e.g., "dependencyName")

    Returns:
        Deduplicated list of nodes
    """
    seen: dict[str, dict[str, Any]] = {}

    for node in nodes:
        props = node.get("properties", {})
        name = props.get(name_key, "")
        if not name:
            continue

        # Normalize for comparison
        normalized = name.lower().replace("-", "_").replace(" ", "_")

        if normalized not in seen:
            seen[normalized] = node

    return list(seen.values())


# =============================================================================
# File Type Utilities
# =============================================================================


def is_python_file(subtype: str | None) -> bool:
    """Check if a file is a Python file based on its subtype."""
    return subtype is not None and subtype.lower() == "python"


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Node/Edge ID generation
    "generate_node_id",
    "generate_edge_id",
    "strip_chunk_suffix",
    # JSON parsing
    "current_timestamp",
    "parse_json_response",
    "validate_required_fields",
    "deduplicate_nodes",
    "create_extraction_result",
    "create_empty_llm_details",
    "extract_llm_details_from_response",
    # Input sources
    "parse_input_sources",
    "matches_file_spec",
    "filter_files_by_input_sources",
    "get_node_sources",
    "has_file_sources",
    "has_node_sources",
    # Normalization
    "normalize_package_name",
    "normalize_concept_name",
    "normalize_technology_name",
    "normalize_node",
    "normalize_nodes",
    "deduplicate_by_normalized_name",
    "singularize",
    "PACKAGE_CANONICAL_NAMES",
    # File type utilities
    "is_python_file",
]
