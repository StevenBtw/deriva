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


def test_an_interface_in_one_built_module_is_composed_by_that_module_instead_of_its_unit(am):
    """The root unit builds the system and a frontend module: its web interface, whose member file is the frontend's,
    moves to the frontend module (the unit reaches it through its roll-up); its commands stay with the unit."""
    for identifier, element_type, source, sources in (
        ("ac_sys", "ApplicationComponent", "module::r::r", None),
        ("ac_web", "ApplicationComponent", "module::r::web", None),
        ("ac_unit", "ApplicationComponent", "unit::r::r::cli", None),
        ("ai_web", "ApplicationInterface", "unit::r::r::cli", ["file::r::web_index.html"]),
        ("ai_cli", "ApplicationInterface", "unit::r::r::cli", ["method::r::cli.main"]),
    ):
        am.add_element(Element(name=identifier, element_type=element_type, identifier=identifier, properties={"source": source, "sources": sources}))
    am.add_relationship(Relationship(source="ac_unit", target="ai_web", relationship_type="Composition", identifier="rel-w"))
    am.add_relationship(Relationship(source="ac_unit", target="ai_cli", relationship_type="Composition", identifier="rel-c"))
    answers = {
        "isSystem": [
            {"id": "module::r::r", "path": "r", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "module::r::web", "path": "r/web", "labels": ["Graph", "BuildModule"], "system": False},
            {"id": "unit::r::r::cli", "path": "r", "labels": ["Graph", "DeployableUnit"], "system": None},
        ],
        "u.active": [{"id": "unit::r::r::cli", "path": "r", "labels": ["Graph", "DeployableUnit"]}],
        "BUILDS": [{"unit": "unit::r::r::cli", "module": "module::r::r"}, {"unit": "unit::r::r::cli", "module": "module::r::web"}],
        "INCLUDES": [{"module": "module::r::r", "path": "r/cli.py"}, {"module": "module::r::web", "path": "r/web/index.html"}],
        "filePath": [{"id": "file::r::web_index.html", "path": "r/web/index.html"}, {"id": "method::r::cli.main", "path": "r/cli.py"}],
    }
    graph = MagicMock()
    graph.query.side_effect = lambda query, params=None: next(rows for key, rows in answers.items() if key in query)

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    assert result.success and result.report["interfaces_moved"] == 1
    compositions = {(r.source, r.target): r for r in am.get_relationships() if r.relationship_type == "Composition"}
    assert ("ac_unit", "ai_web") not in compositions
    assert compositions[("ac_web", "ai_web")].properties["derived_from"] == "interface_owner"
    assert compositions[("ac_web", "ai_web")].properties["levels"] == ["solution"]
    assert ("ac_unit", "ai_cli") in compositions
    # Run again: nothing moves twice
    again = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)
    assert again.report["interfaces_moved"] == 0 and again.relationships_created == 0


def test_a_roll_up_replaces_the_reverse_composition_so_no_two_components_compose_each_other(am):
    """Containment let the unit compose the system at its folder; at one folder the system holds the unit."""
    am.add_element(Element(name="m", element_type="ApplicationComponent", identifier="ac_mod", properties={"source": "module::r::web"}))
    am.add_element(Element(name="u", element_type="ApplicationComponent", identifier="ac_unit", properties={"source": "unit::r::web"}))
    am.add_relationship(Relationship(source="ac_unit", target="ac_mod", relationship_type="Composition", identifier="rel-x", properties={"derived_from": "containment"}))
    graph = _graph(
        [
            {"id": "module::r::web", "path": "r/web", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "unit::r::web", "path": "r/web", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    assert [(r.source, r.relationship_type, r.target) for r in am.get_relationships()] == [("ac_mod", "Composition", "ac_unit")]
    assert result.report["reversed"] == 1


def test_the_only_unit_at_a_module_folder_composes_the_module_and_containment_agrees(am):
    """A unit and a build module share a folder: the unit composes the module (the containment Composition stays)."""
    am.add_element(Element(name="m", element_type="ApplicationComponent", identifier="ac_mod", properties={"source": "module::r::web"}))
    am.add_element(Element(name="u", element_type="ApplicationComponent", identifier="ac_unit", properties={"source": "unit::r::web"}))
    am.add_relationship(Relationship(source="ac_unit", target="ac_mod", relationship_type="Composition", identifier="rel-x", properties={"derived_from": "containment"}))
    graph = _graph(
        [
            {"id": "module::r::web", "path": "r/web", "labels": ["Graph", "BuildModule"], "system": False},
            {"id": "unit::r::web", "path": "r/web", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    assert [(r.source, r.relationship_type, r.target, r.identifier) for r in am.get_relationships()] == [("ac_unit", "Composition", "ac_mod", "rel-x")]
    assert result.report["reversed"] == 0 and result.relationships_created == 0
    levels = {e.identifier: e.properties.get("levels") for e in am.get_elements()}
    assert levels == {"ac_unit": ["enterprise", "solution"], "ac_mod": ["solution"]}


def test_a_composition_from_a_component_to_one_of_its_ancestors_is_removed(am):
    """Containment let a unit compose the system two levels above it (the unit's files lie in the system's folder)."""
    for identifier, source in (("ac_sys", "module::r::r"), ("ac_mod", "module::r::pkg"), ("ac_unit", "unit::r::pkg::x"), ("ac_unit2", "unit::r::pkg::y")):
        am.add_element(Element(name=identifier, element_type="ApplicationComponent", identifier=identifier, properties={"source": source}))
    am.add_relationship(Relationship(source="ac_unit", target="ac_sys", relationship_type="Composition", identifier="rel-x", properties={"derived_from": "containment"}))
    graph = _graph(
        [
            {"id": "module::r::r", "path": "r", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "module::r::pkg", "path": "r/pkg", "labels": ["Graph", "BuildModule"], "system": False},
            {"id": "unit::r::pkg::x", "path": "r/pkg", "labels": ["Graph", "DeployableUnit"], "system": None},
            {"id": "unit::r::pkg::y", "path": "r/pkg", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    compositions = sorted((r.source, r.target) for r in am.get_relationships() if r.relationship_type == "Composition")
    assert compositions == [("ac_mod", "ac_unit"), ("ac_mod", "ac_unit2"), ("ac_sys", "ac_mod")]
    assert result.report["reversed"] == 1


def test_only_the_hierarchy_composes_one_component_into_another(am):
    """Containment let the unit compose the module nested in its module as well: the module's own module keeps it."""
    for identifier, source in (("ac_unit", "unit::r::gui"), ("ac_mod", "module::r::gui"), ("ac_src", "module::r::gui/src")):
        am.add_element(Element(name=identifier, element_type="ApplicationComponent", identifier=identifier, properties={"source": source}))
    am.add_relationship(Relationship(source="ac_unit", target="ac_mod", relationship_type="Composition", identifier="rel-a", properties={"derived_from": "containment"}))
    am.add_relationship(Relationship(source="ac_unit", target="ac_src", relationship_type="Composition", identifier="rel-b", properties={"derived_from": "containment"}))
    graph = _graph(
        [
            {"id": "unit::r::gui", "path": "r/gui", "labels": ["Graph", "DeployableUnit"], "system": None},
            {"id": "module::r::gui", "path": "r/gui", "labels": ["Graph", "BuildModule"], "system": False},
            {"id": "module::r::gui/src", "path": "r/gui/src", "labels": ["Graph", "BuildModule"], "system": False},
        ]
    )

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)

    compositions = sorted((r.source, r.target) for r in am.get_relationships() if r.relationship_type == "Composition")
    assert compositions == [("ac_mod", "ac_src"), ("ac_unit", "ac_mod")]
    assert result.report["reversed"] == 1


def _two_systems(am):
    """Two systems, each with a unit; the first unit's interface serves the second unit."""
    for identifier, element_type, source in (
        ("ac_a", "ApplicationComponent", "module::r::a"),
        ("ac_ua", "ApplicationComponent", "unit::r::a/u"),
        ("ai_ua", "ApplicationInterface", "unit::r::a/u"),
        ("ac_b", "ApplicationComponent", "module::r::b"),
        ("ac_ub", "ApplicationComponent", "unit::r::b/u"),
    ):
        am.add_element(
            Element(
                name=identifier, element_type=element_type, identifier=identifier, properties={"source": source, "role": "rest" if element_type == "ApplicationInterface" else None}
            )
        )
    am.add_relationship(Relationship(source="ac_ua", target="ai_ua", relationship_type="Composition", identifier="rel-c", properties={"derived_from": "containment"}))
    am.add_relationship(Relationship(source="ai_ua", target="ac_ub", relationship_type="Serving", identifier="rel-s", properties={"derived_from": "graph_link"}))
    return _graph(
        [
            {"id": "module::r::a", "path": "r/a", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "unit::r::a/u", "path": "r/a/u", "labels": ["Graph", "DeployableUnit"], "system": None},
            {"id": "module::r::b", "path": "r/b", "labels": ["Graph", "BuildModule"], "system": True},
            {"id": "unit::r::b/u", "path": "r/b/u", "labels": ["Graph", "DeployableUnit"], "system": None},
        ]
    )


def test_the_structure_stage_lifts_a_solution_relationship_to_the_enterprise_level(am):
    graph = _two_systems(am)

    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params={**PARAMS, "stage": "structure"})

    lifted = [r for r in am.get_relationships() if (r.properties or {}).get("derived_from") == "lifted"]
    assert [(r.source, r.relationship_type, r.target, r.properties["liftedFrom"], r.properties["levels"]) for r in lifted] == [
        ("ac_a", "Serving", "ac_b", ["rel-s"], ["enterprise"])
    ]
    assert result.report["lifted"] == 1


def test_the_default_stage_lifts_nothing_and_the_annotate_stage_only_tags(am):
    graph = _two_systems(am)
    run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params=PARAMS)
    assert not [r for r in am.get_relationships() if (r.properties or {}).get("derived_from") == "lifted"]

    am.clear_model()
    graph = _two_systems(am)
    before = sorted((r.source, r.relationship_type, r.target) for r in am.get_relationships())
    result = run_refine_step("abstraction_levels", archimate_manager=am, graph_manager=graph, params={**PARAMS, "stage": "annotate"})

    assert sorted((r.source, r.relationship_type, r.target) for r in am.get_relationships()) == before
    assert result.relationships_created == 0 and {e.identifier: e.properties.get("levels") for e in am.get_elements()}["ac_ua"] == ["solution"]


def test_an_unknown_stage_is_refused():
    result = run_refine_step("abstraction_levels", archimate_manager=MagicMock(), graph_manager=MagicMock(), params={**PARAMS, "stage": "later"})

    assert not result.success and "stage" in result.errors[0]
