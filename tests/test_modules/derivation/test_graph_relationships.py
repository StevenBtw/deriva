"""graph_relationships refine step: behaviour on a real in-memory grafeo (Graph + Model namespaces)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.graph import GraphManager
from deriva.modules.derivation.refine.graph_relationships import GraphRelationshipsStep


@pytest.fixture
def managers():
    with patch.dict("os.environ", {"GRAFEO_DB_PATH": ""}, clear=False):
        from deriva.adapters.grafeo.manager import close_database

        close_database()
        gm, am = GraphManager(), ArchimateManager()
        gm.connect()
        am.connect()
        yield gm, am
        gm.disconnect()
        am.disconnect()
        close_database()


def node(gm: GraphManager, node_id: str, active: bool = True) -> None:
    gm.query("CREATE (:Graph:File {id: $id, active: $active})", {"id": node_id, "active": active})


def edge(gm: GraphManager, source: str, target: str, edge_type: str = "USES") -> None:
    gm.query(
        f"MATCH (a {{id: $s}}), (b {{id: $t}}) CREATE (a)-[:`Graph:{edge_type}`]->(b)",
        {"s": source, "t": target},
    )


def element(am: ArchimateManager, identifier: str, source: str | None, element_type: str = "ApplicationComponent", **props) -> None:
    properties = {"source": source, **props} if source else dict(props)
    am.add_element(Element(name=identifier.upper(), element_type=element_type, identifier=identifier, properties=properties))


def created(am: ArchimateManager) -> set[tuple[str, str, str, str]]:
    return {
        (r.source, r.target, r.relationship_type, r.properties.get("derived_from", "")) for r in am.get_relationships() if r.properties.get("derived_from", "").startswith("Graph:")
    }


def run(gm, am, **params):
    return GraphRelationshipsStep().run(am, gm, params={"edge_types": ["USES", "IMPORTS", "CALLS"], **params})


class TestPrimaryMatch:
    def test_edge_between_sources_becomes_relationship(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2")

        result = run(gm, am)

        assert result.success and result.relationships_created == 1
        assert created(am) == {("a", "b", "Serving", "Graph:USES")}

    def test_inactive_graph_node_is_ignored(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2", active=False), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2")

        assert run(gm, am).relationships_created == 0

    def test_disabled_element_is_ignored(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2")
        am.disable_element("b", reason="test")

        assert run(gm, am).relationships_created == 0

    def test_existing_relationship_of_same_type_is_not_duplicated(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2")
        am.add_relationship(Relationship(source="a", target="b", relationship_type="Serving"))

        assert run(gm, am).relationships_created == 0

    def test_two_edge_types_mapping_to_one_type_create_it_once(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2", "USES"), edge(gm, "n1", "n2", "IMPORTS")
        element(am, "a", "n1"), element(am, "b", "n2")

        assert run(gm, am).relationships_created == 1
        assert created(am) == {("a", "b", "Serving", "Graph:USES")}

    def test_invalid_source_type_is_filtered(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "d", "n1", element_type="DataObject"), element(am, "b", "n2")

        assert run(gm, am).relationships_created == 0

    def test_several_elements_per_source_node(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a1", "n1"), element(am, "a2", "n1"), element(am, "b", "n2")

        run(gm, am)

        assert {(s, t) for s, t, _, _ in created(am)} == {("a1", "b"), ("a2", "b")}

    def test_limit_and_dry_run(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a1", "n1"), element(am, "a2", "n1"), element(am, "b", "n2")

        dry = run(gm, am, dry_run=True)
        after_dry_run = created(am)
        limited = run(gm, am, max_relationships=1)

        assert dry.relationships_created == 2 and after_dry_run == set()
        assert [d["action"] for d in dry.details] == ["would_create", "would_create"]
        assert limited.relationships_created == 1 and len(created(am)) == 1


class TestFallbackMatch:
    def test_graph_id_mentioned_in_properties_is_matched(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", None, files="see n1"), element(am, "b", None, files="see n2")

        assert run(gm, am).relationships_created == 1
        assert created(am) == {("a", "b", "Serving", "Graph:USES")}

    def test_fallback_skips_pairs_with_any_relationship(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", None, files="n1"), element(am, "b", None, files="n2")
        am.add_relationship(Relationship(source="a", target="b", relationship_type="Flow"))

        assert run(gm, am).relationships_created == 0

    def test_fallback_not_used_when_primary_matches(self, managers):
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2"), element(am, "c", None, files="n2")

        run(gm, am)

        assert {(s, t) for s, t, _, _ in created(am)} == {("a", "b")}


class TestPerformanceShape:
    def test_no_cypher_join_against_the_model(self, managers):
        """Model rows are read once via the manager API and joined in Python (a Cypher
        join of graph edges x model element pairs took ~460 s on a real run)."""
        gm, am = managers
        node(gm, "n1"), node(gm, "n2"), edge(gm, "n1", "n2")
        element(am, "a", "n1"), element(am, "b", "n2")

        with patch.object(am, "query", wraps=am.query) as model_query:
            run(gm, am)

        model_query.assert_not_called()


def test_pairs_the_metamodel_rejects_do_not_take_candidate_slots():
    """Each type may appear in Composition, but not every source/target pair; check the pair before the limit."""
    from deriva.modules.derivation.refine.graph_relationships import find_relationship_candidates

    elements = [
        Element(name="Proc", element_type="BusinessProcess", identifier="bp", properties={"source": "a1"}),
        Element(name="Comp", element_type="ApplicationComponent", identifier="ac", properties={"source": "a2"}),
        Element(name="Outer", element_type="ApplicationComponent", identifier="ac_outer", properties={"source": "b1"}),
        Element(name="Inner", element_type="ApplicationComponent", identifier="ac_inner", properties={"source": "b2"}),
    ]

    rows = find_relationship_candidates([("a1", "a2"), ("b1", "b2")], elements, set(), "Composition", limit=1)

    assert [(r["source_id"], r["target_id"]) for r in rows] == [("ac_outer", "ac_inner")]
