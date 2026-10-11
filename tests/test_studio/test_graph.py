"""Graph and model endpoints and the anywidget-archimate view of the model."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession

ELEMENTS = [
    {
        "identifier": "n_application_server",
        "name": "Application Server",
        "element_type": "Node",
        "documentation": "Hosts",
        "properties": {"source": "tech::x::jboss"},
        "enabled": True,
    },
    {"identifier": "ac_core", "name": "Core", "element_type": "ApplicationComponent", "documentation": "", "properties": {}, "enabled": True},
    {"identifier": "ac_old", "name": "Old", "element_type": "ApplicationComponent", "documentation": "", "properties": {}, "enabled": False},
]
RELATIONSHIPS = [
    {"identifier": "r1", "source": "n_application_server", "target": "ac_core", "relationship_type": "Serving", "name": "", "documentation": "", "properties": {}},
    {"identifier": "r2", "source": "ac_old", "target": "ac_core", "relationship_type": "Flow", "name": "", "documentation": "", "properties": {}},
]


def test_widget_model_maps_types_layers_and_skips_disabled_elements():
    from deriva.studio.archimate_view import to_widget_model

    model = to_widget_model(ELEMENTS, RELATIONSHIPS)

    assert model["elements"] == [
        {"id": "n_application_server", "name": "Application Server", "type": "Node", "layer": "Technology", "documentation": "Hosts", "source": "tech::x::jboss"},
        {"id": "ac_core", "name": "Core", "type": "ApplicationComponent", "layer": "Application", "documentation": "", "source": None},
    ]
    assert model["relationships"] == [{"id": "r1", "source": "n_application_server", "target": "ac_core", "type": "Serving", "name": ""}]


def test_model_endpoint_returns_the_widget_model(make_client):
    client = make_client(FakeSession(get_archimate_elements=ELEMENTS, get_archimate_relationships=RELATIONSHIPS))

    body = client.get("/api/model").json()

    assert [e["id"] for e in body["elements"]] == ["n_application_server", "ac_core"]
    assert len(body["relationships"]) == 1


def test_graph_stats_nodes_and_clear(make_client):
    session = FakeSession(
        get_graph_stats={"total_nodes": 3, "by_type": {"Directory": 3}},
        get_graph_nodes=lambda node_type, limit=None: [{"id": f"d{i}"} for i in range(5)][:limit],
        clear_graph={"success": True},
    )
    client = make_client(session)

    assert client.get("/api/graph/stats").json() == {"total_nodes": 3, "by_type": {"Directory": 3}}
    assert client.get("/api/graph/nodes/Directory?limit=2").json() == [{"id": "d0"}, {"id": "d1"}]
    assert client.delete("/api/graph").json() == {"success": True}


def test_model_stats_clear_and_export(make_client):
    session = FakeSession(
        get_archimate_stats={"total_elements": 2, "total_relationships": 1, "by_type": {"Node": 1}},
        clear_model={"success": True},
        export_model={"success": True, "path": "workspace/output/model.xml"},
    )
    client = make_client(session)

    assert client.get("/api/model/stats").json()["total_elements"] == 2
    assert client.delete("/api/model").json() == {"success": True}
    assert client.post("/api/model/export", json={"path": "workspace/output/model.xml"}).json()["success"] is True
    assert session.called("export_model") == [((), {"output_path": "workspace/output/model.xml", "confined": True})]


def test_a_node_type_must_be_a_label_and_the_limit_is_passed_on(make_client):
    """The node type becomes a Cypher label: anything but a plain name could end the label and add clauses."""
    session = FakeSession(get_graph_nodes=lambda node_type, limit=None: [{"id": "d0"}])
    client = make_client(session)

    assert client.get("/api/graph/nodes/Directory`) DETACH DELETE n //").status_code == 400
    assert client.get("/api/graph/nodes/Directory?limit=-1").status_code == 422
    assert client.get("/api/graph/nodes/Directory?limit=2").status_code == 200
    assert session.called("get_graph_nodes") == [(("Directory",), {"limit": 2})]


def test_the_model_is_exported_only_into_the_workspace_output_folder(make_client):
    def export_model(output_path=None, confined=False):
        if confined and output_path and ".." in output_path:
            raise ValueError("The studio exports into workspace/output only")
        return {"success": True, "path": output_path}

    client = make_client(FakeSession(export_model=export_model))

    assert client.post("/api/model/export", json={"path": "workspace/output/model.xml"}).status_code == 200
    assert client.post("/api/model/export", json={"path": "workspace/output/../../evil.xml"}).status_code == 400
