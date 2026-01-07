"""
Derivation module - Transform Graph nodes into ArchiMate elements.

Modules:
- base: Shared utilities (prompts, parsing, result creation)

Business Layer:
- business_object: BusinessObject derivation (data entities)
- business_process: BusinessProcess derivation (activities/workflows)
- business_actor: BusinessActor derivation (roles/users)

Application Layer:
- application_component: ApplicationComponent derivation (modules)
- application_service: ApplicationService derivation (endpoints/APIs)
- data_object: DataObject derivation (files/data structures)

Technology Layer:
- technology_service: TechnologyService derivation (infrastructure)
"""

from __future__ import annotations

# Base utilities
from .base import (
    DERIVATION_SCHEMA,
    RELATIONSHIP_SCHEMA,
    Candidate,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    build_element_relationship_prompt,
    build_relationship_prompt,
    create_result,
    parse_derivation_response,
    parse_relationship_response,
    query_candidates,
)

__all__ = [
    # Base
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    "Candidate",
    "batch_candidates",
    "query_candidates",
    "create_result",
    "build_derivation_prompt",
    "build_relationship_prompt",
    "build_element_relationship_prompt",
    "parse_derivation_response",
    "parse_relationship_response",
    "build_element",
]
