"""
Directory Classification extraction - LLM-based classification of directories.

This module classifies Graph:Directory nodes into:
- BusinessConcept: Domain-level concepts (customers, orders, invoicing)
- Technology: Technical components (kafka, redis, api)
- Skip: Structural/utility directories (utils, helpers, common)

This provides stable seed concepts for downstream extraction steps.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import (
    create_empty_llm_details,
    current_timestamp,
    parse_json_response,
)


# JSON schema for LLM structured output
DIRECTORY_CLASSIFICATION_SCHEMA = {
    "name": "directory_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "directoryName": {
                            "type": "string",
                            "description": "Original directory name",
                        },
                        "conceptName": {
                            "type": "string",
                            "description": "PascalCase concept name (e.g., CustomerManagement)",
                        },
                        "classification": {
                            "type": "string",
                            "enum": ["business", "technology", "skip"],
                            "description": "Classification type",
                        },
                        "conceptType": {
                            "type": "string",
                            "description": "Specific type (for business: actor/entity/process; for technology: infrastructure/framework/tool)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what this represents",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score 0.0-1.0",
                        },
                    },
                    "required": [
                        "directoryName",
                        "conceptName",
                        "classification",
                        "conceptType",
                        "description",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["classifications"],
        "additionalProperties": False,
    },
}


def build_classification_prompt(
    directories: list[dict[str, Any]],
    instruction: str,
    example: str,
) -> str:
    """
    Build the LLM prompt for directory classification.

    Args:
        directories: List of directory info dicts with 'name', 'path', and optional file stats
        instruction: Classification instruction from config (contains all rules)
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    import json

    # Format directory list with file context if available
    formatted_dirs = []
    for d in directories:
        dir_info: dict[str, Any] = {
            "name": d.get("name", d.get("dirName", "")),
            "path": d.get("path", d.get("dirPath", "")),
        }
        # Include file stats if available (from graph query enrichment)
        file_count = d.get("file_count", 0)
        if file_count and file_count > 0:
            file_stats = []
            if d.get("source_count", 0) > 0:
                file_stats.append(f"source:{d['source_count']}")
            if d.get("config_count", 0) > 0:
                file_stats.append(f"config:{d['config_count']}")
            if d.get("docs_count", 0) > 0:
                file_stats.append(f"docs:{d['docs_count']}")
            if d.get("test_count", 0) > 0:
                file_stats.append(f"test:{d['test_count']}")
            dir_info["files"] = f"{file_count} ({', '.join(file_stats)})" if file_stats else str(file_count)

            # Include subtypes (languages) if available
            subtypes = d.get("subtypes", [])
            if subtypes and len(subtypes) > 0:
                # Filter out None values
                valid_subtypes = [s for s in subtypes if s]
                if valid_subtypes:
                    dir_info["languages"] = valid_subtypes

        formatted_dirs.append(dir_info)

    dir_list = json.dumps(formatted_dirs, indent=2)

    prompt = f"""{instruction}

## Directories to Classify
```json
{dir_list}
```

## Example Output
{example}

Return JSON with classifications for each directory.
"""
    return prompt


def build_business_concept_node(
    classification: dict[str, Any],
    source_dir_id: str,
    repo_name: str,
) -> dict[str, Any]:
    """Build a BusinessConcept node from classification result."""
    concept_name = classification["conceptName"]
    node_id = f"concept::{repo_name}::{concept_name.lower().replace(' ', '_')}"

    return {
        "id": node_id,
        "labels": ["Graph", "Graph:BusinessConcept"],
        "properties": {
            "conceptName": concept_name,
            "conceptType": classification.get("conceptType", "entity"),
            "description": classification.get("description", ""),
            "originSource": f"directory:{classification['directoryName']}/",
            "confidence": classification.get("confidence", 0.8),
            "repositoryName": repo_name,
            "active": True,
            "extracted_at": current_timestamp(),
        },
    }


def build_technology_node(
    classification: dict[str, Any],
    source_dir_id: str,
    repo_name: str,
) -> dict[str, Any]:
    """Build a Technology node from classification result."""
    concept_name = classification["conceptName"]
    node_id = f"tech::{repo_name}::{concept_name.lower().replace(' ', '_')}"

    return {
        "id": node_id,
        "labels": ["Graph", "Graph:Technology"],
        "properties": {
            "technologyName": concept_name,
            "technologyType": classification.get("conceptType", "infrastructure"),
            "description": classification.get("description", ""),
            "originSource": f"directory:{classification['directoryName']}/",
            "confidence": classification.get("confidence", 0.8),
            "repositoryName": repo_name,
            "active": True,
            "extracted_at": current_timestamp(),
        },
    }


def classify_directories(
    directories: list[dict[str, Any]],
    repo_name: str,
    llm_query_fn: Callable,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Classify directories into BusinessConcept, Technology, or skip.

    Args:
        directories: List of directory info dicts from graph query
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config with 'instruction' and 'example' keys

    Returns:
        Dictionary with:
            - success: bool
            - data: Dict with 'nodes' and 'edges' lists
            - errors: List[str]
            - stats: Dict
            - llm_details: Dict
    """
    llm_details = create_empty_llm_details()

    if not directories:
        return {
            "success": True,
            "data": {"nodes": [], "edges": []},
            "errors": [],
            "stats": {"total_nodes": 0, "skipped": 0},
            "llm_details": llm_details,
        }

    try:
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_classification_prompt(
            directories=directories,
            instruction=instruction,
            example=example,
        )
        llm_details["prompt"] = prompt

        # Call LLM
        response = llm_query_fn(prompt, DIRECTORY_CLASSIFICATION_SCHEMA)

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
        if hasattr(response, "error") and response.error:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": [f"LLM error: {response.error}"],
                "stats": {},
                "llm_details": llm_details,
            }

        # Parse response
        parse_result = parse_json_response(response.content, "classifications")
        if not parse_result["success"]:
            return {
                "success": False,
                "data": {"nodes": [], "edges": []},
                "errors": parse_result.get("errors", ["Failed to parse LLM response"]),
                "stats": {},
                "llm_details": llm_details,
            }

        parsed = {"classifications": parse_result["data"]}

        # Build nodes from classifications
        nodes = []
        edges = []
        stats = {
            "business_concepts": 0,
            "technologies": 0,
            "skipped": 0,
        }

        # Create lookup for source directory IDs
        dir_id_map = {
            d.get("name", d.get("dirName", "")): d.get("id", "") for d in directories
        }

        for classification in parsed.get("classifications", []):
            dir_name = classification.get("directoryName", "")
            class_type = classification.get("classification", "skip")
            confidence = classification.get("confidence", 0.0)
            source_dir_id = dir_id_map.get(dir_name, "")

            # Skip low confidence or explicit skip
            if class_type == "skip" or confidence < 0.7:
                stats["skipped"] += 1
                continue

            if class_type == "business":
                node = build_business_concept_node(
                    classification, source_dir_id, repo_name
                )
                nodes.append(node)
                stats["business_concepts"] += 1

                # Create edge from Directory to BusinessConcept
                if source_dir_id:
                    edges.append(
                        {
                            "source": source_dir_id,
                            "target": node["id"],
                            "relationship_type": "REPRESENTS",
                            "properties": {
                                "created_at": current_timestamp(),
                                "confidence": confidence,
                            },
                        }
                    )

            elif class_type == "technology":
                node = build_technology_node(classification, source_dir_id, repo_name)
                nodes.append(node)
                stats["technologies"] += 1

                # Create edge from Directory to Technology
                if source_dir_id:
                    edges.append(
                        {
                            "source": source_dir_id,
                            "target": node["id"],
                            "relationship_type": "REPRESENTS",
                            "properties": {
                                "created_at": current_timestamp(),
                                "confidence": confidence,
                            },
                        }
                    )

        stats["total_nodes"] = len(nodes)

        return {
            "success": True,
            "data": {"nodes": nodes, "edges": edges},
            "errors": [],
            "stats": stats,
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [str(e)],
            "stats": {},
            "llm_details": llm_details,
        }
