"""The linked view: both graphs as lanes, each element linked to the graph nodes it was derived from."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession
from tests.test_studio.test_grafeo_routes import graph_db, small_repository

GRAPH_FILE = {"_id": 11, "_labels": ["Graph", "File"], "id": "file::r::a.py", "fileName": "a.py"}
GRAPH_DIR = {"_id": 12, "_labels": ["Graph", "Directory"], "id": "dir::r::src"}
GRAPH_REPO = {"_id": 10, "_labels": ["Graph", "Repository"], "id": "repo::r", "name": "r"}
GRAPH_REPO_TWO = {"_id": 9, "_labels": ["Graph", "Repository"], "id": "repo::s", "name": "s"}
# As the archimate adapter stores them: the element's own properties are one map, with source or sources inside
ELEMENT_ONE = {
    "_id": 21,
    "_labels": ["Model", "ApplicationComponent"],
    "identifier": "ac_a",
    "name": "A",
    "properties": {"source": "file::r::a.py"},
    "source_identifier": "file::r::a.py",
}
ELEMENT_MANY = {"_id": 22, "_labels": ["Model", "DataObject"], "identifier": "do_b", "name": "B", "properties": {"sources": ["file::r::a.py", "dir::r::src", "file::r::gone.py"]}}
# Rejected by refine: still in the model database, left out of the exported model
ELEMENT_REJECTED = {"_id": 23, "_labels": ["Model", "BusinessActor"], "identifier": "ba_c", "name": "C", "enabled": False, "properties": {"source": "dir::r::src"}}


def model_db(*elements: dict):
    """A fake model database: elements as stored, the enabled filter applied as the database would."""

    def answer(query, params):
        if "RETURN a, r, b" in query:
            return []
        valid_only = "coalesce(n.enabled, true) = true" in query
        return [{"n": element} for element in elements if not valid_only or element.get("enabled", True) is not False]

    return answer


def derived_from(view: dict) -> list[tuple[str, str]]:
    return sorted((e["source"], e["target"]) for e in view["edges"] if e.get("label") == "DERIVED_FROM")


def in_model(view: dict) -> list[tuple[str, str]]:
    return sorted((e["source"], e["target"]) for e in view["edges"] if e.get("label") == "IN_MODEL")


def test_element_sources_prefer_the_list_over_the_single_source():
    from deriva.studio.linked_view import element_sources

    assert element_sources({"properties": {"sources": ["x", "y"], "source": "z"}, "source_identifier": "w"}) == ["x", "y"]
    assert element_sources({"properties": {"source": "z"}}) == ["z"]
    assert element_sources({"properties": None}) == []
    assert element_sources({}) == []


def test_element_sources_of_an_older_model_fall_back_to_the_source_identifier():
    from deriva.studio.linked_view import element_sources

    # Models derived before elements kept their own properties map carry only the adapter's source_identifier
    assert element_sources({"source_identifier": "dir::r::src"}) == ["dir::r::src"]
    assert element_sources({"properties": {}, "source_identifier": "dir::r::src"}) == ["dir::r::src"]


def test_build_puts_both_graphs_in_lanes_and_links_elements_to_present_sources():
    from deriva.studio.grafeo_compat import to_widget_graph
    from deriva.studio.linked_view import build_linked_view

    graph = to_widget_graph([{"n": GRAPH_FILE}, {"n": GRAPH_DIR}])
    model = to_widget_graph([{"n": ELEMENT_ONE}, {"n": ELEMENT_MANY}])
    view = build_linked_view(model, graph)

    assert [lane["id"] for lane in view["lanes"]] == ["repository", "intermediate", "output"]
    assert {n["id"]: n["lane"] for n in view["nodes"]} == {"11": "intermediate", "12": "intermediate", "21": "output", "22": "output"}
    assert derived_from(view) == [("21", "11"), ("22", "11"), ("22", "12")]
    assert all(e.get("cross") for e in view["edges"] if e.get("label") == "DERIVED_FROM")
    assert view["missing_links"] == 1


def test_elements_in_the_model_link_to_the_model_lane_and_rejected_ones_do_not():
    from deriva.studio.grafeo_compat import to_widget_graph
    from deriva.studio.linked_view import MODEL_LANE, build_linked_view

    graph = to_widget_graph([{"n": GRAPH_FILE}, {"n": GRAPH_DIR}])
    model = to_widget_graph([{"n": ELEMENT_ONE}, {"n": ELEMENT_REJECTED}])
    view = build_linked_view(model, graph)

    assert in_model(view) == [("21", MODEL_LANE)]
    assert all(e.get("cross") for e in view["edges"] if e.get("label") == "IN_MODEL")
    # A rejected element keeps the links to where it came from
    assert derived_from(view) == [("21", "11"), ("23", "12")]


def test_the_view_carries_the_totals_of_the_sampled_graph():
    from deriva.studio.grafeo_compat import to_widget_graph
    from deriva.studio.linked_view import build_linked_view

    totals = {"nodes": {"File": 40}, "edges": {"CONTAINS": 39}}
    view = build_linked_view(to_widget_graph([]), {**to_widget_graph([{"n": GRAPH_FILE}]), "totals": totals})

    assert view["totals"] == totals


def test_repositories_get_their_own_narrow_column_lane_on_the_left():
    from deriva.studio.grafeo_compat import to_widget_graph
    from deriva.studio.linked_view import build_linked_view

    one = build_linked_view(to_widget_graph([]), to_widget_graph([{"n": GRAPH_REPO}, {"n": GRAPH_DIR}]))
    two = build_linked_view(to_widget_graph([]), to_widget_graph([{"n": GRAPH_REPO}, {"n": GRAPH_REPO_TWO}, {"n": GRAPH_DIR}]))

    assert {n["id"]: n["lane"] for n in one["nodes"]} == {"10": "repository", "12": "intermediate"}
    repository = one["lanes"][0]
    assert repository["id"] == "repository" and repository["arrange"] == "column" and repository["width"] < 1
    assert repository["title"] == "Repository"
    assert two["lanes"][0]["title"] == "Repositories"


def linked_repository() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """The small repository of the route tests, with the element sources of the fixtures in it."""
    nodes, edges = small_repository()
    nodes.update({"dir::r::src": "Directory", "file::r::a.py": "File"})
    edges += [("repo::r", "dir::r::src", "CONTAINS"), ("dir::r::src", "file::r::a.py", "CONTAINS")]
    return nodes, edges


def test_linked_route_shows_the_whole_output_graph_and_the_repository_and_samples_the_rest(make_client):
    nodes, edges = linked_repository()
    session = FakeSession(query_graph_read_only=graph_db(nodes, edges), query_model_read_only=model_db(ELEMENT_ONE, ELEMENT_REJECTED))
    client = make_client(session)

    view = client.get("/grafeo/view/linked?limit=6").json()

    output = [n for n in view["nodes"] if n["lane"] == "output"]
    graph = [n for n in view["nodes"] if n["lane"] != "output"]
    assert sorted(n["identifier"] for n in output) == ["ac_a", "ba_c"]
    assert [n["enabled"] for n in output if n["identifier"] == "ba_c"] == [False]
    # Six in all: the two elements, then the repository and both sources, then one more from the sample
    assert len(graph) == 4
    assert {"repo::r", "dir::r::src", "file::r::a.py"} <= {n["deriva_id"] for n in graph}
    assert len(derived_from(view)) == 2
    assert view["missing_links"] == 0
    assert view["totals"]["nodes"]["Method"] == 12


def test_a_model_larger_than_the_limit_keeps_its_source_nodes(make_client):
    nodes, edges = linked_repository()
    session = FakeSession(query_graph_read_only=graph_db(nodes, edges), query_model_read_only=model_db(ELEMENT_ONE, ELEMENT_MANY, ELEMENT_REJECTED))
    client = make_client(session)

    # Three elements and a limit of two: no budget is left, but the sources still come in (up to the limit)
    view = client.get("/grafeo/view/linked?limit=2").json()

    graph = {n["deriva_id"] for n in view["nodes"] if n["lane"] != "output"}
    assert {"dir::r::src", "file::r::a.py"} <= graph
    assert len(derived_from(view)) == 4


def test_separate_model_view_shows_only_the_model(make_client):
    client = make_client(FakeSession(query_model_read_only=model_db(ELEMENT_ONE, ELEMENT_REJECTED)))

    view = client.get("/grafeo/view/model").json()

    assert [n["identifier"] for n in view["nodes"]] == ["ac_a"]
