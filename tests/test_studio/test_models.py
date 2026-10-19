"""Model configs over the API: listed masked, written with a key that is never returned."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession

LISTED = [{"name": "anthropic-haiku", "provider": "anthropic", "model": "claude-haiku", "url": None, "key": "sk-...abcd", "key_env": None}]


def test_models_are_listed_saved_and_deleted(make_client):
    session = FakeSession(list_model_configs=LISTED, save_model_config=None, delete_model_config=None)
    client = make_client(session)

    assert client.get("/api/models").json() == LISTED
    response = client.put("/api/models/mistral-small", json={"provider": "mistral", "model": "mistral-small-latest", "key": "sk-secret-key-1234"})
    assert response.status_code == 200
    assert "sk-secret" not in response.text
    assert session.called("save_model_config") == [
        (
            ("mistral-small",),
            {
                "provider": "mistral",
                "model": "mistral-small-latest",
                "url": None,
                "key": "sk-secret-key-1234",
                "key_env": None,
                "sampling": None,
                "reasoning": None,
            },
        )
    ]
    assert client.delete("/api/models/mistral-small").status_code == 204


def test_refused_and_unknown_models(make_client):
    def refuse(name, **kwargs):
        raise ValueError("Unknown provider 'nope'")

    def missing(name):
        raise KeyError(name)

    client = make_client(FakeSession(save_model_config=refuse, delete_model_config=missing))

    assert client.put("/api/models/m", json={"provider": "nope", "model": "x"}).status_code == 400
    assert client.delete("/api/models/m").status_code == 404


def test_model_configs_need_no_database(make_client):
    """They live in .env: listing and editing work while another process holds the database."""
    from tests.test_studio.test_status import HELD

    session = FakeSession(connect_error=HELD, list_model_configs=[{"name": "m"}], save_model_config=None)
    client = make_client(session)

    assert client.get("/api/models").json() == [{"name": "m"}]
    assert client.put("/api/models/m", json={"provider": "mistral", "model": "x"}).status_code == 200
    assert not session.connected


def test_a_model_config_is_tested_with_one_small_call(make_client):
    answer = {"ok": True, "model": "mistral-small4", "provider": "mistral", "model_id": "mistral-small-2603"}
    answer |= {"served_model": "mistral-small-2603", "latency_ms": 812.4, "answer": "OK"}
    session = FakeSession(check_model_config=answer)
    client = make_client(session)

    assert client.post("/api/models/mistral-small4/test").json() == answer
    assert session.called("check_model_config") == [(("mistral-small4",), {})]


def test_testing_an_unknown_model_config_is_404(make_client):
    def unknown(name):
        raise KeyError(name)

    client = make_client(FakeSession(check_model_config=unknown))

    assert client.post("/api/models/nope/test").status_code == 404
