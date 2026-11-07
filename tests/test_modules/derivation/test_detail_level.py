"""The export's detail level: the members of the architect elements (lineage) as nested elements, from structure."""

from __future__ import annotations

from deriva.modules.derivation.detail_level import DetailLineage, detail_level


def _el(identifier, element_type, name, **properties):
    return {"identifier": identifier, "element_type": element_type, "name": name, "properties": properties}


ELEMENTS = [
    _el("do_orders", "DataObject", "Order Data", source="domain::r::order"),
    _el("ai_shop__rest", "ApplicationInterface", "Shop REST API", source="unit::r::shop", role="rest", members=[{"name": "OrderResource", "source": "typedef::r::OrderResource"}]),
    _el("ac_shop", "ApplicationComponent", "Shop", source="unit::r::shop"),
    _el("ac_batch", "ApplicationComponent", "Batch", source="unit::r::batch"),
    _el("node_env", "Node", "Docker Compose", source="environment::r::compose"),
    _el("bp_order", "BusinessProcess", "Order Lifecycle", source="lifecycle::r::order"),
]
LINEAGE = DetailLineage(
    entities={"domain::r::order": [("entity::r::order", "Order"), ("entity::r::orderline", "Order Line")]},
    programs={"unit::r::batch": [("typedef::r::POSTTRAN", "POSTTRAN")]},
    states={"lifecycle::r::order": ["DRAFT", "PLACED", "PAID"]},
)


def _triples(detail):
    names = {e["identifier"]: e["name"] for e in ELEMENTS + detail.elements}
    return {(names[r["source"]], r["relationship_type"], names[r["target"]]) for r in detail.relationships}


def test_members_become_nested_elements_of_their_architect_element():
    detail = detail_level(ELEMENTS, LINEAGE)

    kinds = sorted((e["element_type"], e["name"]) for e in detail.elements)
    assert kinds == [
        ("ApplicationComponent", "POSTTRAN"),
        ("ApplicationInterface", "OrderResource"),
        ("DataObject", "Order"),
        ("DataObject", "Order Line"),
    ]
    assert _triples(detail) == {
        ("Order Data", "Composition", "Order"),
        ("Order Data", "Composition", "Order Line"),
        ("Shop REST API", "Composition", "OrderResource"),
        ("Batch", "Composition", "POSTTRAN"),
    }
    assert all(e["properties"]["level"] == "detail" for e in detail.elements)


def test_identities_are_structural_and_lifecycle_states_are_a_property():
    first, second = detail_level(ELEMENTS, LINEAGE), detail_level(list(reversed(ELEMENTS)), LINEAGE)

    assert sorted(e["identifier"] for e in first.elements) == sorted(e["identifier"] for e in second.elements)
    assert sorted(r["identifier"] for r in first.relationships) == sorted(r["identifier"] for r in second.relationships)
    assert first.properties["bp_order"] == {"states": "DRAFT, PLACED, PAID"}
    assert first.properties["ac_shop"] == {}  # architect elements carry their level only (set by the exporter)


def test_a_deployment_is_no_detail_artifact():
    """A deployment that deploys a unit is that unit's architect-level artifact; one without a unit (a vendor image) is
    its system software, which the node composes: the detail level adds no artifact and nothing to the node."""
    detail = detail_level(ELEMENTS, LINEAGE)

    assert not any(e["element_type"] == "Artifact" for e in detail.elements)
    assert not any("node_env" in (r["source"], r["target"]) for r in detail.relationships)


def test_a_file_member_is_named_without_its_extension_and_a_repeat_takes_its_folder():
    """Pages and code files are members by their file: the name drops the extension and starts with a capital, two members
    of one interface with the same name each take their folder in front, and a template whose name starts with an
    underscore (a partial or layout) is no endpoint. A type member keeps its name."""
    members = [
        {"name": "Index.cshtml", "source": "file::r::a"},
        {"name": "Index.cshtml", "source": "file::r::b"},
        {"name": "list.html", "source": "file::r::c"},
        {"name": "_Layout.cshtml", "source": "file::r::d"},
        {"name": "OrderController.java", "source": "file::r::e"},
        {"name": "OrderResource", "source": "typedef::r::OrderResource"},
    ]
    files = {
        "file::r::a": "r/web/Views/Home/Index.cshtml",
        "file::r::b": "r/web/Views/Account/Index.cshtml",
        "file::r::c": "r/web/templates/list.html",
        "file::r::d": "r/web/Views/Shared/_Layout.cshtml",
        "file::r::e": "r/web/src/OrderController.java",
    }
    elements = [_el("ai_web__ui", "ApplicationInterface", "Web UI", source="unit::r::web", role="web", members=members)]

    detail = detail_level(elements, DetailLineage(files=files))

    assert sorted(e["name"] for e in detail.elements) == ["Account Index", "Home Index", "List", "OrderController", "OrderResource"]


def test_a_file_member_named_as_written_keeps_its_name():
    """A file that registers a service is a member by the service it registers (as_written): it keeps that name."""
    members = [{"name": "CartService", "source": "file::r::a", "as_written": True}, {"name": "main.go", "source": "file::r::b"}]
    files = {"file::r::a": "r/cart/main.go", "file::r::b": "r/shop/main.go"}
    elements = [_el("ai_cart__rpc", "ApplicationInterface", "Cart RPC API", source="unit::r::cart", role="rpc", members=members)]

    detail = detail_level(elements, DetailLineage(files=files))

    assert sorted(e["name"] for e in detail.elements) == ["CartService", "Main"]


def test_a_member_named_as_written_keeps_its_name_when_a_file_member_shares_it():
    """Only the file member named after its file takes folders in front; the one named as written stays as it is."""
    members = [{"name": "Cart", "source": "file::r::a", "as_written": True}, {"name": "cart.go", "source": "file::r::b"}]
    files = {"file::r::a": "r/svc/server/main.go", "file::r::b": "r/svc/model/cart.go"}
    elements = [_el("ai_cart__rpc", "ApplicationInterface", "Cart RPC API", source="unit::r::cart", role="rpc", members=members)]

    detail = detail_level(elements, DetailLineage(files=files))

    assert sorted(e["name"] for e in detail.elements) == ["Cart", "Model Cart"]


def test_members_whose_folders_repeat_take_folders_until_their_names_differ():
    """An area's page and the main page of the same folder name (Areas/Admin/Views/Home and Views/Home) take further
    folders in front until the names differ; a name that is unique keeps a single folder."""
    members = [{"name": "Index.cshtml", "source": f"file::r::{k}"} for k in "abc"]
    files = {"file::r::a": "r/web/Areas/Admin/Views/Home/Index.cshtml", "file::r::b": "r/web/Views/Home/Index.cshtml", "file::r::c": "r/web/Views/Account/Index.cshtml"}
    elements = [_el("ai_web__ui", "ApplicationInterface", "Web UI", source="unit::r::web", role="web", members=members)]

    detail = detail_level(elements, DetailLineage(files=files))

    assert sorted(e["name"] for e in detail.elements) == ["Account Index", "Admin Views Home Index", "Web Views Home Index"]
