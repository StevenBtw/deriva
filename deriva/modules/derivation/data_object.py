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

ELEMENT_TYPE = "DataObject"

# Candidate query: Get File nodes with data-related types
CANDIDATE_QUERY = """
MATCH (n:`Graph:File`)
WHERE n.active = true
RETURN n.id as id,
       COALESCE(n.fileName, n.name) as name,
       labels(n) as labels,
       properties(n) as properties
"""

# File types that are data objects
DATA_FILE_TYPES = {
    # Data storage
    "database", "db", "sqlite", "sql",
    # Configuration
    "config", "json", "yaml", "yml", "toml", "ini", "env",
    # Schemas
    "schema", "xsd", "dtd",
    # Data files
    "csv", "xml", "data",
}

# File types to exclude
EXCLUDED_FILE_TYPES = {
    "source", "python", "javascript", "typescript",
    "template", "html", "css",
    "test", "spec",
    "docs", "markdown", "readme",
    "asset", "image", "font",
}

INSTRUCTION = """
You are identifying DataObject elements from files in a codebase.

A DataObject represents data structured for automated processing:
- Database files (SQLite, SQL scripts)
- Configuration files (JSON, YAML, ENV)
- Schema definitions
- Data exchange formats

Each candidate includes file information and graph metrics.

Review each candidate and decide which should become DataObject elements.

INCLUDE files that:
- Store application data (databases, data files)
- Define configuration (settings, environment)
- Define data schemas or structures
- Are used for data exchange

EXCLUDE files that:
- Are source code (Python, JavaScript, etc.)
- Are templates (HTML, Jinja)
- Are documentation (README, docs)
- Are static assets (images, CSS)

When naming:
- Use descriptive names (e.g., "Application Database" not "database.db")
- Indicate the data's purpose
"""

EXAMPLE = """{
  "elements": [
    {
      "identifier": "do_application_database",
      "name": "Application Database",
      "documentation": "SQLite database storing invoices, customers, and line items",
      "source": "file_database.db",
      "confidence": 0.95
    },
    {
      "identifier": "do_app_configuration",
      "name": "Application Configuration",
      "documentation": "Environment configuration for Flask application settings",
      "source": "file_.flaskenv",
      "confidence": 0.85
    }
  ]
}"""

MAX_CANDIDATES = 30
BATCH_SIZE = 10


def _is_likely_data_object(candidate: Candidate) -> bool:
    """Check if a file is likely a data object."""
    name = candidate.name
    if not name:
        return False

    name_lower = name.lower()
    props = candidate.properties

    # Check file_type from properties
    file_type = props.get("fileType", "").lower() if isinstance(props, dict) else ""
    subtype = props.get("subtype", "").lower() if isinstance(props, dict) else ""

    # Exclude based on file type
    if file_type in EXCLUDED_FILE_TYPES or subtype in EXCLUDED_FILE_TYPES:
        return False

    # Include based on file type
    if file_type in DATA_FILE_TYPES or subtype in DATA_FILE_TYPES:
        return True

    # Check extension patterns
    for pattern in DATA_FILE_TYPES:
        if name_lower.endswith(f".{pattern}") or pattern in name_lower:
            return True

    return False


def filter_candidates(
    candidates: list[Candidate],
    enrichments: dict[str, dict[str, Any]],
) -> list[Candidate]:
    """Filter candidates for DataObject derivation."""
    for c in candidates:
        enrich_candidate(c, enrichments)

    # Filter to data files
    filtered = [c for c in candidates if c.name and _is_likely_data_object(c)]

    # Sort by PageRank
    filtered = filter_by_pagerank(filtered, top_n=MAX_CANDIDATES)

    logger.debug(
        f"DataObject filter: {len(candidates)} total -> {len(filtered)} final"
    )

    return filtered


def generate(
    graph_manager: "GraphManager",
    archimate_manager: "ArchimateManager",
    engine: Any,
    llm_query_fn: Callable[..., Any],
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """Generate DataObject elements from File nodes."""
    result = GenerationResult(success=True)

    enrichments = get_enrichments(engine)
    candidates = query_candidates(graph_manager, CANDIDATE_QUERY, enrichments)

    if not candidates:
        logger.info("No File candidates found")
        return result

    logger.info(f"Found {len(candidates)} file candidates")

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
