"""
LLM-based extraction module - Pure functions for LLM-based graph node extraction.

This package provides extraction functions for semantic elements using LLM:
- business_concept: Business domain concepts from documentation
- type_definition: Classes, interfaces, types from source code
- method: Methods and functions from type definitions
- technology: Infrastructure technology components
- external_dependency: External libraries and integrations
- test: Test definitions and test cases

All functions use LLM for semantic analysis.
"""

from __future__ import annotations

from .business_concept import (
    BUSINESS_CONCEPT_SCHEMA,
    build_business_concept_node,
    build_extraction_prompt as build_business_concept_prompt,
    extract_business_concepts,
    extract_business_concepts_batch,
    parse_llm_response as parse_business_concept_response,
)
from .external_dependency import (
    EXTERNAL_DEPENDENCY_SCHEMA,
    build_external_dependency_node,
    build_extraction_prompt as build_external_dependency_prompt,
    extract_external_dependencies,
    extract_external_dependencies_batch,
    parse_llm_response as parse_external_dependency_response,
)
from .method import (
    METHOD_SCHEMA,
    build_extraction_prompt as build_method_prompt,
    build_method_node,
    extract_methods,
    extract_methods_batch,
    parse_llm_response as parse_method_response,
)
from .technology import (
    TECHNOLOGY_SCHEMA,
    build_extraction_prompt as build_technology_prompt,
    build_technology_node,
    extract_technologies,
    extract_technologies_batch,
    parse_llm_response as parse_technology_response,
)
from .test import (
    TEST_SCHEMA,
    build_extraction_prompt as build_test_prompt,
    build_test_node,
    extract_tests,
    extract_tests_batch,
    parse_llm_response as parse_test_response,
)
from .type_definition import (
    TYPE_DEFINITION_SCHEMA,
    build_extraction_prompt as build_type_definition_prompt,
    build_type_definition_node,
    extract_type_definitions,
    extract_type_definitions_batch,
    parse_llm_response as parse_type_definition_response,
)

__all__ = [
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
]
