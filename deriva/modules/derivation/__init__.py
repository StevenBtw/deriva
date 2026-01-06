"""
Derivation module - Transform Graph nodes into ArchiMate elements.

Modules:
- base: Shared utilities (prompts, parsing, result creation)
- application_component: ApplicationComponent derivation
- technology_service: TechnologyService derivation
"""

from __future__ import annotations

# Base utilities
from .base import (
    DERIVATION_SCHEMA,
    RELATIONSHIP_SCHEMA,
    build_derivation_prompt,
    build_element,
    build_element_relationship_prompt,
    build_relationship_prompt,
    create_result,
    parse_derivation_response,
    parse_relationship_response,
)

__all__ = [
    # Base
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    "create_result",
    "build_derivation_prompt",
    "build_relationship_prompt",
    "build_element_relationship_prompt",
    "parse_derivation_response",
    "parse_relationship_response",
    "build_element",
]
