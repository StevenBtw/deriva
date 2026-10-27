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
    settle = model.get("F120")
    assert settle is not None
    assert settle.name == "Match, clear, and settle"
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
    decisions: dict[str, tuple[str | None, str | None]] = {"as_floor": ("F100", "F110"), "as_floor_2": ("F100", "F120"), "as_members": ("F300", None)}
    processes = {"as_floor": ["lifecycle::r::bid"], "as_floor_2": [], "as_members": []}

    elements = {e["properties"]["source"]: e for e in function_elements(decisions, model, processes)}

    assert set(elements) == {"function::fixture::F100", "function::fixture::F110", "function::fixture::F120", "function::fixture::F300"}
    top, part = elements["function::fixture::F100"], elements["function::fixture::F110"]
    assert (top["name"], top["element_type"], top["properties"]["level"]) == ("Run the Trading Floor", "BusinessFunction", 1)
    assert sorted(top["properties"]["functions"]) == sorted([part["identifier"], elements["function::fixture::F120"]["identifier"]])
    assert top["properties"]["services"] == []  # its services serve its level 2 functions
    assert part["properties"]["services"] == ["as_floor"] and part["properties"]["processes"] == ["lifecycle::r::bid"]
    assert elements["function::fixture::F300"]["properties"]["services"] == ["as_members"]  # none at level 2: it serves level 1


# Richer evidence (catalog v2): operations, states, interfaces, documentation and code notes, all from structure

from deriva.modules.derivation.function_model import EvidenceRules, documentation_text, header_notes, is_technical, operations_of  # noqa: E402

RULES = EvidenceRules(
    operation_patterns=(
        r"^(?:\w+\.)?(?P<verb>get|post|put|delete|patch)\(\s*[\"'](?P<path>[^\"']*)[\"']",
        r"^(?P<verb>Get|Post|Put|Delete|Patch|Request)Mapping(?:\((?:(?:value|path)\s*=\s*)?[\"'](?P<path>[^\"']*)[\"'][^)]*\))?",
        r"^(?P<verb>GET|POST|PUT|DELETE|PATCH)$",
        r"^Path\(\s*[\"'](?P<path>[^\"']*)[\"']",
    ),
    summary_patterns=(r"^Operation\(\s*summary\s*=\s*\"(?P<text>[^\"]*)\"",),
    header_fields=("function", "purpose"),
    technical_words=("auth", "login", "health", "ready", "cache", "error"),
)


def test_operations_come_from_decorators_with_the_class_path_and_the_summary():
    methods = [
        {"name": "getCustomer", "decorators": ['Operation(summary = "Get a customer.")', 'GetMapping(value = "/{id}")']},
        {"name": "create_case", "decorators": ['router.post("/cases", response_model=CaseResponse)']},
        {"name": "list", "decorators": ["GET", 'Path("/items")']},
        {"name": "helper", "decorators": []},
    ]

    ops = operations_of(methods, ["RestController", 'RequestMapping("/customers")'], RULES)

    assert ops == ["GET /customers/{id} getCustomer (Get a customer.)", "POST /customers/cases create_case", "GET /customers/items list"]


def test_header_notes_are_the_named_fields_of_the_leading_comment_block():
    cobol = (
        "      ******************************************\n"
        "      * Program:     COACTUPC.CBL               *\n"
        "      * Function:    Accept and process ACCOUNT UPDATE *\n"
        "      * Copyright Example Corp.                  \n"
        "       IDENTIFICATION DIVISION.\n"
        "      * Function: not in the leading block\n"
    )

    assert header_notes(cobol, RULES) == ["Accept and process ACCOUNT UPDATE"]
    assert header_notes('"""A module."""\nimport os\n', RULES) == []


def test_a_service_is_technical_only_when_every_operation_is():
    assert is_technical(["POST /auth/login login", "GET /ready ready"], [], RULES)
    assert not is_technical(["POST /cart/add/{id} addToCart", "GET /ready ready"], [], RULES)
    assert is_technical([], ["CacheManagerEndpoint"], RULES)  # no operations: the member names decide
    assert not is_technical([], [], RULES)


def test_documentation_is_plain_text_without_images_and_capped():
    lines = ["![Logo](logo.png) Example: Order Core", "The **Order Core** manages [orders](docs/orders.md) of the shop.", "x" * 400]

    text = documentation_text(lines, max_chars=80)

    assert text.startswith("Example: Order Core. The Order Core manages orders of the shop.") and len(text) <= 80


def test_the_prompt_shows_the_richer_evidence_of_a_service():
    model = parse_function_model(FIXTURE, name="fixture")
    item = ServiceItem(
        key="as_floor",
        component="trading-engine",
        members=["BidResource"],
        data=["Bid Data"],
        processes=["Bid Lifecycle"],
        interfaces=["rest"],
        operations=["POST /bids placeBid (Place a bid.)"],
        states=["Bid Lifecycle: PLACED"],
        documentation="The trading engine matches bids.",
        notes=["Accept and match bids"],
    )

    prompt = build_function_prompt([item], model.level(2)[:2], "Classify.", "fixture", 2)

    for text in ("s1: trading-engine", "POST /bids placeBid (Place a bid.)", "Bid Lifecycle: PLACED", "The trading engine matches bids.", "Accept and match bids", "rest"):
        assert text in prompt
    assert "Receiving and recording bids from traders." in prompt  # level-2 options carry their description


def test_component_documentation_is_its_readme_under_the_title_and_the_root_readme_lines_that_name_it():
    from deriva.modules.derivation.function_model import component_documentation

    docs = {
        "repo/README.md": "# Shop\n\n| Unit | Purpose |\n|---|---|\n| **order-core** | Keeps the orders. |\n| billing | Bills. |\n",
        "repo/order-core/README.md": "![logo](l.png)\n# Order Core\n\nThe Order Core keeps the orders of the shop.\nIt offers an HTTP API.\n\n## IDE\n\nUse any IDE.\n",
        "repo/docs/SECURITY.md": "| order-core | a finding |\n",
    }

    text = component_documentation("repo/order-core", "order-core", docs, max_chars=300)

    assert text == "The Order Core keeps the orders of the shop. It offers an HTTP API. order-core | Keeps the orders."


def test_technical_operations_are_left_out_and_repeats_keep_the_one_with_a_summary():
    from deriva.modules.derivation.function_model import shown_operations

    ops = ["GET /orders list", "GET /orders list (List the orders.)", "ANY /error handleError", "POST /orders create"]

    assert shown_operations(ops, RULES) == ["GET /orders list (List the orders.)", "POST /orders create"]


def test_a_type_with_a_path_but_no_method_operations_is_one_operation():
    rules = EvidenceRules(operation_patterns=(r"^WebServlet\([^\"']*[\"'](?P<path>[^\"']*)[\"']",))

    assert operations_of([{"name": "doGet", "decorators": []}], ['WebServlet("/cart")'], rules, type_name="CartServlet") == ["ANY /cart CartServlet"]


def test_only_the_first_root_readme_line_that_names_a_component_counts():
    from deriva.modules.derivation.function_model import component_documentation

    docs = {"repo/README.md": "| order-core | Keeps the orders. |\n| finding | order-core logs too much |\n"}

    assert component_documentation("repo/order-core", "order-core", docs, max_chars=300) == "order-core | Keeps the orders."
