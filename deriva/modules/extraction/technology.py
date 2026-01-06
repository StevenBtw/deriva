"""
Technology extraction - LLM-based extraction of infrastructure technology components.

This module extracts Technology nodes representing high-level infrastructure components
that map to ArchiMate Technology Layer elements: services, system software,
infrastructure, platforms, networks, and security components.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import (
    create_empty_llm_details,
    current_timestamp,
    generate_edge_id,
    parse_json_response,
    strip_chunk_suffix,
)

# JSON schema for LLM structured output
TECHNOLOGY_SCHEMA = {
    "name": "technology_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "technologies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "techName": {
                            "type": "string",
                            "description": "Name of the technology",
                        },
                        "techCategory": {
                            "type": "string",
                            "enum": [
                                "service",
                                "system_software",
                                "infrastructure",
                                "platform",
                                "network",
                                "security",
                            ],
                            "description": "Category of technology component",
                        },
                        "description": {
                            "type": "string",
                            "description": "Role of this technology in the system",
                        },
                        "version": {
                            "type": ["string", "null"],
                            "description": "Version if specified",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "techName",
                        "techCategory",
                        "description",
                        "version",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["technologies"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """
    Build the LLM prompt for technology extraction.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    prompt = f"""You are analyzing a configuration/build file to extract technology infrastructure.

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

Extract technology infrastructure components. Return ONLY a JSON object with a "technologies" array. If no technologies are found, return {{"technologies": []}}.
"""
    return prompt


def build_technology_node(
    tech_data: dict[str, Any], origin_source: str, repo_name: str
) -> dict[str, Any]:
    """
    Build a Technology graph node from extracted technology data.

    Args:
        tech_data: Dictionary containing technology data from LLM
        origin_source: Path to the file where the technology was found
        repo_name: Repository name for node ID generation

    Returns:
        Dictionary with success, data, errors, and stats
    """
    errors = []

    # Validate required fields
    required_fields = ["techName", "techCategory", "description"]
    for field in required_fields:
        if field not in tech_data or not tech_data[field]:
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
        "service",
        "system_software",
        "infrastructure",
        "platform",
        "network",
        "security",
    ]
    category = tech_data["techCategory"].lower()
    if category not in valid_categories:
        category = "infrastructure"

    # Generate unique node ID
    tech_name_slug = tech_data["techName"].lower().replace(" ", "_").replace("-", "_")
    node_id = f"tech_{repo_name}_{tech_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "Technology",
        "properties": {
            "techName": tech_data["techName"],
            "techCategory": category,
            "description": tech_data["description"],
            "version": tech_data.get("version"),
            "originSource": origin_source,
            "confidence": tech_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "Technology"},
    }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """Parse LLM response for technologies. Delegates to base parser."""
    return parse_json_response(response_content, "technologies")


def extract_technologies(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract technologies from a single file using LLM.

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
        )
        llm_details["prompt"] = prompt

        # Call LLM
        response = llm_query_fn(prompt, TECHNOLOGY_SCHEMA)

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

        # Build file node ID for IMPLEMENTS edges
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        # Build nodes for each technology
        for tech_data in parse_result["data"]:
            node_result = build_technology_node(
                tech_data=tech_data, origin_source=file_path, repo_name=repo_name
            )

            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)

                # Create IMPLEMENTS edge: File -> Technology
                edge = {
                    "edge_id": generate_edge_id(
                        file_node_id, node_data["node_id"], "IMPLEMENTS"
                    ),
                    "from_node_id": file_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "IMPLEMENTS",
                    "properties": {"created_at": current_timestamp()},
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
                "node_types": {"Technology": len(nodes)},
                "technologies_found": len(nodes),
                "technologies_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during technology extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_technologies_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract technologies from multiple files.

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
    all_edges: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_file_results: list[dict[str, Any]] = []
    files_processed = 0
    files_with_tech = 0

    # Track unique technologies by name to avoid duplicates
    seen_technologies: set[str] = set()

    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_technologies(
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
                "technologies_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_tech += 1
            # Deduplicate technologies by name, but keep all edges
            result_edges = result["data"].get("edges", [])
            for idx, node in enumerate(result["data"]["nodes"]):
                tech_name = node["properties"]["techName"].lower()
                if tech_name not in seen_technologies:
                    seen_technologies.add(tech_name)
                    all_nodes.append(node)
                # Always add the edge (multiple files can IMPLEMENTS same technology)
                if idx < len(result_edges):
                    all_edges.append(result_edges[idx])

        if result["errors"]:
            all_errors.extend([f"{file_path}: {e}" for e in result["errors"]])

    return {
        "success": len(all_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": all_nodes, "edges": all_edges},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_types": {"Technology": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_technologies": files_with_tech,
        },
        "file_results": all_file_results,
    }
