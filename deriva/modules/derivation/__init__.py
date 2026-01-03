"""
Derivation module - Transform Graph nodes into ArchiMate elements.

Modules:
- base: Shared utilities (prompts, parsing, result creation)
- prep_pagerank: PageRank preparation step
- generate: Generic element generation from graph data
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

# Prep steps
from .prep_pagerank import run_pagerank

# Generate
from .generate import generate_element

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
    # Prep
    "run_pagerank",
    # Generate
    "generate_element",
]
