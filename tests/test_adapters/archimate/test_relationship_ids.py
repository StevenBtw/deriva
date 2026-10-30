"""Relationship identifiers come from what the relationship is, not from chance: the same relationship has the same
identifier in every run (a tie-break on identifiers is then deterministic), and adding it twice stores it once."""

from __future__ import annotations

import re

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship


def rel(source="ac_a", target="as_b", kind="Serving", origin="structure", **extra) -> Relationship:
    return Relationship(source=source, target=target, relationship_type=kind, properties={"derived_from": origin, **extra})


class TestIdentifier:
    def test_the_same_relationship_gets_the_same_identifier(self):
        assert rel().identifier == rel().identifier

    @pytest.mark.parametrize("other", [rel(source="ac_x"), rel(target="as_x"), rel(kind="Flow"), rel(origin="named_in_code"), rel(redirected_from="id-1")])
    def test_what_differs_gets_another(self, other):
        assert other.identifier != rel().identifier

    def test_a_given_identifier_is_kept(self):
        assert Relationship(source="a", target="b", identifier="rel-given").identifier == "rel-given"

    def test_it_is_a_valid_xml_id(self):
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", rel().identifier)


@pytest.fixture
def am():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    manager = ArchimateManager()
    manager.connect()
    yield manager
    manager.disconnect()
    close_database()


def test_adding_a_relationship_twice_stores_it_once(am):
    am.add_element(Element(name="A", element_type="ApplicationComponent", identifier="ac_a"))
    am.add_element(Element(name="B", element_type="ApplicationService", identifier="as_b"))

    first = am.add_relationship(rel(kind="Realization"))
    second = am.add_relationship(rel(kind="Realization"))

    assert first == second
    assert len(am.get_relationships()) == 1
