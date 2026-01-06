"""
TechnologyService Derivation.

A TechnologyService represents an externally visible unit of functionality,
offered by a technology node (e.g., database, message queue, external API).

Graph signals:
- External dependency nodes (imported packages/libraries)
- Nodes with labels like ExternalDependency, Database, API
- High out-degree from application code (many things depend on it)
- Configuration files referencing external services

Filtering strategy:
- Start with ExternalDependency and similar labeled nodes
- Filter to high-importance dependencies (PageRank)
- Exclude standard library and utility packages
- Focus on infrastructure services (databases, queues, APIs)

LLM role:
- Classify which dependencies are technology services vs utilities
- Generate meaningful service names
- Write documentation describing the service's role
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

ELEMENT_TYPE = "TechnologyService"

# Candidate query: Get external dependencies
# Note: ExternalDependency nodes use 'dependencyName' not 'name'
CANDIDATE_QUERY = """
MATCH (n:`Graph:ExternalDependency`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.dependencyName, n.name) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# Common utility/stdlib packages to exclude (not technology services)
EXCLUDED_PACKAGES = {
    # Python stdlib
    "os", "sys", "json", "re", "datetime", "time", "logging", "typing",
    "collections", "functools", "itertools", "pathlib", "io", "copy",
    "dataclasses", "enum", "abc", "contextlib", "warnings", "math",
    # Common utilities (not infrastructure)
    "pytest", "unittest", "mock", "typing_extensions", "pydantic",
    # Build/dev tools
    "setuptools", "pip", "wheel", "black", "ruff", "mypy", "isort",
}

# Keywords that suggest technology services
TECH_SERVICE_KEYWORDS = {
    # Databases
    "sql", "postgres", "mysql", "sqlite", "mongo", "redis", "elastic",
    "database", "db", "orm", "sqlalchemy", "prisma", "duckdb",
    # Message queues
    "kafka", "rabbitmq", "celery", "amqp", "queue", "pubsub",
    # HTTP/APIs
    "http", "request", "api", "rest", "graphql", "grpc", "websocket",
    "flask", "fastapi", "django", "express", "axios", "fetch",
    # Cloud services
    "aws", "azure", "gcp", "s3", "lambda", "dynamodb", "cloudwatch",
    # Auth
    "oauth", "jwt", "auth", "ldap", "saml",
    # Storage
    "storage", "blob", "file", "minio",
    # Other infrastructure
    "docker", "kubernetes", "nginx", "vault", "consul",
}

INSTRUCTION = """
You are identifying TechnologyService elements from external dependencies.

A TechnologyService represents an externally visible unit of functionality
provided by infrastructure or external systems, such as:
- Databases (PostgreSQL, MongoDB, Redis, etc.)
- Message queues (Kafka, RabbitMQ, etc.)
- External APIs and HTTP clients
- Cloud services (AWS S3, Azure Blob, etc.)
- Authentication services

Review each candidate dependency. Consider:
- Does this provide infrastructure functionality?
- Is it a service the application connects TO (not just a utility library)?
- Would it appear in an architecture diagram?

INCLUDE:
- Database drivers and ORMs (sqlalchemy, psycopg2, pymongo)
- HTTP clients for external APIs (requests, httpx, axios)
- Message queue clients (kafka-python, pika)
- Cloud SDK components (boto3, azure-storage)
- Caching services (redis, memcached)

EXCLUDE:
- Standard library modules
- Utility libraries (json parsing, date handling)
- Testing frameworks
- Development tools
- Internal application modules
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "techsvc_postgresql",
      "name": "PostgreSQL Database",
      "documentation": "Relational database service for persistent data storage",
      "source": "dep_sqlalchemy",
      "confidence": 0.95
    },
    {
      "identifier": "techsvc_redis_cache",
      "name": "Redis Cache",
      "documentation": "In-memory data store used for caching and session management",
      "source": "dep_redis",
      "confidence": 0.9
    }
  ]
}"""

MAX_CANDIDATES = 30
BATCH_SIZE = 10  # Process in batches to avoid overwhelming LLM


def _is_likely_tech_service(name: str) -> bool:
    """Check if a dependency name suggests a technology service."""
    name_lower = name.lower()

    # Exclude known utility packages
    if name_lower in EXCLUDED_PACKAGES:
        return False

    # Check for tech service keywords
    for keyword in TECH_SERVICE_KEYWORDS:
        if keyword in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """
    Filter candidates for TechnologyService derivation.

    Strategy:
    1. Pre-filter by name patterns (exclude stdlib/utilities)
    2. Prioritize by keywords suggesting infrastructure
    3. Use PageRank to find most important dependencies
    4. Limit to MAX_CANDIDATES for LLM
    """
    # Enrich all candidates first
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Pre-filter: exclude None names and known non-services
    filtered = [c for c in candidates if c.name and c.name.lower() not in EXCLUDED_PACKAGES]

    # Separate likely tech services from others
    likely_services = [c for c in filtered if _is_likely_tech_service(c.name)]
    others = [c for c in filtered if not _is_likely_tech_service(c.name)]

    # Sort likely services by PageRank
    likely_services = filter_by_pagerank(likely_services, top_n=MAX_CANDIDATES // 2)

    # Fill remaining slots with highest PageRank others
    remaining_slots = MAX_CANDIDATES - len(likely_services)
    if remaining_slots > 0 and others:
        others = filter_by_pagerank(others, top_n=remaining_slots)
        likely_services.extend(others)

    logger.debug(
        f"TechnologyService filter: {len(candidates)} total → {len(filtered)} after exclude → "
        f"{len(likely_services)} final candidates"
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
    """
    Generate TechnologyService elements from external dependencies.

    Pipeline:
    1. Query graph for external dependency nodes
    2. Enrich with graph metrics
    3. Filter to likely technology services
    4. Ask LLM to identify actual services and generate elements
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
        logger.info("No external dependency candidates found")
        return result

    logger.info(f"Found {len(candidates)} external dependency candidates")

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
