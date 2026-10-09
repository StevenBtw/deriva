"""Write guard and the conversion of embedded grafeo values to anywidget-graph's server format."""

from __future__ import annotations

import pytest

NODE = {"_id": 1, "_labels": ["Directory", "Graph"], "id": "dir::deriva::src", "name": "src", "active": True}
EDGE = {"_id": 5, "_source": 1, "_target": 6, "_type": "Graph:CONTAINS", "id": "e1"}


@pytest.mark.parametrize(
    "query",
    [
        "CREATE (n:Graph:X)",
        "match (n) set n.x = 1",
        "MATCH (n) DETACH DELETE n",
        "MERGE (n:Graph {id: 'a'})",
        "MATCH (n) REMOVE n.x",
        "drop index foo",
    ],
)
def test_write_queries_are_detected(query):
    from deriva.studio.grafeo_compat import is_write_query

    assert is_write_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n:Graph:Directory) RETURN n LIMIT 10",
        "MATCH (n) WHERE n.name = 'CREATE something' RETURN n",
        "MATCH (a)-[r:`Graph:SET_UP`]->(b) RETURN a, r, b",
        'MATCH (n) WHERE n.description CONTAINS "delete" RETURN n.id',
    ],
)
def test_reads_with_write_words_in_strings_or_labels_pass(query):
    from deriva.studio.grafeo_compat import is_write_query

    assert not is_write_query(query)


def test_node_becomes_id_labels_properties_without_the_namespace_label():
    from deriva.studio.grafeo_compat import to_widget_value

    # The widget spreads properties after its id, so Deriva's own "id" property travels as deriva_id
    assert to_widget_value(NODE) == {
        "id": "1",
        "labels": ["Directory"],
        "properties": {"deriva_id": "dir::deriva::src", "name": "src", "active": True},
    }


def test_widget_graph_collects_unique_nodes_and_edges_like_the_widget():
    from deriva.studio.grafeo_compat import to_widget_graph

    other = {"_id": 6, "_labels": ["Directory", "Graph"], "id": "dir::deriva::src_x", "path": "src/x"}
    graph = to_widget_graph([{"a": NODE, "r": EDGE, "b": other}, {"a": NODE, "r": None, "b": None}])

    assert graph["nodes"] == [
        {"id": "1", "label": "src", "labels": ["Directory"], "deriva_id": "dir::deriva::src", "name": "src", "active": True},
        {"id": "6", "label": "src/x", "labels": ["Directory"], "deriva_id": "dir::deriva::src_x", "path": "src/x", "name": "src/x"},
    ]
    assert graph["edges"] == [{"source": "1", "target": "6", "label": "CONTAINS", "edge_id": "e1"}]


def test_node_without_name_gets_a_display_name_from_its_deriva_property():
    from deriva.studio.grafeo_compat import to_widget_value

    value = to_widget_value({"_id": 2, "_labels": ["Graph", "Technology"], "id": "tech::x::jboss", "techName": "Jboss"})

    assert value["properties"]["name"] == "Jboss"


def test_edge_becomes_type_start_end_without_the_namespace_prefix():
    from deriva.studio.grafeo_compat import to_widget_value

    assert to_widget_value(EDGE) == {"id": "5", "type": "CONTAINS", "start": "1", "end": "6", "properties": {"id": "e1"}}


def test_result_keeps_columns_and_converts_nested_values():
    from deriva.studio.grafeo_compat import to_widget_result

    result = to_widget_result([{"a": NODE, "r": EDGE, "names": [NODE], "n": 3}])

    assert result["columns"] == ["a", "r", "names", "n"]
    assert result["rows"][0][0]["labels"] == ["Directory"]
    assert result["rows"][0][2][0]["id"] == "1"
    assert result["rows"][0][3] == 3


def test_empty_result():
    from deriva.studio.grafeo_compat import to_widget_result

    assert to_widget_result([]) == {"columns": [], "rows": []}
