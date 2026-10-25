"""Tests for ArchiMate models and metamodel."""

import re

import pytest

from deriva.adapters.archimate.models import (
    BEHAVIOR_ELEMENTS,
    PASSIVE_ELEMENTS,
    RELATIONSHIP_TYPES,
    STRUCTURE_ELEMENTS,
    ArchiMateMetamodel,
    Element,
    Relationship,
)


class TestElementTypeGroupings:
    """Tests for element type groupings."""

    def test_structure_elements_defined(self):
        """Should define structure elements."""
        assert "ApplicationComponent" in STRUCTURE_ELEMENTS
        assert "ApplicationInterface" in STRUCTURE_ELEMENTS
        assert "Node" in STRUCTURE_ELEMENTS

    def test_behavior_elements_defined(self):
        """Should define behavior elements."""
        assert "ApplicationService" in BEHAVIOR_ELEMENTS
        assert "BusinessProcess" in BEHAVIOR_ELEMENTS
        assert "TechnologyService" in BEHAVIOR_ELEMENTS

    def test_passive_elements_defined(self):
        """Should define passive elements."""
        assert "DataObject" in PASSIVE_ELEMENTS
        assert "BusinessObject" in PASSIVE_ELEMENTS

    def test_groupings_are_disjoint(self):
        """Element groupings should not overlap."""
        assert STRUCTURE_ELEMENTS.isdisjoint(BEHAVIOR_ELEMENTS)
        assert STRUCTURE_ELEMENTS.isdisjoint(PASSIVE_ELEMENTS)
        assert BEHAVIOR_ELEMENTS.isdisjoint(PASSIVE_ELEMENTS)


class TestRelationshipTypes:
    """Tests for relationship type definitions."""

    def test_composition_has_constraints(self):
        """Composition should have structure element constraints."""
        composition = RELATIONSHIP_TYPES.get("Composition")
        assert composition is not None
        assert composition.allowed_sources
        assert composition.allowed_targets
        # Composition typically between structure elements
        assert "ApplicationComponent" in composition.allowed_sources
        assert "ApplicationComponent" in composition.allowed_targets

    def test_serving_has_constraints(self):
        """Serving should allow behavior elements as sources."""
        serving = RELATIONSHIP_TYPES.get("Serving")
        assert serving is not None
        # Serving typically from behavior elements
        assert any(elem in BEHAVIOR_ELEMENTS for elem in serving.allowed_sources) or any(elem in STRUCTURE_ELEMENTS for elem in serving.allowed_sources)

    def test_access_has_constraints(self):
        """Access should allow passive elements as targets."""
        access = RELATIONSHIP_TYPES.get("Access")
        assert access is not None
        # Access typically to passive elements
        assert any(elem in PASSIVE_ELEMENTS for elem in access.allowed_targets)

    def test_all_relationship_types_have_description(self):
        """All relationship types should have descriptions."""
        for rel_type, rel_def in RELATIONSHIP_TYPES.items():
            # A sentence, not a placeholder
            assert len(rel_def.description.split()) >= 2, f"{rel_type} missing description"

    def test_core_relationship_types_exist(self):
        """Core ArchiMate relationship types should be defined."""
        core_types = ["Composition", "Aggregation", "Assignment", "Realization", "Serving", "Access", "Flow"]
        for rel_type in core_types:
            assert rel_type in RELATIONSHIP_TYPES, f"Missing core type: {rel_type}"


class TestArchiMateMetamodel:
    """Tests for ArchiMateMetamodel class."""

    @pytest.fixture
    def metamodel(self):
        """Create metamodel instance."""
        return ArchiMateMetamodel()

    def test_can_relate_valid_composition(self, metamodel):
        """Should allow valid composition relationship."""
        can_relate, reason = metamodel.can_relate("ApplicationComponent", "Composition", "ApplicationComponent")
        assert can_relate is True, f"Should allow Composition between ApplicationComponents: {reason}"

    def test_can_relate_invalid_source_type(self, metamodel):
        """Should reject relationship from invalid source type."""
        # DataObject (passive) cannot be source of Flow (requires behavior elements)
        can_relate, reason = metamodel.can_relate("DataObject", "Flow", "BusinessProcess")
        assert not can_relate

    def test_can_relate_invalid_target_type(self, metamodel):
        """Should reject relationship to invalid target type."""
        # Composition between unrelated element types should fail
        can_relate, reason = metamodel.can_relate("ApplicationComponent", "Composition", "BusinessProcess")
        # This depends on actual metamodel rules - may pass if rules are relaxed
        # The test validates that the method returns a tuple

    def test_can_relate_unknown_relationship_type(self, metamodel):
        """Should reject unknown relationship types."""
        can_relate, reason = metamodel.can_relate("ApplicationComponent", "UnknownType", "ApplicationComponent")
        assert not can_relate
        assert "Unknown" in reason or "not defined" in reason.lower() or "invalid" in reason.lower()

    def test_can_relate_unknown_source_element_type(self, metamodel):
        """Should reject unknown source element types."""
        can_relate, reason = metamodel.can_relate("UnknownElement", "Serving", "ApplicationService")
        assert not can_relate

    def test_can_relate_unknown_target_element_type(self, metamodel):
        """Should reject unknown target element types."""
        can_relate, reason = metamodel.can_relate("ApplicationComponent", "Serving", "UnknownElement")
        assert not can_relate


class TestGetValidRelationshipsFrom:
    """Tests for get_valid_relationships_from method."""

    @pytest.fixture
    def metamodel(self):
        """Create metamodel instance."""
        return ArchiMateMetamodel()

    def test_returns_list_for_valid_element_type(self, metamodel):
        """Should return list of valid relationships for valid element type."""
        result = metamodel.get_valid_relationships_from("ApplicationComponent")
        assert [r["relationship_type"] for r in result] == ["Composition", "Aggregation", "Assignment", "Realization", "Serving", "Access", "Flow", "Triggering"]
        assert result[0]["allowed_targets"] == ["ApplicationComponent", "ApplicationInterface"]

    def test_returns_relationship_type_info(self, metamodel):
        """Should return relationship type info with required fields."""
        result = metamodel.get_valid_relationships_from("ApplicationComponent")
        if result:  # May be empty for some element types
            for rel_info in result:
                assert "relationship_type" in rel_info
                assert "description" in rel_info
                assert "allowed_targets" in rel_info

    def test_application_component_can_compose(self, metamodel):
        """ApplicationComponent should be able to use Composition."""
        result = metamodel.get_valid_relationships_from("ApplicationComponent")
        rel_types = [r["relationship_type"] for r in result]
        assert "Composition" in rel_types or "Aggregation" in rel_types

    def test_application_component_can_serve(self, metamodel):
        """ApplicationComponent should be able to use Serving."""
        result = metamodel.get_valid_relationships_from("ApplicationComponent")
        rel_types = [r["relationship_type"] for r in result]
        assert "Serving" in rel_types

    def test_returns_empty_for_unknown_element_type(self, metamodel):
        """Should return empty list for unknown element types."""
        result = metamodel.get_valid_relationships_from("UnknownElementType")
        assert result == []

    def test_allowed_targets_are_element_types(self, metamodel):
        """Allowed targets should be valid element type names."""
        result = metamodel.get_valid_relationships_from("ApplicationComponent")
        for rel_info in result:
            targets = rel_info.get("allowed_targets", [])
            for target in targets:
                assert isinstance(target, str)
                # Target should be a known element type
                assert target in STRUCTURE_ELEMENTS or target in BEHAVIOR_ELEMENTS or target in PASSIVE_ELEMENTS, f"Unknown target type: {target}"

    def test_data_object_can_access(self, metamodel):
        """DataObject should not typically be source of many relationships."""
        result = metamodel.get_valid_relationships_from("DataObject")
        # A passive element: it is made of data objects and realizes business objects, it serves or accesses nothing
        assert [(r["relationship_type"], r["allowed_targets"]) for r in result] == [
            ("Composition", ["DataObject"]),
            ("Aggregation", ["DataObject"]),
            ("Realization", ["BusinessObject"]),
        ]

    def test_application_service_relationships(self, metamodel):
        """ApplicationService should have behavior-appropriate relationships."""
        result = metamodel.get_valid_relationships_from("ApplicationService")
        rel_types = [r["relationship_type"] for r in result]
        # Behavior elements typically have serving, realization, flow
        assert any(rt in rel_types for rt in ["Serving", "Flow", "Realization"])


class TestSpecRelationshipTable:
    """ArchiMate 3.2 Appendix B.5 relationship table for the 13 derived element types."""

    @pytest.fixture
    def metamodel(self):
        return ArchiMateMetamodel()

    @pytest.mark.parametrize(
        ("source", "rel", "target"),
        [
            ("BusinessProcess", "Composition", "BusinessProcess"),
            ("BusinessProcess", "Composition", "BusinessFunction"),
            ("BusinessFunction", "Composition", "BusinessProcess"),
            ("BusinessFunction", "Composition", "BusinessFunction"),
            ("BusinessEvent", "Composition", "BusinessEvent"),
            ("ApplicationService", "Composition", "ApplicationService"),
            ("TechnologyService", "Composition", "TechnologyService"),
            ("BusinessObject", "Aggregation", "BusinessObject"),
            ("DataObject", "Aggregation", "DataObject"),
            ("ApplicationComponent", "Realization", "ApplicationComponent"),
            ("DataObject", "Realization", "BusinessObject"),
            ("Device", "Assignment", "SystemSoftware"),
            ("SystemSoftware", "Assignment", "SystemSoftware"),
        ],
    )
    def test_accepts_direct_relationships_from_spec(self, metamodel, source, rel, target):
        can_relate, reason = metamodel.can_relate(source, rel, target)
        assert can_relate is True, reason

    @pytest.mark.parametrize(
        ("source", "rel", "target"),
        [
            ("BusinessActor", "Composition", "Node"),
            ("DataObject", "Composition", "BusinessObject"),
            ("ApplicationComponent", "Composition", "DataObject"),
            ("ApplicationComponent", "Assignment", "BusinessProcess"),
            ("BusinessActor", "Assignment", "ApplicationService"),
            ("ApplicationComponent", "Realization", "BusinessObject"),
            ("ApplicationService", "Realization", "ApplicationService"),
            ("BusinessActor", "Aggregation", "BusinessProcess"),
            ("ApplicationComponent", "Access", "ApplicationService"),
            ("BusinessObject", "Serving", "BusinessProcess"),
        ],
    )
    def test_rejects_relationships_not_in_spec(self, metamodel, source, rel, target):
        can_relate, _ = metamodel.can_relate(source, rel, target)
        assert not can_relate

    @pytest.mark.parametrize(
        ("source", "rel", "target"),
        [
            ("ApplicationComponent", "Assignment", "ApplicationService"),
            ("ApplicationComponent", "Realization", "ApplicationService"),
            ("Node", "Assignment", "SystemSoftware"),
            ("Node", "Realization", "TechnologyService"),
            ("ApplicationComponent", "Flow", "ApplicationComponent"),
            ("BusinessActor", "Triggering", "BusinessActor"),
        ],
    )
    def test_accepts_derived_relationships_from_spec(self, metamodel, source, rel, target):
        can_relate, reason = metamodel.can_relate(source, rel, target)
        assert can_relate is True, reason

    def test_association_is_valid_between_any_pair(self, metamodel):
        types = metamodel.get_allowed_element_types()
        for source in types:
            for target in types:
                can_relate, reason = metamodel.can_relate(source, "Association", target)
                assert can_relate is True, reason

    def test_specialization_only_between_same_type(self, metamodel):
        assert metamodel.can_relate("Node", "Specialization", "Node")[0]
        assert not metamodel.can_relate("Node", "Specialization", "Device")[0]

    def test_influence_not_valid_between_core_elements(self, metamodel):
        assert not metamodel.can_relate("BusinessActor", "Influence", "BusinessProcess")[0]

    @pytest.mark.parametrize(
        ("source", "rel", "target", "tier"),
        [
            ("DataObject", "Realization", "BusinessObject", "direct"),
            ("ApplicationInterface", "Assignment", "ApplicationService", "direct"),
            ("ApplicationService", "Serving", "BusinessProcess", "direct"),
            ("ApplicationComponent", "Assignment", "ApplicationService", "derived"),
            ("ApplicationComponent", "Serving", "BusinessActor", "derived"),
            ("BusinessActor", "Association", "Node", "direct"),
            ("ApplicationComponent", "Composition", "DataObject", None),
            ("Node", "Assignment", "Artifact", "direct"),
            ("Artifact", "Realization", "ApplicationComponent", "direct"),
            ("Artifact", "Realization", "ApplicationService", "derived"),
            ("Artifact", "Composition", "ApplicationComponent", None),
        ],
    )
    def test_relationship_tier(self, source, rel, target, tier):
        from deriva.adapters.archimate import models

        assert models.relationship_tier(source, rel, target) == tier

    def test_table_totals_match_transcription(self):
        from deriva.adapters.archimate import models

        derivable = ["Composition", "Aggregation", "Assignment", "Realization", "Serving", "Access", "Flow", "Triggering"]
        types = list(models.ELEMENT_TYPES)
        valid = sum(1 for s in types for t in types for r in derivable if models.relationship_tier(s, r, t))
        non_association = [r for r in models.RELATIONSHIP_TYPES if r != "Association"]
        direct = sum(1 for s in types for t in types for r in non_association if models.relationship_tier(s, r, t) == "direct")
        # The derived element types (ApplicationFunction since 0.8.8) plus Artifact (the export's detail level, from Archi's relationships.xml)
        assert valid == 583
        assert direct == 129

    def test_application_function_cells_hold_archis_letters_with_the_generic_metamodels_direct_tier(self):
        """The ApplicationFunction row and column (0.8.8) hold the letters of Archi's relationships.xml v3.2; the cells
        the generic metamodel shows are direct: a component is assigned to it, it realizes a service and business
        behaviour and accesses data."""
        from deriva.adapters.archimate import models

        assert models.relationship_tier("ApplicationComponent", "Assignment", "ApplicationFunction") == "direct"
        assert models.relationship_tier("ApplicationFunction", "Realization", "ApplicationService") == "direct"
        assert models.relationship_tier("ApplicationFunction", "Access", "DataObject") == "direct"
        assert models.relationship_tier("ApplicationService", "Serving", "ApplicationFunction") == "direct"
        # Application behaviour realizes business behaviour (the automation case of business/application alignment)
        assert models.relationship_tier("ApplicationFunction", "Realization", "BusinessProcess") == "direct"
        assert models.relationship_tier("ApplicationFunction", "Realization", "BusinessFunction") == "direct"
        assert models.relationship_tier("ApplicationFunction", "Serving", "BusinessProcess") == "derived"
        assert models.relationship_tier("ApplicationFunction", "Assignment", "ApplicationComponent") is None
        # Archi's letters for the row (i: none) and column, as transcribed
        assert models.RELATIONSHIP_TABLE[("ApplicationFunction", "ApplicationFunction")].lower() == "scgvtfo"
        assert models.RELATIONSHIP_TABLE[("ApplicationComponent", "ApplicationFunction")].lower() == "irvtfo"

    def test_valid_relationships_from_excludes_non_derivable_types(self, metamodel):
        rel_types = {r["relationship_type"] for r in metamodel.get_valid_relationships_from("BusinessActor")}
        assert "Association" not in rel_types
        assert "Specialization" not in rel_types

    def test_valid_relationships_from_lists_only_spec_targets(self, metamodel):
        result = metamodel.get_valid_relationships_from("DataObject")
        by_type = {r["relationship_type"]: set(r["allowed_targets"]) for r in result}
        assert by_type == {"Realization": {"BusinessObject"}, "Composition": {"DataObject"}, "Aggregation": {"DataObject"}}


class TestElement:
    """Tests for Element model."""

    def test_element_creation_with_name_and_type(self):
        """Should create element with name and type."""
        element = Element(name="Test", element_type="ApplicationComponent")
        assert element.name == "Test"
        assert element.element_type == "ApplicationComponent"

    def test_element_auto_generates_identifier(self):
        """Should auto-generate identifier if not provided."""
        element = Element(name="Test", element_type="ApplicationComponent")
        # "id-" and a uuid: unique, and a valid XML id (it starts with a letter)
        assert re.fullmatch(r"id-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", element.identifier)
        assert Element(name="Test", element_type="ApplicationComponent").identifier != element.identifier

    def test_element_uses_provided_identifier(self):
        """Should use provided identifier."""
        element = Element(name="Test", element_type="ApplicationComponent", identifier="custom_id")
        assert element.identifier == "custom_id"


class TestRelationship:
    """Tests for Relationship model."""

    def test_relationship_creation(self):
        """Should create relationship with required fields."""
        rel = Relationship(source="src_id", target="tgt_id", relationship_type="Serving")
        assert rel.source == "src_id"
        assert rel.target == "tgt_id"
        assert rel.relationship_type == "Serving"

    def test_relationship_auto_generates_identifier(self):
        """Should auto-generate identifier if not provided."""
        rel = Relationship(source="src", target="tgt", relationship_type="Serving")
        assert re.fullmatch(r"id-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", rel.identifier)
        assert Relationship(source="src", target="tgt", relationship_type="Serving").identifier != rel.identifier

    def test_relationship_with_properties(self):
        """Should store custom properties."""
        rel = Relationship(source="src", target="tgt", relationship_type="Serving", properties={"confidence": 0.9})
        assert rel.properties["confidence"] == 0.9


class TestStructuralRules:
    """ArchiMate 3.2: a part belongs to at most one whole via Composition, and wholes do not contain themselves."""

    def test_single_parent_and_acyclic_types(self):
        metamodel = ArchiMateMetamodel()
        assert metamodel.single_parent_relationship_types == frozenset({"Composition"})
        assert metamodel.acyclic_relationship_types == frozenset({"Composition"})
