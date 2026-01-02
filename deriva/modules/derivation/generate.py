"""
Generic element generation from graph data using LLM.

This module provides a single entry point for deriving any ArchiMate element type
from graph nodes. The element type and derivation rules come from config.
"""

from __future__ import annotations

from typing import Any

from deriva.adapters.archimate.models import Element

from .base import (
    DERIVATION_SCHEMA,
    build_derivation_prompt,
    build_element,
    parse_derivation_response,
)


def generate_element(
    graph_manager: Any,
    archimate_manager: Any,
    llm_query_fn: Any,
    element_type: str,
    query: str,
    instruction: str,
    example: str,
) -> dict[str, Any]:
    """
    Generate ArchiMate elements from graph data using LLM.

    Args:
        graph_manager: Connected GraphManager
        archimate_manager: Connected ArchimateManager
        llm_query_fn: LLM query function (prompt, schema) -> response
        element_type: ArchiMate element type (e.g., 'ApplicationComponent')
        query: Cypher query to get source graph nodes
        instruction: LLM instruction for derivation
        example: Example output format

    Returns:
        Dict with elements_created, created_elements, errors
    """
    elements_created = 0
    created_elements = []
    errors = []

    # Execute query
    try:
        graph_results = graph_manager.query(query)
    except Exception as e:
        return {
            "elements_created": 0,
            "created_elements": [],
            "errors": [f"Query error: {e}"],
        }

    if not graph_results:
        return {"elements_created": 0, "created_elements": [], "errors": []}

    # Build prompt
    prompt = build_derivation_prompt(
        graph_data=graph_results,
        instruction=instruction,
        example=example,
        element_type=element_type,
    )

    # Call LLM
    if llm_query_fn is None:
        return {
            "elements_created": 0,
            "created_elements": [],
            "errors": ["LLM not configured"],
        }

    try:
        response = llm_query_fn(prompt, DERIVATION_SCHEMA)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )
    except Exception as e:
        return {
            "elements_created": 0,
            "created_elements": [],
            "errors": [f"LLM error: {e}"],
        }

    # Parse response
    parse_result = parse_derivation_response(response_content)

    if not parse_result["success"]:
        return {
            "elements_created": 0,
            "created_elements": [],
            "errors": parse_result.get("errors", []),
        }

    # Create elements
    for derived in parse_result["data"]:
        element_result = build_element(derived, element_type)

        if element_result["success"]:
            data = element_result["data"]
            # Create Element object for archimate_manager
            element = Element(
                name=data["name"],
                element_type=data["element_type"],
                identifier=data["identifier"],
                documentation=data.get("documentation", ""),
                properties=data.get("properties", {}),
            )
            try:
                archimate_manager.add_element(element)
                elements_created += 1
                created_elements.append(
                    {
                        "identifier": element.identifier,
                        "name": element.name,
                        "element_type": element_type,
                    }
                )
            except Exception as e:
                errors.append(f"Failed to persist: {e}")
        else:
            errors.extend(element_result.get("errors", []))

    return {
        "elements_created": elements_created,
        "created_elements": created_elements,
        "errors": errors,
    }


__all__ = ["generate_element"]
