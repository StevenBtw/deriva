"""Validation logic for ArchiMate models.

This module provides validation functions to ensure ArchiMate models conform
to the ArchiMate metamodel and best practices.
"""

from __future__ import annotations


# Re-export for backwards compatibility
from deriva.common.exceptions import ValidationError as ValidationError

from .models import ArchiMateMetamodel, Element, Relationship

__all__ = ["ArchiMateValidator", "ValidationError"]


class ArchiMateValidator:
    """Validates ArchiMate elements and relationships against the metamodel."""

    def __init__(self, strict_mode: bool = False):
        """
        Initialize validator.

        Args:
            strict_mode: If True, enforce all metamodel rules strictly
        """
        self.metamodel = ArchiMateMetamodel()
        self.strict_mode = strict_mode

    def validate_element(self, element: Element) -> tuple[bool, list[str]]:
        """
        Validate an ArchiMate element.

        Args:
            element: Element to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check element type is valid
        if not self.metamodel.is_valid_element_type(element.element_type):
            errors.append(f"Invalid element type: {element.element_type}")

        # Check name is not empty
        if not element.name or not element.name.strip():
            errors.append("Element name cannot be empty")

        # Check identifier format
        if not element.identifier or not element.identifier.startswith("id-"):
            if self.strict_mode:
                errors.append(f"Invalid identifier format: {element.identifier}")

        return len(errors) == 0, errors

    def validate_relationship(
        self,
        relationship: Relationship,
        source_element: Element | None = None,
        target_element: Element | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Validate an ArchiMate relationship.

        Args:
            relationship: Relationship to validate
            source_element: Optional source element (for deeper validation)
            target_element: Optional target element (for deeper validation)

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []

        # Check relationship type is valid
        if not self.metamodel.is_valid_relationship_type(
            relationship.relationship_type
        ):
            errors.append(
                f"Invalid relationship type: {relationship.relationship_type}"
            )

        # Check source and target are not empty
        if not relationship.source:
            errors.append("Relationship source cannot be empty")
        if not relationship.target:
            errors.append("Relationship target cannot be empty")

        # Check source != target (no self-loops in strict mode)
        if self.strict_mode and relationship.source == relationship.target:
            errors.append(
                "Self-referencing relationships are not allowed in strict mode"
            )

        # If elements provided, validate the relationship is allowed by metamodel
        if source_element and target_element:
            can_relate, reason = self.metamodel.can_relate(
                source_element.element_type,
                relationship.relationship_type,
                target_element.element_type,
            )
            if not can_relate:
                errors.append(reason)

        return len(errors) == 0, errors

    def validate_model(
        self, elements: list[Element], relationships: list[Relationship]
    ) -> tuple[bool, list[str]]:
        """
        Validate an entire ArchiMate model.

        Args:
            elements: List of elements in the model
            relationships: List of relationships in the model

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        element_ids = {e.identifier for e in elements}

        # Validate all elements
        for element in elements:
            is_valid, element_errors = self.validate_element(element)
            errors.extend(element_errors)

        # Check for duplicate element identifiers
        identifiers = [e.identifier for e in elements]
        duplicates = set([x for x in identifiers if identifiers.count(x) > 1])
        if duplicates:
            errors.append(f"Duplicate element identifiers: {duplicates}")

        # Validate all relationships
        for relationship in relationships:
            # Check that source and target elements exist
            if relationship.source not in element_ids:
                errors.append(
                    f"Relationship references non-existent source: {relationship.source}"
                )
            if relationship.target not in element_ids:
                errors.append(
                    f"Relationship references non-existent target: {relationship.target}"
                )

            # Get source and target elements for validation
            source_element = next(
                (e for e in elements if e.identifier == relationship.source), None
            )
            target_element = next(
                (e for e in elements if e.identifier == relationship.target), None
            )

            # Validate relationship
            is_valid, rel_errors = self.validate_relationship(
                relationship, source_element, target_element
            )
            errors.extend(rel_errors)

        # Check for duplicate relationship identifiers
        rel_identifiers = [r.identifier for r in relationships]
        rel_duplicates = set(
            [x for x in rel_identifiers if rel_identifiers.count(x) > 1]
        )
        if rel_duplicates:
            errors.append(f"Duplicate relationship identifiers: {rel_duplicates}")

        # Check for orphaned elements (in strict mode)
        if self.strict_mode and len(elements) > 1:
            connected_elements = set()
            for rel in relationships:
                connected_elements.add(rel.source)
                connected_elements.add(rel.target)

            orphaned = element_ids - connected_elements
            if orphaned:
                errors.append(
                    f"Orphaned elements (not connected to any relationship): {orphaned}"
                )

        return len(errors) == 0, errors
