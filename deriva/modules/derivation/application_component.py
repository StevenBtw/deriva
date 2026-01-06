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

from typing import TYPE_CHECKING, Any, Callable

from deriva.adapters.archimate.models import Element

from .base import (
    DERIVATION_SCHEMA,
    Candidate,
    GenerationResult,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    filter_by_pagerank,
    get_community_roots,
    get_enrichments,
    parse_derivation_response,
    query_candidates,
)

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager


# =============================================================================
# Configuration
# =============================================================================

ELEMENT_TYPE = "ApplicationComponent"

# Cypher query to get candidate nodes
# Excludes: build artifacts, dependencies, tests, AND static asset directories
CANDIDATE_QUERY = """
MATCH (n:`Graph:Directory`)
WHERE n.active = true
  AND NOT n.name IN ['__pycache__', 'node_modules', '.git', '.venv', 'venv', 'dist', 'build',
                     'static', 'assets', 'public', 'images', 'img', 'css', 'js', 'fonts',
                     'templates', 'views', 'layouts', 'partials']
  AND NOT n.path =~ '.*(test|spec|__pycache__|node_modules|\\.git|\\.venv|venv|dist|build).*'
RETURN n.id as id, n.name as name, labels(n) as labels, properties(n) as properties
"""

# LLM instruction for this element type
INSTRUCTION = """
You are identifying ApplicationComponent elements from source code directories.

An ApplicationComponent is a modular, deployable part of a system that:
- Encapsulates related functionality (not just a folder)
- Has clear boundaries and responsibilities
- Contains code that works together as a unit
- Could potentially be a separate module or package

Each candidate includes graph metrics to help assess importance:
- pagerank: How central/important the directory is
- community: Which cluster of related code it belongs to
- kcore: How connected it is to the core codebase
- is_bridge: Whether it connects different parts of the codebase

Review each candidate and decide which should become ApplicationComponent elements.

INCLUDE directories that:
- Represent cohesive functional units (services, modules, packages)
- Have meaningful names indicating purpose
- Are structural roots of related code

EXCLUDE directories that:
- Are just organizational containers with no cohesive purpose
- Contain only configuration or static assets
- Are too granular (single-file directories)
"""

# Example output format
EXAMPLE = """{
  "elements": [
    {
      "identifier": "appcomp_user_service",
      "name": "User Service",
      "documentation": "Handles user authentication, registration, and profile management",
      "source": "dir_myproject_src_services_user",
      "confidence": 0.9
    },
    {
      "identifier": "appcomp_frontend",
      "name": "Frontend Application",
      "documentation": "React-based web interface for the application",
      "source": "dir_myproject_frontend",
      "confidence": 0.85
    }
  ]
}"""

# Maximum candidates to send to LLM
MAX_CANDIDATES = 30
BATCH_SIZE = 10  # Process in batches to avoid overwhelming LLM


# =============================================================================
# Filtering
# =============================================================================


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """
    Apply graph-based filtering to reduce candidates for LLM.

    Strategy:
    1. Prioritize community roots (natural component boundaries)
    2. Include high-pagerank non-roots (important directories)
    3. Sort by pagerank and limit
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
    combined = filter_by_pagerank(combined, top_n=MAX_CANDIDATES)

    return combined


# =============================================================================
# Generation
# =============================================================================


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """
    Generate ApplicationComponent elements.

    Args:
        graph_manager: Neo4j connection
        archimate_manager: ArchiMate persistence
        engine: DuckDB connection for enrichments
        llm_query_fn: LLM query function (prompt, schema, **kwargs) -> response
        temperature: Optional LLM temperature override
        max_tokens: Optional LLM max_tokens override

    Returns:
        GenerationResult with created elements
    """
    errors: list[str] = []
    created_elements: list[dict[str, Any]] = []

    # 1. Get enrichment data
    enrichments = get_enrichments(engine)

    # 2. Query candidates from graph
    try:
        candidates = query_candidates(graph_manager, CANDIDATE_QUERY, enrichments)
    except Exception as e:
        return GenerationResult(
            success=False,
            errors=[f"Query failed: {e}"],
        )

    if not candidates:
        return GenerationResult(success=True, elements_created=0)

    # 3. Apply filtering
    filtered = filter_candidates(candidates, enrichments)

    if not filtered:
        return GenerationResult(success=True, elements_created=0)

    # 4. Batch candidates and process each batch
    batches = batch_candidates(filtered, BATCH_SIZE)

    kwargs = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    for batch_num, batch in enumerate(batches, 1):
        # Build prompt for this batch
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=INSTRUCTION,
            example=EXAMPLE,
            element_type=ELEMENT_TYPE,
        )

        # Call LLM
        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **kwargs)
            response_content = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            errors.append(f"LLM error in batch {batch_num}: {e}")
            continue

        # Parse response
        parse_result = parse_derivation_response(response_content)
        if not parse_result["success"]:
            errors.extend(parse_result.get("errors", []))
            continue

        # Create elements from this batch
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
                created_elements.append({
                    "identifier": data["identifier"],
                    "name": data["name"],
                    "element_type": ELEMENT_TYPE,
                    "documentation": data.get("documentation", ""),
                    "source": data.get("properties", {}).get("source"),
                })
            except Exception as e:
                errors.append(f"Failed to create element {data.get('name')}: {e}")

    return GenerationResult(
        success=len(errors) == 0,
        elements_created=len(created_elements),
        created_elements=created_elements,
        errors=errors,
    )


__all__ = [
    "ELEMENT_TYPE",
    "CANDIDATE_QUERY",
    "INSTRUCTION",
    "EXAMPLE",
    "filter_candidates",
    "generate",
]
