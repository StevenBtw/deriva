"""Storage routes: what the workspace keeps on disk, and clearing the parts that can go."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession

OVERVIEW = {
    "graphs": [{"key": "gone", "bytes": 24, "kind": "orphaned", "active": False}],
    "llm_cache": {"bytes": 150, "files": 2},
    "exports": {"bytes": 20, "files": 2},
    "benchmark_sessions": {"bytes": 14, "sessions": 2},
}


def _busy(client):
    from deriva.studio.runs import RunBusy

    def busy(action):
        raise RunBusy("run1")

    client.app.state.runs.while_idle = busy


def test_the_overview_adds_the_studio_s_runs(make_client, tmp_path):
    runs = tmp_path / "runs" / "r1"
    runs.mkdir(parents=True)
    (runs / "run.json").write_text('{"run_id": "r1", "started_at": 1}', encoding="utf-8")
    (runs / "llm.jsonl").write_bytes(b"x" * 100)
    client = make_client(FakeSession(storage_overview=OVERVIEW))

    body = client.get("/api/storage").json()

    assert {k: body[k] for k in OVERVIEW} == OVERVIEW
    assert body["runs"]["runs"] == 1 and body["runs"]["bytes"] >= 100


def test_clearing_the_llm_cache_exports_and_an_orphaned_graph(make_client):
    session = FakeSession(clear_llm_cache={"bytes": 150, "files": 2}, delete_exports={"bytes": 20, "files": 2}, delete_graph={"key": "gone", "bytes": 24})
    client = make_client(session)

    assert client.delete("/api/storage/llm-cache").json() == {"bytes": 150, "files": 2}
    assert client.delete("/api/storage/exports").json() == {"bytes": 20, "files": 2}
    assert client.delete("/api/storage/graphs/gone").json() == {"key": "gone", "bytes": 24}
    assert session.called("delete_graph") == [(("gone",), {})]


def test_a_graph_that_cannot_go_says_why(make_client):
    def refuse(key):
        if key == "never":
            raise KeyError(key)
        raise ValueError("alpha is a repository's database: clear or delete it on the Repositories page")

    client = make_client(FakeSession(delete_graph=refuse))

    assert client.delete("/api/storage/graphs/never").status_code == 404
    response = client.delete("/api/storage/graphs/alpha")
    assert (response.status_code, response.json()["detail"]) == (400, "alpha is a repository's database: clear or delete it on the Repositories page")


def test_clearing_waits_for_a_run_to_end(make_client):
    session = FakeSession(clear_llm_cache={}, delete_exports={}, delete_graph={})
    client = make_client(session)
    _busy(client)

    for path in ("/api/storage/llm-cache", "/api/storage/exports", "/api/storage/graphs/gone"):
        assert client.delete(path).status_code == 409
    assert session.called("clear_llm_cache") == session.called("delete_graph") == []
