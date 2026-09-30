"""Structural quality of a derived ArchiMate model, reported next to consistency."""

from __future__ import annotations

from deriva.modules.analysis.model_quality import compute_model_quality
from deriva.modules.analysis.types import ReferenceElement, ReferenceRelationship


def _el(identifier: str, element_type: str) -> ReferenceElement:
    return ReferenceElement(identifier=identifier, name=identifier, element_type=element_type)


def _rel(source: str, target: str, relationship_type: str) -> ReferenceRelationship:
    return ReferenceRelationship(identifier=f"{source}-{relationship_type}-{target}", source=source, target=target, relationship_type=relationship_type)


ELEMENTS = [
    _el("shop", "ApplicationComponent"),
    _el("store", "ApplicationComponent"),
    _el("api", "ApplicationInterface"),
    _el("ordering", "ApplicationService"),
    _el("order_data", "DataObject"),
    _el("host", "Node"),
    _el("sell", "BusinessProcess"),
    _el("lonely", "BusinessActor"),
]


class TestSizeAndOrphans:
    def test_counts_relationships_per_element_and_orphans(self):
        relationships = [_rel("shop", "api", "Composition"), _rel("shop", "ordering", "Realization"), _rel("host", "shop", "Serving"), _rel("ordering", "sell", "Serving")]

        quality = compute_model_quality(ELEMENTS, relationships)

        assert quality.elements == 8
        assert quality.relationships == 4
        assert quality.relationships_per_element == 0.5
        # store, order_data and lonely take part in no relationship
        assert quality.orphans == 3
        assert quality.orphan_share == 0.375

    def test_relationships_to_unknown_elements_do_not_count(self):
        quality = compute_model_quality(ELEMENTS, [_rel("shop", "gone", "Composition")])

        assert quality.relationships == 0
        assert quality.orphans == 8

    def test_an_empty_model(self):
        quality = compute_model_quality([], [])

        assert quality.elements == 0 and quality.relationships_per_element == 0.0 and quality.orphan_share == 0.0


class TestRuleViolations:
    def test_a_part_composed_into_two_wholes_is_a_violation(self):
        relationships = [_rel("shop", "api", "Composition"), _rel("store", "api", "Composition"), _rel("shop", "order_data", "Composition")]

        assert compute_model_quality(ELEMENTS, relationships).composition_violations == 1

    def test_a_pair_with_several_relationship_types_is_counted_once(self):
        relationships = [_rel("shop", "ordering", "Realization"), _rel("shop", "ordering", "Assignment"), _rel("shop", "api", "Composition")]

        assert compute_model_quality(ELEMENTS, relationships).duplicate_pairs == 1


class TestChains:
    def test_coverage_counts_elements_linked_to_the_other_type_in_either_direction(self):
        relationships = [_rel("shop", "ordering", "Realization"), _rel("host", "shop", "Serving")]

        chains = compute_model_quality(ELEMENTS, relationships).chains

        assert chains["ApplicationService-ApplicationComponent"] == (1, 1)
        assert chains["ApplicationComponent-Node"] == (1, 2)
        assert chains["BusinessProcess-ApplicationService"] == (0, 1)

    def test_a_chain_is_reported_only_when_its_first_type_is_in_the_model(self):
        chains = compute_model_quality([_el("shop", "ApplicationComponent")], []).chains

        assert "BusinessProcess-ApplicationService" not in chains
        assert chains["ApplicationComponent-Node"] == (0, 1)
