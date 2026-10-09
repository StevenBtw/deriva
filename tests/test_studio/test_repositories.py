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
    session = FakeSession(clone_repository={"success": True, "name": "carddemo", "path": "workspace/repositories/carddemo", "url": "u"})
    client = make_client(session)

    response = client.post("/api/repositories", json={"url": "https://github.com/aws-samples/aws-mainframe-modernization-carddemo", "name": "carddemo"})

    assert response.status_code == 201
    assert response.json()["name"] == "carddemo"
    args, kwargs = session.called("clone_repository")[0]
    assert kwargs == {"url": "https://github.com/aws-samples/aws-mainframe-modernization-carddemo", "name": "carddemo", "branch": None}


def test_failed_clone_answers_400_with_the_error(make_client):
    client = make_client(FakeSession(clone_repository={"success": False, "error": "repository exists"}))

    response = client.post("/api/repositories", json={"url": "https://example.org/x.git"})

    assert response.status_code == 400
    assert response.json()["detail"] == "repository exists"


def test_delete_passes_force(make_client):
    session = FakeSession(delete_repository={"success": True, "name": "x"})
    client = make_client(session)

    assert client.delete("/api/repositories/x?force=true").status_code == 200
    assert session.called("delete_repository") == [(("x",), {"force": True})]


def test_data_endpoints_answer_503_when_the_database_is_held(make_client):
    client = make_client(FakeSession(connect_error=HELD))

    response = client.get("/api/repositories")

    assert response.status_code == 503
    assert response.json()["held_by"] == 241896
