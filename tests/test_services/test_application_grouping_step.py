"""The application grouping step: one closed LLM choice per repository, only where structure cannot decide (no system
component, two or more top-level components); the applications chosen by two or more components are stored."""

from __future__ import annotations

import json
from types import SimpleNamespace
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
