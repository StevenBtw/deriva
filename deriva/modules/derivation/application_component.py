"""
ApplicationComponent Derivation.

An ApplicationComponent represents a modular, deployable part of a system
that encapsulates its behavior and data.

Graph signals:
- Directory nodes (structural organization)
- Louvain community roots (cohesive modules)
- High PageRank (important/central directories)
- Path patterns: src/, app/, lib/, components/, modules/

Filtering strategy:
1. Query Directory nodes (excluding test/config/docs)
2. Get enrichment data (pagerank, louvain, kcore)
3. Filter to community roots or high-pagerank nodes
4. Limit to top N by PageRank
5. Send to LLM for final decision and naming
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from deriva.adapters.archimate.models import Element, Relationship

from .base import (
    DERIVATION_SCHEMA,
    Candidate,
    GenerationResult,
    RelationshipRule,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    derive_batch_relationships,
    filter_by_pagerank,
    get_community_roots,
    get_enrichments_from_neo4j,
    parse_derivation_response,
    query_candidates,
)

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "ApplicationComponent"


# =============================================================================
# RELATIONSHIP RULES
# =============================================================================

OUTBOUND_RULES: list[RelationshipRule] = []
INBOUND_RULES: list[RelationshipRule] = []



def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
    max_candidates: int,
) -> list[Candidate]:
    """
    Apply graph-based filtering to reduce candidates for LLM.

    Strategy:
    1. Prioritize community roots (natural component boundaries)
    2. Include high-pagerank non-roots (important directories)
    3. Sort by pagerank and limit

    Args:
        candidates: List of candidates to filter
        enrichments: Graph enrichment data (pagerank, community, etc.)
        max_candidates: Maximum number of candidates to return
    """
    if not candidates:
        return []

    # Get community roots - these are natural component boundaries
    roots = get_community_roots(candidates)

    # Also include high-pagerank nodes that aren't roots
    # (they might be important subdirectories)
    non_roots = [c for c in candidates if c not in roots]
    high_pagerank = filter_by_pagerank(non_roots, top_n=10)

    # Combine and deduplicate
    combined = list(roots)
    for c in high_pagerank:
        if c not in combined:
            combined.append(c)

    # Sort by pagerank (most important first) and limit
    combined = filter_by_pagerank(combined, top_n=max_candidates)

    return combined


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    query: str,
    instruction: str,
    example: str,
    max_candidates: int,
    batch_size: int,
    existing_elements: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """
    Generate ApplicationComponent elements.

    All configuration parameters are required - no defaults, no fallbacks.

    Args:
        graph_manager: Neo4j connection
        archimate_manager: ArchiMate persistence
        engine: DuckDB connection for enrichments
        llm_query_fn: LLM query function (prompt, schema, **kwargs) -> response
        query: Cypher query to get candidate nodes
        instruction: LLM instruction prompt
        example: Example output for LLM
        max_candidates: Maximum candidates to send to LLM
        batch_size: Batch size for LLM processing
        temperature: Optional LLM temperature override
        max_tokens: Optional LLM max_tokens override

    Returns:
        GenerationResult with created elements
    """
    errors: list[str] = []
    created_elements: list[dict[str, Any]] = []

    # 1. Get enrichment data
    enrichments = get_enrichments_from_neo4j(graph_manager)

    # 2. Query candidates from graph
    try:
        candidates = query_candidates(graph_manager, query, enrichments)
    except Exception as e:
        return GenerationResult(
            success=False,
            errors=[f"Query failed: {e}"],
        )

    if not candidates:
        return GenerationResult(success=True, elements_created=0)

    logger.info(f"Found {len(candidates)} directory candidates")

    # 3. Apply filtering
    filtered = filter_candidates(candidates, enrichments, max_candidates)

    if not filtered:
        return GenerationResult(success=True, elements_created=0)

    logger.info(f"Filtered to {len(filtered)} candidates for LLM")

    # 4. Batch candidates and process each batch
    batches = batch_candidates(filtered, batch_size)

    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    for batch_num, batch in enumerate(batches, 1):
        logger.debug(
            f"Processing batch {batch_num}/{len(batches)} with {len(batch)} candidates"
        )

        # Build prompt for this batch
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=instruction,
            example=example,
            element_type=ELEMENT_TYPE,
        )

        # Call LLM
        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **kwargs)
            response_content = (
                response.content if hasattr(response, "content") else str(response)
            )
        except Exception as e:
            errors.append(f"LLM error in batch {batch_num}: {e}")
            continue

        # Parse response
        parse_result = parse_derivation_response(response_content)
        if not parse_result["success"]:
            errors.extend(parse_result.get("errors", []))
            continue

        # Create elements from this batch
        batch_elements: list[dict[str, Any]] = []
        for derived in parse_result.get("data", []):
            element_result = build_element(derived, ELEMENT_TYPE)

            if not element_result["success"]:
                errors.extend(element_result.get("errors", []))
                continue

            data = element_result["data"]

            try:
                element = Element(
                    identifier=data["identifier"],
                    name=data["name"],
                    element_type=data["element_type"],
                    documentation=data.get("documentation", ""),
                    properties=data.get("properties", {}),
                )
                archimate_manager.add_element(element)
                batch_elements.append(data)
                created_elements.append(
                    {
                        "identifier": data["identifier"],
                        "name": data["name"],
                        "element_type": ELEMENT_TYPE,
                        "documentation": data.get("documentation", ""),
                        "source": data.get("properties", {}).get("source"),
                    }
                )
            except Exception as e:
                errors.append(f"Failed to create element {data.get('name')}: {e}")
        # Derive relationships for this batch
        if batch_elements and existing_elements:
            relationships = derive_batch_relationships(
                new_elements=batch_elements,
                existing_elements=existing_elements,
                element_type=ELEMENT_TYPE,
                outbound_rules=OUTBOUND_RULES,
                inbound_rules=INBOUND_RULES,
                llm_query_fn=llm_query_fn,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            for rel_data in relationships:
                try:
                    relationship = Relationship(
                        source=rel_data["source"],
                        target=rel_data["target"],
                        relationship_type=rel_data["relationship_type"],
                        properties={"confidence": rel_data.get("confidence", 0.5)},
                    )
                    archimate_manager.add_relationship(relationship)
                except Exception as e:
                    errors.append(f"Failed to create relationship: {e}")


    logger.info(f"Created {len(created_elements)} {ELEMENT_TYPE} elements")

    return GenerationResult(
        success=len(errors) == 0,
        elements_created=len(created_elements),
        created_elements=created_elements,
        errors=errors,
    )


__all__ = [
    "ELEMENT_TYPE",
    "OUTBOUND_RULES",
    "INBOUND_RULES",
    "filter_candidates",
    "generate",
]
