"""
ApplicationService Derivation.

An ApplicationService represents an explicitly defined exposed application
behavior. This includes API endpoints, web routes, and service interfaces.

Graph signals:
- Method nodes with route/endpoint patterns
- Functions decorated with @app.route, @api.get, etc.
- Controller/handler methods
- Methods in files named routes.py, api.py, views.py

Filtering strategy:
1. Query Method nodes
2. Filter for route/endpoint patterns
3. Look for HTTP method indicators (get, post, put, delete)
4. Focus on externally exposed interfaces

LLM role:
- Identify which methods are application services
- Generate meaningful service names
- Write documentation describing the service's purpose

Relationships:
- OUTBOUND: ApplicationService -> BusinessObject (Flow) - services transfer data
- INBOUND: TechnologyService -> ApplicationService (Serving) - tech serves app services
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from deriva.adapters.archimate.models import Element, Relationship
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    Candidate,
    GenerationResult,
    RelationshipRule,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    derive_batch_relationships,
    enrich_candidate,
    filter_by_pagerank,
    get_enrichments_from_neo4j,
    parse_derivation_response,
    query_candidates,
)
from deriva.services import config

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "ApplicationService"

# =============================================================================
# RELATIONSHIP RULES
# =============================================================================

# Relationships FROM ApplicationService TO other element types
OUTBOUND_RULES = [
    RelationshipRule(
        target_type="BusinessObject",
        rel_type="Flow",
        description="Application services transfer/process business data",
    ),
]

# Relationships FROM other element types TO ApplicationService
INBOUND_RULES = [
    RelationshipRule(
        target_type="TechnologyService",  # source type for inbound
        rel_type="Serving",
        description="Technology services serve application services",
    ),
]


# =============================================================================
# FILTERING
# =============================================================================


def _is_likely_service(
    name: str, include_patterns: set[str], exclude_patterns: set[str]
) -> bool:
    """Check if a method name suggests an application service."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in exclude_patterns:
        if name_lower.startswith(pattern) or pattern in name_lower:
            return False

    # Check for service patterns
    for pattern in include_patterns:
        if pattern in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
    include_patterns: set[str],
    exclude_patterns: set[str],
    max_candidates: int,
) -> list[Candidate]:
    """
    Filter candidates for ApplicationService derivation.

    Args:
        candidates: List of candidates to filter
        enrichments: Graph enrichment data
        include_patterns: Patterns that suggest services
        exclude_patterns: Patterns to exclude
        max_candidates: Maximum number of candidates to return
    """
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter
    filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

    # Separate likely services from others
    likely_services = [
        c
        for c in filtered
        if _is_likely_service(c.name, include_patterns, exclude_patterns)
    ]
    others = [
        c
        for c in filtered
        if not _is_likely_service(c.name, include_patterns, exclude_patterns)
    ]

    # Sort by PageRank
    likely_services = filter_by_pagerank(likely_services, top_n=max_candidates // 2)

    remaining_slots = max_candidates - len(likely_services)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_services.extend(others)

    logger.debug(
        "ApplicationService filter: %d total -> %d final",
        len(candidates),
        len(likely_services),
    )

    return likely_services[:max_candidates]


# =============================================================================
# GENERATION
# =============================================================================


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
    Generate ApplicationService elements and their relationships.

    This function handles both element creation AND relationship derivation
    in a unified flow. After each batch of elements is created, relationships
    are derived to/from existing elements.

    Args:
        graph_manager: Neo4j connection
        archimate_manager: ArchiMate persistence
        engine: DuckDB connection for patterns
        llm_query_fn: LLM query function (prompt, schema, **kwargs) -> response
        query: Cypher query to get candidate nodes
        instruction: LLM instruction prompt
        example: Example output for LLM
        max_candidates: Maximum candidates to send to LLM
        batch_size: Batch size for LLM processing
        existing_elements: Elements from previous derivation steps (for relationships)
        temperature: Optional LLM temperature override
        max_tokens: Optional LLM max_tokens override

    Returns:
        GenerationResult with created elements and relationships
    """
    result = GenerationResult(success=True)

    # Get patterns from database
    patterns = config.get_derivation_patterns(engine, ELEMENT_TYPE)
    include_patterns = patterns.get("include", set())
    exclude_patterns = patterns.get("exclude", set())

    # Get enrichments from Neo4j (not DuckDB)
    enrichments = get_enrichments_from_neo4j(graph_manager)
    candidates = query_candidates(graph_manager, query, enrichments)

    if not candidates:
        logger.info("No Method candidates found")
        return result

    logger.info("Found %d method candidates", len(candidates))

    filtered = filter_candidates(
        candidates, enrichments, include_patterns, exclude_patterns, max_candidates
    )

    if not filtered:
        logger.info("No candidates passed filtering")
        return result

    logger.info("Filtered to %d candidates for LLM", len(filtered))

    batches = batch_candidates(filtered, batch_size)

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    for batch_num, batch in enumerate(batches, 1):
        logger.debug(
            "Processing batch %d/%d with %d candidates",
            batch_num,
            len(batches),
            len(batch),
        )

        # -----------------------------------------------------------------
        # STEP 1: Generate elements
        # -----------------------------------------------------------------
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=instruction,
            example=example,
            element_type=ELEMENT_TYPE,
        )

        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **llm_kwargs)
            response_content = (
                response.content if hasattr(response, "content") else str(response)
            )
        except Exception as e:
            result.errors.append(f"LLM error in batch {batch_num}: {e}")
            continue

        parse_result = parse_derivation_response(response_content)

        if not parse_result["success"]:
            result.errors.extend(parse_result.get("errors", []))
            continue

        # Create elements from this batch
        batch_elements: list[dict[str, Any]] = []
        for derived in parse_result.get("data", []):
            element_result = build_element(derived, ELEMENT_TYPE)

            if not element_result["success"]:
                result.errors.extend(element_result.get("errors", []))
                continue

            element_data = element_result["data"]

            try:
                element = Element(
                    name=element_data["name"],
                    element_type=element_data["element_type"],
                    identifier=element_data["identifier"],
                    documentation=element_data.get("documentation"),
                    properties=element_data.get("properties", {}),
                )
                archimate_manager.add_element(element)
                result.elements_created += 1
                result.created_elements.append(element_data)
                batch_elements.append(element_data)
            except Exception as e:
                result.errors.append(
                    f"Failed to create element {element_data['identifier']}: {e}"
                )

        # -----------------------------------------------------------------
        # STEP 2: Derive relationships for this batch
        # -----------------------------------------------------------------
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

            # Persist relationships
            for rel_data in relationships:
                try:
                    relationship = Relationship(
                        source=rel_data["source"],
                        target=rel_data["target"],
                        relationship_type=rel_data["relationship_type"],
                        properties={"confidence": rel_data.get("confidence", 0.5)},
                    )
                    archimate_manager.add_relationship(relationship)
                    result.relationships_created += 1
                    result.created_relationships.append(rel_data)
                except Exception as e:
                    result.errors.append(f"Failed to create relationship: {e}")

    logger.info(
        "Created %d %s elements and %d relationships",
        result.elements_created,
        ELEMENT_TYPE,
        result.relationships_created,
    )
    return result


__all__ = [
    "ELEMENT_TYPE",
    "OUTBOUND_RULES",
    "INBOUND_RULES",
    "filter_candidates",
    "generate",
]
