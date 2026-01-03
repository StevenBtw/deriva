"""ArchiMate models and metamodel definitions.

This module defines:
- Core data structures for ArchiMate elements and relationships (instances)
- ArchiMate 3.1 metamodel type definitions and validation rules

Reference: https://pubs.opengroup.org/architecture/archimate3-doc/
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


# =============================================================================
# Metamodel Type Definitions
# =============================================================================


@dataclass
class ElementType:
    """ArchiMate element type definition."""

    name: str
    layer: str  # Application, Technology, Business, Strategy, Physical, Motivation, Implementation
    aspect: str  # Behavior, Structure, Passive
    description: str


@dataclass
class RelationshipType:
    """ArchiMate relationship type definition."""

    name: str
    description: str
    allowed_sources: set[str]  # Element types that can be source (empty = any)
    allowed_targets: set[str]  # Element types that can be target (empty = any)


# ArchiMate 3.1 Element Types (Application & Business Layers)
ELEMENT_TYPES: dict[str, ElementType] = {
    # Application Layer
    "ApplicationComponent": ElementType(
        name="ApplicationComponent",
        layer="Application",
        aspect="Structure",
        description="A modular, deployable, and replaceable part of a software system",
    ),
    "ApplicationInterface": ElementType(
        name="ApplicationInterface",
        layer="Application",
        aspect="Structure",
        description="A point of access where application services are made available",
    ),
    "ApplicationService": ElementType(
        name="ApplicationService",
        layer="Application",
        aspect="Behavior",
        description="An explicitly defined exposed application behavior",
    ),
    "DataObject": ElementType(
        name="DataObject",
        layer="Application",
        aspect="Passive",
        description="Data structured for automated processing",
    ),
    # Business Layer
    "BusinessObject": ElementType(
        name="BusinessObject",
        layer="Business",
        aspect="Passive",
        description="A concept used within a particular business domain",
    ),
    "BusinessProcess": ElementType(
        name="BusinessProcess",
        layer="Business",
        aspect="Behavior",
        description="A sequence of business behaviors that produces a defined set of products or services",
    ),
    "BusinessFunction": ElementType(
        name="BusinessFunction",
        layer="Business",
        aspect="Behavior",
        description="A collection of business behavior based on a chosen set of criteria",
    ),
    "BusinessEvent": ElementType(
        name="BusinessEvent",
        layer="Business",
        aspect="Behavior",
        description="An organizational state change",
    ),
    "BusinessActor": ElementType(
        name="BusinessActor",
        layer="Business",
        aspect="Structure",
        description="An organizational entity that is capable of performing behavior",
    ),
    # Technology Layer
    "Node": ElementType(
        name="Node",
        layer="Technology",
        aspect="Structure",
        description="A computational or physical resource that hosts, manipulates, or interacts with other elements",
    ),
    "Device": ElementType(
        name="Device",
        layer="Technology",
        aspect="Structure",
        description="A physical IT resource on which system software and artifacts may be stored or deployed",
    ),
    "SystemSoftware": ElementType(
        name="SystemSoftware",
        layer="Technology",
        aspect="Structure",
        description="Software that provides or contributes to an environment for storing, executing, and using software or data",
    ),
    "TechnologyService": ElementType(
        name="TechnologyService",
        layer="Technology",
        aspect="Behavior",
        description="An explicitly defined exposed technology behavior",
    ),
}


# =============================================================================
# Element Type Groupings by Aspect (for relationship constraints)
# =============================================================================

# Structure elements (active structure)
STRUCTURE_ELEMENTS: set[str] = {
    "ApplicationComponent",
    "ApplicationInterface",
    "BusinessActor",
    "Node",
    "Device",
    "SystemSoftware",
}

# Behavior elements (processes, services, functions)
BEHAVIOR_ELEMENTS: set[str] = {
    "ApplicationService",
    "BusinessProcess",
    "BusinessFunction",
    "BusinessEvent",
    "TechnologyService",
}

# Passive elements (data/objects)
PASSIVE_ELEMENTS: set[str] = {
    "DataObject",
    "BusinessObject",
}

# All elements
ALL_ELEMENTS: set[str] = STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS | PASSIVE_ELEMENTS

# Layer groupings
APPLICATION_LAYER: set[str] = {
    "ApplicationComponent",
    "ApplicationInterface",
    "ApplicationService",
    "DataObject",
}

BUSINESS_LAYER: set[str] = {
    "BusinessActor",
    "BusinessProcess",
    "BusinessFunction",
    "BusinessEvent",
    "BusinessObject",
}

TECHNOLOGY_LAYER: set[str] = {
    "Node",
    "Device",
    "SystemSoftware",
    "TechnologyService",
}


# =============================================================================
# ArchiMate 3.1 Relationship Types with Constraints
# =============================================================================

RELATIONSHIP_TYPES: dict[str, RelationshipType] = {
    # Structural Relationships
    "Composition": RelationshipType(
        name="Composition",
        description="Element consists of other elements (same aspect, same layer)",
        allowed_sources=STRUCTURE_ELEMENTS,  # Only structure elements can compose
        allowed_targets=STRUCTURE_ELEMENTS,  # Only structure elements can be composed
    ),
    "Aggregation": RelationshipType(
        name="Aggregation",
        description="Element combines other elements (same or compatible aspects)",
        allowed_sources=STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS,
        allowed_targets=STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS | PASSIVE_ELEMENTS,
    ),
    # Dependency Relationships
    "Assignment": RelationshipType(
        name="Assignment",
        description="Structure element performs or is responsible for behavior",
        allowed_sources=STRUCTURE_ELEMENTS,  # Only structure elements can be assigned
        allowed_targets=BEHAVIOR_ELEMENTS,  # Only to behavior elements
    ),
    "Realization": RelationshipType(
        name="Realization",
        description="Structure element realizes behavior; lower layer realizes higher",
        allowed_sources=STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS,
        allowed_targets=BEHAVIOR_ELEMENTS | PASSIVE_ELEMENTS,
    ),
    "Serving": RelationshipType(
        name="Serving",
        description="Element provides services to another element",
        allowed_sources=BEHAVIOR_ELEMENTS | STRUCTURE_ELEMENTS,  # Services/components serve
        allowed_targets=STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS,  # Other elements are served
    ),
    "Access": RelationshipType(
        name="Access",
        description="Behavior/structure accesses passive elements (data)",
        allowed_sources=BEHAVIOR_ELEMENTS | STRUCTURE_ELEMENTS,
        allowed_targets=PASSIVE_ELEMENTS,  # Only passive elements can be accessed
    ),
    # Dynamic Relationships
    "Flow": RelationshipType(
        name="Flow",
        description="Transfer of information between behavior elements",
        allowed_sources=BEHAVIOR_ELEMENTS,  # Only behavior elements can flow
        allowed_targets=BEHAVIOR_ELEMENTS,  # Only to behavior elements
    ),
}


class ArchiMateMetamodel:
    """ArchiMate metamodel with validation rules."""

    def __init__(self):
        self.element_types = ELEMENT_TYPES
        self.relationship_types = RELATIONSHIP_TYPES

    def is_valid_element_type(self, element_type: str) -> bool:
        """Check if element type is valid."""
        return element_type in self.element_types

    def is_valid_relationship_type(self, relationship_type: str) -> bool:
        """Check if relationship type is valid."""
        return relationship_type in self.relationship_types

    def get_element_type(self, element_type: str) -> ElementType:
        """Get element type definition."""
        if not self.is_valid_element_type(element_type):
            raise ValueError(f"Invalid element type: {element_type}")
        return self.element_types[element_type]

    def get_relationship_type(self, relationship_type: str) -> RelationshipType:
        """Get relationship type definition."""
        if not self.is_valid_relationship_type(relationship_type):
            raise ValueError(f"Invalid relationship type: {relationship_type}")
        return self.relationship_types[relationship_type]

    def can_relate(
        self, source_element_type: str, relationship_type: str, target_element_type: str
    ) -> tuple[bool, str]:
        """
        Check if a relationship is valid between two element types.

        Args:
            source_element_type: Source element type
            relationship_type: Relationship type
            target_element_type: Target element type

        Returns:
            Tuple of (is_valid, reason)
        """
        # Validate element types exist
        if not self.is_valid_element_type(source_element_type):
            return False, f"Invalid source element type: {source_element_type}"

        if not self.is_valid_element_type(target_element_type):
            return False, f"Invalid target element type: {target_element_type}"

        # Validate relationship type exists
        if not self.is_valid_relationship_type(relationship_type):
            return False, f"Invalid relationship type: {relationship_type}"

        rel_type = self.relationship_types[relationship_type]

        # Check allowed sources (if specified)
        if (
            rel_type.allowed_sources
            and source_element_type not in rel_type.allowed_sources
        ):
            return (
                False,
                f"{relationship_type} cannot originate from {source_element_type}",
            )

        # Check allowed targets (if specified)
        if (
            rel_type.allowed_targets
            and target_element_type not in rel_type.allowed_targets
        ):
            return False, f"{relationship_type} cannot target {target_element_type}"

        return True, "Valid relationship"

    def get_allowed_element_types(self) -> list[str]:
        """Get list of all allowed element types."""
        return list(self.element_types.keys())

    def get_allowed_relationship_types(self) -> list[str]:
        """Get list of all allowed relationship types."""
        return list(self.relationship_types.keys())

    def get_elements_by_layer(self, layer: str) -> list[str]:
        """Get all element types in a specific layer."""
        return [name for name, et in self.element_types.items() if et.layer == layer]

    def get_valid_relationships_from(
        self, source_element_type: str
    ) -> list[dict[str, Any]]:
        """Get valid relationship types and their allowed targets for a source element type.

        Args:
            source_element_type: The source element type (e.g., "ApplicationComponent")

        Returns:
            List of dicts with relationship_type, description, and allowed_targets
        """
        if not self.is_valid_element_type(source_element_type):
            return []

        valid_relationships = []

        for rel_name, rel_type in self.relationship_types.items():
            # Check if source is allowed (empty set means any source is allowed)
            if rel_type.allowed_sources and source_element_type not in rel_type.allowed_sources:
                continue

            # Determine allowed targets
            if rel_type.allowed_targets:
                # Only include target types that exist in our element_types
                allowed_targets = [
                    t for t in rel_type.allowed_targets if t in self.element_types
                ]
            else:
                # All element types are allowed
                allowed_targets = list(self.element_types.keys())

            if allowed_targets:  # Only include if there are valid targets
                valid_relationships.append({
                    "relationship_type": rel_name,
                    "description": rel_type.description,
                    "allowed_targets": allowed_targets,
                })

        return valid_relationships


# =============================================================================
# Instance Models
# =============================================================================


@dataclass
class Element:
    """ArchiMate element.

    Represents any ArchiMate element (ApplicationComponent, ApplicationService, etc.).

    Attributes:
        name: Display name of the element
        element_type: Type of element (must be valid ArchiMate type)
        identifier: Unique identifier (auto-generated if not provided)
        documentation: Optional documentation text
        properties: Optional custom properties (key-value pairs)
    """

    name: str
    element_type: str = "ApplicationComponent"
    identifier: str = ""
    documentation: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Generate identifier if not provided."""
        if not self.identifier:
            self.identifier = f"id-{uuid.uuid4()}"

    def to_dict(self) -> dict[str, Any]:
        """Convert element to dictionary representation."""
        return {
            "identifier": self.identifier,
            "name": self.name,
            "element_type": self.element_type,
            "documentation": self.documentation,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Element:
        """Create element from dictionary representation."""
        return cls(
            name=data["name"],
            element_type=data["element_type"],
            identifier=data.get("identifier") or "",
            documentation=data.get("documentation"),
            properties=data.get("properties", {}),
        )


@dataclass
class Relationship:
    """ArchiMate relationship.

    Represents a relationship between two ArchiMate elements.

    Attributes:
        source: Identifier of source element
        target: Identifier of target element
        relationship_type: Type of relationship (Composition, Aggregation, etc.)
        identifier: Unique identifier (auto-generated if not provided)
        name: Optional name for the relationship
        documentation: Optional documentation text
        properties: Optional custom properties (key-value pairs)
    """

    source: str
    target: str
    relationship_type: str = "Composition"
    identifier: str = ""
    name: str | None = None
    documentation: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Generate identifier if not provided."""
        if not self.identifier:
            self.identifier = f"id-{uuid.uuid4()}"

    def to_dict(self) -> dict[str, Any]:
        """Convert relationship to dictionary representation."""
        return {
            "identifier": self.identifier,
            "source": self.source,
            "target": self.target,
            "relationship_type": self.relationship_type,
            "name": self.name,
            "documentation": self.documentation,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Relationship:
        """Create relationship from dictionary representation."""
        return cls(
            source=data["source"],
            target=data["target"],
            relationship_type=data["relationship_type"],
            identifier=data.get("identifier") or "",
            name=data.get("name"),
            documentation=data.get("documentation"),
            properties=data.get("properties", {}),
        )
