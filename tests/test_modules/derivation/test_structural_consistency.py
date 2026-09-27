"""structural_consistency containment check on a real in-memory grafeo (Graph + Model namespaces)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.graph import GraphManager
from deriva.modules.derivation.refine.structural_consistency import StructuralConsistencyStep


@pytest.fixture
def managers():
    from deriva.adapters.grafeo.manager import close_database

    close_database()
    gm, am = GraphManager(), ArchimateManager()
    gm.connect()
    am.connect()
    yield gm, am
    gm.disconnect()
    am.disconnect()
    close_database()


def contains(gm: GraphManager, parent: str, child: str, active: bool = True) -> None:
    for node_id in (parent, child):
        gm.query("MERGE (n:Graph:Directory {id: $id}) SET n.active = $active", {"id": node_id, "active": active})
    gm.query("MATCH (a {id: $p}), (b {id: $c}) CREATE (a)-[:`Graph:CONTAINS`]->(b)", {"p": parent, "c": child})


def element(am: ArchimateManager, identifier: str, **props) -> None:
    am.add_element(Element(name=identifier.upper(), element_type="ApplicationComponent", identifier=identifier, properties=props))


def flagged(result) -> set[tuple[str, str]]:
    return {(d["model_parent_id"], d["model_child_id"]) for d in result.details if d.get("issue_type") == "missing_containment_relationship"}


def run(gm, am):
    return StructuralConsistencyStep().run(am, gm, params={"check_calls": False, "check_aspect_constraints": False})


def test_containment_without_model_relationship_is_flagged(managers):
    gm, am = managers
    contains(gm, "dir::p", "dir::c")
    element(am, "a", source="dir::p"), element(am, "b", source="dir::c")

    result = run(gm, am)

    assert flagged(result) == {("a", "b")} and result.issues_found == 1
    (detail,) = [d for d in result.details if d.get("issue_type")]
    assert (detail["graph_parent"], detail["graph_child"]) == ("dir::p", "dir::c")
    assert (detail["model_parent_name"], detail["model_child_name"]) == ("A", "B")


def test_any_model_relationship_counts_as_preserved(managers):
    gm, am = managers
    contains(gm, "dir::p", "dir::c")
    element(am, "a", source="dir::p"), element(am, "b", source="dir::c")
    am.add_relationship(Relationship(source="a", target="b", relationship_type="Serving"))

    result = run(gm, am)
    assert result.success
    assert flagged(result) == set()


def test_disabled_elements_and_inactive_nodes_are_ignored(managers):
    gm, am = managers
    contains(gm, "dir::p", "dir::c")
    contains(gm, "dir::q", "dir::d", active=False)
    element(am, "a", source="dir::p"), element(am, "b", source="dir::c")
    element(am, "x", source="dir::q"), element(am, "y", source="dir::d")
    am.disable_element("b", reason="test")

    result = run(gm, am)
    assert result.success
    assert flagged(result) == set()


def test_graph_id_mentioned_anywhere_in_properties_matches(managers):
    gm, am = managers
    contains(gm, "dir::p", "dir::c")
    element(am, "a", files="see dir::p"), element(am, "b", files="see dir::c")

    assert flagged(run(gm, am)) == {("a", "b")}


def test_no_cypher_join_against_the_model(managers):
    """The containment check reads model rows once and joins in Python."""
    gm, am = managers
    contains(gm, "dir::p", "dir::c")
    element(am, "a", source="dir::p"), element(am, "b", source="dir::c")

    from deriva.adapters.grafeo.manager import GrafeoConnection

    queries: list[str] = []
    real_execute = GrafeoConnection.execute

    def record(conn, query, parameters=None, database=None):
        queries.append(query)
        return real_execute(conn, query, parameters, database)

    # Every Cypher query of both namespaces goes through GrafeoConnection.execute
    with patch.object(GrafeoConnection, "execute", record):
        result = run(gm, am)

    assert result.success
    assert any("Graph:CONTAINS" in q for q in queries)
    assert not [q for q in queries if "Graph:CONTAINS" in q and "Model" in q]
