"""Settings and the file type registry."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession


def test_get_and_set_a_setting(make_client):
    session = FakeSession(get_setting=lambda key: '["node_modules", ".git"]' if key == "excluded_directories" else None)
    client = make_client(session)

    assert client.get("/api/settings/excluded_directories").json()["value"] == '["node_modules", ".git"]'
    assert client.put("/api/settings/llm_cache", json={"value": "true"}).json() == {"key": "llm_cache", "value": "true"}
    assert session.called("set_setting") == [(("llm_cache", "true"), {})]


def test_an_unset_setting_comes_with_the_value_that_applies(make_client):
    """Unset excluded directories mean the built-in list: the editor starts from it, so saving keeps .git and node_modules out."""
    import json

    client = make_client(FakeSession(get_setting=lambda key: None))

    body = client.get("/api/settings/excluded_directories").json()
    other = client.get("/api/settings/llm_cache").json()

    assert body["value"] is None
    assert {".git", "node_modules"} <= set(json.loads(body["default"]))
    assert other == {"key": "llm_cache", "value": None, "default": None}


def test_file_types_with_stats(make_client):
    client = make_client(FakeSession(get_file_types=[{"extension": ".java", "file_type": "source", "subtype": "java"}], get_file_type_stats={"source": 1}))

    body = client.get("/api/filetypes").json()

    assert body == {"file_types": [{"extension": ".java", "file_type": "source", "subtype": "java"}], "stats": {"source": 1}}


def test_add_update_delete_file_types(make_client):
    session = FakeSession(add_file_type=lambda e, t, s: e == ".rs", update_file_type=lambda e, t, s: e == ".rs", delete_file_type=lambda e: e == ".rs")
    client = make_client(session)

    assert client.post("/api/filetypes", json={"extension": ".rs", "file_type": "source", "subtype": "rust"}).status_code == 201
    assert client.post("/api/filetypes", json={"extension": ".java", "file_type": "source", "subtype": "java"}).status_code == 409
    assert client.put("/api/filetypes/.rs", json={"file_type": "source", "subtype": "rust"}).status_code == 200
    assert client.put("/api/filetypes/.zzz", json={"file_type": "source", "subtype": "x"}).status_code == 404
    assert client.delete("/api/filetypes/.rs").status_code == 200
    assert client.delete("/api/filetypes/.zzz").status_code == 404


def test_a_file_type_key_with_slashes_can_be_changed_and_deleted(make_client):
    session = FakeSession(update_file_type=lambda e, t, s: True, delete_file_type=lambda e: True)
    client = make_client(session)

    assert client.put("/api/filetypes/path:**/tests/**", json={"file_type": "test", "subtype": "any"}).status_code == 200
    assert client.delete("/api/filetypes/path:**/tests/**").status_code == 200
    assert session.called("delete_file_type") == [(("path:**/tests/**",), {})]


def test_an_invalid_setting_value_is_a_client_error(make_client):
    def refuse(key, value):
        raise ValueError("excluded_directories must be a JSON list of directory names")

    client = make_client(FakeSession(set_setting=refuse))

    response = client.put("/api/settings/excluded_directories", json={"value": "{}"})

    assert response.status_code == 400
    assert "JSON list" in response.json()["detail"]
