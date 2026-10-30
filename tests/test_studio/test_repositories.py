"""Repository endpoints."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession
from tests.test_studio.test_status import HELD


def test_list_repositories_returns_the_detailed_list(make_client):
    session = FakeSession(get_repositories=[{"name": "deriva", "size_mb": 5.6}])
    client = make_client(session)

    response = client.get("/api/repositories")

    assert response.status_code == 200
    assert response.json() == [{"name": "deriva", "size_mb": 5.6}]
    assert session.called("get_repositories") == [((), {"detailed": True})]


def test_repository_info_and_missing_repository(make_client):
    client = make_client(FakeSession(get_repository_info=lambda name: {"name": name} if name == "deriva" else None))

    assert client.get("/api/repositories/deriva").json() == {"name": "deriva"}
    assert client.get("/api/repositories/unknown").status_code == 404


def test_clone_passes_url_name_and_branch(make_client):
    session = FakeSession(clone_repository={"success": True, "name": "sampleapp", "path": "workspace/repositories/sampleapp", "url": "u"})
    client = make_client(session)

    response = client.post("/api/repositories", json={"url": "https://github.com/example/sample-app", "name": "sampleapp"})

    assert response.status_code == 201
    assert response.json()["name"] == "sampleapp"
    args, kwargs = session.called("clone_repository")[0]
    # Never allow_local: a request to the studio cannot clone a local repository
    assert kwargs == {"url": "https://github.com/example/sample-app", "name": "sampleapp", "branch": None, "submodules": True}


def test_clone_without_submodules(make_client):
    session = FakeSession(clone_repository={"success": True, "name": "x", "path": "p", "url": "u"})
    make_client(session).post("/api/repositories", json={"url": "https://example.org/x.git", "submodules": False})
    assert session.called("clone_repository")[0][1]["submodules"] is False


def test_failed_clone_answers_400_with_the_error(make_client):
    client = make_client(FakeSession(clone_repository={"success": False, "error": "repository exists"}))

    response = client.post("/api/repositories", json={"url": "https://example.org/x.git"})

    assert response.status_code == 400
    assert response.json()["detail"] == "repository exists"


def test_delete_passes_force(make_client):
    session = FakeSession(delete_repository={"success": True, "name": "x"})
    client = make_client(session)

    assert client.delete("/api/repositories/x?force=true").status_code == 200
    assert session.called("delete_repository") == [(("x",), {"force": True, "with_data": False})]


def test_data_endpoints_answer_503_when_the_database_is_held(make_client):
    client = make_client(FakeSession(connect_error=HELD))

    response = client.get("/api/repositories")

    assert response.status_code == 503
    assert response.json()["held_by"] == 241896


def test_delete_is_refused_while_a_run_is_in_progress(make_client):
    from deriva.studio.runs import RunBusy

    session = FakeSession(delete_repository={"success": True, "name": "x"})
    client = make_client(session)

    def busy(action):
        raise RunBusy("run1")

    client.app.state.runs.while_idle = busy

    assert client.delete("/api/repositories/x").status_code == 409
    assert session.called("delete_repository") == []


def _busy(client):
    from deriva.studio.runs import RunBusy

    def busy(action):
        raise RunBusy("run1")

    client.app.state.runs.while_idle = busy


def _summary(runs_dir, run_id, kind, repository, started_at, status="finished"):
    import json

    (runs_dir / run_id).mkdir(parents=True)
    row = {"run_id": run_id, "kind": kind, "repository": repository, "status": status, "events": 3, "started_at": started_at, "finished_at": started_at + 5}
    (runs_dir / run_id / "run.json").write_text(json.dumps(row), encoding="utf-8")


def test_repository_data_with_its_last_extraction_and_derivation_run(make_client, tmp_path):
    data = {"repository": "x", "graph": {"nodes": 2, "edges": 1}, "model": {"elements": 2, "relationships": 1}, "database_bytes": 4096}
    session = FakeSession(get_repositories=[{"name": "x"}], repository_data=data)
    client = make_client(session)
    runs = tmp_path / "runs"
    _summary(runs, "r1", "all", "x", 100.0)
    _summary(runs, "r2", "derivation", "x", 200.0, status="cancelled")
    _summary(runs, "r3", "extraction", "other", 300.0)

    body = client.get("/api/repositories/x/data").json()

    assert {k: body[k] for k in data} == data
    assert (body["last_runs"]["extraction"]["run_id"], body["last_runs"]["derivation"]["run_id"]) == ("r1", "r2")
    assert client.get("/api/repositories/unknown/data").status_code == 404


def test_another_repository_s_data_waits_for_a_run_to_end(make_client):
    session = FakeSession(get_repositories=[{"name": "x"}], repository_data={}, repository="other")
    client = make_client(session)
    _busy(client)

    assert client.get("/api/repositories/x/data").status_code == 409


def test_clearing_a_repository_s_model_or_data(make_client):
    session = FakeSession(get_repositories=[{"name": "x"}], clear_repository_model={"success": True}, clear_repository_data={"success": True})
    client = make_client(session)

    assert client.delete("/api/repositories/x/model").status_code == 200
    assert client.delete("/api/repositories/x/graph").status_code == 200
    assert session.called("clear_repository_model") == [(("x",), {})]
    assert session.called("clear_repository_data") == [(("x",), {})]


def test_repository_actions_are_refused_while_a_run_is_in_progress(make_client):
    session = FakeSession(get_repositories=[{"name": "x"}], clear_repository_model={"success": True}, update_repository={"success": True})
    client = make_client(session)
    _busy(client)

    for response in (client.delete("/api/repositories/x/model"), client.delete("/api/repositories/x/graph"), client.post("/api/repositories/x/update")):
        assert response.status_code == 409
    assert session.called("clear_repository_model") == session.called("update_repository") == []


def test_updating_a_clone_answers_its_new_state_or_git_s_reason(make_client):
    ok = make_client(FakeSession(get_repositories=[{"name": "x"}], update_repository={"success": True, "repository": {"name": "x", "last_commit": "abc"}}))
    refused = make_client(FakeSession(get_repositories=[{"name": "x"}], update_repository={"success": False, "error": "Repository has uncommitted changes: x"}))

    assert ok.post("/api/repositories/x/update").json()["repository"]["last_commit"] == "abc"
    response = refused.post("/api/repositories/x/update")
    assert (response.status_code, response.json()["detail"]) == (400, "Repository has uncommitted changes: x")


def test_delete_can_take_the_repository_s_data_along(make_client):
    session = FakeSession(delete_repository={"success": True, "name": "x", "data_deleted": True})
    client = make_client(session)

    assert client.delete("/api/repositories/x?with_data=true").json()["data_deleted"] is True
    assert session.called("delete_repository") == [(("x",), {"force": False, "with_data": True})]


def test_clearing_the_session_s_graph_or_model_waits_for_a_run_to_end(make_client):
    session = FakeSession(clear_graph={"success": True}, clear_model={"success": True})
    client = make_client(session)
    _busy(client)

    assert client.delete("/api/graph").status_code == 409
    assert client.delete("/api/model").status_code == 409
    assert session.called("clear_graph") == session.called("clear_model") == []


def test_a_clone_does_not_hold_the_session_other_requests_need(make_client):
    """A clone takes minutes for a large repository and needs no database: reads go on meanwhile."""
    import threading

    session = FakeSession(clone_repository={"success": True, "name": "x", "branch": "main", "last_commit": "abc", "size_mb": 1.0})
    client = make_client(session)
    provider = client.app.state.provider
    held, release = threading.Event(), threading.Event()

    def hold():
        with provider.session(wait=None):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    try:
        response = client.post("/api/repositories", json={"url": "https://example.org/x.git"})
    finally:
        release.set()
        holder.join(5)

    assert response.status_code == 201 and response.json()["name"] == "x"


def test_no_clone_starts_while_a_run_is_in_progress(make_client):
    session = FakeSession(clone_repository={"success": True, "name": "x"})
    client = make_client(session)
    _busy(client)

    assert client.post("/api/repositories", json={"url": "https://example.org/x.git"}).status_code == 409
    assert session.called("clone_repository") == []


def test_unregistered_lists_git_folders_without_a_record(make_client):
    session = FakeSession(unregistered_repositories=["orphan"])
    client = make_client(session)

    response = client.get("/api/repositories/unregistered")

    assert response.status_code == 200
    assert response.json() == ["orphan"]


def test_register_records_a_folder_and_answers_its_details(make_client):
    session = FakeSession(register_repository={"success": True, "name": "orphan", "branch": "main"})
    client = make_client(session)

    response = client.post("/api/repositories/orphan/register")

    assert response.status_code == 201
    assert response.json()["name"] == "orphan"
    assert session.called("register_repository") == [(("orphan",), {})]


def test_a_failed_register_answers_400_with_the_reason(make_client):
    client = make_client(FakeSession(register_repository={"success": False, "error": "notes has no git checkout in the workspace"}))

    response = client.post("/api/repositories/notes/register")

    assert response.status_code == 400
    assert response.json()["detail"] == "notes has no git checkout in the workspace"


def test_coverage_answers_the_repository_s_report(make_client):
    report = {"files": 3, "in_graph": 3, "complete": True, "reasons": [], "notes": []}
    session = FakeSession(get_repositories=[{"name": "x"}], extraction_coverage=report, repository="x")
    client = make_client(session)

    assert client.get("/api/repositories/x/coverage").json() == report
    assert session.called("extraction_coverage") == [(("x",), {})]
    assert client.get("/api/repositories/unknown/coverage").status_code == 404


def test_another_repository_s_coverage_waits_for_a_run_to_end(make_client):
    session = FakeSession(get_repositories=[{"name": "x"}], extraction_coverage={}, repository="other")
    client = make_client(session)
    _busy(client)

    assert client.get("/api/repositories/x/coverage").status_code == 409
