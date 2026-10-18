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
    deployments={"environment::r::compose": [("deployment::r::compose::shop", "shop", "unit::r::shop"), ("deployment::r::compose::db", "db", None)]},
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
        ("Artifact", "db"),
        ("Artifact", "shop"),
        ("DataObject", "Order"),
        ("DataObject", "Order Line"),
    ]
    assert _triples(detail) == {
        ("Order Data", "Composition", "Order"),
        ("Order Data", "Composition", "Order Line"),
        ("Shop REST API", "Composition", "OrderResource"),
        ("Docker Compose", "Assignment", "shop"),
        ("Docker Compose", "Assignment", "db"),
        ("shop", "Realization", "Shop"),  # the artifact realizes the component of the unit it deploys
        ("Batch", "Composition", "POSTTRAN"),
    }
    assert all(e["properties"]["level"] == "detail" for e in detail.elements)


def test_identities_are_structural_and_lifecycle_states_are_a_property():
    first, second = detail_level(ELEMENTS, LINEAGE), detail_level(list(reversed(ELEMENTS)), LINEAGE)

    assert sorted(e["identifier"] for e in first.elements) == sorted(e["identifier"] for e in second.elements)
    assert sorted(r["identifier"] for r in first.relationships) == sorted(r["identifier"] for r in second.relationships)
    assert first.properties["bp_order"] == {"states": "DRAFT, PLACED, PAID"}
    assert first.properties["ac_shop"] == {}  # architect elements carry their level only (set by the exporter)


def test_a_deployments_artifact_is_assigned_to_its_service_node_where_there_is_one():
    """A service node made from the deployment takes the artifact; a deployment without one stays with the environment."""
    elements = [*ELEMENTS, _el("n_shop", "Node", "shop", source="deployment::r::compose::shop", role="service")]
    detail = detail_level(elements, LINEAGE)
    names = {e["identifier"]: e["name"] for e in elements + detail.elements}
    triples = {(r["source"], r["relationship_type"], names[r["target"]]) for r in detail.relationships}

    assert ("n_shop", "Assignment", "shop") in triples and ("node_env", "Assignment", "shop") not in triples
    assert ("node_env", "Assignment", "db") in triples
    # The artifact keeps its identity: one artifact per deployment, whichever node holds it
    assert sorted(e["identifier"] for e in detail.elements) == sorted(e["identifier"] for e in detail_level(ELEMENTS, LINEAGE).elements)
