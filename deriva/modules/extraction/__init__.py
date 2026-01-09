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
"""

from __future__ import annotations

# Base utilities (includes input_sources, normalization, and common helpers)
from .base import (
    # Node/Edge ID generation
    generate_node_id,
    generate_edge_id,
    strip_chunk_suffix,
    # JSON parsing
    current_timestamp,
    parse_json_response,
    validate_required_fields,
    deduplicate_nodes,
    create_extraction_result,
    create_empty_llm_details,
    extract_llm_details_from_response,
    # Input sources
    parse_input_sources,
    matches_file_spec,
    filter_files_by_input_sources,
    get_node_sources,
    has_file_sources,
    has_node_sources,
    # Normalization
    normalize_package_name,
    normalize_concept_name,
    normalize_technology_name,
    normalize_node,
    normalize_nodes,
    deduplicate_by_normalized_name,
    singularize,
    PACKAGE_CANONICAL_NAMES,
    # File type utilities
    is_python_file,
)

# Structural extractors
from .repository import (
    build_repository_node,
    extract_repository,
)
from .directory import (
    build_directory_node,
    extract_directories,
)
from .file import (
    build_file_node,
    extract_files,
)

# LLM/AST-based extractors
from .business_concept import (
    BUSINESS_CONCEPT_SCHEMA,
    build_business_concept_node,
    build_extraction_prompt as build_business_concept_prompt,
    extract_business_concepts,
    extract_business_concepts_batch,
    parse_llm_response as parse_business_concept_response,
)
from .type_definition import (
    TYPE_DEFINITION_SCHEMA,
    build_type_definition_node,
    build_extraction_prompt as build_type_definition_prompt,
    extract_type_definitions,
    extract_type_definitions_batch,
    parse_llm_response as parse_type_definition_response,
    # AST extraction
    extract_types_from_python,
)
from .method import (
    METHOD_SCHEMA,
    build_method_node,
    build_extraction_prompt as build_method_prompt,
    extract_methods,
    extract_methods_batch,
    parse_llm_response as parse_method_response,
    # AST extraction
    extract_methods_from_python,
)
from .technology import (
    TECHNOLOGY_SCHEMA,
    build_technology_node,
    build_extraction_prompt as build_technology_prompt,
    extract_technologies,
    extract_technologies_batch,
    parse_llm_response as parse_technology_response,
)
from .external_dependency import (
    EXTERNAL_DEPENDENCY_SCHEMA,
    build_external_dependency_node,
    build_extraction_prompt as build_external_dependency_prompt,
    extract_external_dependencies,
    extract_external_dependencies_batch,
    parse_llm_response as parse_external_dependency_response,
    get_extraction_method,
)
from .test import (
    TEST_SCHEMA,
    build_test_node,
    build_extraction_prompt as build_test_prompt,
    extract_tests,
    extract_tests_batch,
    parse_llm_response as parse_test_response,
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
    # Method (LLM + AST)
    "build_method_node",
    "extract_methods",
    "extract_methods_batch",
    "build_method_prompt",
    "parse_method_response",
    "METHOD_SCHEMA",
    "extract_methods_from_python",
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
]
