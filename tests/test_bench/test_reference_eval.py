"""Evaluation against a reference model: elements match on type and name (or alias) or on their structural
lineage; relationships on mapped ends, type and direction; chains step by step."""

from __future__ import annotations

import json

from deriva.bench.reference_eval import evaluate, evaluate_session, parse_reference

REFERENCE = {
    "repository": "shop",
    "elements": [
        {"key": "core", "type": "ApplicationComponent", "name": "Customer Core", "lineage": ["unit::shop::core"]},
        {"key": "web", "type": "ApplicationComponent", "name": "Web Shop", "aliases": ["Shop Frontend"]},
        {"key": "core-api", "type": "ApplicationInterface", "name": "Customer Core API", "lineage": ["ai_core__rest"]},
        {"key": "customer-data", "type": "DataObject", "name": "Customer Data", "lineage": ["entity::shop::customer", "entity::shop::address"]},
        {"key": "support", "type": ["BusinessFunction", "BusinessProcess"], "name": "Customer Support"},
        {"key": "messaging", "type": "TechnologyService", "name": "Messaging", "optional": True},
    ],
    "relationships": [
        {"source": "core-api", "target": "web", "type": "Serving", "kind": "cooperation"},
        {"source": "core", "target": "core-api", "type": "Composition", "kind": "composition"},
        {"source": "core", "target": "customer-data", "type": "Access", "kind": "access"},
    ],
    "chains": [{"name": "web uses core", "steps": [["core", "Composition", "core-api"], ["core-api", "Serving", "web"]]}],
}


def _model(elements, relationships=()):
    return {
        "elements": [{"identifier": i, "type": t, "name": n, "source": s} for i, t, n, s in elements],
        "relationships": [{"source": a, "target": b, "type": t, "derived_from": "rule"} for a, t, b in relationships],
    }


def test_elements_match_on_name_alias_or_lineage_and_splits_are_counted():
    model = _model(
        [
            ("ac_core", "ApplicationComponent", "Core Service", "unit::shop::core"),  # lineage
            ("ac_web", "ApplicationComponent", "Shop Frontend", "unit::shop::web"),  # alias
            ("ac_admin", "ApplicationComponent", "Admin", "unit::shop::admin"),  # extra
            ("do_customer", "DataObject", "Customer", "entity::shop::customer"),
            ("do_address", "DataObject", "Address", "entity::shop::address"),  # a split of Customer Data
            ("bp_support", "BusinessProcess", "customer support", "concept::shop::support"),  # one of the allowed types
        ]
    )

    result = evaluate(parse_reference(REFERENCE), model)

    components = result["elements"]["ApplicationComponent"]
    assert (components["covered"], components["required"], components["mapped"], components["model"]) == (2, 2, 2, 3)
    assert components["extra"] == ["Admin"]
    data = result["elements"]["DataObject"]
    assert (data["covered"], data["mapped"], data["splits"]) == (1, 2, {"Customer Data": 2})
    assert result["elements"]["BusinessFunction"]["covered"] == 1  # the reference element's first type
    assert result["elements"]["ApplicationInterface"]["missing"] == ["Customer Core API"]
    assert result["optional"] == {"total": 1, "covered": 0, "names": ["Messaging"]}  # outside recall, reported


def test_internal_behaviour_matches_across_its_types_within_a_layer_by_name_and_lineage():
    """A derived function covers a reference process of its layer (user, 2026-10-19), never one of another layer."""
    reference = parse_reference(
        {
            "repository": "shop",
            "elements": [
                {"key": "order", "type": "BusinessProcess", "name": "Order Goods"},
                {"key": "post", "type": "ApplicationProcess", "name": "Post Transactions", "lineage": ["file::shop::batch/post.cbl"]},
                {"key": "pay", "type": "BusinessProcess", "name": "Pay Bill"},
            ],
            "relationships": [],
            "chains": [],
        }
    )
    model = _model(
        [
            ("bf_order", "BusinessFunction", "Order Goods", "concept::shop::order"),  # by name
            ("af_post", "ApplicationFunction", "Posting", "file::shop::batch/post.cbl"),  # by lineage
            ("af_pay", "ApplicationFunction", "Pay Bill", "file::shop::pay.cbl"),  # another layer
        ]
    )

    result = evaluate(reference, model)

    assert result["elements"]["BusinessProcess"]["covered"] == 1
    assert result["elements"]["BusinessProcess"]["missing"] == ["Pay Bill"]
    assert result["elements"]["ApplicationProcess"]["covered"] == 1


def test_relationships_match_on_mapped_ends_type_and_direction_and_chains_step_by_step():
    elements = [
        ("ac_core", "ApplicationComponent", "Customer Core", "unit::shop::core"),
        ("ac_web", "ApplicationComponent", "Web Shop", "unit::shop::web"),
        ("ai_core__rest", "ApplicationInterface", "Core REST API", "unit::shop::core"),
        ("ac_other", "ApplicationComponent", "Other", "unit::shop::other"),
    ]
    model = _model(elements, [("ac_core", "Composition", "ai_core__rest"), ("ac_web", "Serving", "ai_core__rest"), ("ac_other", "Serving", "ac_web")])

    result = evaluate(parse_reference(REFERENCE), model)

    rels = result["relationships"]
    assert (rels["composition"]["matched"], rels["composition"]["required"]) == (1, 1)
    assert rels["cooperation"]["matched"] == 0  # drawn the wrong way round
    assert rels["cooperation"]["missing"] == ["Customer Core API -Serving-> Web Shop"]
    assert result["relationship_totals"]["assessable"] == 2 and result["relationship_totals"]["correct"] == 1  # ac_other is unmapped
    assert result["relationship_totals"]["unassessable"] == 1
    assert result["chains"] == [{"name": "web uses core", "steps": 2, "present": 1, "complete": False}]


def test_a_session_is_evaluated_per_repository_and_run_with_the_mean(tmp_path):
    models = tmp_path / "bench_x" / "models"
    models.mkdir(parents=True)
    for run, name in ((1, "Customer Core"), (2, "Something Else")):
        model = _model([("ac_core", "ApplicationComponent", name, "unit::shop::other")])
        (models / f"shop_m1_run{run}.json").write_text(json.dumps(model), encoding="utf-8")
    (models / "elsewhere_m1_run1.json").write_text(json.dumps(_model([])), encoding="utf-8")  # no reference: skipped
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "shop.json").write_text(json.dumps(REFERENCE), encoding="utf-8")

    payload = evaluate_session(tmp_path / "bench_x", refs)

    shop = payload["repositories"]["shop"]
    assert [r["run"] for r in shop["runs"]] == [1, 2]
    assert [r["elements"]["ApplicationComponent"]["covered"] for r in shop["runs"]] == [1, 0]
    assert shop["mean"]["element_recall"] == round((1 / 5 + 0 / 5) / 2, 3)  # 5 required reference elements
    assert set(payload["repositories"]) == {"shop"}


def test_the_reference_command_prints_a_table_and_writes_the_summary_and_a_page_per_repository(tmp_path):
    from typer.testing import CliRunner

    from deriva.cli.cli import app

    session = tmp_path / "benchmarks" / "bench_x"
    (session / "models").mkdir(parents=True)
    model = _model([("ac_core", "ApplicationComponent", "Customer Core", "unit::shop::core")])
    (session / "models" / "shop_m1_run1.json").write_text(json.dumps(model), encoding="utf-8")
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "shop.json").write_text(json.dumps(REFERENCE), encoding="utf-8")
    out = tmp_path / "out"

    result = CliRunner().invoke(app, ["benchmark", "reference", "bench_x", "--benchmarks", str(tmp_path / "benchmarks"), "--references", str(refs), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert "shop" in result.output and "ApplicationComponent" in result.output
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["repositories"]["shop"]["runs"][0]["elements"]["ApplicationComponent"]["covered"] == 1
    assert "Missing" in (out / "shop.md").read_text(encoding="utf-8")


def test_naming_compares_the_chosen_and_the_structural_name_with_the_reference_by_lineage():
    """Per named type, how often the LLM-chosen name and the structural name match the reference element the
    element's lineage maps to (normalized, and with aliases); elements without lineage or structure name are left out."""
    reference = {
        "repository": "shop",
        "elements": [
            {"key": "core", "type": "ApplicationComponent", "name": "Customer Core", "lineage": ["unit::shop::core"]},
            {"key": "web", "type": "ApplicationComponent", "name": "Web Shop", "aliases": ["Shop Frontend"], "lineage": ["unit::shop::web"]},
            {"key": "orders", "type": "ApplicationComponent", "name": "Order Service", "lineage": ["unit::shop::orders"]},
        ],
    }
    model = _model(
        [
            ("ac_core", "ApplicationComponent", "Customer Core", "unit::shop::core"),
            ("ac_web", "ApplicationComponent", "Shop Frontend", "unit::shop::web"),
            ("ac_orders", "ApplicationComponent", "Orders", "unit::shop::orders"),
            ("ac_none", "ApplicationComponent", "Admin", "unit::shop::admin"),  # no reference element by lineage
        ]
    )
    structure = {"ac_core": "Core", "ac_web": "Web Shop", "ac_orders": "Order Service"}
    for e in model["elements"]:
        if e["identifier"] in structure:
            e["structure_name"] = structure[e["identifier"]]

    naming = evaluate(parse_reference(reference), model)["naming"]["ApplicationComponent"]

    assert naming == {"compared": 3, "chosen": 1, "chosen_alias": 2, "structural": 2, "structural_alias": 2}


LEVELED = {
    "repository": "shop",
    "elements": [
        {"key": "core", "type": "ApplicationComponent", "name": "Customer Core", "levels": ["enterprise", "solution"]},
        {"key": "web", "type": "ApplicationComponent", "name": "Web Shop"},  # no levels: enterprise
        {"key": "lib", "type": "ApplicationComponent", "name": "Pricing Library", "levels": ["solution"]},
    ],
    "relationships": [
        {"source": "core", "target": "web", "type": "Serving", "kind": "cooperation"},
        {"source": "lib", "target": "core", "type": "Serving", "kind": "module-dependency", "levels": ["solution"]},
    ],
}


def _leveled_model():
    model = _model(
        [("ac_core", "ApplicationComponent", "Customer Core", "unit::shop::core"), ("ac_lib", "ApplicationComponent", "Pricing Library", "module::shop::lib")],
        [("ac_lib", "Serving", "ac_core")],
    )
    model["elements"][0]["levels"] = ["enterprise", "solution"]
    model["elements"][1]["levels"] = ["solution"]
    model["relationships"][0]["levels"] = ["solution"]
    return model


def test_a_level_filters_the_reference_and_the_model_and_none_keeps_todays_behaviour():
    reference, model = parse_reference(LEVELED), _leveled_model()

    enterprise = evaluate(reference, model, level="enterprise")
    solution = evaluate(reference, model, level="solution")

    # Enterprise: core and web are required, only core is derived at that level; the library is not counted
    assert (enterprise["element_recall"], enterprise["element_precision"], enterprise["model_size"]) == (0.5, 1.0, 1)
    assert enterprise["relationship_recall"] == 0.0  # core -> web is missing
    # Solution: core and the library, both derived; the module dependency is there
    assert (solution["element_recall"], solution["element_precision"], solution["relationship_recall"]) == (1.0, 1.0, 1.0)
    # Union and None: every element and relationship, whatever its level
    union = evaluate(reference, model, level="union")
    assert (union["reference_size"], union["model_size"]) == (3, 2) and evaluate(reference, model)["reference_size"] == 3


def test_an_unknown_level_is_refused():
    import pytest

    with pytest.raises(ValueError, match="level"):
        evaluate(parse_reference(LEVELED), _leveled_model(), level="detail")


def test_a_cross_level_relationship_counts_only_in_the_union():
    """A roll-up joins an enterprise element to a solution element: no level holds both ends, so only the union scores it."""
    data = {
        "repository": "shop",
        "elements": [
            {"key": "system", "type": "ApplicationComponent", "name": "Shop System"},
            {"key": "core", "type": "ApplicationComponent", "name": "Customer Core", "levels": ["solution"]},
        ],
        "relationships": [{"source": "system", "target": "core", "type": "Composition", "kind": "roll-up", "levels": [], "cross_level": True}],
    }
    model = _model(
        [("ac_sys", "ApplicationComponent", "Shop System", "unit::shop"), ("ac_core", "ApplicationComponent", "Customer Core", "unit::shop::core")],
        [("ac_sys", "Composition", "ac_core")],
    )
    model["elements"][1]["levels"] = ["solution"]
    model["relationships"][0] |= {"levels": [], "cross_level": True}

    reference = parse_reference(data)

    assert evaluate(reference, model, level="union")["relationship_recall"] == 1.0
    assert evaluate(reference, model, level="enterprise")["relationship_recall"] is None  # nothing to find at that level
    assert evaluate(reference, model, level="solution")["relationship_totals"]["model"] == 0


def test_an_explicit_empty_level_set_is_no_level_at_all():
    """levels: [] (with cross_level) is not the enterprise default: the item belongs to no single level."""
    from deriva.bench.reference_eval import _levels_of

    assert _levels_of({}) == frozenset({"enterprise"})
    assert _levels_of({"levels": []}) == frozenset() and _levels_of({"levels": ["solution"], "cross_level": True}) == frozenset()
    data = {
        "repository": "shop",
        "elements": [{"key": "a", "type": "ApplicationComponent", "name": "A"}, {"key": "b", "type": "ApplicationComponent", "name": "B"}],
        "relationships": [{"source": "a", "target": "b", "type": "Serving", "kind": "x", "levels": [], "cross_level": True}],
    }
    model = _model([("a", "ApplicationComponent", "A", "s"), ("b", "ApplicationComponent", "B", "t")], [("a", "Serving", "b")])

    assert evaluate(parse_reference(data), model, level="enterprise")["relationship_recall"] is None
    assert evaluate(parse_reference(data), model, level="union")["relationship_recall"] == 1.0
