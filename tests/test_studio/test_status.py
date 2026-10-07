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
