"""
Business Concept extraction - LLM-based extraction of business domain concepts.

This module extracts BusinessConcept nodes from documentation files using LLM analysis.
It identifies actors, entities, processes, events, rules, goals, etc.

Supports hybrid extraction:
- Layer 1 (Deterministic): Extract seed concepts from code structure (directories, classes)
- Layer 2 (Context-aware LLM): Extract additional concepts with seed concepts as context
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .base import (
    create_empty_llm_details,
    current_timestamp,
    parse_json_response,
    strip_chunk_suffix,
)


def extract_seed_concepts_from_structure(
    repo_path: str | Path,
    include_directories: bool = True,
    include_classes: bool = False,
) -> list[dict[str, str]]:
    """
    Extract seed concepts from code structure (deterministic layer).

    This provides stable "anchor" concepts from directory names and optionally
    class names. These seed concepts guide the LLM to reuse consistent names.

    Args:
        repo_path: Path to the repository root
        include_directories: Extract concepts from directory names
        include_classes: Extract concepts from class definitions (requires parsing)

    Returns:
        List of seed concepts with keys: conceptName, conceptType, source
    """
    seed_concepts: list[dict[str, str]] = []
    repo_path = Path(repo_path)

    # Keywords that indicate process-type concepts
    process_keywords = {
        "processing",
        "pipeline",
        "service",
        "handler",
        "manager",
        "controller",
        "worker",
        "scheduler",
        "queue",
        "stream",
        "ingestion",
        "transformation",
        "analytics",
        "engine",
    }

    # Keywords that indicate entity-type concepts
    entity_keywords = {
        "model",
        "entity",
        "data",
        "storage",
        "repository",
        "database",
        "cache",
        "store",
        "record",
        "schema",
    }

    if include_directories:
        # Skip common non-business directories
        skip_dirs = {
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
            "target",
            ".idea",
            ".vscode",
            "tests",
            "test",
            "docs",
            "examples",
            "scripts",
            "bin",
            "lib",
        }

        for item in repo_path.iterdir():
            if (
                item.is_dir()
                and item.name not in skip_dirs
                and not item.name.startswith(".")
            ):
                # Convert directory name to concept name
                concept_name = _dir_name_to_concept_name(item.name)
                if concept_name and len(concept_name) > 2:
                    # Determine concept type based on keywords
                    name_lower = item.name.lower()
                    if any(kw in name_lower for kw in process_keywords):
                        concept_type = "process"
                    elif any(kw in name_lower for kw in entity_keywords):
                        concept_type = "entity"
                    else:
                        concept_type = "capability"

                    seed_concepts.append(
                        {
                            "conceptName": concept_name,
                            "conceptType": concept_type,
                            "source": f"directory:{item.name}/",
                        }
                    )

    return seed_concepts


def _dir_name_to_concept_name(dir_name: str) -> str:
    """
    Convert a directory name to a PascalCase concept name.

    Examples:
        data_processing -> DataProcessing
        message-queue -> MessageQueue
        analytics -> Analytics
    """
    # Split by underscores, hyphens, or camelCase boundaries
    parts = re.split(r"[-_]", dir_name)
    # Capitalize each part
    return "".join(part.capitalize() for part in parts if part)


def get_existing_concepts_from_graph(
    graph_manager: Any,
    repo_name: str,
    limit: int = 50,
) -> list[dict[str, str]]:
    """
    Fetch existing BusinessConcept nodes from the graph.

    This retrieves concepts that were previously extracted, allowing
    the LLM to build on existing knowledge and maintain consistency.

    Args:
        graph_manager: GraphManager instance
        repo_name: Repository name to filter concepts
        limit: Maximum number of concepts to return

    Returns:
        List of existing concepts with keys: conceptName, conceptType, source
    """
    query = """
    MATCH (c:BusinessConcept)
    WHERE c.repository_name = $repo_name
    RETURN c.conceptName AS conceptName,
           c.conceptType AS conceptType,
           c.originSource AS source
    ORDER BY c.confidence DESC
    LIMIT $limit
    """

    try:
        result = graph_manager.run_cypher(
            query, {"repo_name": repo_name, "limit": limit}
        )
        return [
            {
                "conceptName": r["conceptName"],
                "conceptType": r["conceptType"],
                "source": r.get("source", "graph"),
            }
            for r in result
            if r.get("conceptName")
        ]
    except Exception:
        # If graph query fails, return empty list (graceful degradation)
        return []


# Shared concepts array schema - used by both single and multi-file extraction
_CONCEPTS_ARRAY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "conceptName": {
                "type": "string",
                "description": "Name of the business concept",
            },
            "conceptType": {
                "type": "string",
                "enum": [
                    "actor",
                    "service",
                    "process",
                    "entity",
                    "event",
                    "rule",
                    "goal",
                    "channel",
                    "product",
                    "capability",
                    "other",
                ],
                "description": "Type of business concept",
            },
            "description": {
                "type": "string",
                "description": "Brief description of the concept",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score between 0.0 and 1.0",
            },
        },
        "required": [
            "conceptName",
            "conceptType",
            "description",
            "confidence",
        ],
        "additionalProperties": False,
    },
}

# JSON schema for LLM structured output
BUSINESS_CONCEPT_SCHEMA = {
    "name": "business_concepts_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "concepts": _CONCEPTS_ARRAY_SCHEMA,
        },
        "required": ["concepts"],
        "additionalProperties": False,
    },
}


# Multi-file batch schema - wraps concepts in per-file results
BUSINESS_CONCEPT_MULTI_SCHEMA = {
    "name": "business_concepts_multi_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path of the file these concepts were extracted from",
                        },
                        "concepts": _CONCEPTS_ARRAY_SCHEMA,
                    },
                    "required": ["file_path", "concepts"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    },
}


def build_system_prompt(instruction: str) -> str:
    """
    Build system prompt with static instructions for business concept extraction.

    This separates static role/guideline content (sent once) from dynamic
    file-specific content (sent per file), reducing token usage.

    Args:
        instruction: Additional extraction instruction from config

    Returns:
        System prompt string
    """
    return f"""You are an expert at extracting business domain concepts from code documentation.

## What ARE Business Concepts (extract these):
- **Actors**: People/roles (Customer, Admin, User, Manager)
- **Entities**: Things the system manages (Invoice, Order, Product, Process)
- **Processes**: Business operations (Checkout, Approval, Registration, Execution)
- **Events**: Business happenings (OrderPlaced, PaymentReceived)
- **Rules/Goals**: Policies and objectives (DiscountPolicy, Compliance)

## What are NOT Business Concepts (skip these):
- Technical infrastructure (Kafka, Docker, Gateway, REST API)
- Code structure (Utils, Service, Controller, Repository pattern)
- Framework/library names (Spring, React, MongoDB)

## Confidence Scoring:
- 0.9-1.0: Core business concept, central to the domain
- 0.8-0.9: Clear business concept
- 0.7-0.8: Likely business-relevant
- 0.6-0.7: Borderline, might be technical

Only return concepts with confidence >= 0.6

{instruction}

IMPORTANT: Output stable, deterministic results. Always use the same naming conventions."""


def build_user_prompt(
    file_content: str,
    file_path: str,
    example: str,
    existing_concepts: list[dict[str, str]] | None = None,
) -> str:
    """
    Build user prompt with dynamic file-specific content only.

    This contains the file content and context that changes per extraction call.
    Used together with build_system_prompt() for token-efficient extraction.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file being analyzed
        example: Example output from config
        existing_concepts: Optional list of existing concepts from graph/code structure.

    Returns:
        User prompt string
    """
    import json

    from deriva.common.chunking import truncate_content

    # Truncate large files to reduce token usage
    content, was_truncated = truncate_content(file_content, max_tokens=2000)
    truncation_note = ""
    if was_truncated:
        truncation_note = (
            "\n**Note:** File content has been truncated. Focus on visible content.\n"
        )

    # Build existing concepts context section (compact JSON for token efficiency)
    existing_context = ""
    if existing_concepts:
        high_conf = [
            c for c in existing_concepts if float(c.get("confidence", 0.8)) >= 0.8
        ]
        if high_conf:
            existing_json = json.dumps(high_conf, separators=(",", ":"))
            existing_context = f"""
## Previously Identified Concepts (use these exact names):
{existing_json}

"""

    return f"""Extract BUSINESS DOMAIN concepts from this file.

## File: {file_path}
{truncation_note}{existing_context}
## Content
```
{content}
```

Return JSON matching this format: {example}"""


def build_extraction_prompt(
    file_content: str,
    file_path: str,
    instruction: str,
    example: str,
    existing_concepts: list[dict[str, str]] | None = None,
) -> str:
    """
    Build the LLM prompt for business concept extraction (legacy combined format).

    This combines system and user prompts for backward compatibility with
    callers that don't support separate system prompts.

    For token-efficient extraction, use build_system_prompt() and build_user_prompt()
    separately with an LLM that supports system prompts.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config
        existing_concepts: Optional list of existing concepts from graph/code structure.

    Returns:
        Combined prompt string (system + user content)
    """
    system = build_system_prompt(instruction)
    user = build_user_prompt(file_content, file_path, example, existing_concepts)
    return f"{system}\n\n{user}"


def build_multi_file_user_prompt(
    files: list[dict[str, str]],
    example: str,
    existing_concepts: list[dict[str, str]] | None = None,
) -> str:
    """
    Build user prompt for extracting concepts from multiple files in one LLM call.

    This batches multiple small files together to reduce per-call overhead.

    Args:
        files: List of dicts with 'path' and 'content' keys
        example: Example output from config
        existing_concepts: Optional list of existing concepts from graph/code structure.

    Returns:
        User prompt string for multi-file extraction
    """
    import json

    from deriva.common.chunking import truncate_content

    # Build existing concepts context section (compact JSON for token efficiency)
    existing_context = ""
    if existing_concepts:
        high_conf = [
            c for c in existing_concepts if float(c.get("confidence", 0.8)) >= 0.8
        ]
        if high_conf:
            existing_json = json.dumps(high_conf, separators=(",", ":"))
            existing_context = f"""
## Previously Identified Concepts (use these exact names):
{existing_json}

"""

    # Build file sections
    file_sections = []
    for file_info in files:
        file_path = file_info["path"]
        file_content = file_info["content"]

        # Truncate large files
        content, was_truncated = truncate_content(file_content, max_tokens=1500)
        truncation_note = " (truncated)" if was_truncated else ""

        file_sections.append(f"""### File: {file_path}{truncation_note}
```
{content}
```""")

    files_content = "\n\n".join(file_sections)

    return f"""Extract BUSINESS DOMAIN concepts from these files.
{existing_context}
## Files to Analyze

{files_content}

Return JSON with a "results" array. Each result must have "file_path" and "concepts" array.
Example format for a single file's concepts: {example}"""


def build_business_concept_node(
    concept_data: dict[str, Any], origin_source: str, repo_name: str
) -> dict[str, Any]:
    """
    Build a BusinessConcept graph node from extracted concept data.

    Args:
        concept_data: Dictionary containing concept data from LLM
            Expected keys: conceptName, conceptType, description, confidence
        origin_source: Path to the file where the concept was found
        repo_name: Repository name for node ID generation

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = []

    # Validate required fields
    required_fields = ["conceptName", "conceptType", "description"]
    for field in required_fields:
        if field not in concept_data or not concept_data[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Validate concept type
    valid_types = [
        "actor",
        "service",
        "process",
        "entity",
        "event",
        "rule",
        "goal",
        "channel",
        "product",
        "capability",
        "other",
    ]
    concept_type = concept_data["conceptType"].lower()
    if concept_type not in valid_types:
        concept_type = "other"

    # Generate unique node ID using :: separator to avoid repo name conflicts
    concept_name_slug = (
        concept_data["conceptName"].lower().replace(" ", "_").replace("-", "_")
    )
    node_id = f"concept::{repo_name}::{concept_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "BusinessConcept",
        "properties": {
            "conceptName": concept_data["conceptName"],
            "conceptType": concept_type,
            "description": concept_data["description"],
            "originSource": origin_source,
            "confidence": concept_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "BusinessConcept"},
    }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """
    Parse LLM response for business concepts. Delegates to base parser.

    Args:
        response_content: Raw JSON string from LLM response

    Returns:
        Dictionary with:
            - success: bool - True if parsing succeeded
            - data: List[Dict] - Parsed concept items
            - errors: List[str] - Parsing errors if any

    Example:
        >>> response = '{"concepts": [{"conceptName": "Invoice", "conceptType": "entity"}]}'
        >>> result = parse_llm_response(response)
        >>> result["data"][0]["conceptName"]
        'Invoice'
    """
    return parse_json_response(response_content, "concepts")


def extract_business_concepts(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    existing_concepts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Extract business concepts from a single file using LLM.

    This is the main extraction function that:
    1. Builds the prompt using config instruction/example
    2. Calls the LLM via the provided query function
    3. Parses the response and builds nodes
    4. Creates REFERENCES edges from File to BusinessConcept

    Args:
        file_path: Path to the file being analyzed (relative to repo)
        file_content: Content of the file
        repo_name: Repository name
        llm_query_fn: Function to call LLM (signature: (prompt, schema) -> response)
        config: Extraction config with 'instruction' and 'example' keys
        existing_concepts: Optional list of existing concepts from graph/code structure.
            When provided, guides the LLM to reuse existing names for consistency.

    Returns:
        Dictionary with:
            - success: bool - Whether the extraction succeeded
            - data: Dict - Contains 'nodes' list and 'edges' list
            - errors: List[str] - Any errors encountered
            - stats: Dict - Statistics about the extraction
            - llm_details: Dict - LLM call details for logging
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Initialize LLM details for logging
    llm_details = create_empty_llm_details()

    try:
        # Build the prompt
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_extraction_prompt(
            file_content=file_content,
            file_path=file_path,
            instruction=instruction,
            example=example,
            existing_concepts=existing_concepts,
        )
        llm_details["prompt"] = prompt

        # Call LLM
        response = llm_query_fn(prompt, BUSINESS_CONCEPT_SCHEMA)

        # Extract LLM details from response
        if hasattr(response, "content"):
            llm_details["response"] = response.content
        if hasattr(response, "usage") and response.usage:
            llm_details["tokens_in"] = response.usage.get("prompt_tokens", 0)
            llm_details["tokens_out"] = response.usage.get("completion_tokens", 0)
        if hasattr(response, "response_type"):
            llm_details["cache_used"] = (
                str(response.response_type) == "ResponseType.CACHED"
            )

        # Check for failed response
        if hasattr(response, "error"):
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"LLM error: {response.error}"],
                "stats": {"total_nodes": 0, "total_edges": 0, "llm_error": True},
                "llm_details": llm_details,
            }

        # Parse the response
        parse_result = parse_llm_response(response.content)

        if not parse_result["success"]:
            errors.extend(parse_result["errors"])
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": errors,
                "stats": {"total_nodes": 0, "total_edges": 0, "parse_error": True},
                "llm_details": llm_details,
            }

        # Build nodes for each concept
        # Strip chunk suffix from file_path to get original file node ID
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file::{repo_name}::{safe_path}"

        for concept_data in parse_result["data"]:
            node_result = build_business_concept_node(
                concept_data=concept_data, origin_source=file_path, repo_name=repo_name
            )

            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)

                # Create REFERENCES edge: File -> BusinessConcept
                edge = {
                    "edge_id": f"references_{file_node_id}_to_{node_data['node_id']}",
                    "from_node_id": file_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "REFERENCES",
                    "properties": {
                        "created_at": current_timestamp(),
                        "confidence": concept_data.get("confidence", 0.8),
                    },
                }
                edges.append(edge)
            else:
                errors.extend(node_result["errors"])

        return {
            "success": len(nodes) > 0 or len(errors) == 0,
            "data": {"nodes": nodes, "edges": edges},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"BusinessConcept": len(nodes)},
                "concepts_found": len(nodes),
                "concepts_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during business concept extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_business_concepts_multi(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    existing_concepts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Extract business concepts from multiple files in a single LLM call.

    This is used for batch extraction where multiple small files are sent
    together to reduce overhead and improve token efficiency.

    Args:
        files: List of dicts with 'path' and 'content' keys
        repo_name: Repository name
        llm_query_fn: Function to call LLM (signature: (prompt, schema, system_prompt) -> response)
        config: Extraction config with 'instruction' and 'example' keys
        existing_concepts: Optional list of existing concepts from graph/code structure.

    Returns:
        Dictionary with success, data (nodes/edges), errors, stats, and llm_details
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Initialize LLM details for logging
    llm_details = create_empty_llm_details()

    try:
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        # Build prompts
        system_prompt = build_system_prompt(instruction)
        user_prompt = build_multi_file_user_prompt(files, example, existing_concepts)

        llm_details["prompt"] = f"{system_prompt}\n\n{user_prompt}"

        # Call LLM with multi-file schema
        response = llm_query_fn(
            user_prompt, BUSINESS_CONCEPT_MULTI_SCHEMA, system_prompt
        )

        # Extract LLM details from response
        if hasattr(response, "content"):
            llm_details["response"] = response.content
        if hasattr(response, "usage") and response.usage:
            llm_details["tokens_in"] = response.usage.get("prompt_tokens", 0)
            llm_details["tokens_out"] = response.usage.get("completion_tokens", 0)
        if hasattr(response, "response_type"):
            llm_details["cache_used"] = (
                str(response.response_type) == "ResponseType.CACHED"
            )

        # Check for failed response
        if hasattr(response, "error"):
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"LLM error: {response.error}"],
                "stats": {"total_nodes": 0, "total_edges": 0, "llm_error": True},
                "llm_details": llm_details,
            }

        # Parse the multi-file response
        import json

        try:
            response_data = json.loads(response.content)
            file_results = response_data.get("results", [])
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"Failed to parse multi-file response: {str(e)}"],
                "stats": {"total_nodes": 0, "total_edges": 0, "parse_error": True},
                "llm_details": llm_details,
            }

        # Process each file's results
        for file_result in file_results:
            file_path = file_result.get("file_path", "")
            concepts = file_result.get("concepts", [])

            # Build file node ID for edges
            original_path = strip_chunk_suffix(file_path)
            safe_path = original_path.replace("/", "_").replace("\\", "_")
            file_node_id = f"file::{repo_name}::{safe_path}"

            for concept_data in concepts:
                node_result = build_business_concept_node(
                    concept_data=concept_data,
                    origin_source=file_path,
                    repo_name=repo_name,
                )

                if node_result["success"]:
                    node_data = node_result["data"]
                    nodes.append(node_data)

                    # Create REFERENCES edge: File -> BusinessConcept
                    edge = {
                        "edge_id": f"references_{file_node_id}_to_{node_data['node_id']}",
                        "from_node_id": file_node_id,
                        "to_node_id": node_data["node_id"],
                        "relationship_type": "REFERENCES",
                        "properties": {
                            "created_at": current_timestamp(),
                            "confidence": concept_data.get("confidence", 0.8),
                        },
                    }
                    edges.append(edge)
                else:
                    errors.extend(node_result["errors"])

        return {
            "success": len(nodes) > 0 or len(errors) == 0,
            "data": {"nodes": nodes, "edges": edges},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "node_types": {"BusinessConcept": len(nodes)},
                "concepts_found": len(nodes),
                "files_in_batch": len(files),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during multi-file extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_business_concepts_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
    existing_concepts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Extract business concepts from multiple files.

    Args:
        files: List of dicts with 'path' and 'content' keys
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config
        progress_callback: Optional callback(current, total, file_path)
        existing_concepts: Optional list of existing concepts from graph/code structure.
            When provided, guides the LLM to reuse existing names for consistency.

    Returns:
        Aggregated results from all file extractions including llm_details per file
    """
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_file_results: list[dict[str, Any]] = []  # Per-file results with llm_details
    files_processed = 0
    files_with_concepts = 0

    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_business_concepts(
            file_path=file_path,
            file_content=file_content,
            repo_name=repo_name,
            llm_query_fn=llm_query_fn,
            config=config,
            existing_concepts=existing_concepts,
        )

        files_processed += 1

        # Store per-file result with llm_details for L3 logging
        all_file_results.append(
            {
                "file_path": file_path,
                "success": result["success"],
                "concepts_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_concepts += 1
            all_nodes.extend(result["data"]["nodes"])
            all_edges.extend(result["data"]["edges"])

        if result["errors"]:
            all_errors.extend([f"{file_path}: {e}" for e in result["errors"]])

    return {
        "success": len(all_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": all_nodes, "edges": all_edges},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_types": {"BusinessConcept": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_concepts": files_with_concepts,
        },
        "file_results": all_file_results,  # Per-file details for L3 logging
    }
