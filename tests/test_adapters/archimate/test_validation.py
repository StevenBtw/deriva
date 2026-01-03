"""Tests for adapters.archimate.validation module."""

from __future__ import annotations

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.validation import ArchiMateValidator, ValidationError


class TestArchiMateValidatorElement:
    """Tests for ArchiMateValidator.validate_element method."""

    def test_valid_element(self):
        """Should validate a well-formed element."""
        validator = ArchiMateValidator()
        element = Element(
            name="Core Service",
            element_type="ApplicationService",
            identifier="id-12345",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is True
        assert errors == []

    def test_invalid_element_type(self):
        """Should reject invalid element type."""
        validator = ArchiMateValidator()
        element = Element(
            name="Test",
            element_type="InvalidType",
            identifier="id-12345",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is False
        assert any("Invalid element type" in e for e in errors)

    def test_empty_name(self):
        """Should reject element with empty name."""
        validator = ArchiMateValidator()
        element = Element(
            name="",
            element_type="ApplicationComponent",
            identifier="id-12345",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is False
        assert any("name cannot be empty" in e for e in errors)

    def test_whitespace_only_name(self):
        """Should reject element with whitespace-only name."""
        validator = ArchiMateValidator()
        element = Element(
            name="   ",
            element_type="ApplicationComponent",
            identifier="id-12345",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is False
        assert any("name cannot be empty" in e for e in errors)

    def test_strict_mode_invalid_identifier(self):
        """Should reject non-id-prefixed identifier in strict mode."""
        validator = ArchiMateValidator(strict_mode=True)
        element = Element(
            name="Test",
            element_type="ApplicationComponent",
            identifier="invalid-prefix",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is False
        assert any("Invalid identifier format" in e for e in errors)

    def test_non_strict_mode_allows_any_identifier(self):
        """Should allow any identifier format in non-strict mode."""
        validator = ArchiMateValidator(strict_mode=False)
        element = Element(
            name="Test",
            element_type="ApplicationComponent",
            identifier="any-format",
        )

        is_valid, errors = validator.validate_element(element)

        assert is_valid is True

    def test_valid_element_types(self):
        """Should accept all standard ArchiMate element types."""
        validator = ArchiMateValidator()
        valid_types = [
            "ApplicationComponent",
            "ApplicationService",
            "ApplicationInterface",
            "DataObject",
            "BusinessActor",
            "BusinessProcess",
            "TechnologyService",
        ]

        for elem_type in valid_types:
            element = Element(
                name=f"Test {elem_type}",
                element_type=elem_type,
                identifier=f"id-{elem_type.lower()}",
            )
            is_valid, errors = validator.validate_element(element)
            assert is_valid is True, f"Element type {elem_type} should be valid"


class TestArchiMateValidatorRelationship:
    """Tests for ArchiMateValidator.validate_relationship method."""

    def test_valid_relationship(self):
        """Should validate a well-formed relationship."""
        validator = ArchiMateValidator()
        relationship = Relationship(
            source="id-source",
            target="id-target",
            relationship_type="Composition",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is True
        assert errors == []

    def test_invalid_relationship_type(self):
        """Should reject invalid relationship type."""
        validator = ArchiMateValidator()
        relationship = Relationship(
            source="id-source",
            target="id-target",
            relationship_type="InvalidRelType",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is False
        assert any("Invalid relationship type" in e for e in errors)

    def test_empty_source(self):
        """Should reject relationship with empty source."""
        validator = ArchiMateValidator()
        relationship = Relationship(
            source="",
            target="id-target",
            relationship_type="Composition",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is False
        assert any("source cannot be empty" in e for e in errors)

    def test_empty_target(self):
        """Should reject relationship with empty target."""
        validator = ArchiMateValidator()
        relationship = Relationship(
            source="id-source",
            target="",
            relationship_type="Composition",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is False
        assert any("target cannot be empty" in e for e in errors)

    def test_strict_mode_rejects_self_loop(self):
        """Should reject self-referencing relationships in strict mode."""
        validator = ArchiMateValidator(strict_mode=True)
        relationship = Relationship(
            source="id-same",
            target="id-same",
            relationship_type="Composition",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is False
        assert any("Self-referencing" in e for e in errors)

    def test_non_strict_mode_allows_self_loop(self):
        """Should allow self-referencing relationships in non-strict mode."""
        validator = ArchiMateValidator(strict_mode=False)
        relationship = Relationship(
            source="id-same",
            target="id-same",
            relationship_type="Composition",
            identifier="id-rel-1",
        )

        is_valid, errors = validator.validate_relationship(relationship)

        assert is_valid is True

    def test_valid_relationship_types(self):
        """Should accept all standard ArchiMate relationship types."""
        validator = ArchiMateValidator()
        # These match the RELATIONSHIP_TYPES in models.py
        valid_types = [
            "Composition",
            "Aggregation",
            "Assignment",
            "Serving",
            "Access",
            "Realization",
            "Flow",
        ]

        for rel_type in valid_types:
            relationship = Relationship(
                source="id-source",
                target="id-target",
                relationship_type=rel_type,
                identifier=f"id-rel-{rel_type.lower()}",
            )
            is_valid, errors = validator.validate_relationship(relationship)
            assert is_valid is True, f"Relationship type {rel_type} should be valid"


class TestArchiMateValidatorModel:
    """Tests for ArchiMateValidator.validate_model method."""

    def test_valid_model(self):
        """Should validate a well-formed model."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="Service A", element_type="ApplicationService", identifier="id-svc-a"),
            Element(name="Component A", element_type="ApplicationComponent", identifier="id-comp-a"),
        ]
        relationships = [
            Relationship(
                source="id-comp-a",
                target="id-svc-a",
                relationship_type="Realization",
                identifier="id-rel-1",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is True
        assert errors == []

    def test_duplicate_element_identifiers(self):
        """Should detect duplicate element identifiers."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="Service A", element_type="ApplicationService", identifier="id-same"),
            Element(name="Service B", element_type="ApplicationService", identifier="id-same"),
        ]

        is_valid, errors = validator.validate_model(elements, [])

        assert is_valid is False
        assert any("Duplicate element identifiers" in e for e in errors)

    def test_duplicate_relationship_identifiers(self):
        """Should detect duplicate relationship identifiers."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="A", element_type="ApplicationService", identifier="id-a"),
            Element(name="B", element_type="ApplicationService", identifier="id-b"),
            Element(name="C", element_type="ApplicationService", identifier="id-c"),
        ]
        relationships = [
            Relationship(source="id-a", target="id-b", relationship_type="Serving", identifier="id-rel"),
            Relationship(source="id-b", target="id-c", relationship_type="Serving", identifier="id-rel"),
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is False
        assert any("Duplicate relationship identifiers" in e for e in errors)

    def test_nonexistent_source(self):
        """Should detect relationships with nonexistent source."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="Target", element_type="ApplicationService", identifier="id-target"),
        ]
        relationships = [
            Relationship(
                source="id-nonexistent",
                target="id-target",
                relationship_type="Serving",
                identifier="id-rel-1",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is False
        assert any("non-existent source" in e for e in errors)

    def test_nonexistent_target(self):
        """Should detect relationships with nonexistent target."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="Source", element_type="ApplicationService", identifier="id-source"),
        ]
        relationships = [
            Relationship(
                source="id-source",
                target="id-nonexistent",
                relationship_type="Serving",
                identifier="id-rel-1",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is False
        assert any("non-existent target" in e for e in errors)

    def test_strict_mode_orphaned_elements(self):
        """Should detect orphaned elements in strict mode."""
        validator = ArchiMateValidator(strict_mode=True)
        elements = [
            Element(name="Connected A", element_type="ApplicationService", identifier="id-a"),
            Element(name="Connected B", element_type="ApplicationService", identifier="id-b"),
            Element(name="Orphaned", element_type="ApplicationService", identifier="id-orphan"),
        ]
        relationships = [
            Relationship(
                source="id-a",
                target="id-b",
                relationship_type="Serving",
                identifier="id-rel-1",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is False
        assert any("Orphaned elements" in e for e in errors)

    def test_non_strict_mode_allows_orphaned_elements(self):
        """Should allow orphaned elements in non-strict mode."""
        validator = ArchiMateValidator(strict_mode=False)
        elements = [
            Element(name="Connected A", element_type="ApplicationService", identifier="id-a"),
            Element(name="Connected B", element_type="ApplicationService", identifier="id-b"),
            Element(name="Orphaned", element_type="ApplicationService", identifier="id-orphan"),
        ]
        relationships = [
            Relationship(
                source="id-a",
                target="id-b",
                relationship_type="Serving",
                identifier="id-rel-1",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        # Only orphaned check is skipped in non-strict mode
        assert "Orphaned elements" not in str(errors)

    def test_empty_model(self):
        """Should validate empty model."""
        validator = ArchiMateValidator()

        is_valid, errors = validator.validate_model([], [])

        assert is_valid is True
        assert errors == []

    def test_single_element_no_relationships(self):
        """Should validate single element without relationships."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="Solo", element_type="ApplicationService", identifier="id-solo"),
        ]

        is_valid, errors = validator.validate_model(elements, [])

        assert is_valid is True

    def test_accumulates_multiple_errors(self):
        """Should accumulate all errors from elements and relationships."""
        validator = ArchiMateValidator()
        elements = [
            Element(name="", element_type="InvalidType", identifier="id-bad"),
        ]
        relationships = [
            Relationship(
                source="",
                target="",
                relationship_type="InvalidRel",
                identifier="id-rel-bad",
            )
        ]

        is_valid, errors = validator.validate_model(elements, relationships)

        assert is_valid is False
        # Should have errors for: invalid element type, empty name,
        # invalid rel type, empty source, empty target, nonexistent refs
        assert len(errors) >= 5


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_is_importable(self):
        """Should be able to import ValidationError."""
        assert ValidationError is not None

    def test_validation_error_is_exception(self):
        """ValidationError should be an exception."""
        assert issubclass(ValidationError, Exception)
