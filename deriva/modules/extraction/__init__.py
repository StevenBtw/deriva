"""
Extraction module - Pure functions for building graph nodes from repository data.

This package provides extraction functions organized by extraction type:
- structural/: Filesystem-based extraction (repository, directory, file)
- llm/: LLM-based semantic extraction (business_concept, type_definition, etc.)
- ast/: AST-based extraction (Phase 2 - type_definition, method, external_dependency)

Also includes:
- base: Shared utilities for all extraction modules
- classification: File classification by type
- input_sources: Input source parsing utilities

All functions follow the module pattern:
- Pure functions only (no I/O, no state)
- Return data structures with error information
- Never raise exceptions (return errors as data)
"""

from __future__ import annotations

# Base utilities
from .base import (
    create_empty_llm_details,
    create_extraction_result,
    current_timestamp,
    extract_llm_details_from_response,
    generate_edge_id,
    generate_node_id,
    parse_json_response,
    validate_required_fields,
)

# Input sources parsing utilities
from .input_sources import (
    filter_files_by_input_sources,
    get_node_sources,
    has_file_sources,
    has_node_sources,
    matches_file_spec,
    parse_input_sources,
)

# Structural extractors
from .structural import (
    build_directory_node,
    build_file_node,
    build_repository_node,
    extract_directories,
    extract_files,
    extract_repository,
)

# LLM-based extractors
from .llm import (
    BUSINESS_CONCEPT_SCHEMA,
    EXTERNAL_DEPENDENCY_SCHEMA,
    METHOD_SCHEMA,
    TECHNOLOGY_SCHEMA,
    TEST_SCHEMA,
    TYPE_DEFINITION_SCHEMA,
    build_business_concept_node,
    build_business_concept_prompt,
    build_external_dependency_node,
    build_external_dependency_prompt,
    build_method_node,
    build_method_prompt,
    build_technology_node,
    build_technology_prompt,
    build_test_node,
    build_test_prompt,
    build_type_definition_node,
    build_type_definition_prompt,
    extract_business_concepts,
    extract_business_concepts_batch,
    extract_external_dependencies,
    extract_external_dependencies_batch,
    extract_methods,
    extract_methods_batch,
    extract_technologies,
    extract_technologies_batch,
    extract_tests,
    extract_tests_batch,
    extract_type_definitions,
    extract_type_definitions_batch,
    parse_business_concept_response,
    parse_external_dependency_response,
    parse_method_response,
    parse_technology_response,
    parse_test_response,
    parse_type_definition_response,
)

__all__ = [
    # Base utilities
    "generate_node_id",
    "generate_edge_id",
    "current_timestamp",
    "parse_json_response",
    "validate_required_fields",
    "create_extraction_result",
    "create_empty_llm_details",
    "extract_llm_details_from_response",
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
    # Type Definition
    "build_type_definition_node",
    "extract_type_definitions",
    "extract_type_definitions_batch",
    "build_type_definition_prompt",
    "parse_type_definition_response",
    "TYPE_DEFINITION_SCHEMA",
    # Method
    "build_method_node",
    "extract_methods",
    "extract_methods_batch",
    "build_method_prompt",
    "parse_method_response",
    "METHOD_SCHEMA",
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
    # Test
    "build_test_node",
    "extract_tests",
    "extract_tests_batch",
    "build_test_prompt",
    "parse_test_response",
    "TEST_SCHEMA",
    # Input Sources
    "parse_input_sources",
    "matches_file_spec",
    "filter_files_by_input_sources",
    "get_node_sources",
    "has_file_sources",
    "has_node_sources",
]
