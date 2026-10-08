"""Config listing, versioned saves and enabling steps."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession

EXTRACTION = [
    {"node_type": "DirectoryClassification", "sequence": 11, "enabled": True, "instruction": "classify", "example": "{}"},
    {"node_type": "Test", "sequence": 14, "enabled": False, "instruction": None, "example": None},
]
VERSIONS = {"extraction": {"DirectoryClassification": 9}, "derivation": {"Node": 21}}


def session_with_configs(**extra) -> FakeSession:
    return FakeSession(
        get_extraction_configs=EXTRACTION,
        get_derivation_configs=[{"element_type": "Node", "sequence": 9, "enabled": True, "instruction": "roles", "example": "{}"}],
        get_config_versions=VERSIONS,
        **extra,
    )


def test_list_extraction_configs_with_versions(make_client):
    client = make_client(session_with_configs())

    rows = client.get("/api/configs/extraction").json()

    assert rows[0]["name"] == "DirectoryClassification"
    assert rows[0]["version"] == 9
    assert rows[1]["name"] == "Test"
    assert rows[1]["version"] is None


def test_list_derivation_configs_uses_the_element_type_as_name(make_client):
    client = make_client(session_with_configs())

    rows = client.get("/api/configs/derivation").json()

    assert rows == [{"name": "Node", "element_type": "Node", "sequence": 9, "enabled": True, "instruction": "roles", "example": "{}", "version": 21}]


def test_unknown_step_type_is_404(make_client):
    client = make_client(session_with_configs())

    assert client.get("/api/configs/refine").status_code == 404


def test_save_creates_a_new_version(make_client):
    session = session_with_configs(save_extraction_config={"success": True, "old_version": 9, "new_version": 10})
    client = make_client(session)

    response = client.put("/api/configs/extraction/DirectoryClassification", json={"instruction": "new text", "example": "{}"})

    assert response.status_code == 200
    assert response.json() == {"name": "DirectoryClassification", "old_version": 9, "new_version": 10}
    args, kwargs = session.called("save_extraction_config")[0]
    assert args == ("DirectoryClassification",)
    assert kwargs == {"instruction": "new text", "example": "{}", "enabled": None, "params": None, "batch_size": None}
    assert session.called("update_extraction_config") == []


def test_save_without_changes_is_400(make_client):
    client = make_client(session_with_configs())

    assert client.put("/api/configs/derivation/Node", json={}).status_code == 400


def test_failed_save_is_404(make_client):
    client = make_client(session_with_configs(save_derivation_config={"success": False, "error": "Config not found for X"}))

    response = client.put("/api/configs/derivation/X", json={"instruction": "t"})

    assert response.status_code == 404


def test_enable_and_disable_a_step(make_client):
    session = session_with_configs(enable_step=True, disable_step=True)
    client = make_client(session)

    assert client.put("/api/configs/extraction/Test/enabled", json={"enabled": True}).json() == {"name": "Test", "enabled": True}
    assert client.put("/api/configs/extraction/Test/enabled", json={"enabled": False}).json() == {"name": "Test", "enabled": False}
    assert session.called("enable_step") == [(("extraction", "Test"), {})]
    assert session.called("disable_step") == [(("extraction", "Test"), {})]


def test_save_with_params_query_and_batch_size(make_client):
    session = FakeSession(save_derivation_config={"success": True, "old_version": 3, "new_version": 4})
    client = make_client(session)

    response = client.put("/api/configs/derivation/Node", json={"params": '{"k": 2}', "input_graph_query": "MATCH (n) RETURN n", "batch_size": 5})

    assert response.json() == {"name": "Node", "old_version": 3, "new_version": 4}
    kwargs = session.called("save_derivation_config")[0][1]
    assert (kwargs["params"], kwargs["input_graph_query"], kwargs["batch_size"]) == ('{"k": 2}', "MATCH (n) RETURN n", 5)


def test_bad_params_and_extraction_queries_are_refused(make_client):
    def refuse(name, **kwargs):
        raise ValueError("params must be a JSON object, got list")

    client = make_client(FakeSession(save_derivation_config=refuse))

    assert client.put("/api/configs/derivation/Node", json={"params": "[1]"}).status_code == 400
    assert client.put("/api/configs/extraction/Concept", json={"input_graph_query": "MATCH (n) RETURN n"}).status_code == 400


def test_history_scan_and_dry_run_routes(make_client):
    session = FakeSession(
        get_config_history=[{"version": 2, "is_active": True}],
        scan_prompt_texts={"available": True, "findings": [{"field": "instruction", "finding": "'widgetco' (repo term)"}]},
        get_derivation_configs=[{"element_type": "Node", "input_graph_query": "MATCH (n:Graph:Technology) RETURN n"}],
        dry_run_graph_query={"count": 3, "rows": []},
    )
    client = make_client(session)

    assert client.get("/api/configs/derivation/Node/versions").json() == [{"version": 2, "is_active": True}]
    assert session.called("get_config_history") == [(("derivation", "Node"), {})]
    assert client.post("/api/configs/scan", json={"texts": {"instruction": "WidgetCo"}}).json()["findings"][0]["field"] == "instruction"
    assert client.post("/api/configs/derivation/Node/dry-run", json={}).json() == {"count": 3, "rows": []}
    assert session.called("dry_run_graph_query") == [(("MATCH (n:Graph:Technology) RETURN n",), {})]
    client.post("/api/configs/derivation/Node/dry-run", json={"query": "MATCH (n:Graph:Directory) RETURN n"})
    assert session.called("dry_run_graph_query")[-1] == (("MATCH (n:Graph:Directory) RETURN n",), {})
