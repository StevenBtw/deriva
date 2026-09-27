"""ArchimateManager element writes on a real in-memory grafeo."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element


@pytest.fixture
def am():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    manager = ArchimateManager()
    manager.connect()
    yield manager
    manager.disconnect()
    close_database()


def test_element_is_created_and_readable(am):
    am.add_element(Element(name="Claims", element_type="ApplicationComponent", identifier="ac_claims", properties={"source": "dir::x"}))

    (element,) = am.get_elements()
    assert (element.identifier, element.name, element.element_type, element.enabled) == ("ac_claims", "Claims", "ApplicationComponent", True)
    assert element.properties == {"source": "dir::x"}
    assert am.query("MATCH (e:Model {identifier: 'ac_claims'}) RETURN e.source_identifier AS s") == [{"s": "dir::x"}]


def test_adding_the_same_element_twice_updates_it(am):
    am.add_element(Element(name="Claims", element_type="ApplicationComponent", identifier="ac_claims"))
    am.add_element(Element(name="Claims Handling", element_type="ApplicationComponent", identifier="ac_claims", documentation="d"))

    (element,) = am.get_elements()
    assert (element.name, element.documentation) == ("Claims Handling", "d")


def test_element_writes_use_the_index_not_merge(am):
    # execute is what every Cypher write goes through (execute_write delegates to it)
    with (
        patch.object(am.db, "execute", wraps=am.db.execute) as execute,
        patch.object(am.db, "merge_node", wraps=am.db.merge_node) as merge_node,
    ):
        am.add_element(Element(name="Claims", element_type="ApplicationComponent", identifier="ac_claims"))

    merge_node.assert_called_once()
    assert not [c for c in execute.call_args_list if "MERGE" in c.args[0]]


def test_disabled_element_can_be_enabled_again(am):
    am.add_element(Element(name="Claims", element_type="ApplicationComponent", identifier="ac_claims"))
    am.disable_element("ac_claims", reason="duplicate_of:ac_other")

    assert am.enable_element("ac_claims") is True

    (element,) = am.get_elements(enabled_only=True)
    assert element.identifier == "ac_claims"
    assert am.query("MATCH (e:Model {identifier: 'ac_claims'}) RETURN e.disabled_reason AS r") == [{"r": None}]


def test_enabling_an_unknown_element_returns_false(am):
    assert am.enable_element("nope") is False
