"""The export levels: lineage from the graph, the detail elements, the level property and the views."""

from __future__ import annotations

from deriva.adapters.archimate.models import Element, Relationship
from deriva.services.export_levels import detail_lineage, leveled_model


class FakeGraph:
    ROWS = {
        "DataEntity": [{"d": "domain::r::order", "e": "entity::r::order", "n": "Order"}, {"d": "domain::r::order", "e": "entity::r::line", "n": "Order Line"}],
        "Deployment": [{"v": "environment::r::compose", "d": "deployment::r::compose::shop", "n": "shop", "u": "unit::r::shop"}],
        "program": [],
        "Lifecycle": [{"l": "lifecycle::r::order", "s": ["DRAFT", "PAID"]}],
    }

    def query(self, cypher, params=None):
        return next(rows for key, rows in self.ROWS.items() if key in cypher)


ELEMENTS = [
    Element(name="Order Data", element_type="DataObject", identifier="do_order", properties={"source": "domain::r::order"}),
    Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop", properties={"source": "unit::r::shop"}),
    Element(name="Docker Compose", element_type="Node", identifier="node_env", properties={"source": "environment::r::compose"}),
    Element(name="Order Lifecycle", element_type="BusinessProcess", identifier="bp_order", properties={"source": "lifecycle::r::order"}),
]
RELATIONSHIPS = [Relationship(source="node_env", target="ac_shop", relationship_type="Realization", identifier="r1")]


def test_the_lineage_is_read_from_the_graph():
    lineage = detail_lineage(FakeGraph())

    assert lineage.entities == {"domain::r::order": [("entity::r::line", "Order Line"), ("entity::r::order", "Order")]}
    assert lineage.deployments == {"environment::r::compose": [("deployment::r::compose::shop", "shop", "unit::r::shop")]}
    assert lineage.states == {"lifecycle::r::order": ["DRAFT", "PAID"]}


def test_without_a_graph_there_is_no_detail_level():
    model = leveled_model(ELEMENTS, RELATIONSHIPS, detail_lineage(None))

    assert model.summary() == {"architect_elements": 4, "detail_elements": 0, "detail_relationships": 0}
    assert len(model.elements) == len(ELEMENTS) and len(model.relationships) == len(RELATIONSHIPS)


def test_the_leveled_model_adds_the_detail_level_and_keeps_the_architect_level():
    model = leveled_model(ELEMENTS, RELATIONSHIPS, detail_lineage(FakeGraph()))

    levels = {e.name: model.properties[e.identifier]["level"] for e in model.elements}
    assert levels == {
        "Order Data": "architect",
        "Shop": "architect",
        "Docker Compose": "architect",
        "Order Lifecycle": "architect",
        "Order": "detail",
        "Order Line": "detail",
        "shop": "detail",
    }
    assert model.properties["bp_order"]["states"] == "DRAFT, PAID"
    assert {r.relationship_type for r in model.relationships} == {"Realization", "Composition", "Assignment"}
    assert [e.identifier for e in model.elements[: len(ELEMENTS)]] == [e.identifier for e in ELEMENTS]
    assert {v.name for v in model.views} >= {"Layered", "Information Structure (detail)", "Implementation and Deployment (detail)"}
    assert model.summary() == {"architect_elements": 4, "detail_elements": 3, "detail_relationships": 4}
