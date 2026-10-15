"""The ArchiMate convention checklist on hand-made run snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from deriva.modules.analysis.conventions import check_runs, render_review, render_summary

CONVENTIONS = json.loads((Path(__file__).parents[3] / "packages/deriva-dev/src/deriva/bench/data/conventions.json").read_text(encoding="utf-8"))


def _el(identifier: str, element_type: str, name: str, source: str = "") -> dict:
    return {"identifier": identifier, "type": element_type, "name": name, "source": source or f"dir::r::{identifier}"}


def _rel(source: str, kind: str, target: str) -> dict:
    return {"source": source, "type": kind, "target": target}


def _snapshot(elements: list[dict], relationships: list[dict]) -> dict:
    return {"elements": elements, "relationships": relationships, "disabled": []}


def _status(result: dict, check: str) -> str:
    return next(c["status"] for c in result["checks"] if c["check"] == check)


def _hits(result: dict, check: str) -> list[str]:
    return next(c["items"] for c in result["checks"] if c["check"] == check)


BASE = [
    _el("ac_shop", "ApplicationComponent", "Shop"),
    _el("ai_shop_rest", "ApplicationInterface", "Shop HTTP API"),
    _el("as_ordering", "ApplicationService", "Ordering"),
    _el("bo_order", "BusinessObject", "Order", "concept::r::order"),
    _el("do_order", "DataObject", "Order", "typedef::r::src/Order.java::Order"),
]
BASE_RELS = [
    _rel("ac_shop", "Composition", "ai_shop_rest"),
    _rel("ac_shop", "Realization", "as_ordering"),
    _rel("do_order", "Realization", "bo_order"),
    _rel("as_ordering", "Access", "do_order"),
]


def test_a_model_that_follows_the_conventions_fails_nothing():
    result = check_runs({"run1": _snapshot(BASE, BASE_RELS)}, CONVENTIONS)["run1"]

    assert [c["check"] for c in result["checks"] if c["status"] == "fail"] == []
    # Too small for a mid-sized repository, so the size bands only warn
    assert _status(result, "size: total") == "warn"


def test_forbidden_names_fail_with_the_element():
    elements = [
        *BASE,
        _el("nd_app", "Node", "Application Server", "tech::r::java"),
        _el("do_x", "DataObject", "Customer Id"),
        _el("do_y", "DataObject", "settings.yaml", "file::r::settings.yaml"),
        _el("nd_d", "Node", "Dockerfile", "file::r::Dockerfile"),
        _el("sw_py", "SystemSoftware", "Python", "tech::r::python"),
        _el("sw_rt", "SystemSoftware", "Java Runtime", "tech::r::java"),
    ]

    result = check_runs({"run1": _snapshot(elements, BASE_RELS)}, CONVENTIONS)["run1"]
    hits = _hits(result, "forbidden patterns")

    joined = " | ".join(hits)
    assert "Application Server" in joined and "Customer Id" in joined and "settings.yaml" in joined and "Dockerfile" in joined
    assert "Python" in joined and "Java Runtime" not in joined
    assert _status(result, "forbidden patterns") == "fail"


def test_any_technology_service_and_any_orphan_fail():
    elements = [*BASE, _el("ts_store", "TechnologyService", "Data Storage", "tech::r::db"), _el("ac_lonely", "ApplicationComponent", "Lonely")]

    result = check_runs({"run1": _snapshot(elements, BASE_RELS)}, CONVENTIONS)["run1"]

    assert _status(result, "technology services") == "fail" and _hits(result, "technology services") == ["Data Storage"]
    assert _status(result, "unconnected elements") == "fail"
    assert {"Data Storage", "Lonely"} <= {h.split(" (")[0] for h in _hits(result, "unconnected elements")}


def test_exact_duplicates_fail_and_spelling_variants_only_warn():
    elements = [
        *BASE,
        _el("sw_mq", "SystemSoftware", "ActiveMQ", "tech::r::activemq"),
        _el("sw_mq2", "SystemSoftware", "Apache ActiveMQ", "tech::r::apacheactivemq"),
        _el("ac_mgmt", "ApplicationComponent", "Customer Management", "dir::r::a"),
        _el("ac_mgmt2", "ApplicationComponent", "Customer-Management", "dir::r::b"),
        _el("bo_customer", "BusinessObject", "Customer", "concept::r::customer"),
        _el("do_customer", "DataObject", "Customer", "typedef::r::Customer"),
        _el("sw_shop", "SystemSoftware", "Shop", "tech::r::shop"),
    ]

    result = check_runs({"run1": _snapshot(elements, BASE_RELS)}, CONVENTIONS)["run1"]

    exact = " | ".join(_hits(result, "exact duplicates"))
    assert "Customer Management" in exact  # same name key within a type
    assert "Customer" in exact and "no Realization" in exact  # business and data object of one name, unlinked
    assert "Shop" in exact  # a component and system software of one name
    assert "Order" not in exact  # the same-named pair that is linked by a Realization is fine
    assert _status(result, "exact duplicates") == "fail"
    assert _status(result, "spelling variants") == "warn" and any("ActiveMQ" in h for h in _hits(result, "spelling variants"))


def test_the_same_name_across_any_two_types_is_an_exact_duplicate():
    """An interface named like its component, or a service like a function, is one name for two things."""
    elements = [
        *BASE,
        _el("ac_batch", "ApplicationComponent", "Ledger Batch", "unit::r::batch"),
        _el("ai_batch", "ApplicationInterface", "Ledger Batch", "unit::r::batch"),
        _el("as_billing", "ApplicationService", "Billing", "unit::r::billing"),
        _el("bf_billing", "BusinessFunction", "Billing", "concept::r::billing"),
    ]

    result = check_runs({"run1": _snapshot(elements, BASE_RELS)}, CONVENTIONS)["run1"]

    exact = _hits(result, "exact duplicates")
    assert "Ledger Batch: ApplicationComponent and ApplicationInterface" in exact
    assert "Billing: ApplicationService and BusinessFunction" in exact
    assert not any(h.startswith("Order") for h in exact)  # a data object realizing its business object stays fine


def test_more_than_one_interface_per_component_and_channel_fails():
    elements = [*BASE, _el("ai_shop_rest2", "ApplicationInterface", "Shop Orders HTTP API"), _el("ai_shop_web", "ApplicationInterface", "Shop Web UI")]
    rels = [*BASE_RELS, _rel("ac_shop", "Composition", "ai_shop_rest2"), _rel("ac_shop", "Composition", "ai_shop_web")]

    result = check_runs({"run1": _snapshot(elements, rels)}, CONVENTIONS)["run1"]

    assert _status(result, "interfaces per component and channel") == "fail"
    assert _hits(result, "interfaces per component and channel") == ["Shop · REST: Shop HTTP API, Shop Orders HTTP API"]


def test_a_channel_is_matched_on_a_whole_word():
    """A name ending in "interest" is no REST interface."""
    elements = [*BASE, _el("ai_shop_interest", "ApplicationInterface", "Shop Interest")]
    rels = [*BASE_RELS, _rel("ac_shop", "Composition", "ai_shop_interest")]

    result = check_runs({"run1": _snapshot(elements, rels)}, CONVENTIONS)["run1"]

    assert _status(result, "interfaces per component and channel") == "pass"


def test_interfaces_without_a_component_are_not_one_component():
    elements = [*BASE, _el("ai_a", "ApplicationInterface", "Billing HTTP API"), _el("ai_b", "ApplicationInterface", "Ledger HTTP API")]
    rels = [*BASE_RELS, _rel("ai_a", "Serving", "as_ordering"), _rel("ai_b", "Serving", "as_ordering")]

    result = check_runs({"run1": _snapshot(elements, rels)}, CONVENTIONS)["run1"]

    assert _status(result, "interfaces per component and channel") == "pass"


def test_data_objects_must_realize_a_business_object_and_nodes_need_a_deployment_unit():
    elements = [
        *BASE,
        _el("do_loose", "DataObject", "Shipment"),
        _el("nd_unit", "Node", "Shop Service", "deploy::r::shop"),
        _el("nd_file", "Node", "Shop Host", "file::r::Dockerfile"),
    ]
    rels = [*BASE_RELS, _rel("as_ordering", "Access", "do_loose"), _rel("nd_unit", "Assignment", "ac_shop"), _rel("nd_file", "Assignment", "ac_shop")]

    result = check_runs({"run1": _snapshot(elements, rels)}, CONVENTIONS)["run1"]

    assert _hits(result, "data objects without a business object") == ["Shipment"]
    assert _hits(result, "nodes without a deployment unit") == ["Shop Host (file)"]
    assert _status(result, "data objects without a business object") == "fail" and _status(result, "nodes without a deployment unit") == "fail"


def test_business_behaviour_is_reported_with_its_source_kind_only():
    elements = [*BASE, _el("bp_pay", "BusinessProcess", "Pay Order", "concept::r::pay order"), _el("be_paid", "BusinessEvent", "Order Paid", "typedef::r::OrderPaid")]
    rels = [*BASE_RELS, _rel("as_ordering", "Serving", "bp_pay"), _rel("be_paid", "Triggering", "bp_pay")]

    result = check_runs({"run1": _snapshot(elements, rels)}, CONVENTIONS)["run1"]

    assert _status(result, "business behaviour evidence") == "info"
    assert _hits(result, "business behaviour evidence") == ["Order Paid (BusinessEvent, structural)", "Pay Order (BusinessProcess, concept)"]


def test_stability_marks_each_element_with_the_runs_it_appears_in_and_the_views_render():
    runs = {"run1": _snapshot(BASE, BASE_RELS), "run2": _snapshot(BASE[:-1], BASE_RELS[:-1]), "run3": _snapshot(BASE, BASE_RELS)}

    results = check_runs(runs, CONVENTIONS)
    review = render_review("r", "m", results, runs)
    summary = render_summary({"r": results})

    assert "| Order | typedef::r::src/Order.java::Order | 2 | 2/3 |" in review
    assert "## Checklist" in review and "| check | run1 | run2 | run3 |" in review
    assert summary.startswith("| repository |") and "| r |" in summary
