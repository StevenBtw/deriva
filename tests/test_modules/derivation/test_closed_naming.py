"""Closed-set naming: a unit's component takes one of its structural name candidates; the LLM only chooses."""

from __future__ import annotations

import json
from types import SimpleNamespace

from deriva.modules.derivation.base import Candidate, NamingConfig, build_choice_prompt, choice_schema
from tests.test_modules.derivation.test_roles import Derivation

NAMING = NamingConfig(instruction="NAME FREELY", choose_instruction="CHOOSE ONE")


def _unit(*names: str) -> Candidate:
    return Candidate(
        node_id="unit::r::app::online",
        name="app Online",
        labels=["Graph", "DeployableUnit"],
        properties={"path": "r/app", "unitKind": "online", "nameCandidates": list(names), "nameSources": ["mainframe"] * len(names)},
    )


def _name(candidate: Candidate, answer: str | None = None) -> tuple[dict, list[tuple[str, dict]]]:
    calls: list[tuple[str, dict]] = []

    def llm(prompt: str, schema: dict, **kwargs):
        calls.append((prompt, schema))
        return SimpleNamespace(content=json.dumps({"name": answer}))

    element = {"name": "App Online", "properties": {}}
    Derivation()._apply_naming(element, candidate, NAMING, llm, {}, "r", [], {})
    return element, calls


def test_the_prompt_lists_the_candidates_in_order_after_the_instruction():
    source = {"kind": "DeployableUnit", "name": "app Online", "unit_kind": "online"}

    prompt = build_choice_prompt(source, "ApplicationComponent", "CHOOSE ONE", ["Shop Online", "Shop App Online"])

    assert prompt.startswith("CHOOSE ONE")
    assert prompt.index('"Shop Online"') < prompt.index('"Shop App Online"') and '"unit_kind":"online"' in prompt


def test_the_schema_is_a_closed_enum_of_the_candidates():
    schema = choice_schema(["Shop Online", "Shop App Online"])

    assert schema["strict"] is True and schema["schema"]["properties"]["name"] == {"type": "string", "enum": ["Shop Online", "Shop App Online"]}


def test_one_candidate_is_the_name_without_a_call():
    element, calls = _name(_unit("Shop Online"))

    assert element["name"] == "Shop Online" and element["properties"]["structure_name"] == "App Online"
    assert calls == []


def test_several_candidates_are_chosen_from_with_the_choice_instruction():
    element, calls = _name(_unit("Shop Online", "Mainframe Card Management Online"), answer="Mainframe Card Management Online")

    assert element["name"] == "Mainframe Card Management Online"
    ((prompt, schema),) = calls
    assert prompt.startswith("CHOOSE ONE") and "NAME FREELY" not in prompt
    assert schema["schema"]["properties"]["name"]["enum"] == ["Shop Online", "Mainframe Card Management Online"]


def test_an_answer_outside_the_set_falls_back_to_the_first_candidate():
    element, _ = _name(_unit("Shop Online", "Shop App Online"), answer="Card Demo Online System")

    assert element["name"] == "Shop Online"


def test_a_candidate_another_element_took_is_passed_over():
    calls: list[str] = []

    def llm(prompt, schema, **kwargs):
        calls.append(prompt)
        return SimpleNamespace(content=json.dumps({"name": "Shop Online"}))

    element = {"name": "App Online", "properties": {}}
    Derivation()._apply_naming(element, _unit("Shop Online", "Shop App Online"), NAMING, llm, {}, "r", ["Shop Online"], {})

    # Only one candidate is still free: no call
    assert element["name"] == "Shop App Online" and calls == []


def test_a_name_chosen_by_a_call_is_marked_and_a_single_candidate_is_not():
    """For the origin split: an element whose name an LLM call chose depends on the LLM."""
    chosen, _ = _name(_unit("Shop Online", "Mainframe Card Management Online"), answer="Mainframe Card Management Online")
    single, _ = _name(_unit("Shop Online"))

    assert chosen["properties"]["name_choice"] is True
    assert single["properties"]["name_choice"] is False


def test_the_full_candidate_list_is_kept_in_order_next_to_the_name():
    """Every closed-set name keeps all its candidates, a taken one included, so a reviewer sees what was chosen from."""
    chosen, _ = _name(_unit("Shop Online", "Mainframe Card Management Online"), answer="Mainframe Card Management Online")
    single, _ = _name(_unit("Shop Online"))
    element = {"name": "App Online", "properties": {}}
    Derivation()._apply_naming(element, _unit("Shop Online", "Shop App Online"), NAMING, lambda *a, **k: None, {}, "r", ["Shop Online"], {})

    assert chosen["properties"]["name_candidates"] == ["Shop Online", "Mainframe Card Management Online"]
    assert single["properties"]["name_candidates"] == ["Shop Online"]
    # One candidate is taken: no call (name_choice False), but both stay listed
    assert element["properties"]["name_candidates"] == ["Shop Online", "Shop App Online"] and element["properties"]["name_choice"] is False


def _sourced(*pairs: tuple[str, str]) -> Candidate:
    return Candidate(
        node_id="unit::r::shop",
        name="shop",
        labels=["Graph", "DeployableUnit"],
        properties={"path": "r/shop", "unitKind": "container", "nameCandidates": [n for n, _ in pairs], "nameSources": [s for _, s in pairs]},
    )


def test_with_a_source_order_a_declared_name_beats_a_documented_one_without_a_call():
    import dataclasses

    naming = dataclasses.replace(NAMING, source_order=("manifest", "mainframe", "readme", "docs", "structure"))
    candidate = _sourced(("Shop Server", "readme"), ("Online Shop", "docs"), ("Shop", "manifest"), ("Shop Core", "structure"))
    calls: list[str] = []

    element = {"name": "Shop", "properties": {}}
    Derivation()._apply_naming(element, candidate, naming, lambda p, s, **k: calls.append(p), {}, "r", [], {})

    assert element["name"] == "Shop" and calls == []
    assert element["properties"]["name_candidates"] == ["Shop Server", "Online Shop", "Shop", "Shop Core"]  # as extracted, for review


def test_with_a_source_order_the_first_of_a_source_wins_and_a_taken_one_is_passed_over():
    import dataclasses

    naming = dataclasses.replace(NAMING, source_order=("manifest", "readme", "structure"))
    candidate = _sourced(("Shop Server", "readme"), ("Shop Portal", "readme"), ("Shop Core", "structure"))

    first = {"name": "Shop", "properties": {}}
    Derivation()._apply_naming(first, candidate, naming, lambda p, s, **k: None, {}, "r", [], {})
    second = {"name": "Shop", "properties": {}}
    Derivation()._apply_naming(second, candidate, naming, lambda p, s, **k: None, {}, "r", ["Shop Server"], {})

    assert (first["name"], second["name"]) == ("Shop Server", "Shop Portal")
