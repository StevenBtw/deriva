"""Health and status endpoints, and a database held by another process."""

from __future__ import annotations

import platform

import pytest

from deriva.services import about
from tests.test_studio.conftest import FakeSession

HELD = OSError(
    'IO Error: Cannot open file "\\\\?\\H:\\Deriva\\deriva\\deriva\\adapters\\database\\sql.db": The process cannot access '
    "the file because it is being used by another process.\nFile is already open in C:\\Python314\\python.exe (PID 241896)"
)


def test_health_reports_ok_and_version(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": about.version()}


def test_status_reports_an_owned_database(client, fake_session):
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["db"] == {"state": "owned"}
    assert fake_session.connected


def test_status_reports_the_optional_features(client):
    assert client.get("/api/status").json()["features"] == {"benchmark": True}


def test_status_reports_the_environment(client):
    environment = client.get("/api/status").json()["environment"]

    assert environment["python"] == platform.python_version()
    assert environment["os"] == ("macOS" if platform.system() == "Darwin" else platform.system())


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

    with pytest.raises(ValueError, match="bad config"), provider.session():
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


def test_the_linux_lock_message_also_means_held(make_client):
    held = OSError('IO Error: Could not set lock on file "/home/u/.deriva/sql.db": Conflicting lock is held in /usr/bin/python3.14 (PID 4242) by user u.')
    client = make_client(FakeSession(connect_error=held))

    response = client.get("/api/status")

    assert response.json()["db"]["state"] == "held"
    assert response.json()["db"]["held_by"] == 4242


def test_a_config_database_held_by_a_cli_run_is_held_with_the_pid(make_client):
    """Deriva's ConfigDatabaseBusy (DuckDB's lock error behind its own message) is a held database, matched by class."""
    from deriva.services import ConfigDatabaseBusy

    try:
        raise OSError("IO Error: Cannot open file: being used by another process. File is already open in python.exe (PID 36740)")
    except OSError as cause:
        busy = ConfigDatabaseBusy("The config database x is open in another Deriva process (the studio or another deriva-cli run)")
        busy.__cause__ = cause
    client = make_client(FakeSession(connect_error=busy))

    db = client.get("/api/status").json()["db"]

    assert db["state"] == "held" and db["held_by"] == 36740


def test_a_graph_held_by_another_process_is_held_and_no_session_is_kept():
    """The session's connect closes what it opened (its own tests); the provider keeps no half-open session."""
    from deriva.services import GraphDatabaseBusy
    from deriva.studio.provider import DatabaseHeld, SessionProvider

    provider = SessionProvider(factory=lambda: FakeSession(connect_error=GraphDatabaseBusy("x.grafeo")))

    with pytest.raises(DatabaseHeld) as raised, provider.session():
        pass

    assert raised.value.pid is None and "x.grafeo is open in another Deriva process" in str(raised.value)
    assert provider.status()["state"] == "held"
    assert provider._session is None


def test_status_reports_the_database_engines_and_their_versions(client):
    from importlib.metadata import version

    engines = client.get("/api/status").json()["engines"]

    assert engines == {"duckdb": version("duckdb"), "grafeo": version("grafeo")}
