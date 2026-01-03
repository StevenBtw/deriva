"""
Business Concept extraction - LLM-based extraction of business domain concepts.

This module extracts BusinessConcept nodes from documentation files using LLM analysis.
It identifies actors, entities, processes, events, rules, goals, etc.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import current_timestamp, strip_chunk_suffix

# JSON schema for LLM structured output
BUSINESS_CONCEPT_SCHEMA = {
    "name": "business_concepts_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "concepts": {
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
        },
        "required": ["concepts"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """
    Build the LLM prompt for business concept extraction.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    prompt = f"""You are analyzing a documentation file to extract business domain concepts.

## File Information
- **File Path:** {file_path}

## Instructions
{instruction}

## Example Output
{example}

## File Content
```
{file_content}
```

Apply the instructions above to extract business concepts. Return ONLY a JSON object with a "concepts" array. If no business concepts are found, return {{"concepts": []}}.
"""
    return prompt


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

    # Generate unique node ID
    concept_name_slug = (
        concept_data["conceptName"].lower().replace(" ", "_").replace("-", "_")
    )
    node_id = f"concept_{repo_name}_{concept_name_slug}"

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
    Parse and validate LLM response content.

    Args:
        response_content: Raw JSON string from LLM

    Returns:
        Dictionary with:
            - success: bool
            - data: Parsed concepts list
            - errors: List of parsing errors
    """
    try:
        parsed = json.loads(response_content)

        if "concepts" not in parsed:
            return {
                "success": False,
                "data": [],
                "errors": ['Response missing "concepts" array'],
            }

        if not isinstance(parsed["concepts"], list):
            return {
                "success": False,
                "data": [],
                "errors": ['"concepts" must be an array'],
            }

        return {"success": True, "data": parsed["concepts"], "errors": []}

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "data": [],
            "errors": [f"JSON parsing error: {str(e)}"],
        }


def extract_business_concepts(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
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
    llm_details = {
        "prompt": "",
        "response": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "cache_used": False,
    }

    try:
        # Build the prompt
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_extraction_prompt(
            file_content=file_content,
            file_path=file_path,
            instruction=instruction,
            example=example,
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
        file_node_id = f"file_{repo_name}_{safe_path}"

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


def extract_business_concepts_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract business concepts from multiple files.

    Args:
        files: List of dicts with 'path' and 'content' keys
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config
        progress_callback: Optional callback(current, total, file_path)

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
