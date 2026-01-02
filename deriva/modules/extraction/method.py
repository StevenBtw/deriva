"""
Method extraction - LLM-based extraction of methods from TypeDefinition code snippets.

This module extracts Method nodes from TypeDefinition code snippets using LLM analysis.
It identifies methods, functions, and their signatures within type definitions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import current_timestamp

# JSON schema for LLM structured output
METHOD_SCHEMA = {
    "name": "methods_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "methods": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "methodName": {
                            "type": "string",
                            "description": "Name of the method or function",
                        },
                        "returnType": {
                            "type": "string",
                            "description": "Return type of the method (e.g., 'str', 'int', 'void', 'None', 'Promise<User>')",
                        },
                        "visibility": {
                            "type": "string",
                            "enum": ["public", "private", "protected"],
                            "description": "Visibility/access level of the method",
                        },
                        "parameters": {
                            "type": "string",
                            "description": "Parameter signature (e.g., 'self, name: str, age: int' or 'userId: number, options?: Options')",
                        },
                        "description": {
                            "type": "string",
                            "description": "Brief description of what the method does",
                        },
                        "isStatic": {
                            "type": "boolean",
                            "description": "Whether this is a static method",
                        },
                        "isAsync": {
                            "type": "boolean",
                            "description": "Whether this is an async method",
                        },
                        "startLine": {
                            "type": "integer",
                            "description": "Line number where the method starts (relative to the snippet, 1-indexed)",
                        },
                        "endLine": {
                            "type": "integer",
                            "description": "Line number where the method ends (relative to the snippet, 1-indexed)",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "methodName",
                        "returnType",
                        "visibility",
                        "parameters",
                        "description",
                        "isStatic",
                        "isAsync",
                        "startLine",
                        "endLine",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["methods"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    code_snippet: str,
    type_name: str,
    type_category: str,
    file_path: str,
    instruction: str,
    example: str,
) -> str:
    """
    Build the LLM prompt for method extraction from a TypeDefinition code snippet.

    Args:
        code_snippet: The code snippet from the TypeDefinition node
        type_name: Name of the type (class, interface, etc.)
        type_category: Category of the type (class, interface, struct, etc.)
        file_path: Path to the file where the type is defined
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    # Add line numbers to the code snippet for accurate line references
    lines = code_snippet.split("\n")
    numbered_content = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))

    prompt = f"""You are analyzing a {type_category} definition to extract its methods.

## Context
- **Type Name:** {type_name}
- **Category:** {type_category}
- **File Path:** {file_path}

## Instructions
{instruction}

## Example Output
{example}

## Code (with line numbers)
```
{numbered_content}
```

Extract all methods and functions from this {type_category}. Return ONLY a JSON object with a "methods" array. If no methods are found, return {{"methods": []}}.
"""
    return prompt


def build_method_node(
    method_data: dict[str, Any],
    type_name: str,
    file_path: str,
    repo_name: str,
    type_start_line: int = 0,
) -> dict[str, Any]:
    """
    Build a Method graph node from extracted method data.

    Args:
        method_data: Dictionary containing method data from LLM
        type_name: Name of the parent type
        file_path: Path to the file where the type is defined
        repo_name: Repository name for node ID generation
        type_start_line: Start line of the parent type (to calculate absolute line numbers)

    Returns:
        Dictionary with:
            - success: bool - Whether the operation succeeded
            - data: Dict - The node data ready for GraphManager.add_node()
            - errors: List[str] - Any validation or transformation errors
            - stats: Dict - Statistics about the extraction
    """
    errors = []

    # Validate required fields
    required_fields = ["methodName", "returnType", "visibility"]
    for field in required_fields:
        if field not in method_data:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Validate visibility
    valid_visibilities = ["public", "private", "protected"]
    visibility = method_data.get("visibility", "public").lower()
    if visibility not in valid_visibilities:
        visibility = "public"

    # Extract line numbers (relative to snippet)
    start_line = method_data.get("startLine", 0)
    end_line = method_data.get("endLine", 0)

    # Generate unique node ID
    method_name_slug = method_data["methodName"].replace(" ", "_").replace("-", "_")
    type_name_slug = type_name.replace(" ", "_").replace("-", "_")
    file_path_slug = file_path.replace("/", "_").replace("\\", "_")
    node_id = f"method_{repo_name}_{file_path_slug}_{type_name_slug}_{method_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "Method",
        "properties": {
            "methodName": method_data["methodName"],
            "returnType": method_data.get("returnType", "None"),
            "visibility": visibility,
            "parameters": method_data.get("parameters", ""),
            "description": method_data.get("description", ""),
            "isStatic": method_data.get("isStatic", False),
            "isAsync": method_data.get("isAsync", False),
            "typeName": type_name,
            "filePath": file_path,
            "startLine": start_line,
            "endLine": end_line,
            "confidence": method_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "Method"},
    }


def parse_llm_response(response_content: str) -> dict[str, Any]:
    """
    Parse and validate LLM response content.

    Args:
        response_content: Raw JSON string from LLM

    Returns:
        Dictionary with:
            - success: bool
            - data: Parsed methods list
            - errors: List of parsing errors
    """
    try:
        parsed = json.loads(response_content)

        if "methods" not in parsed:
            return {
                "success": False,
                "data": [],
                "errors": ['Response missing "methods" array'],
            }

        if not isinstance(parsed["methods"], list):
            return {
                "success": False,
                "data": [],
                "errors": ['"methods" must be an array'],
            }

        return {"success": True, "data": parsed["methods"], "errors": []}

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "data": [],
            "errors": [f"JSON parsing error: {str(e)}"],
        }


def extract_methods(
    type_node: dict[str, Any], repo_name: str, llm_query_fn, config: dict[str, Any]
) -> dict[str, Any]:
    """
    Extract methods from a single TypeDefinition node using LLM.

    This is the main extraction function that:
    1. Uses the codeSnippet from the TypeDefinition node
    2. Builds the prompt using config instruction/example
    3. Calls the LLM via the provided query function
    4. Parses the response and builds Method nodes
    5. Creates CONTAINS edges from TypeDefinition to Method

    Args:
        type_node: TypeDefinition node dict with properties including codeSnippet
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

    # Extract type information
    type_props = type_node.get("properties", type_node)
    type_name = type_props.get("typeName", "")
    type_category = type_props.get("category", "class")
    file_path = type_props.get("filePath", "")
    code_snippet = type_props.get("codeSnippet", "")
    type_start_line = type_props.get("startLine", 0)
    type_node_id = type_node.get("node_id", "")

    # Skip if no code snippet
    if not code_snippet or not code_snippet.strip():
        return {
            "success": True,
            "data": {"nodes": [], "edges": []},
            "errors": [],
            "stats": {"total_nodes": 0, "total_edges": 0, "skipped": "no_code_snippet"},
            "llm_details": llm_details,
        }

    try:
        # Build the prompt
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_extraction_prompt(
            code_snippet=code_snippet,
            type_name=type_name,
            type_category=type_category,
            file_path=file_path,
            instruction=instruction,
            example=example,
        )
        llm_details["prompt"] = prompt

        # Call LLM
        response = llm_query_fn(prompt, METHOD_SCHEMA)

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

        # Build nodes for each method
        for method_data in parse_result["data"]:
            node_result = build_method_node(
                method_data=method_data,
                type_name=type_name,
                file_path=file_path,
                repo_name=repo_name,
                type_start_line=type_start_line,
            )

            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)

                # Create CONTAINS edge: TypeDefinition -> Method
                edge = {
                    "edge_id": f"contains_{type_node_id}_to_{node_data['node_id']}",
                    "from_node_id": type_node_id,
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
                "node_types": {"Method": len(nodes)},
                "methods_found": len(nodes),
                "methods_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during method extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_methods_batch(
    type_nodes: list[dict[str, Any]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract methods from multiple TypeDefinition nodes.

    Args:
        type_nodes: List of TypeDefinition node dicts with codeSnippet property
        repo_name: Repository name
        llm_query_fn: Function to call LLM
        config: Extraction config
        progress_callback: Optional callback(current, total, type_name)

    Returns:
        Aggregated results from all type extractions including llm_details per type
    """
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []
    all_errors: list[str] = []
    all_type_results: list[dict[str, Any]] = []  # Per-type results with llm_details
    types_processed = 0
    types_with_methods = 0

    total_types = len(type_nodes)

    for i, type_node in enumerate(type_nodes):
        type_props = type_node.get("properties", type_node)
        type_name = type_props.get("typeName", "Unknown")

        if progress_callback:
            progress_callback(i + 1, total_types, type_name)

        result = extract_methods(
            type_node=type_node,
            repo_name=repo_name,
            llm_query_fn=llm_query_fn,
            config=config,
        )

        types_processed += 1

        # Store per-type result with llm_details for L3 logging
        all_type_results.append(
            {
                "type_name": type_name,
                "file_path": type_props.get("filePath", ""),
                "success": result["success"],
                "methods_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            types_with_methods += 1
            all_nodes.extend(result["data"]["nodes"])
            all_edges.extend(result["data"]["edges"])

        if result["errors"]:
            all_errors.extend([f"{type_name}: {e}" for e in result["errors"]])

    return {
        "success": len(all_nodes) > 0 or len(all_errors) == 0,
        "data": {"nodes": all_nodes, "edges": all_edges},
        "errors": all_errors,
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_types": {"Method": len(all_nodes)},
            "types_processed": types_processed,
            "types_with_methods": types_with_methods,
        },
        "type_results": all_type_results,  # Per-type details for L3 logging
    }
