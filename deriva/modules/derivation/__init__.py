"""
Derivation module - Transform Graph nodes into ArchiMate elements.

This module implements a hybrid derivation approach combining:
1. **Graph signals** - PageRank, Louvain communities, k-core for importance ranking
2. **Deterministic rules** - Name matching, file proximity, community membership
3. **LLM refinement** - Semantic understanding for complex relationships

Modules:
- base: Shared utilities (prompts, parsing, result creation)
- enrich: Graph enrichment algorithms (PageRank, Louvain, k-core, etc.)

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

Usage:
    from deriva.modules.derivation import (
        Candidate,
        batch_candidates,
        build_derivation_prompt,
        derive_batch_relationships,
    )

    # Query and enrich candidates
    candidates = query_candidates(graph_manager, cypher_query, enrichments)
    batches = batch_candidates(candidates, batch_size=15, group_by_community=True)

    # Derive elements with LLM
    prompt = build_derivation_prompt(batch, instruction, example, "BusinessObject")
    response = llm_query_fn(prompt, DERIVATION_SCHEMA)

Three-Tier Relationship Derivation:
    Relationships are derived using a priority-based approach:
    - **Tier 1a**: Community-based (same Louvain community = related)
    - **Tier 1b**: Graph neighbor (direct graph connections)
    - **Tier 1c**: Name/file matching (semantic word overlap + same source file)
    - **Tier 2**: LLM refinement (adds relationships missed by deterministic rules)
"""

from __future__ import annotations

# Base utilities
from .base import (
    DERIVATION_SCHEMA,
    RELATIONSHIP_SCHEMA,
    Candidate,
    GenerationResult,
    RelationshipRule,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    build_element_relationship_prompt,
    build_per_element_relationship_prompt,
    build_relationship_prompt,
    build_unified_relationship_prompt,
    create_result,
    clear_enrichment_cache,
    derive_batch_relationships,
    derive_element_relationships,
    get_enrichments_from_graph,
    parse_derivation_response,
    parse_relationship_response,
    query_candidates,
)

# Prep module (submodule, not re-exported at top level)
from . import prep

__all__ = [
    # Base
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    "Candidate",
    "GenerationResult",
    "RelationshipRule",
    "batch_candidates",
    "query_candidates",
    "create_result",
    "build_derivation_prompt",
    "build_relationship_prompt",
    "build_element_relationship_prompt",
    "build_per_element_relationship_prompt",
    "build_unified_relationship_prompt",
    "derive_element_relationships",
    "derive_batch_relationships",
    "get_enrichments_from_graph",
    "clear_enrichment_cache",
    "parse_derivation_response",
    "parse_relationship_response",
    "build_element",
    # Submodules
    "prep",
]
