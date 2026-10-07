"""Settings and the file type registry."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession


def test_get_and_set_a_setting(make_client):
    session = FakeSession(get_setting=lambda key: '["node_modules", ".git"]' if key == "excluded_directories" else None)
    client = make_client(session)

    assert client.get("/api/settings/excluded_directories").json() == {"key": "excluded_directories", "value": '["node_modules", ".git"]'}
    assert client.put("/api/settings/llm_cache", json={"value": "true"}).json() == {"key": "llm_cache", "value": "true"}
    assert session.called("set_setting") == [(("llm_cache", "true"), {})]


def test_file_types_with_stats(make_client):
    client = make_client(FakeSession(get_file_types=[{"extension": ".java", "file_type": "source", "subtype": "java"}], get_file_type_stats={"source": 1}))

    body = client.get("/api/filetypes").json()

    assert body == {"file_types": [{"extension": ".java", "file_type": "source", "subtype": "java"}], "stats": {"source": 1}}


def test_add_update_delete_file_types(make_client):
    session = FakeSession(add_file_type=lambda e, t, s: e == ".cbl", update_file_type=lambda e, t, s: e == ".cbl", delete_file_type=lambda e: e == ".cbl")
    client = make_client(session)

    assert client.post("/api/filetypes", json={"extension": ".cbl", "file_type": "source", "subtype": "cobol"}).status_code == 201
    assert client.post("/api/filetypes", json={"extension": ".java", "file_type": "source", "subtype": "java"}).status_code == 409
    assert client.put("/api/filetypes/.cbl", json={"file_type": "source", "subtype": "cobol"}).status_code == 200
    assert client.put("/api/filetypes/.zzz", json={"file_type": "source", "subtype": "x"}).status_code == 404
    assert client.delete("/api/filetypes/.cbl").status_code == 200
    assert client.delete("/api/filetypes/.zzz").status_code == 404
