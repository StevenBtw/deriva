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

ELEMENT_TYPE = "ApplicationService"

# Candidate query: Get Method nodes
CANDIDATE_QUERY = """
MATCH (n:`Graph:Method`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.name, n.methodName) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# Patterns that suggest exposed services
SERVICE_PATTERNS = {
    # REST/HTTP
    "get", "post", "put", "patch", "delete",
    "route", "endpoint", "api", "rest",
    # Views/handlers
    "view", "handler", "controller",
    "index", "list", "detail", "show",
    # Common endpoints
    "login", "logout", "register", "authenticate",
    "search", "filter", "export", "download",
    "upload", "import",
}

# Patterns to exclude (internal, not exposed)
EXCLUDED_PATTERNS = {
    # Private/internal
    "_", "private", "internal", "helper",
    # Lifecycle
    "__init__", "__del__", "setup", "teardown",
    # Utilities
    "validate", "parse", "format", "convert",
    "serialize", "deserialize",
}

INSTRUCTION = """
You are identifying ApplicationService elements from source code methods.

An ApplicationService represents explicitly exposed application behavior:
- Web routes and API endpoints
- Service interfaces that external clients can call
- Handlers that respond to external requests

Each candidate includes method information and graph metrics.

Review each candidate and decide which should become ApplicationService elements.

INCLUDE methods that:
- Handle HTTP requests (routes, endpoints, views)
- Expose functionality to external clients
- Are entry points for user interactions
- Have names suggesting they respond to requests

EXCLUDE methods that:
- Are internal/private helpers
- Are utility functions
- Are lifecycle methods (__init__, setup, etc.)
- Only perform internal processing

When naming:
- Use service-oriented names (e.g., "Invoice Form Service" not "invoice_form")
- Describe what the service provides
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "as_invoice_form",
      "name": "Invoice Form Service",
      "documentation": "Web endpoint for creating and managing invoice data through a form interface",
      "source": "method_invoice_form",
      "confidence": 0.9
    },
    {
      "identifier": "as_export_pdf",
      "name": "PDF Export Service",
      "documentation": "Endpoint for generating and downloading invoice PDFs",
      "source": "method_invoice_pdf",
      "confidence": 0.85
    }
  ]
}"""

MAX_CANDIDATES = 30
BATCH_SIZE = 10


def _is_likely_service(name: str) -> bool:
    """Check if a method name suggests an application service."""
    if not name:
        return False

    name_lower = name.lower()

    # Check exclusion patterns first
    for pattern in EXCLUDED_PATTERNS:
        if name_lower.startswith(pattern) or pattern in name_lower:
            return False

    # Check for service patterns
    for pattern in SERVICE_PATTERNS:
        if pattern in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """Filter candidates for ApplicationService derivation."""
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter
    filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

    # Separate likely services from others
    likely_services = [c for c in filtered if _is_likely_service(c.name)]
    others = [c for c in filtered if not _is_likely_service(c.name)]

    # Sort by PageRank
    likely_services = filter_by_pagerank(likely_services, top_n=MAX_CANDIDATES // 2)

    remaining_slots = MAX_CANDIDATES - len(likely_services)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_services.extend(others)

    logger.debug(
        f"ApplicationService filter: {len(candidates)} total -> {len(likely_services)} final"
    )

    return likely_services[:MAX_CANDIDATES]


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """Generate ApplicationService elements from Method nodes."""
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
