"""anywidget-graph's grafeo server requests, answered from the embedded databases, read-only."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession
from tests.test_studio.test_grafeo_compat import EDGE, NODE


def test_health(client):
    assert client.get("/grafeo/health").json() == {"status": "ok", "engine": "grafeo-embedded"}


def test_query_on_the_graph_database(make_client):
    session = FakeSession(query_graph_read_only=[{"a": NODE, "r": EDGE}])
    client = make_client(session)

    response = client.post("/grafeo/query", json={"query": "MATCH (a)-[r]->(b) RETURN a, r", "language": "cypher", "database": "graph"})

    assert response.status_code == 200
    assert response.json()["columns"] == ["a", "r"]
    assert session.called("query_graph_read_only")[0][0] == ("MATCH (a)-[r]->(b) RETURN a, r", None)


def test_default_database_is_the_graph_and_model_is_separate(make_client):
    session = FakeSession(query_graph_read_only=[], query_model_read_only=[])
    client = make_client(session)

    client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "cypher"})
    client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "cypher", "database": "model"})

    assert len(session.called("query_graph_read_only")) == 1
    assert len(session.called("query_model_read_only")) == 1


def test_write_query_is_rejected_before_it_reaches_the_database(make_client):
    session = FakeSession(query_graph_read_only=[])
    client = make_client(session)

    response = client.post("/grafeo/query", json={"query": "MATCH (n) DETACH DELETE n", "language": "cypher"})

    assert response.status_code == 400
    assert "read-only" in response.json()["detail"]
    assert session.called("query_graph_read_only") == []


def test_unknown_database_and_language(make_client):
    client = make_client(FakeSession(query_graph_read_only=[]))

    assert client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "cypher", "database": "other"}).status_code == 404
    assert client.post("/grafeo/query", json={"query": "g.V()", "language": "gremlin"}).status_code == 400


def test_query_errors_are_400_with_the_message(make_client):
    def fail(query, params):
        raise ValueError("Syntax error at line 1")

    client = make_client(FakeSession(query_graph_read_only=fail))

    response = client.post("/grafeo/query", json={"query": "MATCH (n RETURN n", "language": "cypher"})

    assert response.status_code == 400
    assert "Syntax error" in response.json()["detail"]


def test_graph_view_reads_the_derivation_relevant_types_and_their_edges(make_client):
    calls = []

    def answer(query, params):
        calls.append((query, params))
        if "RETURN a, r, b" in query:
            return [{"a": NODE, "r": EDGE, "b": {"_id": 6, "_labels": ["Graph", "Directory"], "id": "dir::deriva::x"}}]
        if ":Directory" in query:
            return [{"n": NODE}]
        return []

    client = make_client(FakeSession(query_graph_read_only=answer))

    view = client.get("/grafeo/view/graph?limit=50").json()

    assert [n["id"] for n in view["nodes"]] == ["1", "6"]
    assert view["edges"] == [{"source": "1", "target": "6", "label": "CONTAINS", "edge_id": "e1"}]
    assert any("LIMIT 50" in q for q, _ in calls)
    edge_query = [p for q, p in calls if "RETURN a, r, b" in q][0]
    assert edge_query == {"ids": ["dir::deriva::src"]}


def test_model_view_reads_elements_and_relationships(make_client):
    def answer(query, params):
        if "RETURN a, r, b" in query:
            return []
        return [{"n": {"_id": 3, "_labels": ["Model", "Node"], "identifier": "n_app", "name": "Application Server"}}]

    session = FakeSession(query_model_read_only=answer)
    client = make_client(session)

    view = client.get("/grafeo/view/model").json()

    assert view["nodes"][0]["label"] == "Application Server"
    assert view["nodes"][0]["labels"] == ["Node"]
    assert session.called("query_graph_read_only") == []


def test_unknown_view_database_is_404(make_client):
    client = make_client(FakeSession())

    assert client.get("/grafeo/view/other").status_code == 404


def test_schema_lists_labels_and_edge_types_with_counts(make_client):
    def answer(query, params):
        if "labels(n)" in query:
            return [{"labels": ["Graph", "Directory"]}, {"labels": ["Graph", "Directory"]}, {"labels": ["Graph", "File"]}]
        return [{"type": "Graph:CONTAINS", "count": 4}]

    client = make_client(FakeSession(query_graph_read_only=answer))

    schema = client.get("/grafeo/databases/graph/schema").json()

    assert schema == {
        "labels": [{"name": "Directory", "count": 2}, {"name": "File", "count": 1}],
        "edge_types": [{"name": "CONTAINS", "count": 4}],
    }
