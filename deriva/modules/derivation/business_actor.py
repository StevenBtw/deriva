"""
BusinessActor Derivation.

A BusinessActor represents a business entity that is capable of performing
behavior. This includes users, roles, departments, or external parties.

Graph signals:
- TypeDefinition nodes with user/role/actor patterns
- BusinessConcept nodes representing people or organizations
- Authentication/authorization related code
- Route handlers with user context

Filtering strategy:
1. Query TypeDefinition and BusinessConcept nodes
2. Filter for actor/role/user patterns
3. Exclude technical/utility classes
4. Focus on entities that perform actions

LLM role:
- Identify which types represent actors
- Generate meaningful actor names
- Write documentation describing the actor's role
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from deriva.adapters.archimate.models import Element
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    Candidate,
    GenerationResult,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    enrich_candidate,
    filter_by_pagerank,
    get_enrichments,
    parse_derivation_response,
    query_candidates,
)
from deriva.services import config

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "BusinessActor"


def _is_likely_actor(name: str, include_patterns: set[str], exclude_patterns: set[str]) -> bool:
    """Check if a type name suggests a business actor."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in exclude_patterns:
        if pattern in name_lower:
            return False

    # Check for actor patterns
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
    Filter candidates for BusinessActor derivation.

    Strategy:
    1. Enrich with graph metrics
    2. Filter by actor patterns
    3. Exclude technical/utility types
    4. Use PageRank to find most important actors
    """
    for c in candidates:
        enrich_candidate(c, enrichments)

    filtered = [c for c in candidates if c.name]

    likely_actors = [c for c in filtered if _is_likely_actor(c.name, include_patterns, exclude_patterns)]
    others = [c for c in filtered if not _is_likely_actor(c.name, include_patterns, exclude_patterns)]

    likely_actors = filter_by_pagerank(likely_actors, top_n=max_candidates // 2)

    remaining_slots = max_candidates - len(likely_actors)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_actors.extend(others)

    logger.debug(
        f"BusinessActor filter: {len(candidates)} total -> {len(filtered)} after null -> "
        f"{len(likely_actors)} final candidates"
    )

    return likely_actors[:max_candidates]


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
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """
    Generate BusinessActor elements from type definitions and business concepts.

    All configuration parameters are required - no defaults, no fallbacks.
    """
    result = GenerationResult(success=True)

    patterns = config.get_derivation_patterns(engine, ELEMENT_TYPE)
    include_patterns = patterns.get("include", set())
    exclude_patterns = patterns.get("exclude", set())

    enrichments = get_enrichments(engine)
    candidates = query_candidates(graph_manager, query, enrichments)

    if not candidates:
        logger.info("No TypeDefinition or BusinessConcept candidates found")
        return result

    logger.info(f"Found {len(candidates)} type/concept candidates")

    filtered = filter_candidates(candidates, enrichments, include_patterns, exclude_patterns, max_candidates)

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
            response_content = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            result.errors.append(f"LLM error in batch {batch_num}: {e}")
            continue

        parse_result = parse_derivation_response(response_content)

        if not parse_result["success"]:
            result.errors.extend(parse_result.get("errors", []))
            continue

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
            except Exception as e:
                result.errors.append(f"Failed to create element {element_data['identifier']}: {e}")

    logger.info(f"Created {result.elements_created} {ELEMENT_TYPE} elements")
    return result


__all__ = [
    "ELEMENT_TYPE",
    "filter_candidates",
    "generate",
]
