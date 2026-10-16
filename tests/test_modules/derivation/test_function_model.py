"""Business functions from a supplied business function model: the model file (levels, parents, exclusions) and
the closed classification of the application services into it, level by level (one choice or none per service)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deriva.modules.derivation.function_model import (
    ServiceItem,
    build_function_prompt,
    classify_services,
    function_elements,
    parse_function_model,
)

FIXTURE = (Path(__file__).parent / "data" / "function_model_fixture.csv").read_text(encoding="utf-8")


def test_the_model_reads_levels_one_and_two_and_skips_notes_and_deeper_rows():
    model = parse_function_model(FIXTURE, name="fixture")

    assert [f.id for f in model.level(1)] == ["F100", "F200", "F300"]
    assert [f.id for f in model.children("F100")] == ["F110", "F120"]
    assert model.get("F120").name == "Match, clear, and settle"
    assert model.get("F311") is None  # level 3 is not read


def test_an_excluded_function_drops_with_its_children():
    model = parse_function_model(FIXTURE, name="fixture", exclude=("F200",))

    assert [f.id for f in model.level(1)] == ["F100", "F300"]
    assert model.get("F210") is None


@pytest.mark.parametrize(
    "text, problem",
    [
        ("id,name,level\nA,One,1\nA,Two,1\n", "unique"),
        ("id,name,parent,level\nA,One,,1\nB,Two,X,2\n", "parent"),
        ("id,name,parent,level\nA,One,,1\nB,Two,,2\n", "parent"),
        ("id,name,level\nA,One,one\n", "level"),
        ("name,level\nOne,1\n", "id"),
    ],
)
def test_an_invalid_model_is_an_error(text, problem):
    with pytest.raises(ValueError, match=problem):
        parse_function_model(text, name="broken")


ITEMS = [
    ServiceItem(key="as_floor", component="trading-engine", members=["BidResource", "OrderBook"], data=["Bid Data"], processes=["Bid Lifecycle"]),
    ServiceItem(key="as_members", component="member-portal", members=["MemberQuestionResource"], data=["Member Data"], processes=[]),
]


def _llm(answers: dict[int, dict[str, str]], calls: list[str]):
    """answers: level -> item key -> option id; the item keys in a prompt are s1, s2, ... in item order."""

    def query(prompt, schema, **kwargs):
        calls.append(prompt)
        level = 1 if "level 1" in prompt else 2
        keys = list(schema["schema"]["properties"]["choices"]["properties"])
        options = schema["schema"]["properties"]["choices"]["properties"][keys[0]]["enum"]
        chosen = {}
        for k in keys:
            item = next(i for i in ITEMS if f"{k}: {i.component}" in prompt)
            chosen[k] = answers[level].get(item.key, "none")
            assert chosen[k] in options
        return SimpleNamespace(content=json.dumps({"choices": chosen}))

    return query


def test_services_are_classified_level_by_level_and_none_stops_or_keeps_the_level_one_choice():
    model = parse_function_model(FIXTURE, name="fixture")
    calls: list[str] = []
    answers = {1: {"as_floor": "F100", "as_members": "F300"}, 2: {"as_floor": "F110"}}  # the member service: none at level 2

    decisions = classify_services(ITEMS, model, "Classify.", _llm(answers, calls), batch_size=10)

    assert decisions == {"as_floor": ("F100", "F110"), "as_members": ("F300", None)}
    # One level 1 batch, then one level 2 batch per chosen category
    assert len(calls) == 3
    assert "F110" in calls[1] + calls[2] and "F310" in calls[1] + calls[2]


def test_the_prompt_lists_only_the_options_of_its_level_and_only_structure():
    model = parse_function_model(FIXTURE, name="fixture")

    prompt = build_function_prompt([ITEMS[0]], model.level(1), "Classify.", "fixture", 1)

    assert "F100: Run the Trading Floor" in prompt and "F110" not in prompt
    assert "Everything that happens between a bid and a settled trade." in prompt  # the description helps the choice
    assert "BidResource" in prompt and "Bid Lifecycle" in prompt


def test_an_answer_outside_the_options_counts_as_none():
    model = parse_function_model(FIXTURE, name="fixture")

    def query(prompt, schema, **kwargs):
        keys = list(schema["schema"]["properties"]["choices"]["properties"])
        return SimpleNamespace(content=json.dumps({"choices": dict.fromkeys(keys, "F999")}))

    assert classify_services(ITEMS, model, "Classify.", query, batch_size=10) == {"as_floor": (None, None), "as_members": (None, None)}


def test_the_elements_are_the_chosen_functions_named_and_identified_by_the_model():
    model = parse_function_model(FIXTURE, name="fixture")
    decisions = {"as_floor": ("F100", "F110"), "as_floor_2": ("F100", "F120"), "as_members": ("F300", None)}
    processes = {"as_floor": ["lifecycle::r::bid"], "as_floor_2": [], "as_members": []}

    elements = {e["properties"]["source"]: e for e in function_elements(decisions, model, processes)}

    assert set(elements) == {"function::fixture::F100", "function::fixture::F110", "function::fixture::F120", "function::fixture::F300"}
    top, part = elements["function::fixture::F100"], elements["function::fixture::F110"]
    assert (top["name"], top["element_type"], top["properties"]["level"]) == ("Run the Trading Floor", "BusinessFunction", 1)
    assert sorted(top["properties"]["functions"]) == sorted([part["identifier"], elements["function::fixture::F120"]["identifier"]])
    assert top["properties"]["services"] == []  # its services serve its level 2 functions
    assert part["properties"]["services"] == ["as_floor"] and part["properties"]["processes"] == ["lifecycle::r::bid"]
    assert elements["function::fixture::F300"]["properties"]["services"] == ["as_members"]  # none at level 2: it serves level 1
