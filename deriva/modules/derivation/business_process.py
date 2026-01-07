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

ELEMENT_TYPE = "BusinessProcess"

# Candidate query: Get Method nodes
CANDIDATE_QUERY = """
MATCH (n:`Graph:Method`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.methodName) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# Patterns that suggest non-process utility methods
EXCLUDED_PATTERNS = {
    # Lifecycle methods
    "__init__", "__del__", "__enter__", "__exit__",
    "__str__", "__repr__", "__eq__", "__hash__",
    # Utility patterns
    "helper", "util", "validate", "parse", "format",
    "convert", "transform", "serialize", "deserialize",
    # Accessors
    "get_", "set_", "is_", "has_", "_get", "_set",
    # Framework internals
    "setup", "teardown", "configure", "initialize",
}

# Patterns that strongly suggest business processes
PROCESS_PATTERNS = {
    # CRUD operations
    "create", "add", "insert", "new",
    "update", "modify", "edit", "change",
    "delete", "remove", "cancel",
    "submit", "approve", "reject", "review",
    # Business actions
    "process", "handle", "execute", "run",
    "generate", "calculate", "compute",
    "send", "notify", "email", "alert",
    "export", "import", "sync",
    "register", "login", "logout", "authenticate",
    # Workflow
    "checkout", "payment", "order", "invoice",
    "ship", "deliver", "fulfill",
}

INSTRUCTION = """
You are identifying BusinessProcess elements from source code methods.

A BusinessProcess represents a sequence of business behaviors that achieves
a specific outcome. It is NOT just any function - it represents a complete
business activity that delivers value.

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the method is
- in_degree/out_degree: How connected it is

Review each candidate and decide which should become BusinessProcess elements.

INCLUDE methods that:
- Represent complete business activities (Create Invoice, Process Payment)
- Coordinate multiple steps to achieve a business outcome
- Would be meaningful to a business analyst
- Are named with verbs indicating business actions

EXCLUDE methods that:
- Are purely technical (validation, parsing, formatting)
- Are framework lifecycle methods (__init__, setup, etc.)
- Are simple getters/setters
- Are utility/helper functions
- Only do one small technical step

When naming:
- Use business-friendly verb phrases (e.g., "Create Invoice" not "create_invoice")
- Focus on the business outcome, not technical implementation
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "bp_create_invoice",
      "name": "Create Invoice",
      "documentation": "Process of generating a new invoice with line items and customer details",
      "source": "method_invoice_form",
      "confidence": 0.9
    },
    {
      "identifier": "bp_process_payment",
      "name": "Process Payment",
      "documentation": "Handles payment submission and validation for customer orders",
      "source": "method_handle_payment",
      "confidence": 0.85
    }
  ]
}"""

MAX_CANDIDATES = 30
BATCH_SIZE = 10


def _is_likely_process(name: str) -> bool:
    """Check if a method name suggests a business process."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in EXCLUDED_PATTERNS:
        if pattern in name_lower:
            return False

    # Check for process patterns
    for pattern in PROCESS_PATTERNS:
        if pattern in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """
    Filter candidates for BusinessProcess derivation.

    Strategy:
    1. Enrich with graph metrics
    2. Pre-filter by name patterns (exclude utilities)
    3. Prioritize likely processes
    4. Use PageRank to find most important methods
    """
    # Enrich all candidates first
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter: exclude None names and dunder methods
    filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

    # Separate likely processes from others
    likely_processes = [c for c in filtered if _is_likely_process(c.name)]
    others = [c for c in filtered if not _is_likely_process(c.name)]

    # Sort likely processes by PageRank
    likely_processes = filter_by_pagerank(likely_processes, top_n=MAX_CANDIDATES // 2)

    # Fill remaining slots with highest PageRank others
    remaining_slots = MAX_CANDIDATES - len(likely_processes)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_processes.extend(others)

    logger.debug(
        f"BusinessProcess filter: {len(candidates)} total -> {len(filtered)} after exclude -> "
        f"{len(likely_processes)} final candidates"
    )

    return likely_processes[:MAX_CANDIDATES]


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """Generate BusinessProcess elements from Method nodes."""
    result = GenerationResult(success=True)

    enrichments = get_enrichments(engine)
    candidates = query_candidates(graph_manager, CANDIDATE_QUERY, enrichments)

    if not candidates:
        logger.info("No Method candidates found")
        return result

    logger.info(f"Found {len(candidates)} method candidates")

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
