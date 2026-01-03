"""JSON parsing utilities for Deriva.

Provides consistent JSON parsing with error handling for LLM responses.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["parse_json_array", "ParseResult", "extract_json_from_response"]


def extract_json_from_response(content: str) -> str:
    """
    Extract JSON from LLM response, handling common wrapping patterns.

    Handles:
    - Markdown code blocks (```json ... ``` or ``` ... ```)
    - Leading/trailing whitespace
    - Raw JSON (passed through as-is)

    Args:
        content: Raw LLM response that may contain JSON

    Returns:
        Extracted JSON string ready for parsing
    """
    content = content.strip()

    # Handle markdown code blocks: ```json ... ``` or ``` ... ```
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
    match = re.search(code_block_pattern, content)
    if match:
        return match.group(1).strip()

    # If content looks like JSON object/array, return as-is
    if content.startswith(("{", "[")):
        return content

    # Try to find JSON object within the response
    json_obj_pattern = r"(\{[\s\S]*\})"
    match = re.search(json_obj_pattern, content)
    if match:
        return match.group(1)

    # Return original if no patterns match
    return content


class ParseResult:
    """Result of a JSON parsing operation."""

    __slots__ = ("success", "data", "errors")

    def __init__(self, success: bool, data: list[Any], errors: list[str]):
        self.success = success
        self.data = data
        self.errors = errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        return {
            "success": self.success,
            "data": self.data,
            "errors": self.errors,
        }


def parse_json_array(content: str, array_key: str) -> ParseResult:
    """
    Parse JSON content and extract an array by key.

    This is the common pattern used across extraction, derivation, and validation
    modules for parsing LLM responses that contain arrays of items.

    Args:
        content: Raw JSON string (typically from LLM response)
        array_key: Expected key containing the array (e.g., 'concepts', 'elements', 'results')

    Returns:
        ParseResult with:
            - success: Whether parsing succeeded
            - data: Extracted list (empty on failure)
            - errors: List of error messages (empty on success)

    Examples:
        >>> result = parse_json_array('{"items": [1, 2, 3]}', 'items')
        >>> result.success
        True
        >>> result.data
        [1, 2, 3]

        >>> result = parse_json_array('{"other": []}', 'items')
        >>> result.success
        False
        >>> result.errors
        ['Response missing "items" array']
    """
    try:
        # Extract JSON from potential markdown wrapping
        extracted = extract_json_from_response(content)
        parsed = json.loads(extracted)

        if array_key not in parsed:
            return ParseResult(
                success=False,
                data=[],
                errors=[f'Response missing "{array_key}" array'],
            )

        if not isinstance(parsed[array_key], list):
            return ParseResult(
                success=False,
                data=[],
                errors=[f'"{array_key}" must be an array'],
            )

        return ParseResult(
            success=True,
            data=parsed[array_key],
            errors=[],
        )

    except json.JSONDecodeError as e:
        return ParseResult(
            success=False,
            data=[],
            errors=[f"JSON parsing error: {e!s}"],
        )
