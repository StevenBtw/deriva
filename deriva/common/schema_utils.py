"""JSON Schema utilities for Deriva.

Provides helpers for building JSON Schema definitions used with LLM structured output.
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_array_schema", "build_object_schema"]


def build_array_schema(
    name: str,
    array_key: str,
    item_properties: dict[str, dict[str, Any]],
    required_item_fields: list[str],
    *,
    allow_additional_properties: bool = True,
) -> dict[str, Any]:
    """
    Build a JSON Schema for an object containing an array of items.

    This is the standard pattern for LLM structured output in Deriva:
    - A root object with a single array property
    - Each item in the array has defined properties

    Args:
        name: Schema name (e.g., 'extraction_output', 'derivation_output')
        array_key: Key for the array (e.g., 'elements', 'concepts', 'results')
        item_properties: Dictionary of property definitions for array items
        required_item_fields: List of required field names for each item
        allow_additional_properties: Whether items can have extra properties

    Returns:
        Complete JSON Schema dictionary ready for LLM structured output

    Example:
        >>> schema = build_array_schema(
        ...     name="concept_output",
        ...     array_key="concepts",
        ...     item_properties={
        ...         "name": {"type": "string"},
        ...         "description": {"type": "string"},
        ...         "confidence": {"type": "number"},
        ...     },
        ...     required_item_fields=["name", "description"],
        ... )
    """
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                array_key: {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": item_properties,
                        "required": required_item_fields,
                        "additionalProperties": allow_additional_properties,
                    },
                }
            },
            "required": [array_key],
            "additionalProperties": False,
        },
    }


def build_object_schema(
    name: str,
    properties: dict[str, dict[str, Any]],
    required_fields: list[str],
) -> dict[str, Any]:
    """
    Build a JSON Schema for a simple object response.

    Args:
        name: Schema name
        properties: Dictionary of property definitions
        required_fields: List of required field names

    Returns:
        Complete JSON Schema dictionary ready for LLM structured output

    Example:
        >>> schema = build_object_schema(
        ...     name="summary_output",
        ...     properties={
        ...         "summary": {"type": "string"},
        ...         "key_points": {"type": "array", "items": {"type": "string"}},
        ...     },
        ...     required_fields=["summary"],
        ... )
    """
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": required_fields,
            "additionalProperties": False,
        },
    }
