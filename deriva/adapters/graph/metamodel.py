"""Graph metamodel introspection.

This module provides functions to introspect the graph manager's models
and extract the metamodel structure for UI display and validation.
"""

from __future__ import annotations
import inspect
from dataclasses import fields
from typing import Any

from . import models

__all__ = [
    "get_all_node_classes",
    "get_node_properties",
    "get_relationship_types",
    "get_metamodel",
    "get_node_order",
]


def get_all_node_classes() -> dict[str, type]:
    """Get all node class definitions from models module.

    Returns:
        Dict mapping node type names to their dataclass types
    """
    node_classes = {}
    for name, obj in inspect.getmembers(models):
        if inspect.isclass(obj) and name.endswith("Node"):
            # Extract node type name (e.g., "RepositoryNode" -> "Repository")
            node_type = name.replace("Node", "")
            node_classes[node_type] = obj
    return node_classes


def get_node_properties(node_class: type) -> list[str]:
    """Get all property names for a node class.

    Args:
        node_class: The dataclass type representing a node

    Returns:
        List of property names
    """
    return [field.name for field in fields(node_class)]


def get_relationship_types() -> list[str]:
    """Get all relationship type constants.

    Returns:
        List of relationship type names
    """
    relationships = []
    for name, value in inspect.getmembers(models):
        if (
            isinstance(value, str)
            and name.isupper()
            and name not in ["Optional", "List"]
        ):
            relationships.append(value)
    return sorted(relationships)


def get_metamodel() -> dict[str, Any]:
    """Get complete graph metamodel structure.

    Returns:
        Dictionary with nodes and relationships metadata
    """
    node_classes = get_all_node_classes()

    # Build nodes list
    nodes = []
    for node_type, node_class in sorted(node_classes.items()):
        nodes.append(
            {
                "name": node_type,
                "class": node_class.__name__,
                "properties": get_node_properties(node_class),
                "docstring": node_class.__doc__ or "",
            }
        )

    # Build relationships list
    # Note: For now we'll use the constants. In future could add metadata about valid from/to
    relationships = [
        {
            "name": "CONTAINS",
            "description": "Hierarchical containment (repository→module, directory→file, etc.)",
        },
        {
            "name": "DEPENDS_ON",
            "description": "Dependencies between modules, files, or services",
        },
        {"name": "REFERENCES", "description": "File references to business concepts"},
        {"name": "IMPLEMENTS", "description": "File implements a technology"},
        {"name": "DECLARES", "description": "TypeDefinition declares methods"},
        {"name": "PROVIDES", "description": "TypeDefinition provides services"},
        {"name": "EXPOSES", "description": "Method exposes a service"},
        {"name": "USES", "description": "Uses external dependencies"},
        {"name": "TESTS", "description": "Test tests code elements"},
    ]

    return {"nodes": nodes, "relationships": relationships}


def get_node_order() -> list[str]:
    """Get the canonical order of node types for extraction.

    This defines the order in which nodes should be extracted based on
    dependencies between them.

    Returns:
        List of node type names in extraction order
    """
    return [
        "Repository",
        "Directory",
        "Module",
        "File",
        "BusinessConcept",
        "Technology",
        "TypeDefinition",
        "Method",
        "Test",
        "Service",
        "ExternalDependency",
    ]
