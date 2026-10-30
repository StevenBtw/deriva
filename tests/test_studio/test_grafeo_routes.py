"""anywidget-graph's grafeo server requests, answered from the embedded databases, read-only."""

from __future__ import annotations

from collections import Counter

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


def test_the_query_runs_in_the_language_the_widget_chose(make_client):
    session = FakeSession(query_graph_read_only=[])
    client = make_client(session)

    client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "Cypher"})
    client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "gql"})
    client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n"})

    # Without a language the query runs in GRAFEO_QUERY_LANGUAGE
    assert [kwargs for _, kwargs in session.called("query_graph_read_only")] == [{"language": "cypher"}, {"language": "gql"}, {"language": None}]


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


def test_a_query_that_reads_a_local_file_is_rejected(make_client):
    """grafeo's LOAD CSV reads any local file (file:///...): the studio's query view must never pass it on."""
    session = FakeSession(query_graph_read_only=[])
    client = make_client(session)

    for query in ("LOAD CSV FROM 'file:///etc/passwd' AS row RETURN row", "load csv with headers from 'file:///x' as r return r"):
        response = client.post("/grafeo/query", json={"query": query, "language": "cypher"})
        assert response.status_code == 400
    assert session.called("query_graph_read_only") == []


def test_unknown_database_and_language(make_client):
    client = make_client(FakeSession(query_graph_read_only=[]))

    assert client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "language": "cypher", "database": "other"}).status_code == 404
    assert client.post("/grafeo/query", json={"query": "g.V()", "language": "gremlin"}).status_code == 400


def test_query_errors_are_400_with_the_message(make_client):
    def fail(query, params, language=None):
        raise ValueError("Syntax error at line 1")

    client = make_client(FakeSession(query_graph_read_only=fail))

    response = client.post("/grafeo/query", json={"query": "MATCH (n RETURN n", "language": "cypher"})

    assert response.status_code == 400
    assert "Syntax error" in response.json()["detail"]


def graph_db(nodes: dict[str, str], edges: list[tuple[str, str, str]]):
    """A fake extraction graph (Deriva id to node type; source, target, edge type) answering the view's read-only queries."""
    engine_id = {node: number for number, node in enumerate(nodes, start=100)}

    def node(deriva_id: str) -> dict:
        return {"_id": engine_id[deriva_id], "_labels": ["Graph", nodes[deriva_id]], "id": deriva_id}

    def answer(query, params):
        if "RETURN n.id AS id, labels(n) AS labels" in query:
            return [{"id": deriva_id, "labels": ["Graph", kind]} for deriva_id, kind in nodes.items()]
        if "RETURN a.id AS source, b.id AS target, type(r) AS type" in query:
            return [{"source": a, "target": b, "type": f"Graph:{kind}"} for a, b, kind in edges]
        if "WHERE n.id IN $ids RETURN n" in query:
            return [{"n": node(deriva_id)} for deriva_id in nodes if deriva_id in params["ids"]]
        if "RETURN a, r, b" in query:
            ids = set(params["ids"])
            return [
                {"a": node(a), "r": {"_id": f"e{i}", "_type": f"Graph:{kind}", "_source": engine_id[a], "_target": engine_id[b]}, "b": node(b)}
                for i, (a, b, kind) in enumerate(edges)
                if a in ids and b in ids
            ]
        return []

    return answer


def small_repository() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """One repository, two directories, six files and twelve methods, as CONTAINS trees."""
    nodes = {"repo::r": "Repository", "dir::r::a": "Directory", "dir::r::b": "Directory"}
    edges = [("repo::r", "dir::r::a", "CONTAINS"), ("repo::r", "dir::r::b", "CONTAINS")]
    for f in range(6):
        nodes[f"file::r::{f}"] = "File"
        edges.append((f"dir::r::{'ab'[f % 2]}", f"file::r::{f}", "CONTAINS"))
        for m in range(2):
            nodes[f"method::r::{f}.{m}"] = "Method"
            edges.append((f"file::r::{f}", f"method::r::{f}.{m}", "CONTAINS"))
    return nodes, edges


def test_graph_view_samples_every_node_type_with_the_repositories_always_in(make_client):
    nodes, edges = small_repository()
    client = make_client(FakeSession(query_graph_read_only=graph_db(nodes, edges)))

    view = client.get("/grafeo/view/graph?limit=8").json()

    kinds = Counter(node["labels"][0] for node in view["nodes"])
    assert len(view["nodes"]) == 8
    assert kinds["Repository"] == 1
    assert {"Directory", "File", "Method"} <= set(kinds)
    assert kinds["Method"] > kinds["File"] > kinds["Directory"]
    assert view["totals"] == {"nodes": {"Repository": 1, "Directory": 2, "File": 6, "Method": 12}, "edges": {"CONTAINS": 20}}


def test_graph_view_keeps_the_relationships_of_its_sample(make_client):
    nodes, edges = small_repository()
    client = make_client(FakeSession(query_graph_read_only=graph_db(nodes, edges)))

    view = client.get("/grafeo/view/graph?limit=8").json()

    touched = {end for edge in view["edges"] for end in (edge["source"], edge["target"])}
    assert len(view["nodes"]) == 8
    assert touched == {node["id"] for node in view["nodes"]}


def test_graph_view_without_a_limit_samples_as_many_nodes_as_the_setting_says(make_client):
    nodes, edges = small_repository()
    session = FakeSession(query_graph_read_only=graph_db(nodes, edges), graph_view_nodes=8)
    client = make_client(session)

    view = client.get("/grafeo/view/graph").json()

    assert len(view["nodes"]) == 8
    assert len(session.called("graph_view_nodes")) == 1


def test_linked_view_without_a_limit_reads_the_setting_and_a_given_limit_wins(make_client):
    nodes, edges = small_repository()
    session = FakeSession(query_graph_read_only=graph_db(nodes, edges), query_model_read_only=[], graph_view_nodes=8)
    client = make_client(session)

    sampled = client.get("/grafeo/view/linked").json()
    given = client.get("/grafeo/view/linked?limit=300").json()

    assert len(sampled["nodes"]) == 8
    assert len(given["nodes"]) == len(nodes)
    assert len(session.called("graph_view_nodes")) == 1


def test_a_graph_within_the_limit_is_shown_whole(make_client):
    nodes, edges = small_repository()
    client = make_client(FakeSession(query_graph_read_only=graph_db(nodes, edges)))

    view = client.get("/grafeo/view/graph?limit=300").json()

    assert len(view["nodes"]) == len(nodes)
    assert len(view["edges"]) == len(edges)


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

    # The widget's grafeo client asks /db/<name>/schema; the older /databases/<name>/schema answers the same
    for path in ("/grafeo/db/graph/schema", "/grafeo/databases/graph/schema"):
        schema = client.get(path).json()
        assert schema == {
            "labels": [{"name": "Directory", "count": 2}, {"name": "File", "count": 1}],
            "edge_types": [{"name": "CONTAINS", "count": 4}],
        }


def test_a_query_answers_from_the_chosen_database_only(make_client):
    """Both namespaces share one graph file: MATCH (n) would return the model's nodes in the graph pane too."""
    rows = [
        {"n": {"_id": 1, "_labels": ["Graph", "File"], "id": "file_a"}},
        {"n": {"_id": 2, "_labels": ["Model", "Node"], "id": "n_server"}},
    ]
    client = make_client(FakeSession(query_graph_read_only=lambda q, p, language=None: rows, query_model_read_only=lambda q, p, language=None: rows))

    graph = client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "database": "graph"}).json()
    model = client.post("/grafeo/query", json={"query": "MATCH (n) RETURN n", "database": "model"}).json()

    assert [row[0]["_id"] for row in graph["rows"]] == [1]
    assert [row[0]["_id"] for row in model["rows"]] == [2]
