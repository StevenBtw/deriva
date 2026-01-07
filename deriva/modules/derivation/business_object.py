"""
BusinessObject Derivation.

A BusinessObject represents a passive element that has relevance from a
business perspective. It represents things like data entities, domain
concepts, or business documents.

Graph signals:
- TypeDefinition nodes (classes/data models)
- BusinessConcept nodes (from LLM extraction)
- File nodes with model patterns (models.py, entities.py, schema.py)
- High in-degree (many references = important domain concept)

Filtering strategy:
1. Query TypeDefinition and BusinessConcept nodes
2. Exclude utility classes (helpers, mixins, base classes)
3. Prioritize by PageRank (central domain concepts)
4. Focus on nouns that represent business data

LLM role:
- Identify which type definitions are business-relevant
- Generate meaningful business names (not code names)
- Write documentation describing the business meaning
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

ELEMENT_TYPE = "BusinessObject"

# Candidate query: Get TypeDefinition and BusinessConcept nodes
# TypeDefinition nodes are classes/types from the codebase
# BusinessConcept nodes are LLM-extracted domain concepts
CANDIDATE_QUERY = """
MATCH (n)
WHERE (n:`Graph:TypeDefinition` OR n:`Graph:BusinessConcept`)
  AND n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.typeName, n.conceptName) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# Patterns that suggest non-business utility classes
EXCLUDED_PATTERNS = {
    # Base/abstract classes
    "base", "abstract", "mixin", "interface", "protocol",
    # Utility patterns
    "helper", "utils", "util", "tools", "common",
    # Framework internals
    "handler", "middleware", "decorator", "wrapper",
    "factory", "builder", "adapter", "proxy",
    # Testing
    "test", "mock", "stub", "fake", "fixture",
    # Configuration
    "config", "settings", "options", "params",
    # Exceptions
    "error", "exception",
}

# Patterns that strongly suggest business objects
BUSINESS_PATTERNS = {
    # Common domain entities
    "user", "account", "customer", "client", "member",
    "order", "invoice", "payment", "transaction", "receipt",
    "product", "item", "catalog", "inventory", "stock",
    "document", "report", "contract", "agreement",
    "message", "notification", "email", "alert",
    "project", "task", "workflow", "process",
    "employee", "department", "organization", "company",
    "address", "contact", "profile", "preference",
    "subscription", "plan", "license", "quota",
    "position", "entry", "record", "detail",
}

INSTRUCTION = """
You are identifying BusinessObject elements from source code type definitions.

A BusinessObject represents a passive element that has business relevance:
- Data entities that the business cares about (Customer, Order, Invoice)
- Domain concepts that appear in business conversations
- Information structures that would appear in business documentation

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the type is
- community: Which cluster of related types it belongs to
- in_degree: How many other types reference it (higher = more important)

Review each candidate and decide which should become BusinessObject elements.

INCLUDE types that:
- Represent real-world business concepts (Customer, Order, Product)
- Are data entities that store business information
- Would be meaningful to a business analyst (not just a developer)
- Have names that are nouns representing "things" the business cares about

EXCLUDE types that:
- Are purely technical (handlers, adapters, decorators)
- Are framework/library classes (BaseModel, FlaskForm)
- Are utility classes (StringHelper, DateUtils)
- Are internal implementation details
- Are exceptions or error types
- Are configuration or settings classes

When naming:
- Use business-friendly names (e.g., "Invoice" not "InvoiceModel")
- Capitalize appropriately (e.g., "Customer Order" not "customer_order")
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "bo_invoice",
      "name": "Invoice",
      "documentation": "A commercial document issued by a seller to a buyer, indicating products, quantities, and prices",
      "source": "type_Invoice",
      "confidence": 0.95
    },
    {
      "identifier": "bo_customer",
      "name": "Customer",
      "documentation": "A person or organization that purchases goods or services",
      "source": "type_Customer",
      "confidence": 0.9
    },
    {
      "identifier": "bo_line_item",
      "name": "Line Item",
      "documentation": "An individual entry on an invoice representing a product or service with quantity and price",
      "source": "type_Position",
      "confidence": 0.85
    }
  ]
}"""

MAX_CANDIDATES = 30
BATCH_SIZE = 10


def _is_likely_business_object(name: str) -> bool:
    """Check if a type name suggests a business object."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in EXCLUDED_PATTERNS:
        if pattern in name_lower:
            return False

    # Check for business patterns
    for pattern in BUSINESS_PATTERNS:
        if pattern in name_lower:
            return True

    # Default: include if it looks like a noun (starts with capital, no underscores)
    # This catches domain-specific names we don't have patterns for
    return name[0].isupper() and "_" not in name


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """
    Filter candidates for BusinessObject derivation.

    Strategy:
    1. Enrich with graph metrics
    2. Pre-filter by name patterns (exclude utilities)
    3. Prioritize likely business objects
    4. Use PageRank/in-degree to find most important types
    5. Limit to MAX_CANDIDATES for LLM
    """
    # Enrich all candidates first
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter: exclude None names
    filtered = [c for c in candidates if c.name]

    # Separate likely business objects from others
    likely_business = [c for c in filtered if _is_likely_business_object(c.name)]
    others = [c for c in filtered if not _is_likely_business_object(c.name)]

    # Sort likely business objects by PageRank (most important first)
    likely_business = filter_by_pagerank(likely_business, top_n=MAX_CANDIDATES // 2)

    # Fill remaining slots with highest PageRank others (LLM might find some useful)
    remaining_slots = MAX_CANDIDATES - len(likely_business)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_business.extend(others)

    logger.debug(
        f"BusinessObject filter: {len(candidates)} total -> {len(filtered)} after null check -> "
        f"{len(likely_business)} final candidates"
    )

    return likely_business[:MAX_CANDIDATES]


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """
    Generate BusinessObject elements from type definitions and business concepts.

    Pipeline:
    1. Query graph for TypeDefinition and BusinessConcept nodes
    2. Enrich with graph metrics
    3. Filter to likely business objects
    4. Ask LLM to identify actual business objects and generate elements
    5. Create ArchiMate elements

    Args:
        graph_manager: Connected GraphManager for Cypher queries
        archimate_manager: Connected ArchimateManager for element creation
        engine: DuckDB connection for enrichment data
        llm_query_fn: Function to call LLM (prompt, schema, **kwargs) -> response
        temperature: Optional LLM temperature override
        max_tokens: Optional LLM max_tokens override

    Returns:
        GenerationResult with success status, created elements, and errors
    """
    result = GenerationResult(success=True)

    # Step 1: Get enrichment data
    enrichments = get_enrichments(engine)

    # Step 2: Query candidates
    candidates = query_candidates(graph_manager, CANDIDATE_QUERY, enrichments)

    if not candidates:
        logger.info("No TypeDefinition or BusinessConcept candidates found")
        return result

    logger.info(f"Found {len(candidates)} type/concept candidates")

    # Step 3: Filter candidates
    filtered = filter_candidates(candidates, enrichments)

    if not filtered:
        logger.info("No candidates passed filtering")
        return result

    logger.info("Filtered to %d candidates for LLM", len(filtered))

    # Step 4: Batch candidates and process each batch
    batches = batch_candidates(filtered, BATCH_SIZE)
    logger.info("Processing %d batches of up to %d candidates each", len(batches), BATCH_SIZE)

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    for batch_num, batch in enumerate(batches, 1):
        logger.debug("Processing batch %d/%d with %d candidates", batch_num, len(batches), len(batch))

        # Build prompt for this batch
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=INSTRUCTION,
            example=EXAMPLE,
            element_type=ELEMENT_TYPE,
        )

        # Call LLM
        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **llm_kwargs)
            response_content = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            result.errors.append(f"LLM error in batch {batch_num}: {e}")
            continue

        # Parse response
        parse_result = parse_derivation_response(response_content)

        if not parse_result["success"]:
            result.errors.extend(parse_result.get("errors", []))
            continue

        # Create elements from this batch
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
