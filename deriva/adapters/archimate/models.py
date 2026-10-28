"""ArchiMate models and metamodel definitions.

This module defines:
- Core data structures for ArchiMate elements and relationships (instances)
- ArchiMate 3.2 metamodel type definitions and validation rules

Reference: https://pubs.opengroup.org/architecture/archimate3-doc/
"""

from __future__ import annotations

import hashlib
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
    # Element types appearing as source / target for this type in RELATIONSHIP_TABLE
    allowed_sources: set[str]
    allowed_targets: set[str]


# ArchiMate 3.2 Element Types (Application, Business & Technology Layers)
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
    "ApplicationFunction": ElementType(
        name="ApplicationFunction",
        layer="Application",
        aspect="Behavior",
        description="Automated behavior that can be performed by an application component",
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
    "BusinessRole": ElementType(
        name="BusinessRole",
        layer="Business",
        aspect="Structure",
        description="The responsibility for performing specific behavior, to which an actor can be assigned",
    ),
    "BusinessService": ElementType(
        name="BusinessService",
        layer="Business",
        aspect="Behavior",
        description="An explicitly defined behavior that a business role, business actor, or business collaboration exposes to its environment",
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
    "TechnologyFunction": ElementType(
        name="TechnologyFunction",
        layer="Technology",
        aspect="Behavior",
        description="A collection of technology behavior that can be performed by a technology internal active structure element",
    ),
    "TechnologyService": ElementType(
        name="TechnologyService",
        layer="Technology",
        aspect="Behavior",
        description="An explicitly defined exposed technology behavior",
    ),
    # The deployed image, package or bundle of a component (one per component with a function; 0.8.8)
    "Artifact": ElementType(
        name="Artifact",
        layer="Technology",
        aspect="Passive",
        description="A piece of data that is used or produced in a software development process, or by deployment and operation of an IT system",
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
    "BusinessRole",
    "Node",
    "Device",
    "SystemSoftware",
}

# Behavior elements (processes, services, functions)
BEHAVIOR_ELEMENTS: set[str] = {
    "ApplicationService",
    "ApplicationFunction",
    "BusinessProcess",
    "BusinessFunction",
    "BusinessEvent",
    "BusinessService",
    "TechnologyFunction",
    "TechnologyService",
}

# Passive elements (data/objects)
PASSIVE_ELEMENTS: set[str] = {
    "DataObject",
    "BusinessObject",
    "Artifact",
}

# All elements
ALL_ELEMENTS: set[str] = STRUCTURE_ELEMENTS | BEHAVIOR_ELEMENTS | PASSIVE_ELEMENTS

# Layer groupings
APPLICATION_LAYER: set[str] = {
    "ApplicationComponent",
    "ApplicationInterface",
    "ApplicationService",
    "ApplicationFunction",
    "DataObject",
}

BUSINESS_LAYER: set[str] = {
    "BusinessActor",
    "BusinessRole",
    "BusinessService",
    "BusinessProcess",
    "BusinessFunction",
    "BusinessEvent",
    "BusinessObject",
}

TECHNOLOGY_LAYER: set[str] = {
    "Node",
    "Device",
    "SystemSoftware",
    "TechnologyFunction",
    "TechnologyService",
    "Artifact",
}


def layer_of(element_type: str) -> str:
    """The ArchiMate layer of an element type: Business, Application, Technology or Other."""
    if element_type in BUSINESS_LAYER:
        return "Business"
    if element_type in APPLICATION_LAYER:
        return "Application"
    if element_type in TECHNOLOGY_LAYER:
        return "Technology"
    return "Other"


# Internal behaviour per layer: the same behaviour is often modelled as any of these (a function or a process)
INTERNAL_BEHAVIOUR: dict[str, str] = {f"{layer}{kind}": layer for layer in ("Business", "Application", "Technology") for kind in ("Process", "Function", "Interaction", "Event")}


def types_match(derived: str, reference: str) -> bool:
    """Whether a derived element's type counts as a reference element's type when a model is compared with a reference:
    the same type, or both internal behaviour (process, function, interaction, event) of one layer (user, 2026-10-19).
    Services and structure types stay strict."""
    if derived == reference:
        return True
    layer = INTERNAL_BEHAVIOUR.get(derived)
    return layer is not None and layer == INTERNAL_BEHAVIOUR.get(reference)


def match_kind(element_type: str) -> str:
    """The key an element type is matched under: internal behaviour as its layer's behaviour, else the type itself (two
    types match exactly when their keys are equal, as ``types_match`` says)."""
    layer = INTERNAL_BEHAVIOUR.get(element_type)
    return f"{layer} behaviour" if layer else element_type


# =============================================================================
# ArchiMate 3.2 Relationship Table
# =============================================================================
# Source: ArchiMate 3.2 Specification (C226), restricted to the element types Deriva derives plus Artifact. Letters:
# Archi's relationships.xml v3.2 (Influence left out), which matches the spec's Appendix B.5 tables in every cell. Tier,
# from the metamodel figures (0.8.8; B.4, p. 140: the restrictions apply to derived relationships only, not to those the
# metamodel diagrams define): uppercase where a figure draws the relationship, else lowercase. The figures: within a
# layer Fig. 52 p. 58 (business), Fig. 70 p. 73 (application), Fig. 82 p. 83 (technology), with Fig. 53 p. 59 (actor
# assigned to role), Fig. 71 p. 74 (component realizes component), Fig. 83 p. 84 (node, device, system software) and
# Fig. 97 p. 93 (artifact); across layers Fig. 104 p. 101 and Fig. 105 p. 102; the note under every layer figure for
# same-type composition, aggregation and specialization. Triggering and flow only where a figure draws both line ends
# unambiguously. Association is allowed between any two elements (uppercase everywhere).
#
# Uppercase letter: relationship explicit in the metamodel figures ("direct").
# Lowercase letter: allowed only via the spec's derivation rules ("derived").
# Deriva never applies derivation rules itself; the tier is read from the table.

RELATIONSHIP_LETTERS: dict[str, str] = {
    "a": "Access",
    "c": "Composition",
    "f": "Flow",
    "g": "Aggregation",
    "i": "Assignment",
    "n": "Influence",
    "o": "Association",
    "r": "Realization",
    "s": "Specialization",
    "t": "Triggering",
    "v": "Serving",
}
_LETTER_BY_RELATIONSHIP = {name: letter for letter, name in RELATIONSHIP_LETTERS.items()}

_TABLE_COLUMNS = (
    "BusinessActor",
    "BusinessRole",
    "BusinessProcess",
    "BusinessFunction",
    "BusinessEvent",
    "BusinessService",
    "BusinessObject",
    "ApplicationComponent",
    "ApplicationInterface",
    "ApplicationService",
    "ApplicationFunction",
    "DataObject",
    "Node",
    "Device",
    "SystemSoftware",
    "TechnologyFunction",
    "TechnologyService",
    "Artifact",
)

# fmt: off
_TABLE_ROWS: dict[str, tuple[str, ...]] = {
    "BusinessActor":        ("SCGvtfO", "IvtfO", "IvtfO", "IvtfO", "IvtfO", "irvtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "BusinessRole":         ("vtfO", "SCGvtfO", "IvtfO", "IvtfO", "IvtfO", "irvtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "BusinessProcess":      ("vtfO", "vtfO", "SCGvTFO", "CGvTFO", "vTFO", "RvtfO", "AO", "vtfO", "vtfO", "vtfO", "vtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "BusinessFunction":     ("vtfO", "vtfO", "CGvTFO", "SCGvTFO", "vTFO", "RvtfO", "AO", "vtfO", "vtfO", "vtfO", "vtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "BusinessEvent":        ("vtfO", "vtfO", "vTFO", "vTFO", "SCGvTFO", "vtfO", "AO", "vtfO", "vtfO", "vtfO", "vtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "BusinessService":      ("VtfO", "VtfO", "VtfO", "VtfO", "vtfO", "SCGvTFO", "AO", "vtfO", "vtfO", "vtfO", "VtfO", "aO", "vtfO", "vtfO", "vtfO", "VtfO", "vtfO", "aO"),
    "BusinessObject":       ("O", "O", "O", "O", "O", "O", "SCGO", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O", "O"),
    "ApplicationComponent": ("vtfO", "vtfO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "SCGRvtfO", "CgrvtfO", "irvtfO", "IrvtfO", "aO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),  # noqa: E501
    "ApplicationInterface": ("VtfO", "VtfO", "vtfO", "vtfO", "vtfO", "rvtfO", "aO", "VtfO", "SCGvtfO", "IvtfO", "vtfO", "aO", "VtfO", "VtfO", "VtfO", "vtfO", "vtfO", "aO"),
    "ApplicationService":   ("vtfO", "vtfO", "VtfO", "VtfO", "vtfO", "RvtfO", "aO", "VtfO", "vtfO", "SCGvTFO", "VtfO", "AO", "vtfO", "vtfO", "vtfO", "VtfO", "vtfO", "aO"),
    "ApplicationFunction":  ("vtfO", "vtfO", "RvtfO", "RvtfO", "vtfO", "rvtfO", "aO", "vtfO", "vtfO", "RvtfO", "SCGvTFO", "AO", "vtfO", "vtfO", "vtfO", "vtfO", "vtfO", "aO"),
    "DataObject":           ("O", "O", "O", "O", "O", "O", "RO", "O", "O", "O", "O", "SCGO", "O", "O", "O", "O", "O", "O"),
    "Node":                 ("ivtfO", "ivtfO", "irvtfO", "irvtfO", "irvtfO", "irvtfO", "aO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "SCGivtfO", "CGirvtfO", "CGirvtfO", "IrvtfO", "irvtfO", "iaO"),  # noqa: E501
    "Device":               ("vtfO", "vtfO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "vtfO", "SCGvtfO", "CGIrvtfO", "IrvtfO", "irvtfO", "IaO"),  # noqa: E501
    "SystemSoftware":       ("vtfO", "vtfO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "rvtfO", "rvtfO", "rvtfO", "rvtfO", "aO", "vtfO", "vtfO", "SCGIrvtfO", "IrvtfO", "irvtfO", "IaO"),  # noqa: E501
    "TechnologyFunction":   ("vtfO", "vtfO", "RvtfO", "RvtfO", "vtfO", "rvtfO", "aO", "vtfO", "vtfO", "rvtfO", "RvtfO", "aO", "vtfO", "vtfO", "vtfO", "SCGvTFO", "RvtfO", "AO"),
    "TechnologyService":    ("vtfO", "vtfO", "VtfO", "VtfO", "vtfO", "RvtfO", "aO", "vtfO", "vtfO", "RvtfO", "VtfO", "aO", "VtfO", "VtfO", "VtfO", "VtfO", "SCGvTFO", "AO"),
    "Artifact":             ("O", "O", "rO", "rO", "rO", "rO", "RO", "RO", "rO", "rO", "rO", "RO", "O", "O", "RO", "rO", "rO", "SCGrO"),
}
# fmt: on

RELATIONSHIP_TABLE: dict[tuple[str, str], str] = {(source, target): cell for source, row in _TABLE_ROWS.items() for target, cell in zip(_TABLE_COLUMNS, row, strict=True)}

# The valid derivation rules of ArchiMate 3.2, Appendix B.2 (spec pp. 127-131; the potential rules of B.3 are left out),
# as plain data for the derivation engine: (number, first relationship types, second types, join, derived type).
# Joins: "chain" p(a,b) q(b,c) -> r(a,c); "back" p(a,b) q(c,b) -> r(c,a). Derived type: "weakest" (by
# STRUCTURAL_STRENGTH), "first" (p's type) or "second" (q's type). The restrictions of B.4 (p. 139) hold through the
# relationship table, which is built from the figures and these rules: a derived triple the table does not allow is none.
STRUCTURAL_RELATIONSHIPS = ("Composition", "Aggregation", "Assignment", "Realization")  # Section 5.1
DEPENDENCY_RELATIONSHIPS = ("Serving", "Access", "Influence", "Association")  # Section 5.2
DYNAMIC_RELATIONSHIPS = ("Triggering", "Flow")  # Section 5.3
STRUCTURAL_STRENGTH = ("Realization", "Assignment", "Aggregation", "Composition")  # B.2.2, weakest first
VALID_DERIVATION_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...], str, str], ...] = (
    ("DR 1", ("Specialization",), ("Specialization",), "chain", "first"),  # p. 127: transitivity of specialization
    ("DR 2", STRUCTURAL_RELATIONSHIPS, STRUCTURAL_RELATIONSHIPS, "chain", "weakest"),  # p. 128
    ("DR 3", STRUCTURAL_RELATIONSHIPS, DEPENDENCY_RELATIONSHIPS, "chain", "second"),  # p. 129: in line
    ("DR 4", STRUCTURAL_RELATIONSHIPS, DEPENDENCY_RELATIONSHIPS, "back", "second"),  # p. 129: opposing
    ("DR 5", STRUCTURAL_RELATIONSHIPS, DYNAMIC_RELATIONSHIPS, "chain", "second"),  # p. 130
    ("DR 6", STRUCTURAL_RELATIONSHIPS, ("Flow",), "back", "second"),  # p. 130
    ("DR 7", ("Triggering",), STRUCTURAL_RELATIONSHIPS, "chain", "first"),  # p. 130
    ("DR 8", ("Triggering",), ("Triggering",), "chain", "first"),  # p. 131: transitivity of triggering
)

# Relationship types Deriva may propose. Association, Specialization and Influence
# are valid ArchiMate but deliberately not derived.
DERIVABLE_RELATIONSHIP_TYPES: tuple[str, ...] = (
    "Composition",
    "Aggregation",
    "Assignment",
    "Realization",
    "Serving",
    "Access",
    "Flow",
    "Triggering",
)


def relationship_tier(source_type: str, relationship_type: str, target_type: str) -> str | None:
    """Return "direct", "derived", or None if ArchiMate 3.2 does not allow it."""
    letter = _LETTER_BY_RELATIONSHIP.get(relationship_type)
    cell = RELATIONSHIP_TABLE.get((source_type, target_type))
    if letter is None or cell is None:
        return None
    if letter.upper() in cell:
        return "direct"
    if letter in cell:
        return "derived"
    return None


def _endpoints(relationship_type: str) -> tuple[set[str], set[str]]:
    letter = _LETTER_BY_RELATIONSHIP[relationship_type]
    pairs = [pair for pair, cell in RELATIONSHIP_TABLE.items() if letter in cell.lower()]
    return {s for s, _ in pairs}, {t for _, t in pairs}


def _relationship_type(name: str, description: str) -> RelationshipType:
    sources, targets = _endpoints(name)
    return RelationshipType(
        name=name,
        description=description,
        allowed_sources=sources,
        allowed_targets=targets,
    )


RELATIONSHIP_TYPES: dict[str, RelationshipType] = {
    # Structural
    "Composition": _relationship_type("Composition", "Element consists of other elements"),
    "Aggregation": _relationship_type("Aggregation", "Element combines other elements"),
    "Assignment": _relationship_type("Assignment", "Active structure element performs or is responsible for behavior"),
    "Realization": _relationship_type("Realization", "Element realizes a more abstract element"),
    # Dependency
    "Serving": _relationship_type("Serving", "Element provides services to another element"),
    "Access": _relationship_type("Access", "Behavior or structure accesses passive elements (data)"),
    "Influence": _relationship_type("Influence", "Element influences a motivation element"),
    "Association": _relationship_type("Association", "Unspecified relationship"),
    # Dynamic
    "Flow": _relationship_type("Flow", "Transfer from one element to another"),
    "Triggering": _relationship_type("Triggering", "Temporal or causal relationship between elements"),
    # Other
    "Specialization": _relationship_type("Specialization", "Element is a particular kind of another element"),
}


class ArchiMateMetamodel:
    """ArchiMate metamodel with validation rules."""

    # ArchiMate 3.2: a part is composed into at most one whole, and composition hierarchies are acyclic.
    single_parent_relationship_types: frozenset[str] = frozenset({"Composition"})
    acyclic_relationship_types: frozenset[str] = frozenset({"Composition"})
    # Appendix B.2: the valid derivation rules as data, and the structural strength order they use (weakest first)
    derivation_rules = VALID_DERIVATION_RULES
    structural_strength = STRUCTURAL_STRENGTH

    def __init__(self):
        self.element_types = ELEMENT_TYPES
        self.relationship_types = RELATIONSHIP_TYPES

    def tier(self, source_element_type: str, relationship_type: str, target_element_type: str) -> str | None:
        """ "direct" (a metamodel figure draws it), "derived", or None if ArchiMate 3.2 does not allow it."""
        return relationship_tier(source_element_type, relationship_type, target_element_type)

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

    def can_relate(self, source_element_type: str, relationship_type: str, target_element_type: str) -> tuple[bool, str]:
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

        tier = relationship_tier(source_element_type, relationship_type, target_element_type)
        if tier is None:
            return (
                False,
                f"{relationship_type} from {source_element_type} to {target_element_type} is not allowed by ArchiMate 3.2",
            )

        return True, f"Valid relationship ({tier})"

    def get_allowed_element_types(self) -> list[str]:
        """Get list of all allowed element types."""
        return list(self.element_types.keys())

    def get_allowed_relationship_types(self) -> list[str]:
        """Get list of all allowed relationship types."""
        return list(self.relationship_types.keys())

    def get_elements_by_layer(self, layer: str) -> list[str]:
        """Get all element types in a specific layer."""
        return [name for name, et in self.element_types.items() if et.layer == layer]

    def get_valid_relationships_from(self, source_element_type: str) -> list[dict[str, Any]]:
        """Get derivable relationship types and their allowed targets for a source type.

        Only DERIVABLE_RELATIONSHIP_TYPES are listed; Association, Specialization
        and Influence are valid but never proposed by Deriva.

        Args:
            source_element_type: The source element type (e.g., "ApplicationComponent")

        Returns:
            List of dicts with relationship_type, description, and allowed_targets
        """
        if not self.is_valid_element_type(source_element_type):
            return []

        valid_relationships = []

        for rel_name in DERIVABLE_RELATIONSHIP_TYPES:
            rel_type = self.relationship_types[rel_name]
            allowed_targets = [t for t in self.element_types if relationship_tier(source_element_type, rel_name, t)]

            if allowed_targets:
                valid_relationships.append(
                    {
                        "relationship_type": rel_name,
                        "description": rel_type.description,
                        "allowed_targets": allowed_targets,
                    }
                )

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
        enabled: Whether element is active (disabled elements are excluded from export)
    """

    name: str
    element_type: str = "ApplicationComponent"
    identifier: str = ""
    documentation: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

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
            "enabled": self.enabled,
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
            enabled=data.get("enabled", True),
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
        """Without a given identifier, one from what the relationship is (type, ends, origin): the same relationship
        has the same identifier in every run, so a tie-break on identifiers is deterministic and a duplicate is one."""
        if not self.identifier:
            origin = f"{self.properties.get('derived_from') or ''}|{self.properties.get('redirected_from') or ''}"
            digest = hashlib.sha256(f"{self.relationship_type}|{self.source}|{self.target}|{origin}".encode()).hexdigest()
            self.identifier = f"id-{digest[:32]}"

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


# =============================================================================
# Validation Helper Functions
# =============================================================================

# Singleton metamodel instance for validation
_metamodel: ArchiMateMetamodel | None = None


def _get_metamodel() -> ArchiMateMetamodel:
    """Get or create singleton metamodel instance."""
    global _metamodel
    if _metamodel is None:
        _metamodel = ArchiMateMetamodel()
    return _metamodel


def validate_relationship_rule(source_type: str, rel_type: str, target_type: str) -> tuple[bool, str]:
    """Validate a relationship rule against ArchiMate metamodel constraints.

    This is a convenience function for validating relationship rules defined
    in derivation modules (OUTBOUND_RULES, INBOUND_RULES).

    Args:
        source_type: Source element type (e.g., "ApplicationService")
        rel_type: Relationship type (e.g., "Flow", "Access")
        target_type: Target element type (e.g., "BusinessObject")

    Returns:
        Tuple of (is_valid, reason_message)

    Example:
        >>> is_valid, msg = validate_relationship_rule("ApplicationService", "Flow", "BusinessObject")
        >>> print(is_valid, msg)
        False Flow from ApplicationService to BusinessObject is not allowed by ArchiMate 3.2
    """
    metamodel = _get_metamodel()
    return metamodel.can_relate(source_type, rel_type, target_type)


def get_element_aspect(element_type: str) -> str | None:
    """Get the aspect (Structure, Behavior, Passive) for an element type.

    Args:
        element_type: Element type name (e.g., "ApplicationService")

    Returns:
        Aspect string or None if element type is invalid
    """
    if element_type in STRUCTURE_ELEMENTS:
        return "Structure"
    if element_type in BEHAVIOR_ELEMENTS:
        return "Behavior"
    if element_type in PASSIVE_ELEMENTS:
        return "Passive"
    return None
