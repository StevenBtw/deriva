"""
ExternalDependency extraction - LLM-based extraction of external dependencies.

This module extracts ExternalDependency nodes representing libraries, external APIs,
and external service integrations that the application depends on.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from deriva.common.json_utils import extract_json_from_response

from .base import current_timestamp

# JSON schema for LLM structured output
EXTERNAL_DEPENDENCY_SCHEMA = {
    "name": "external_dependency_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dependencyName": {
                            "type": "string",
                            "description": "Name of the dependency",
                        },
                        "dependencyCategory": {
                            "type": "string",
                            "enum": [
                                "library",
                                "external_api",
                                "external_service",
                                "external_database",
                            ],
                            "description": "Category of external dependency",
                        },
                        "version": {
                            "type": ["string", "null"],
                            "description": "Version constraint if applicable",
                        },
                        "ecosystem": {
                            "type": ["string", "null"],
                            "description": "Package ecosystem or provider",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this dependency is used for",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "dependencyName",
                        "dependencyCategory",
                        "version",
                        "ecosystem",
                        "description",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["dependencies"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """
    Build the LLM prompt for external dependency extraction.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    prompt = f"""You are analyzing a file to extract external dependencies.

## Context
- **File Path:** {file_path}

## Instructions
{instruction}

## Example Output
{example}

## File Content
```
{file_content}
```

Extract external dependencies. Return ONLY a JSON object with a "dependencies" array. If no dependencies are found, return {{"dependencies": []}}.
"""
    return prompt


def build_external_dependency_node(
    dep_data: dict[str, Any], origin_source: str, repo_name: str
) -> dict[str, Any]:
    """
    Build an ExternalDependency graph node from extracted data.

    Args:
        dep_data: Dictionary containing dependency data from LLM
        origin_source: Path to the file where the dependency was found
        repo_name: Repository name for node ID generation

    Returns:
        Dictionary with success, data, errors, and stats
    """
    errors = []

    # Validate required fields
    required_fields = ["dependencyName", "dependencyCategory"]
    for field in required_fields:
        if field not in dep_data or not dep_data[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Validate category
    valid_categories = [
        "library",
        "external_api",
        "external_service",
        "external_database",
    ]
    category = dep_data["dependencyCategory"].lower()
    if category not in valid_categories:
        category = "library"

    # Generate unique node ID
    dep_name_slug = dep_data["dependencyName"].lower()
    dep_name_slug = dep_name_slug.replace(" ", "_").replace("-", "_").replace("/", "_")
    node_id = f"extdep_{repo_name}_{dep_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "ExternalDependency",
        "properties": {
            "dependencyName": dep_data["dependencyName"],
            "dependencyCategory": category,
            "version": dep_data.get("version"),
            "ecosystem": dep_data.get("ecosystem"),
            "description": dep_data.get("description", ""),
            "originSource": origin_source,
            "confidence": dep_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "ExternalDependency"},
    }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """
    Parse and validate LLM response content.

    Args:
        response_content: Raw JSON string from LLM

    Returns:
        Dictionary with success, data, and errors
    """
    try:
        # Extract JSON from potential markdown wrapping
        extracted = extract_json_from_response(response_content)
        parsed = json.loads(extracted)

        # Handle null/None response (LLM returning "null")
        if parsed is None:
            return {"success": True, "data": [], "errors": []}

        # Handle case where response is a list directly
        if isinstance(parsed, list):
            return {"success": True, "data": parsed, "errors": []}

        # Check for expected key first (must be a dict at this point)
        if not isinstance(parsed, dict):
            return {"success": True, "data": [], "errors": []}

        if "dependencies" in parsed:
            data = parsed["dependencies"]
            if isinstance(data, list):
                return {"success": True, "data": data, "errors": []}
            # Handle {"dependencies": null} or {"dependencies": "none"} - treat as empty
            return {"success": True, "data": [], "errors": []}

        # Try alternate key names that LLM might use (not "data" - too generic)
        alternate_keys = ["result", "results", "items", "externalDependencies"]
        for key in alternate_keys:
            if key in parsed and isinstance(parsed[key], list):
                return {"success": True, "data": parsed[key], "errors": []}

        # If dict has no recognized keys, treat as empty (no dependencies found)
        # This handles edge cases like {"status": "empty"} or {"message": "no deps"}
        return {"success": True, "data": [], "errors": []}

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "data": [],
            "errors": [f"JSON parsing error: {e!s}"],
        }


def extract_external_dependencies(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract external dependencies from a single file using LLM.

    Args:
        file_path: Path to the file being analyzed
        file_content: Content of the file
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config with 'instruction' and 'example' keys

    Returns:
        Dictionary with success, data, errors, stats, and llm_details
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []

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
        response = llm_query_fn(prompt, EXTERNAL_DEPENDENCY_SCHEMA)

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
                "data": {"nodes": []},
                "errors": [f"LLM error: {response.error}"],
                "stats": {"total_nodes": 0, "llm_error": True},
                "llm_details": llm_details,
            }

        # Parse the response
        parse_result = parse_llm_response(response.content)

        if not parse_result["success"]:
            errors.extend(parse_result["errors"])
            return {
                "success": False,
                "data": {"nodes": []},
                "errors": errors,
                "stats": {"total_nodes": 0, "parse_error": True},
                "llm_details": llm_details,
            }

        # Build nodes for each dependency
        for dep_data in parse_result["data"]:
            node_result = build_external_dependency_node(
                dep_data=dep_data, origin_source=file_path, repo_name=repo_name
            )

            if node_result["success"]:
                nodes.append(node_result["data"])
            else:
                errors.extend(node_result["errors"])

        return {
            "success": len(nodes) > 0 or len(errors) == 0,
            "data": {"nodes": nodes},
            "errors": errors,
            "stats": {
                "total_nodes": len(nodes),
                "node_types": {"ExternalDependency": len(nodes)},
                "dependencies_found": len(nodes),
                "dependencies_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": []},
            "errors": [f"Fatal error during dependency extraction: {str(e)}"],
            "stats": {"total_nodes": 0},
            "llm_details": llm_details,
        }


def extract_external_dependencies_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract external dependencies from multiple files.

    Args:
        files: List of dicts with 'path' and 'content' keys
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config
        progress_callback: Optional callback(current, total, file_path)

    Returns:
        Aggregated results from all file extractions
    """
    all_nodes: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_file_results: list[dict[str, Any]] = []
    files_processed = 0
    files_with_deps = 0

    # Track unique dependencies by name to avoid duplicates
    seen_dependencies: set = set()

    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_external_dependencies(
            file_path=file_path,
            file_content=file_content,
            repo_name=repo_name,
            llm_query_fn=llm_query_fn,
            config=config,
        )

        files_processed += 1

        # Store per-file result for L3 logging
        all_file_results.append(
            {
                "file_path": file_path,
                "success": result["success"],
                "dependencies_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_deps += 1
            # Deduplicate dependencies by name
            for node in result["data"]["nodes"]:
                dep_name = node["properties"]["dependencyName"].lower()
                if dep_name not in seen_dependencies:
                    seen_dependencies.add(dep_name)
                    all_nodes.append(node)

        if result["errors"]:
            all_errors.extend([f"{file_path}: {e}" for e in result["errors"]])

    return {
        "success": len(all_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": all_nodes},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(all_nodes),
            "node_types": {"ExternalDependency": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_dependencies": files_with_deps,
        },
        "file_results": all_file_results,
    }
