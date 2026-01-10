"""
BusinessProcess Derivation.

A BusinessProcess represents a sequence of business behaviors that achieves
a specific outcome such as a defined set of products or business services.

Graph signals:
- Method nodes (functions implementing business logic)
- Nodes with workflow/process naming patterns
- High betweenness centrality (orchestrates other components)
- Route handlers in web applications

Filtering strategy:
1. Query Method nodes from source code
2. Exclude utility/helper methods
3. Prioritize methods with business-relevant names
4. Focus on methods that coordinate activities

LLM role:
- Identify which methods represent business processes
- Generate meaningful process names
- Write documentation describing the process purpose

Relationships:
- OUTBOUND: BusinessProcess -> BusinessObject (Access) - processes access business objects
- INBOUND: None defined
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

ELEMENT_TYPE = "BusinessProcess"

# =============================================================================
# RELATIONSHIP RULES
# =============================================================================

OUTBOUND_RULES = [
    RelationshipRule(
        target_type="BusinessObject",
        rel_type="Access",
        description="Business processes access business objects",
    ),
]

INBOUND_RULES: list[RelationshipRule] = []


# =============================================================================
# FILTERING
# =============================================================================


def _is_likely_process(
    name: str, include_patterns: set[str], exclude_patterns: set[str]
) -> bool:
    """Check if a method name suggests a business process."""
    if not name:
        return False

    name_lower = name.lower()

    for pattern in exclude_patterns:
        if pattern in name_lower:
            return False

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
    """Filter candidates for BusinessProcess derivation."""
    for c in candidates:
        enrich_candidate(c, enrichments)

    filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

    likely_processes = [
        c
        for c in filtered
        if _is_likely_process(c.name, include_patterns, exclude_patterns)
    ]
    others = [
        c
        for c in filtered
        if not _is_likely_process(c.name, include_patterns, exclude_patterns)
    ]

    likely_processes = filter_by_pagerank(likely_processes, top_n=max_candidates // 2)

    remaining_slots = max_candidates - len(likely_processes)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_processes.extend(others)

    logger.debug(
        "BusinessProcess filter: %d total -> %d final",
        len(candidates),
        len(likely_processes),
    )

    return likely_processes[:max_candidates]


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
    """Generate BusinessProcess elements and their relationships."""
    result = GenerationResult(success=True)

    patterns = config.get_derivation_patterns(engine, ELEMENT_TYPE)
    include_patterns = patterns.get("include", set())
    exclude_patterns = patterns.get("exclude", set())

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
