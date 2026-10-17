"""The abstraction_levels refine step: levels on every element and relationship, roll-up Compositions between the
components of the hierarchy, and services realized at the enterprise level by the top-level component."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship
from deriva.modules.derivation.refine import run_refine_step

PARAMS = {"types": {"ApplicationInterface": ["solution"], "ApplicationService": ["enterprise"]}}


@pytest.fixture
def am():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    manager = ArchimateManager()
    manager.connect()
    yield manager
    manager.disconnect()
    close_database()


def _graph(rows):
    graph = MagicMock()
    graph.query.return_value = rows
    return graph


def test_levels_roll_ups_and_service_lifts_are_written(am):
    for identifier, element_type, source in (
        ("ac_sys", "ApplicationComponent", "module::r::r"),
        ("ac_orders", "ApplicationComponent", "unit::r::orders"),
        ("ai_orders", "ApplicationInterface", "unit::r::orders"),
        ("as_orders", "ApplicationService", "unit::r::orders"),
    ):
        am.add_element(Element(name=identifier, element_type=element_type, identifier=identifier, properties={"source": source}))
    am.add_relationship(Relationship(source="ac_orders", target="ai_orders", relationship_type="Composition", identifier="rel-c"))
    am.add_relationship(Relationship(source="ac_orders", target="as_orders", relationship_type="Realization", identifier="rel-r"))
    graph = _graph(
        [
            {"id": "module::r::r", "path": "r", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "unit::r::orders", "path": "r/orders", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    assert result.success and result.relationships_created == 2
    levels = {e.identifier: e.properties.get("levels") for e in am.get_elements()}
    assert levels == {"ac_sys": ["enterprise"], "ac_orders": ["solution"], "ai_orders": ["solution"], "as_orders": ["enterprise"]}
    relationships = {(r.source, r.relationship_type, r.target): r.properties for r in am.get_relationships()}
    # The roll-up joins the enterprise system and the solution unit: a cross-level link
    assert relationships[("ac_sys", "Composition", "ac_orders")] | {} == {"derived_from": "roll_up", "levels": [], "cross_level": True}
    # The system realizes the unit's service at the enterprise level; the unit's own realization is kept, across levels
    assert relationships[("ac_sys", "Realization", "as_orders")]["levels"] == ["enterprise"]
    assert (relationships[("ac_orders", "Realization", "as_orders")]["levels"], relationships[("ac_orders", "Realization", "as_orders")]["cross_level"]) == ([], True)
    assert relationships[("ac_orders", "Composition", "ai_orders")]["levels"] == ["solution"]


def test_a_second_run_adds_nothing_twice(am):
    am.add_element(Element(name="s", element_type="ApplicationComponent", identifier="ac_sys", properties={"source": "module::r::r"}))
    am.add_element(Element(name="o", element_type="ApplicationComponent", identifier="ac_orders", properties={"source": "unit::r::orders"}))
    graph = _graph(
        [
            {"id": "module::r::r", "path": "r", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "unit::r::orders", "path": "r/orders", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )

    run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)
    again = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    assert again.relationships_created == 0 and len(am.get_relationships()) == 1


def test_the_type_table_is_required():
    result = run_refine_step("abstraction_levels", archimate_manager=MagicMock(), graph_manager=MagicMock(), params={})

    assert not result.success and "types" in result.errors[0]
