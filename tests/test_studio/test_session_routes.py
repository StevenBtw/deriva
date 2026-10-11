"""The studio session's current repository (the graph file the views and the model read)."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession


def test_current_repository(make_client):
    session = FakeSession()
    session.repository = "default"
    client = make_client(session)

    assert client.get("/api/session").json() == {"repository": "default"}


def test_switching_the_repository(make_client):
    session = FakeSession(get_repositories=[{"name": "deriva"}, {"name": "TeaStore"}])
    session.repository = "default"
    client = make_client(session)

    response = client.put("/api/session/repository", json={"repository": "TeaStore"})

    assert response.status_code == 200
    assert response.json() == {"repository": "TeaStore"}
    assert session.called("use_repository") == [(("TeaStore",), {})]


def test_unknown_repository_is_404(make_client):
    session = FakeSession(get_repositories=[{"name": "deriva"}])
    session.repository = "default"
    client = make_client(session)

    assert client.put("/api/session/repository", json={"repository": "nope"}).status_code == 404
    assert session.called("use_repository") == []


def test_switching_is_refused_while_a_run_is_in_progress(make_client):
    import threading
    import time

    release = threading.Event()

    def blocking(*args, **kwargs):
        release.wait(5)
        yield from ()

    session = FakeSession(get_repositories=[{"name": "deriva"}], run_extraction_iter=blocking, use_repository=None)
    session.repository = "default"
    client = make_client(session)
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]

    response = client.put("/api/session/repository", json={"repository": "deriva"})

    release.set()
    assert response.status_code == 409
    # The run ends before the fixture closes the provider (it still detaches its call log)
    run = client.app.state.runs.get(run_id)
    deadline = time.time() + 5
    while run.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    assert run.status != "running"
