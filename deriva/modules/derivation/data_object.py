"""
DataObject Derivation.

A DataObject represents data structured for automated processing.
This includes database tables, files, messages, and other data structures.

Graph signals:
- File nodes (especially data files, configs, schemas)
- TypeDefinition nodes representing data structures
- Nodes related to persistence, storage, or data transfer

Filtering strategy:
1. Query File nodes with data-related types
2. Include schema/config/data files
3. Exclude source code and templates
4. Focus on structured data artifacts

LLM role:
- Identify which files/types represent data objects
- Generate meaningful data object names
- Write documentation describing the data purpose

Relationships:
- OUTBOUND: DataObject -> TechnologyService (Realization) - config realizes tech
- INBOUND: TechnologyService -> DataObject (Access) - tech accesses data
- INBOUND: ApplicationService -> DataObject (Flow) - app services flow data
- INBOUND: BusinessProcess -> DataObject (Access) - processes access data
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

ELEMENT_TYPE = "DataObject"

# =============================================================================
# RELATIONSHIP RULES
# =============================================================================

# Relationships FROM DataObject TO other element types
OUTBOUND_RULES = [
    RelationshipRule(
        target_type="TechnologyService",
        rel_type="Realization",
        description="Data objects (config/requirements) realize technology services",
    ),
]

# Relationships FROM other element types TO DataObject
INBOUND_RULES = [
    RelationshipRule(
        target_type="TechnologyService",
        rel_type="Access",
        description="Technology services access data objects",
    ),
    RelationshipRule(
        target_type="ApplicationService",
        rel_type="Flow",
        description="Application services transfer data to/from data objects",
    ),
    RelationshipRule(
        target_type="BusinessProcess",
        rel_type="Access",
        description="Business processes access data objects",
    ),
]


# =============================================================================
# FILTERING
# =============================================================================


def _is_likely_data_object(
    name: str, include_patterns: set[str], exclude_patterns: set[str]
) -> bool:
    """Check if a file name suggests a data object."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in exclude_patterns:
        if pattern in name_lower:
            return False

    # Check for data file patterns
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
    Filter candidates for DataObject derivation.

    Strategy:
    1. Enrich with graph metrics
    2. Filter by data file patterns
    3. Exclude source code and templates
    4. Use PageRank to find most important data files
    """
    for c in candidates:
        enrich_candidate(c, enrichments)

    filtered = [c for c in candidates if c.name]

    likely_data = [
        c
        for c in filtered
        if _is_likely_data_object(c.name, include_patterns, exclude_patterns)
    ]
    others = [
        c
        for c in filtered
        if not _is_likely_data_object(c.name, include_patterns, exclude_patterns)
    ]

    likely_data = filter_by_pagerank(likely_data, top_n=max_candidates // 2)

    remaining_slots = max_candidates - len(likely_data)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_data.extend(others)

    logger.debug(
        "DataObject filter: %d total -> %d after null -> %d final candidates",
        len(candidates),
        len(filtered),
        len(likely_data),
    )

    return likely_data[:max_candidates]


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
    Generate DataObject elements and their relationships.

    All configuration parameters are required - no defaults, no fallbacks.
    """
    result = GenerationResult(success=True)

    patterns = config.get_derivation_patterns(engine, ELEMENT_TYPE)
    include_patterns = patterns.get("include", set())
    exclude_patterns = patterns.get("exclude", set())

    enrichments = get_enrichments_from_neo4j(graph_manager)
    candidates = query_candidates(graph_manager, query, enrichments)

    if not candidates:
        logger.info("No File candidates found")
        return result

    logger.info("Found %d file candidates", len(candidates))

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
