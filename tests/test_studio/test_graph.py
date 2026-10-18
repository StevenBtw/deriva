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


LEVELS = {
    "elements": [
        {**ELEMENTS[0], "level": "architect", "layer": "Technology"},
        {**ELEMENTS[1], "level": "architect", "layer": "Application"},
        {"identifier": "art_core", "name": "core", "element_type": "Artifact", "properties": {}, "enabled": True, "level": "detail", "layer": "Technology"},
    ],
    "relationships": [*RELATIONSHIPS[:1], {"identifier": "r3", "source": "n_application_server", "target": "art_core", "relationship_type": "Assignment"}],
    "views": [
        {"name": "Layered", "viewpoint": "Layered", "level": "architect", "elements": ["n_application_server", "ac_core"]},
        {
            "name": "Implementation and Deployment (detail)",
            "viewpoint": "Implementation and Deployment",
            "level": "detail",
            "elements": ["n_application_server", "ac_core", "art_core"],
        },
    ],
}


def test_model_endpoint_returns_the_widget_model_per_level_with_its_views(make_client):
    client = make_client(FakeSession(get_model_levels=LEVELS))

    architect = client.get("/api/model").json()
    detail = client.get("/api/model?level=detail").json()

    assert [e["id"] for e in architect["elements"]] == ["n_application_server", "ac_core"]
    assert len(architect["relationships"]) == 1
    assert [v["name"] for v in architect["views"]] == ["Layered"]
    # Detail: the architect elements of a model without levels stay, with the members, and only the detail views
    assert [e["id"] for e in detail["elements"]] == ["n_application_server", "ac_core", "art_core"]
    assert detail["elements"][2]["layer"] == "Technology"  # a type the widget does not know keeps Deriva's layer
    assert [v["name"] for v in detail["views"]] == ["Implementation and Deployment (detail)"]
    assert client.get("/api/model?level=other").status_code == 422


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


def test_the_architect_level_is_every_level_but_detail(make_client):
    """The session reports the model's levels (enterprise, solution, both); the studio's architect level shows them all."""
    levels = {
        "elements": [
            {**ELEMENTS[0], "level": "enterprise", "layer": "Technology"},
            {**ELEMENTS[1], "level": "enterprise solution", "layer": "Application"},
            {"identifier": "art_core", "name": "core", "element_type": "Artifact", "properties": {}, "enabled": True, "level": "detail", "layer": "Technology"},
        ],
        "relationships": RELATIONSHIPS[:1],
        "views": [
            {"name": "Layered (enterprise)", "viewpoint": "Layered", "level": "enterprise", "elements": ["n_application_server", "ac_core"]},
            {"name": "Application Structure (solution)", "viewpoint": "Application Structure", "level": "solution", "elements": ["ac_core"]},
            {"name": "Implementation and Deployment (detail)", "viewpoint": "Implementation and Deployment", "level": "detail", "elements": ["art_core"]},
        ],
    }
    architect = make_client(FakeSession(get_model_levels=levels)).get("/api/model").json()

    assert [e["id"] for e in architect["elements"]] == ["n_application_server", "ac_core"]
    assert [v["name"] for v in architect["views"]] == ["Layered (enterprise)", "Application Structure (solution)"]


def test_the_model_per_abstraction_level_holds_that_level_only(make_client):
    """Enterprise and solution show their own elements, relationships and views (no cross-level link, no lift on the
    solution level); detail is the solution level with the members, as the exchange file's detail views are."""

    def element(identifier, level, element_type="ApplicationComponent"):
        return {"identifier": identifier, "name": identifier, "element_type": element_type, "properties": {}, "enabled": True, "level": level, "layer": "Application"}

    def relationship(identifier, source, target, level):
        return {"identifier": identifier, "source": source, "target": target, "relationship_type": "Serving", "level": level}

    levels = {
        "elements": [
            element("svc", "enterprise", "ApplicationService"),
            element("top", "enterprise solution"),
            element("lib", "solution"),
            element("member", "detail", "ApplicationInterface"),
        ],
        "relationships": [
            relationship("lift", "top", "svc", "enterprise"),
            relationship("uses", "lib", "top", "solution"),
            relationship("cross", "lib", "svc", "cross-level"),
            relationship("part", "top", "member", "detail"),
        ],
        "views": [
            {"name": "Layered (enterprise)", "viewpoint": "Layered", "level": "enterprise", "elements": ["svc", "top"], "relationships": ["lift"]},
            {"name": "Application Structure (solution)", "viewpoint": "Application Structure", "level": "solution", "elements": ["top", "lib"], "relationships": ["uses"]},
            {"name": "Application Interfaces (detail)", "viewpoint": "Application Cooperation", "level": "detail", "elements": ["top", "member"], "relationships": ["part"]},
        ],
    }
    client = make_client(FakeSession(get_model_levels=levels))

    def shown(level):
        model = client.get(f"/api/model?level={level}").json()
        return [e["id"] for e in model["elements"]], [r["id"] for r in model["relationships"]], [v["name"] for v in model["views"]]

    assert shown("enterprise") == (["svc", "top"], ["lift"], ["Layered (enterprise)"])
    assert shown("solution") == (["top", "lib"], ["uses"], ["Application Structure (solution)"])
    assert shown("detail") == (["top", "lib", "member"], ["uses", "part"], ["Application Interfaces (detail)"])
    # The whole model of earlier studios stays available
    assert shown("architect")[0] == ["svc", "top", "lib"]
