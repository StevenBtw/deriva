"""Writes inside a step's scope carry the step; an edge can be removed on its own."""

from __future__ import annotations

import pytest

from deriva.adapters.graph.models import FileNode


@pytest.fixture
def graph():
    from deriva.adapters.grafeo.manager import close_database
    from deriva.adapters.graph import GraphManager

    close_database()
    with GraphManager() as gm:
        yield gm
    close_database()


def test_nodes_and_edges_written_in_a_step_carry_its_name_and_version(graph):
    with graph.step_tags("File", 3):
        graph.add_node(FileNode(name="a.py", path="a.py", repository_name="r", file_type="source"), node_id="file::r::a")
        graph.add_node(FileNode(name="b.py", path="b.py", repository_name="r", file_type="source"), node_id="file::r::b")
        graph.add_edge("file::r::a", "file::r::b", "IMPORTS")
    graph.add_node(FileNode(name="c.py", path="c.py", repository_name="r", file_type="source"), node_id="file::r::c")

    (a,) = graph.query("MATCH (n {id: 'file::r::a'}) RETURN n.extractStep AS step, n.extractSteps AS steps, n.extractVersion AS version")
    assert (a["step"], list(a["steps"]), a["version"]) == ("File", ["File"], 3)
    (edge,) = graph.query("MATCH (a {id: 'file::r::a'})-[r]->(b) RETURN r.extractStep AS step")
    assert edge["step"] == "File"
    (c,) = graph.query("MATCH (n {id: 'file::r::c'}) RETURN n.extractStep AS step")
    assert c["step"] is None  # outside a step nothing is tagged


def test_an_edge_is_deleted_without_its_nodes(graph):
    graph.add_node(FileNode(name="a.py", path="a.py", repository_name="r", file_type="source"), node_id="file::r::a")
    graph.add_node(FileNode(name="b.py", path="b.py", repository_name="r", file_type="source"), node_id="file::r::b")
    graph.add_edge("file::r::a", "file::r::b", "IMPORTS")

    assert graph.delete_edge("file::r::a", "IMPORTS", "file::r::b") is True

    assert graph.query("MATCH (a)-[r]->(b) RETURN count(r) AS n")[0]["n"] == 0
    assert graph.node_exists("file::r::a") and graph.node_exists("file::r::b")
