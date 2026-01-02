"""Tests for services.derivation module."""

from deriva.services.derivation import _normalize_relationship_type


class TestNormalizeRelationshipType:
    """Tests for relationship type normalization."""

    def test_valid_pascalcase_unchanged(self):
        """Valid PascalCase types should be returned unchanged."""
        assert _normalize_relationship_type("Realization") == "Realization"
        assert _normalize_relationship_type("Serving") == "Serving"
        assert _normalize_relationship_type("Access") == "Access"
        assert _normalize_relationship_type("Composition") == "Composition"
        assert _normalize_relationship_type("Aggregation") == "Aggregation"
        assert _normalize_relationship_type("Flow") == "Flow"
        assert _normalize_relationship_type("Assignment") == "Assignment"

    def test_uppercase_normalized_to_pascalcase(self):
        """UPPERCASE types should be normalized to PascalCase."""
        assert _normalize_relationship_type("REALIZATION") == "Realization"
        assert _normalize_relationship_type("SERVING") == "Serving"
        assert _normalize_relationship_type("ACCESS") == "Access"
        assert _normalize_relationship_type("COMPOSITION") == "Composition"
        assert _normalize_relationship_type("AGGREGATION") == "Aggregation"
        assert _normalize_relationship_type("FLOW") == "Flow"
        assert _normalize_relationship_type("ASSIGNMENT") == "Assignment"

    def test_lowercase_normalized_to_pascalcase(self):
        """lowercase types should be normalized to PascalCase."""
        assert _normalize_relationship_type("realization") == "Realization"
        assert _normalize_relationship_type("serving") == "Serving"
        assert _normalize_relationship_type("access") == "Access"

    def test_mixed_case_normalized_to_pascalcase(self):
        """Mixed case types should be normalized to PascalCase."""
        assert _normalize_relationship_type("ReAlIzAtIoN") == "Realization"
        assert _normalize_relationship_type("sErViNg") == "Serving"

    def test_unknown_type_returned_unchanged(self):
        """Unknown types should be returned unchanged (will fail validation)."""
        assert _normalize_relationship_type("Unknown") == "Unknown"
        assert _normalize_relationship_type("INVALID") == "INVALID"
        assert _normalize_relationship_type("custom") == "custom"
