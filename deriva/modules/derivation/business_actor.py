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

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "BusinessActor"

# Candidate query: Get TypeDefinition and BusinessConcept nodes
CANDIDATE_QUERY = """
MATCH (n)
WHERE (n:`Graph:TypeDefinition` OR n:`Graph:BusinessConcept`)
  AND n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.typeName, n.conceptName) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# Patterns that strongly suggest actors
ACTOR_PATTERNS = {
    # People/roles
    "user", "admin", "administrator", "manager", "operator",
    "customer", "client", "buyer", "seller", "vendor",
    "employee", "staff", "worker", "agent", "representative",
    "member", "subscriber", "owner", "author", "creator",
    # Organizational
    "department", "team", "group", "organization", "company",
    "partner", "supplier", "provider",
    # System actors
    "system", "service", "bot", "scheduler", "daemon",
    # Authentication
    "principal", "identity", "account", "role", "permission",
}

# Patterns to exclude (not actors)
EXCLUDED_PATTERNS = {
    # Data objects
    "data", "model", "entity", "record", "item", "entry",
    "request", "response", "message", "event", "log",
    # Technical
    "handler", "controller", "service", "repository", "factory",
    "helper", "util", "config", "settings", "option",
    "exception", "error", "validator", "parser",
    # Base classes
    "base", "abstract", "interface", "mixin",
}

INSTRUCTION = """
You are identifying BusinessActor elements from source code types and concepts.

A BusinessActor represents a business entity capable of performing behavior:
- Users and roles (Customer, Administrator, Operator)
- Organizational units (Department, Team)
- External parties (Supplier, Partner)
- System actors when they represent a logical role

Each candidate includes graph metrics to help assess importance.

Review each candidate and decide which should become BusinessActor elements.

INCLUDE types that:
- Represent people, roles, or organizational entities
- Can initiate or perform business activities
- Would appear in a business context diagram
- Have names indicating actors (User, Customer, Manager, etc.)

EXCLUDE types that:
- Represent data/information (Invoice, Order, Report)
- Are technical components (Controller, Handler, Service)
- Are utility/framework classes
- Are abstract base classes

When naming:
- Use role names (e.g., "Customer" not "CustomerModel")
- Be specific about the actor's function
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "ba_customer",
      "name": "Customer",
      "documentation": "External party who purchases products or services and receives invoices",
      "source": "type_Customer",
      "confidence": 0.95
    },
    {
      "identifier": "ba_administrator",
      "name": "Administrator",
      "documentation": "Internal user with elevated privileges for system management",
      "source": "type_Admin",
      "confidence": 0.9
    }
  ]
}"""

MAX_CANDIDATES = 20
BATCH_SIZE = 10


def _is_likely_actor(name: str) -> bool:
    """Check if a type name suggests an actor."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in EXCLUDED_PATTERNS:
        if pattern in name_lower:
            return False

    # Check for actor patterns
    for pattern in ACTOR_PATTERNS:
        if pattern in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """Filter candidates for BusinessActor derivation."""
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter
    filtered = [c for c in candidates if c.name]

    # Separate likely actors from others
    likely_actors = [c for c in filtered if _is_likely_actor(c.name)]
    others = [c for c in filtered if not _is_likely_actor(c.name)]

    # Sort by PageRank
    likely_actors = filter_by_pagerank(likely_actors, top_n=MAX_CANDIDATES // 2)

    remaining_slots = MAX_CANDIDATES - len(likely_actors)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_actors.extend(others)

    logger.debug(
        f"BusinessActor filter: {len(candidates)} total -> {len(likely_actors)} final"
    )

    return likely_actors[:MAX_CANDIDATES]


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """Generate BusinessActor elements."""
    result = GenerationResult(success=True)

    enrichments = get_enrichments(engine)
    candidates = query_candidates(graph_manager, CANDIDATE_QUERY, enrichments)

    if not candidates:
        logger.info("No candidates found for BusinessActor")
        return result

    logger.info(f"Found {len(candidates)} candidates")

    filtered = filter_candidates(candidates, enrichments)

    if not filtered:
        logger.info("No candidates passed filtering")
        return result

    logger.info("Filtered to %d candidates for LLM", len(filtered))

    batches = batch_candidates(filtered, BATCH_SIZE)

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    for batch_num, batch in enumerate(batches, 1):
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=INSTRUCTION,
            example=EXAMPLE,
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
    "CANDIDATE_QUERY",
    "INSTRUCTION",
    "EXAMPLE",
    "filter_candidates",
    "generate",
]
