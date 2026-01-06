"""
TypeDefinition extraction - LLM-based extraction of type definitions from source files.

This module extracts TypeDefinition nodes from source code files using LLM analysis.
It identifies classes, interfaces, structs, enums, functions, and other type definitions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .base import (
    create_empty_llm_details,
    current_timestamp,
    parse_json_response,
    strip_chunk_suffix,
)

# JSON schema for LLM structured output
TYPE_DEFINITION_SCHEMA = {
    "name": "type_definitions_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "types": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "typeName": {
                            "type": "string",
                            "description": "Name of the type (class, interface, function, etc.)",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "class",
                                "interface",
                                "struct",
                                "enum",
                                "function",
                                "alias",
                                "module",
                                "other",
                            ],
                            "description": "Category of the type definition",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what this type does",
                        },
                        "interfaceType": {
                            "type": "string",
                            "enum": [
                                "REST API",
                                "GraphQL",
                                "gRPC",
                                "WebSocket",
                                "CLI",
                                "Internal API",
                                "none",
                            ],
                            "description": "Type of interface this definition exposes, or 'none' if not an interface",
                        },
                        "startLine": {
                            "type": "integer",
                            "description": "Line number where the type definition starts (1-indexed)",
                        },
                        "endLine": {
                            "type": "integer",
                            "description": "Line number where the type definition ends (1-indexed)",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "typeName",
                        "category",
                        "description",
                        "interfaceType",
                        "startLine",
                        "endLine",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["types"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """
    Build the LLM prompt for type definition extraction.

    Args:
        file_content: Content of the source file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    # Add line numbers to the file content for accurate line references
    lines = file_content.split("\n")
    numbered_content = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))

    prompt = f"""You are analyzing a source code file to extract type definitions.

## Context
- **File Path:** {file_path}

## Instructions
{instruction}

## Example Output
{example}

## File Content (with line numbers)
```
{numbered_content}
```

Extract all type definitions from this file. Return ONLY a JSON object with a "types" array. If no type definitions are found, return {{"types": []}}.
"""
    return prompt


def build_type_definition_node(
    type_data: dict[str, Any], file_path: str, repo_name: str, file_content: str = ""
) -> dict[str, Any]:
    """
    Build a TypeDefinition graph node from extracted type data.

    Args:
        type_data: Dictionary containing type data from LLM
            Expected keys: typeName, category, description, interfaceType, startLine, endLine, confidence
        file_path: Path to the file where the type was found
        repo_name: Repository name for node ID generation
        file_content: Full content of the source file (used to extract code snippet)

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = []

    # Validate required fields
    required_fields = ["typeName", "category", "description"]
    for field in required_fields:
        if field not in type_data or not type_data[field]:
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
        "class",
        "interface",
        "struct",
        "enum",
        "function",
        "alias",
        "module",
        "other",
    ]
    category = type_data["category"].lower()
    if category not in valid_categories:
        category = "other"

    # Validate interface type
    valid_interface_types = [
        "REST API",
        "GraphQL",
        "gRPC",
        "WebSocket",
        "CLI",
        "Internal API",
        "none",
    ]
    interface_type = type_data.get("interfaceType", "none")
    if interface_type not in valid_interface_types:
        interface_type = "none"

    # Extract line numbers
    start_line = type_data.get("startLine", 0)
    end_line = type_data.get("endLine", 0)

    # Extract code snippet from file content using line numbers
    code_snippet = ""
    if file_content and start_line > 0 and end_line >= start_line:
        lines = file_content.split("\n")
        # Convert to 0-indexed and extract the range
        snippet_lines = lines[start_line - 1 : end_line]
        code_snippet = "\n".join(snippet_lines)

    # Generate unique node ID
    type_name_slug = type_data["typeName"].replace(" ", "_").replace("-", "_")
    file_path_slug = file_path.replace("/", "_").replace("\\", "_")
    node_id = f"typedef_{repo_name}_{file_path_slug}_{type_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "TypeDefinition",
        "properties": {
            "typeName": type_data["typeName"],
            "category": category,
            "description": type_data["description"],
            "interfaceType": interface_type if interface_type != "none" else None,
            "filePath": file_path,
            "startLine": start_line,
            "endLine": end_line,
            "codeSnippet": code_snippet,
            "confidence": type_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "TypeDefinition"},
    }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """Parse LLM response for type definitions. Delegates to base parser."""
    return parse_json_response(response_content, "types")


def extract_type_definitions(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract type definitions from a single source file using LLM.

    This is the main extraction function that:
    1. Builds the prompt using config instruction/example
    2. Calls the LLM via the provided query function
    3. Parses the response and builds nodes
    4. Creates CONTAINS edges from File to TypeDefinition

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
        response = llm_query_fn(prompt, TYPE_DEFINITION_SCHEMA)

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

        # Build nodes for each type definition
        # Strip chunk suffix from file_path to get original file node ID
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        for type_data in parse_result["data"]:
            node_result = build_type_definition_node(
                type_data=type_data,
                file_path=file_path,
                repo_name=repo_name,
                file_content=file_content,
            )

            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)

                # Create CONTAINS edge: File -> TypeDefinition
                edge = {
                    "edge_id": f"contains_{file_node_id}_to_{node_data['node_id']}",
                    "from_node_id": file_node_id,
                    "to_node_id": node_data["node_id"],
                    "relationship_type": "CONTAINS",
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
                "node_types": {"TypeDefinition": len(nodes)},
                "types_found": len(nodes),
                "types_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during type definition extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_type_definitions_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract type definitions from multiple source files.

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
    files_with_types = 0

    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_type_definitions(
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
                "types_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_types += 1
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
            "node_types": {"TypeDefinition": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_types": files_with_types,
        },
        "file_results": all_file_results,  # Per-file details for L3 logging
    }
