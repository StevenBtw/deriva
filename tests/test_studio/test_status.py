"""Health and status endpoints, and a database held by another process."""

from __future__ import annotations

from importlib.metadata import version

import pytest

from tests.test_studio.conftest import FakeSession

HELD = OSError(
    'IO Error: Cannot open file "\\\\?\\H:\\Deriva\\deriva\\deriva\\adapters\\database\\sql.db": The process cannot access '
    "the file because it is being used by another process.\nFile is already open in C:\\Python314\\python.exe (PID 241896)"
)


def test_health_reports_ok_and_version(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": version("Deriva")}


def test_status_reports_an_owned_database(client, fake_session):
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["db"] == {"state": "owned"}
    assert fake_session.connected


def test_status_reports_a_held_database_with_the_pid(make_client):
    client = make_client(FakeSession(connect_error=HELD))

    db = client.get("/api/status").json()["db"]

    assert db["state"] == "held"
    assert db["held_by"] == 241896


def test_provider_raises_database_held_with_the_pid():
    from deriva.studio.provider import DatabaseHeld, SessionProvider

    provider = SessionProvider(factory=lambda: FakeSession(connect_error=HELD))

    with pytest.raises(DatabaseHeld) as raised, provider.session():
        pass

    assert raised.value.pid == 241896


def test_other_connect_errors_are_not_reported_as_held():
    from deriva.studio.provider import SessionProvider

    provider = SessionProvider(factory=lambda: FakeSession(connect_error=ValueError("bad config")))

    with pytest.raises(ValueError), provider.session():
        pass


def test_the_session_can_be_released_from_another_thread():
    """FastAPI runs a generator dependency's setup and teardown on thread-pool threads, which may differ."""
    import threading

    from deriva.studio.provider import SessionProvider

    provider = SessionProvider(factory=FakeSession)
    context = provider.session()
    context.__enter__()
    released: list[bool] = []

    def release() -> None:
        context.__exit__(None, None, None)
        released.append(True)

    worker = threading.Thread(target=release)
    worker.start()
    worker.join()

    assert released == [True]
    with provider.session(wait=0.5) as session:
        assert session.connected


def test_status_answers_while_a_step_holds_the_session(make_client, fake_session):
    client = make_client(fake_session)
    provider = client.app.state.provider
    assert client.get("/api/status").json()["db"]["state"] == "owned"

    with provider.session():
        import threading

        answers: list[dict] = []
        reader = threading.Thread(target=lambda: answers.append(client.get("/api/status").json()))
        reader.start()
        reader.join(5)

    assert answers[0]["db"] == {"state": "owned", "busy": True}
