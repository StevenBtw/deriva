"""Services per capability: interface members grouped by the objects they reach, across components."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from deriva.modules.derivation.component_services import ComponentServicesConfig, derive_member_services


def _el(identifier: str, element_type: str, source: str, name: str, **properties: Any) -> dict:
    return {"identifier": identifier, "name": name, "element_type": element_type, "properties": {"source": source, **properties}}


def _member(name: str, source: str) -> dict:
    return {"name": name, "source": source}


CONFIG = ComponentServicesConfig(group_by="members", member_min_names=1, overlap=0.5, max_groups=7, max_doc_lines=0)

COMPONENTS = [_el("ac_orders", "ApplicationComponent", "unit::r::orders", "Orders Backend"), _el("ac_web", "ApplicationComponent", "unit::r::web", "Shop Frontend")]
INTERFACES = [
    _el(
        "ai_orders_rest",
        "ApplicationInterface",
        "unit::r::orders",
        "Orders Backend REST API",
        members=[_member("OrderController", "file::orders_ctl"), _member("InvoiceController", "file::invoice_ctl")],
    ),
    _el(
        "ai_web_ui", "ApplicationInterface", "unit::r::web", "Shop Frontend Web UI", members=[_member("CartPage", "file::cart_page"), _member("BillingPage", "file::billing_page")]
    ),
]
OBJECTS = [
    _el("do_order", "DataObject", "typedef::order", "Order"),
    _el("do_invoice", "DataObject", "typedef::invoice", "Invoice"),
    _el("bo_cart", "BusinessObject", "concept::cart", "Cart"),
]
PATHS = {
    "file::orders_ctl": "r/orders/OrderController.java",
    "file::invoice_ctl": "r/orders/InvoiceController.java",
    "file::cart_page": "r/web/cart.js",
    "file::billing_page": "r/web/billing.js",
    "typedef::order": "r/orders/model/Order.java",
    "typedef::invoice": "r/orders/model/Invoice.java",
}
IMPORTS = [
    ("r/orders/OrderController.java", "r/orders/model/Order.java"),
    ("r/orders/InvoiceController.java", "r/orders/model/Invoice.java"),
    ("r/web/billing.js", "r/orders/model/Invoice.java"),
]
CODE_NAMES = [("CartItem", "r/web/cart.js"), ("CartView", "r/web/cart.js")]


def _llm(prompts: list[str]):
    def answer(prompt: str, schema: dict, **kwargs: Any) -> SimpleNamespace:
        prompts.append(prompt)
        name = "Invoicing" if "InvoiceController" in prompt else "Ordering" if "OrderController" in prompt else "Shopping Cart"
        return SimpleNamespace(content=json.dumps({"name": name, "documentation": "x"}))

    return answer


def test_members_that_reach_the_same_objects_form_one_service_across_components():
    prompts: list[str] = []

    services = derive_member_services([*COMPONENTS, *INTERFACES, *OBJECTS], PATHS, IMPORTS, CODE_NAMES, {}, CONFIG, "NAME", _llm(prompts))

    by_name = {s["name"]: s["properties"] for s in services}
    assert sorted(by_name) == ["Invoicing", "Ordering", "Shopping Cart"]
    invoicing = by_name["Invoicing"]
    # The invoice controller and the billing page both reach the invoice: one capability over two components
    assert invoicing["sources"] == ["unit::r::orders", "unit::r::web"] and invoicing["interfaces"] == ["ai_orders_rest", "ai_web_ui"]
    assert invoicing["objects"] == ["do_invoice"] and [m["name"] for m in invoicing["members"]] == ["BillingPage", "InvoiceController"]
    assert by_name["Shopping Cart"]["objects"] == ["bo_cart"]  # named in the code of the page
    assert len(prompts) == 3


def test_more_groups_than_allowed_are_merged_most_similar_first():
    config = ComponentServicesConfig(group_by="members", member_min_names=1, overlap=0.9, max_groups=2, max_doc_lines=0)
    objects = [*OBJECTS, _el("do_line", "DataObject", "typedef::line", "Order Line")]
    paths = {**PATHS, "typedef::line": "r/orders/model/Line.java"}
    imports = [*IMPORTS, ("r/orders/OrderController.java", "r/orders/model/Line.java"), ("r/orders/InvoiceController.java", "r/orders/model/Line.java")]

    services = derive_member_services([*COMPONENTS, *INTERFACES, *objects], paths, imports, CODE_NAMES, {}, config, "NAME", _llm([]))

    assert len(services) == 2
    merged = next(s for s in services if "do_line" in s["properties"]["objects"])
    assert merged["properties"]["objects"] == ["do_invoice", "do_line", "do_order"]


def test_screen_members_reach_records_through_the_programs_linked_to_them():
    interface = _el(
        "ai_online", "ApplicationInterface", "unit::r::online", "Cards Online Web UI", members=[_member("CARDMAP", "typedef::map"), _member("ACCTMAP", "typedef::amap")]
    )
    component = _el("ac_online", "ApplicationComponent", "unit::r::online", "Cards Online")
    records = [_el("do_card", "DataObject", "typedef::cardrec", "Card Record"), _el("do_acct", "DataObject", "typedef::acctrec", "Account Record")]
    member_links = [("typedef::cardprog", "typedef::map"), ("typedef::acctprog", "typedef::amap")]
    object_links = [("typedef::cardprog", "typedef::cardrec"), ("typedef::acctprog", "typedef::acctrec")]

    services = derive_member_services([component, interface, *records], {}, [], [], {}, CONFIG, "NAME", _llm([]), member_links=member_links, object_links=object_links)

    assert sorted(s["properties"]["objects"] for s in services) == [["do_acct"], ["do_card"]]


def test_a_member_that_reaches_no_object_joins_the_group_of_its_interfaces_other_members():
    interface = _el(
        "ai_orders_rest",
        "ApplicationInterface",
        "unit::r::orders",
        "Orders Backend REST API",
        members=[_member("OrderController", "file::orders_ctl"), _member("Health", "file::health")],
    )

    services = derive_member_services([COMPONENTS[0], interface, OBJECTS[0]], {**PATHS, "file::health": "r/orders/Health.java"}, IMPORTS, [], {}, CONFIG, "NAME", _llm([]))

    assert [[m["name"] for m in s["properties"]["members"]] for s in services] == [["Health", "OrderController"]]


def test_an_object_most_members_reach_does_not_decide_the_grouping():
    """A session record every screen uses would join all of them; it only groups the screens that use nothing else."""
    members = [_member(n, f"file::{n}") for n in ("Accounts", "Cards", "Users", "Admin")]
    interface = _el("ai_ui", "ApplicationInterface", "unit::r::online", "Online Web UI", members=members)
    component = _el("ac_online", "ApplicationComponent", "unit::r::online", "Online")
    objects = [
        _el("do_session", "DataObject", "typedef::session", "Session Data"),
        _el("do_acct", "DataObject", "typedef::acct", "Account"),
        _el("do_card", "DataObject", "typedef::card", "Card"),
    ]
    reach = {"Accounts": ["session", "acct"], "Cards": ["session", "card"], "Users": ["session"], "Admin": ["session"]}
    object_links = [(f"file::{m}", f"typedef::{o}") for m, objs in reach.items() for o in objs]
    config = ComponentServicesConfig(group_by="members", member_min_names=1, overlap=0.3, max_groups=7, max_doc_lines=0, ubiquity=0.5)

    services = derive_member_services([component, interface, *objects], {}, [], [], {}, config, "NAME", _llm([]), object_links=object_links)

    grouped = sorted(([m["name"] for m in s["properties"]["members"]], s["properties"]["objects"]) for s in services)
    assert grouped == [(["Accounts"], ["do_acct"]), (["Admin", "Users"], ["do_session"]), (["Cards"], ["do_card"])]


def test_a_member_reaches_a_data_entity_through_any_of_its_types():
    from deriva.modules.derivation.base import UnitScopes

    entity = _el("do_invoice", "DataObject", "entity::r::invoice", "Invoice")
    scopes = UnitScopes(
        files={},
        nodes={},
        entity_files={"entity::r::invoice": frozenset({"r/orders/model/Invoice.java"})},
        entity_nodes={"entity::r::invoice": frozenset({"typedef::invoice"})},
    )

    services = derive_member_services([*COMPONENTS, *INTERFACES, entity], PATHS, IMPORTS, [], {}, CONFIG, "NAME", _llm([]), scopes=scopes)

    invoicing = next(s for s in services if "do_invoice" in s["properties"]["objects"])
    # The two members that import the entity's type file reach it (the others join their interface's group)
    assert {"BillingPage", "InvoiceController"} <= {m["name"] for m in invoicing["properties"]["members"]}
