"""The application grouping step: one closed LLM choice per repository, only where structure cannot decide (no system
component, two or more top-level components); the applications chosen by two or more components are stored."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element
from deriva.services import derivation


@pytest.fixture
def am():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    manager = ArchimateManager()
    manager.connect()
    yield manager
    manager.disconnect()
    close_database()


def _graph(units):
    graph = MagicMock()
    graph.query.side_effect = lambda query, params=None: (
        [{"id": f"unit::r::{u}", "path": f"r/{u}", "labels": ["Graph", "DeployableUnit"], "system": None} for u in units] if "n.id IN" in query or "u.active" in query else []
    )
    return graph


def test_the_components_the_llm_groups_become_one_application_and_the_call_sees_only_closed_candidates(am, monkeypatch):
    for unit, name in (("front", "Shop Frontend"), ("back", "Shop Backend"), ("jobs", "Nightly Jobs")):
        am.add_element(Element(name=name, element_type="ApplicationComponent", identifier=f"ac_{unit}", properties={"source": f"unit::r::{unit}"}))
    monkeypatch.setattr(derivation, "_documentation_files", lambda graph: {"r/README.md": "# Shop System - Online Store\n"})
    seen = {}

    def llm(prompt, schema, **kwargs):
        seen["enum"] = schema["schema"]["properties"]["assignments"]["properties"]["ac_front"]["enum"]
        return SimpleNamespace(content=json.dumps({"assignments": {"ac_front": "Shop System", "ac_back": "Shop System", "ac_jobs": "Nightly Jobs"}}))

    result = derivation._application_grouping_step({"kind_words": ["Frontend", "Backend"]}, "Group.", _graph(["front", "back", "jobs"]), am, llm)

    assert seen["enum"] == ["Shop System", "Online Store", "Shop", "Nightly Jobs"]
    assert [(e["name"], e["properties"]["sources"]) for e in result["created_elements"]] == [("Shop System", ["unit::r::back", "unit::r::front"])]
    assert result["grouping_decisions"] == {"ac_back": "Shop System", "ac_front": "Shop System", "ac_jobs": "Nightly Jobs"}


def test_a_system_component_or_a_single_top_level_component_makes_no_call(am):
    am.add_element(Element(name="Only", element_type="ApplicationComponent", identifier="ac_only", properties={"source": "unit::r::only"}))
    llm = MagicMock()

    result = derivation._application_grouping_step({}, "Group.", _graph(["only"]), am, llm)

    assert result["created_elements"] == [] and not llm.called


def test_an_actor_the_model_holds_already_is_reused_and_a_new_one_is_made_from_its_concept(am, monkeypatch):
    """Same name, same element: the role-derived Customer only gains the application's units; Clinician is new."""
    am.add_element(Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop", properties={"source": "unit::r::shop"}))
    am.add_element(Element(name="Customer", element_type="BusinessActor", identifier="ba_customer", properties={"source": "role::r::customer"}))
    monkeypatch.setattr(derivation, "_documentation_files", lambda graph: {"r/README.md": "# Shop\n\n## Use\n\nA customer and a clinician use the shop.\n"})
    graph = MagicMock()
    concepts = [{"id": "concept::r::customer", "name": "Customer"}, {"id": "concept::r::clinician", "name": "Clinician"}]
    graph.query.side_effect = lambda query, params=None: (
        concepts if "BusinessConcept" in query else [{"id": "unit::r::shop", "path": "r/shop", "labels": ["Graph", "DeployableUnit"], "system": None}] if "n.id IN" in query else []
    )

    def llm(prompt, schema, **kwargs):
        return SimpleNamespace(content=json.dumps({"actors": {"ac_shop": ["Customer", "Clinician"]}}))

    result = derivation._documentation_actors_step({}, "Choose.", graph, am, llm)

    assert [(e["name"], e["properties"]["sources"]) for e in result["created_elements"]] == [("Clinician", ["unit::r::shop"])]
    assert next(e for e in am.get_elements() if e.identifier == "ba_customer").properties["sources"] == ["unit::r::shop"]


def test_the_documentation_step_settings_are_read_from_their_params_key_and_checked():
    """Each documentation step reads its own params key (None for any other step) and refuses settings it cannot use."""
    assert derivation._application_grouping_config(json.dumps({"other": 1})) is None
    settings = {"kind_words": ["Backend"], "title": "first"}
    assert derivation._application_grouping_config(json.dumps({"application_grouping": settings})) == settings
    with pytest.raises(ValueError, match="params.application_grouping"):
        derivation._application_grouping_config(json.dumps({"application_grouping": {"title": "some"}}))
    assert derivation._documentation_actors_config(json.dumps({"other": 1})) is None
    assert derivation._documentation_actors_config(json.dumps({"documentation_actors": {"intro_chars": 200}})) == {"intro_chars": 200}
    with pytest.raises(ValueError, match="params.documentation_actors"):
        derivation._documentation_actors_config(json.dumps({"documentation_actors": {"intro_chars": -1}}))


def test_the_actor_step_makes_no_call_without_components_or_without_a_documented_actor(am, monkeypatch):
    llm = MagicMock()
    monkeypatch.setattr(derivation, "_documentation_files", lambda graph: {"r/README.md": "# Shop\n\nNo one is named here.\n"})

    nothing = derivation._documentation_actors_step({}, "Choose.", MagicMock(query=MagicMock(return_value=[])), am, llm)
    am.add_element(Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop", properties={"source": "unit::r::shop"}))
    graph = MagicMock()
    graph.query.side_effect = lambda query, params=None: (
        [{"id": "concept::r::customer", "name": "Customer"}]
        if "BusinessConcept" in query
        else [{"id": "unit::r::shop", "path": "r/shop", "labels": ["Graph", "DeployableUnit"], "system": None}]
        if "n.id IN" in query
        else []
    )
    unmentioned = derivation._documentation_actors_step({}, "Choose.", graph, am, llm)

    assert nothing["created_elements"] == [] and unmentioned["created_elements"] == [] and not llm.called
    assert nothing["actor_decisions"] == {} and unmentioned["actor_decisions"] == {}


def test_one_element_per_unit_needs_elements_per_unit():
    roles = {"labels": ["File"], "instruction": "Classify.", "names": {"web": "Web UI"}, "one_per_unit": True}

    with pytest.raises(ValueError, match="one_per_unit"):
        derivation._role_config(json.dumps({"roles": roles}))


def _documentation_step_cfg(name, params):
    cfg = MagicMock(step_name=name, element_type="BusinessActor", instruction="Choose.", params=json.dumps(params), input_graph_query=None, example=None)
    cfg.max_candidates = cfg.batch_size = None
    return cfg


@pytest.mark.parametrize("iterate", [False, True])
def test_both_run_paths_dispatch_the_documentation_steps_and_refuse_bad_settings(monkeypatch, iterate):
    """A row with application grouping or documentation actors settings runs that step (no candidate query needed);
    settings it cannot use skip the step with the reason."""
    result = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "created_relationships": [], "errors": []}
    grouping, actors = MagicMock(return_value=result), MagicMock(return_value=result)
    monkeypatch.setattr(derivation, "_application_grouping_step", grouping)
    monkeypatch.setattr(derivation, "_documentation_actors_step", actors)
    cfgs = [
        _documentation_step_cfg("ApplicationGrouping", {"application_grouping": {"kind_words": []}}),
        _documentation_step_cfg("DocumentationActors", {"documentation_actors": {"intro_chars": 0}}),
        _documentation_step_cfg("Broken", {"documentation_actors": {"intro_chars": "x"}}),
    ]
    from unittest.mock import patch

    with patch.object(derivation.config, "get_derivation_configs") as get:
        get.side_effect = lambda engine, enabled_only, phase: cfgs if phase == "generate" else []
        kwargs: dict[str, Any] = {"engine": MagicMock(), "graph_manager": MagicMock(), "archimate_manager": MagicMock(), "llm_query_fn": MagicMock(), "phases": ["generate"]}
        if iterate:
            messages = [u.message for u in derivation.run_derivation_iter(**kwargs) if u.status == "error"]
        else:
            messages = derivation.run_derivation(**kwargs)["errors"]

    assert grouping.call_count == 1 and actors.call_count == 1
    assert any("Missing required config for Broken" in m and "params.documentation_actors" in m for m in messages)
