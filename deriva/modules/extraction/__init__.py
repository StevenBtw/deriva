"""
Extraction module - Pure functions for building graph nodes from repository data.

This package provides extraction functions for different node types:
- Structural: repository, directory, file (filesystem-based, no LLM)
- Semantic: business_concept, type_definition, method, technology, etc. (LLM/AST)

Architecture:
- base.py: Shared utilities for all extraction modules
- classification.py: File classification by type
- One .py file per node type (repository, directory, file, business_concept, etc.)

All functions follow the module pattern:
- Pure functions only (no I/O, no state)
- Return data structures with error information
- Never raise exceptions (return errors as data)

Usage:
    # Structural extraction (no LLM required)
    from deriva.modules.extraction import extract_repository, extract_files

    repo_result = extract_repository({"name": "myrepo", "url": "https://..."})
    files_result = extract_files("/path/to/repo", "myrepo")

    # Semantic extraction (requires LLM)
    from deriva.modules.extraction import extract_type_definitions_batch

    result = extract_type_definitions_batch(
        files=[{"path": "app.py", "content": "class Foo: ..."}],
        repo_name="myrepo",
        llm_query_fn=my_llm_query,
        config={"instruction": "...", "example": "..."},
    )

Return Format:
    All extraction functions return a dict with consistent structure::

        {
            "success": bool,           # Whether extraction succeeded
            "data": {
                "nodes": [...],        # List of node dicts
                "edges": [...],        # List of edge dicts
            },
            "errors": [...],           # List of error messages
            "stats": {...},            # Statistics about the extraction
            "llm_details": {...},      # Optional LLM call details (for LLM extractors)
        }
"""

from __future__ import annotations

# Base utilities (includes input_sources, normalization, and common helpers)
from .base import (
    PACKAGE_CANONICAL_NAMES,
    create_empty_llm_details,
    create_extraction_result,
    # JSON parsing
    current_timestamp,
    deduplicate_by_normalized_name,
    deduplicate_nodes,
    extract_llm_details_from_response,
    filter_files_by_input_sources,
    generate_edge_id,
    # Node/Edge ID generation
    generate_node_id,
    get_node_sources,
    has_file_sources,
    has_node_sources,
    # File type utilities
    is_python_file,
    matches_file_spec,
    normalize_concept_name,
    normalize_node,
    normalize_nodes,
    # Normalization
    normalize_package_name,
    normalize_technology_name,
    # Input sources
    parse_input_sources,
    parse_json_response,
    singularize,
    strip_chunk_suffix,
    validate_required_fields,
)

# LLM/AST-based extractors
from .business_concept import (
    BUSINESS_CONCEPT_SCHEMA,
    build_business_concept_node,
    extract_business_concepts,
    extract_business_concepts_batch,
    extract_business_concepts_multi,
)
from .business_concept import (
    build_extraction_prompt as build_business_concept_prompt,
)
from .business_concept import (
    parse_llm_response as parse_business_concept_response,
)
from .directory import (
    build_directory_node,
    extract_directories,
)

# Tree-sitter based edge extraction (unified module)
from .edges import (
    ALL_EDGE_TYPES,
    SUPPORTED_LANGUAGES,
    EdgeType,
    extract_edges_batch,
    extract_edges_from_file,
)
from .external_dependency import (
    EXTERNAL_DEPENDENCY_SCHEMA,
    build_external_dependency_node,
    extract_external_dependencies,
    extract_external_dependencies_batch,
    get_extraction_method,
)
from .external_dependency import (
    build_extraction_prompt as build_external_dependency_prompt,
)
from .external_dependency import (
    parse_llm_response as parse_external_dependency_response,
)
from .file import (
    build_file_node,
    extract_files,
)
from .method import (
    METHOD_SCHEMA,
    build_method_node,
    extract_methods,
    extract_methods_batch,
    # AST extraction (both names for compatibility)
    extract_methods_from_python,
    extract_methods_from_source,
)
from .method import (
    build_extraction_prompt as build_method_prompt,
)
from .method import (
    parse_llm_response as parse_method_response,
)

# Structural extractors
from .repository import (
    build_repository_node,
    extract_repository,
)
from .technology import (
    TECHNOLOGY_SCHEMA,
    build_technology_node,
    extract_technologies,
    extract_technologies_batch,
)
from .technology import (
    build_extraction_prompt as build_technology_prompt,
)
from .technology import (
    parse_llm_response as parse_technology_response,
)
from .test import (
    TEST_SCHEMA,
    build_test_node,
    extract_tests,
    extract_tests_batch,
)
from .test import (
    build_extraction_prompt as build_test_prompt,
)
from .test import (
    parse_llm_response as parse_test_response,
)
from .type_definition import (
    TYPE_DEFINITION_SCHEMA,
    build_type_definition_node,
    extract_type_definitions,
    extract_type_definitions_batch,
    # AST extraction (both names for compatibility)
    extract_types_from_python,
    extract_types_from_source,
)
from .type_definition import (
    build_extraction_prompt as build_type_definition_prompt,
)
from .type_definition import (
    parse_llm_response as parse_type_definition_response,
)

__all__ = [
    # Base utilities
    "generate_node_id",
    "generate_edge_id",
    "strip_chunk_suffix",
    "current_timestamp",
    "parse_json_response",
    "validate_required_fields",
    "deduplicate_nodes",
    "create_extraction_result",
    "create_empty_llm_details",
    "extract_llm_details_from_response",
    # Input Sources
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
    # Repository
    "build_repository_node",
    "extract_repository",
    # Directory
    "build_directory_node",
    "extract_directories",
    # File
    "build_file_node",
    "extract_files",
    # Business Concept
    "build_business_concept_node",
    "extract_business_concepts",
    "extract_business_concepts_batch",
    "extract_business_concepts_multi",
    "build_business_concept_prompt",
    "parse_business_concept_response",
    "BUSINESS_CONCEPT_SCHEMA",
    # Type Definition (LLM + AST)
    "build_type_definition_node",
    "extract_type_definitions",
    "extract_type_definitions_batch",
    "build_type_definition_prompt",
    "parse_type_definition_response",
    "TYPE_DEFINITION_SCHEMA",
    "extract_types_from_python",
    "extract_types_from_source",
    # Method (LLM + AST)
    "build_method_node",
    "extract_methods",
    "extract_methods_batch",
    "build_method_prompt",
    "parse_method_response",
    "METHOD_SCHEMA",
    "extract_methods_from_python",
    "extract_methods_from_source",
    # Technology
    "build_technology_node",
    "extract_technologies",
    "extract_technologies_batch",
    "build_technology_prompt",
    "parse_technology_response",
    "TECHNOLOGY_SCHEMA",
    # External Dependency
    "build_external_dependency_node",
    "extract_external_dependencies",
    "extract_external_dependencies_batch",
    "build_external_dependency_prompt",
    "parse_external_dependency_response",
    "EXTERNAL_DEPENDENCY_SCHEMA",
    "get_extraction_method",
    # Test
    "build_test_node",
    "extract_tests",
    "extract_tests_batch",
    "build_test_prompt",
    "parse_test_response",
    "TEST_SCHEMA",
    # Unified edge extraction (Tree-sitter based)
    "EdgeType",
    "ALL_EDGE_TYPES",
    "SUPPORTED_LANGUAGES",
    "extract_edges_from_file",
    "extract_edges_batch",
]
