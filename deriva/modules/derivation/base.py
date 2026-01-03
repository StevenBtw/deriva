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


# Hardcoded critical rules are a fallback, default is element config from database
def build_relationship_prompt(elements: list[dict[str, Any]]) -> str:
    """Build LLM prompt for relationship derivation."""
    elements_json = json.dumps(elements, indent=2, default=str)

    # Extract valid identifiers for the prompt
    valid_ids = [e.get("identifier", "") for e in elements if e.get("identifier")]

    return f"""Derive relationships between these ArchiMate elements:

```json
{elements_json}
```

CRITICAL RULES:
1. You must ONLY use identifiers from this exact list: {json.dumps(valid_ids)}
2. Do NOT invent new identifiers or modify existing ones
3. Use identifiers exactly as shown (case-sensitive, character-for-character)
4. Only create relationships where BOTH source AND target exist in the list

VALID RELATIONSHIP TYPES (use ONLY these exact names):
- Composition: element consists of other elements
- Aggregation: element combines other elements
- Serving: element provides services to another
- Realization: element realizes/implements another
- Access: element reads/writes data objects
- Flow: transfer of information between elements
- Assignment: allocates responsibility between elements

INVALID TYPES (NEVER use these):
- Association (use Serving or Flow instead)
- Dependency (use Serving instead)
- Uses (use Serving instead)

Output stable, deterministic results.
Return {{"relationships": []}} with source, target, relationship_type for each.
"""


def build_element_relationship_prompt(
    source_elements: list[dict[str, Any]],
    target_elements: list[dict[str, Any]],
    source_element_type: str,
    valid_relationships: list[dict[str, Any]],
    instruction: str | None = None,
    example: str | None = None,
) -> str:
    """Build LLM prompt for element-type-specific relationship derivation.

    Args:
        source_elements: Elements of the current type to derive relationships FROM
        target_elements: All elements that can be relationship targets
        source_element_type: The ArchiMate element type of source elements
        valid_relationships: List of valid relationship types with allowed_targets
        instruction: Custom instruction from database config (optional)
        example: Custom example from database config (optional)

    Returns:
        Formatted prompt string for LLM
    """
    sources_json = json.dumps(source_elements, indent=2, default=str)
    targets_json = json.dumps(target_elements, indent=2, default=str)

    # Extract valid identifiers for strict validation
    source_ids = [
        e.get("identifier", "") for e in source_elements if e.get("identifier")
    ]
    target_ids = [
        e.get("identifier", "") for e in target_elements if e.get("identifier")
    ]

    # Build relationship rules from metamodel constraints
    rel_rules = []
    for rel in valid_relationships:
        targets = ", ".join(rel["allowed_targets"])
        rel_rules.append(
            f"- {rel['relationship_type']}: {rel['description']} → can target: [{targets}]"
        )
    rel_rules_text = (
        "\n".join(rel_rules) if rel_rules else "No valid relationship types available."
    )

    # Use default instruction if not provided
    default_instruction = f"""Derive relationships FROM the {source_element_type} elements to other elements.
Only create relationships where the source is from the Source Elements list.
Use only the relationship types valid for {source_element_type} as specified below."""

    # Use default example if not provided
    default_example = """{"relationships": [
  {"source": "source_id", "target": "target_id", "relationship_type": "Serving", "confidence": 0.8}
]}"""

    return f"""You are deriving ArchiMate relationships FROM {source_element_type} elements.

## Instructions
{instruction or default_instruction}

## Source Elements (type: {source_element_type})
These are the elements you must create relationships FROM:
```json
{sources_json}
```

## Target Elements (all types)
These are the available elements you can create relationships TO:
```json
{targets_json}
```

## Valid Relationship Types for {source_element_type}
{rel_rules_text}

## Example Output Format
```json
{example or default_example}
```

CRITICAL RULES:
1. Source identifiers MUST be from this list: {json.dumps(source_ids)}
2. Target identifiers MUST be from this list: {json.dumps(target_ids)}
3. Use identifiers exactly as shown (case-sensitive)
4. Only use relationship types listed above for {source_element_type}
5. Each relationship must respect the allowed target types

Return {{"relationships": []}} with source, target, relationship_type for each.
If no valid relationships can be derived, return {{"relationships": []}}.
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
    "build_element_relationship_prompt",
    "parse_derivation_response",
    "parse_relationship_response",
    "build_element",
]
