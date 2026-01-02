"""
Base utilities for derivation modules.

Minimal shared functions for prep and generate steps.
"""

from __future__ import annotations

import json
from typing import Any

from deriva.common import current_timestamp, parse_json_array
from deriva.common.types import PipelineResult


# =============================================================================
# Schemas for LLM
# =============================================================================

DERIVATION_SCHEMA: dict[str, Any] = {
    "name": "derivation_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "identifier": {"type": "string"},
                        "name": {"type": "string"},
                        "documentation": {"type": "string"},
                        "source": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["identifier", "name"],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["elements"],
        "additionalProperties": False,
    },
}

RELATIONSHIP_SCHEMA: dict[str, Any] = {
    "name": "relationship_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "relationship_type": {"type": "string"},
                        "name": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["source", "target", "relationship_type"],
                    "additionalProperties": True,
                },
            }
        },
        "required": ["relationships"],
        "additionalProperties": False,
    },
}


# =============================================================================
# Result Creation
# =============================================================================


def create_result(
    success: bool,
    errors: list[str] | None = None,
    stats: dict[str, Any] | None = None,
) -> PipelineResult:
    """Create a simple pipeline result."""
    return {
        "success": success,
        "errors": errors or [],
        "stats": stats or {},
        "timestamp": current_timestamp(),
    }


# =============================================================================
# Prompt Building
# =============================================================================


def build_derivation_prompt(
    graph_data: list[dict[str, Any]],
    instruction: str,
    example: str,
    element_type: str,
) -> str:
    """Build LLM prompt for element derivation."""
    data_json = json.dumps(graph_data, indent=2, default=str)

    return f"""You are deriving ArchiMate {element_type} elements from source code graph data.

## Instructions
{instruction}

## Example Output
{example}

## Source Data
```json
{data_json}
```

Return a JSON object with an "elements" array. Each element needs: identifier, name.
If no elements can be derived, return {{"elements": []}}.
"""


def build_relationship_prompt(elements: list[dict[str, Any]]) -> str:
    """Build LLM prompt for relationship derivation."""
    elements_json = json.dumps(elements, indent=2, default=str)

    # Extract valid identifiers for the prompt
    valid_ids = [e.get("identifier", "") for e in elements if e.get("identifier")]

    return f"""Derive relationships between these ArchiMate elements:

```json
{elements_json}
```

IMPORTANT RULES:
1. You must ONLY use identifiers from this exact list: {json.dumps(valid_ids)}
2. Do NOT invent new identifiers or modify existing ones
3. Use identifiers exactly as shown (case-sensitive, character-for-character)
4. Only create relationships where BOTH source AND target exist in the list

Relationship types: Composition, Aggregation, Serving, Realization, Access.
Return {{"relationships": []}} with source, target, relationship_type for each.
"""


# =============================================================================
# Response Parsing
# =============================================================================


def parse_derivation_response(response: str) -> dict[str, Any]:
    """Parse LLM response for elements."""
    return parse_json_array(response, "elements").to_dict()


def parse_relationship_response(response: str) -> dict[str, Any]:
    """Parse LLM response for relationships."""
    return parse_json_array(response, "relationships").to_dict()


# =============================================================================
# Element Building
# =============================================================================


def _sanitize_identifier(identifier: str) -> str:
    """
    Sanitize identifier to be valid XML NCName and ensure consistency.

    Applies the same normalization as extraction to ensure consistent IDs:
    - Lowercase everything
    - Replace spaces, hyphens, colons with underscores
    - Remove non-alphanumeric characters (except underscore)
    - Ensure starts with letter/underscore (NCName requirement)
    """
    # Normalize: lowercase, replace separators with underscores
    sanitized = identifier.lower().replace(" ", "_").replace("-", "_").replace(":", "_")
    # Keep only alphanumeric and underscore
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "_")
    # Ensure it starts with a letter or underscore (NCName requirement)
    if sanitized and not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = f"id_{sanitized}"
    return sanitized


def build_element(derived: dict[str, Any], element_type: str) -> dict[str, Any]:
    """Build ArchiMate element dict from LLM output."""
    identifier = derived.get("identifier")
    name = derived.get("name")

    if not identifier or not name:
        return {"success": False, "errors": ["Missing identifier or name"]}

    # Sanitize identifier for XML compatibility
    identifier = _sanitize_identifier(identifier)

    return {
        "success": True,
        "data": {
            "identifier": identifier,
            "name": name,
            "element_type": element_type,
            "documentation": derived.get("documentation", ""),
            "properties": {
                "source": derived.get("source"),
                "confidence": derived.get("confidence", 0.5),
                "derived_at": current_timestamp(),
            },
        },
    }


__all__ = [
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    "create_result",
    "build_derivation_prompt",
    "build_relationship_prompt",
    "parse_derivation_response",
    "parse_relationship_response",
    "build_element",
]
