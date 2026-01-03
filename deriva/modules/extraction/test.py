"""
Test extraction - LLM-based extraction of test definitions from test files.

This module extracts Test nodes representing test cases, their types,
and what they're testing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import current_timestamp

# JSON schema for LLM structured output
TEST_SCHEMA = {
    "name": "test_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "tests": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "testName": {
                            "type": "string",
                            "description": "Name of the test function/method",
                        },
                        "testType": {
                            "type": "string",
                            "enum": [
                                "unit",
                                "integration",
                                "e2e",
                                "performance",
                                "smoke",
                                "regression",
                                "other",
                            ],
                            "description": "Type of test",
                        },
                        "description": {
                            "type": "string",
                            "description": "What the test verifies",
                        },
                        "testedElement": {
                            "type": ["string", "null"],
                            "description": "What is being tested (class, function, feature)",
                        },
                        "framework": {
                            "type": ["string", "null"],
                            "description": "Test framework used",
                        },
                        "startLine": {
                            "type": "integer",
                            "description": "Line number where test starts",
                        },
                        "endLine": {
                            "type": "integer",
                            "description": "Line number where test ends",
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score between 0.0 and 1.0",
                        },
                    },
                    "required": [
                        "testName",
                        "testType",
                        "description",
                        "testedElement",
                        "framework",
                        "startLine",
                        "endLine",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tests"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str, file_path: str, instruction: str, example: str
) -> str:
    """
    Build the LLM prompt for test extraction.

    Args:
        file_content: Content of the test file to analyze
        file_path: Path to the file being analyzed
        instruction: Extraction instruction from config
        example: Example output from config

    Returns:
        Formatted prompt string
    """
    # Add line numbers to the file content for accurate line references
    lines = file_content.split("\n")
    numbered_content = "\n".join(f"{i + 1:4d} | {line}" for i, line in enumerate(lines))

    prompt = f"""You are analyzing a test file to extract test definitions.

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

Extract all test definitions from this file. Return ONLY a JSON object with a "tests" array. If no tests are found, return {{"tests": []}}.
"""
    return prompt


def build_test_node(
    test_data: dict[str, Any], file_path: str, repo_name: str
) -> dict[str, Any]:
    """
    Build a Test graph node from extracted test data.

    Args:
        test_data: Dictionary containing test data from LLM
        file_path: Path to the file where the test was found
        repo_name: Repository name for node ID generation

    Returns:
        Dictionary with success, data, errors, and stats
    """
    errors = []

    # Validate required fields
    required_fields = ["testName", "testType", "description"]
    for field in required_fields:
        if field not in test_data or not test_data[field]:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {
            "success": False,
            "data": {},
            "errors": errors,
            "stats": {"nodes_created": 0},
        }

    # Validate test type
    valid_types = [
        "unit",
        "integration",
        "e2e",
        "performance",
        "smoke",
        "regression",
        "other",
    ]
    test_type = test_data["testType"].lower()
    if test_type not in valid_types:
        test_type = "other"

    # Generate unique node ID
    test_name_slug = test_data["testName"].replace(" ", "_").replace("-", "_")
    file_path_slug = file_path.replace("/", "_").replace("\\", "_")
    node_id = f"test_{repo_name}_{file_path_slug}_{test_name_slug}"

    # Build the node structure
    node_data = {
        "node_id": node_id,
        "label": "Test",
        "properties": {
            "testName": test_data["testName"],
            "testType": test_type,
            "description": test_data["description"],
            "testedElement": test_data.get("testedElement"),
            "framework": test_data.get("framework"),
            "filePath": file_path,
            "startLine": test_data.get("startLine", 0),
            "endLine": test_data.get("endLine", 0),
            "confidence": test_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }

    return {
        "success": True,
        "data": node_data,
        "errors": [],
        "stats": {"nodes_created": 1, "node_type": "Test"},
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
        parsed = json.loads(response_content)

        if "tests" not in parsed:
            return {
                "success": False,
                "data": [],
                "errors": ['Response missing "tests" array'],
            }

        if not isinstance(parsed["tests"], list):
            return {
                "success": False,
                "data": [],
                "errors": ['"tests" must be an array'],
            }

        return {"success": True, "data": parsed["tests"], "errors": []}

    except json.JSONDecodeError as e:
        return {
            "success": False,
            "data": [],
            "errors": [f"JSON parsing error: {str(e)}"],
        }


def extract_tests(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract tests from a single test file using LLM.

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
        response = llm_query_fn(prompt, TEST_SCHEMA)

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

        # Build nodes for each test and create CONTAINS edge from File
        safe_path = file_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file_{repo_name}_{safe_path}"

        for test_data in parse_result["data"]:
            node_result = build_test_node(
                test_data=test_data, file_path=file_path, repo_name=repo_name
            )

            if node_result["success"]:
                node_data = node_result["data"]
                nodes.append(node_data)

                # Create CONTAINS edge: File -> Test
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
                "node_types": {"Test": len(nodes)},
                "tests_found": len(nodes),
                "tests_from_llm": len(parse_result["data"]),
            },
            "llm_details": llm_details,
        }

    except Exception as e:
        return {
            "success": False,
            "data": {"nodes": [], "edges": []},
            "errors": [f"Fatal error during test extraction: {str(e)}"],
            "stats": {"total_nodes": 0, "total_edges": 0},
            "llm_details": llm_details,
        }


def extract_tests_batch(
    files: list[dict[str, str]],
    repo_name: str,
    llm_query_fn,
    config: dict[str, Any],
    progress_callback: Callable | None = None,
) -> dict[str, Any]:
    """
    Extract tests from multiple test files.

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
    files_with_tests = 0

    total_files = len(files)

    for i, file_info in enumerate(files):
        file_path = file_info["path"]
        file_content = file_info["content"]

        if progress_callback:
            progress_callback(i + 1, total_files, file_path)

        result = extract_tests(
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
                "tests_extracted": len(result["data"]["nodes"]),
                "llm_details": result.get("llm_details", {}),
                "errors": result["errors"],
            }
        )

        if result["success"] and result["data"]["nodes"]:
            files_with_tests += 1
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
            "node_types": {"Test": len(all_nodes)},
            "files_processed": files_processed,
            "files_with_tests": files_with_tests,
        },
        "file_results": all_file_results,
    }
