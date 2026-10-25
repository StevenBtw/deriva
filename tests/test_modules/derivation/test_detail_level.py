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
