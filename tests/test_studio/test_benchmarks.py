"""Benchmark export over the API: the bundle downloads as a zip."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from tests.test_studio.conftest import FakeSession
from tests.test_studio.test_runs import finished, wait_for


def test_export_downloads_the_bundle(make_client):
    written: list[Path] = []

    def export(session_id, out):
        Path(out).write_bytes(b"PK bundle")
        written.append(Path(out))
        return {"session_id": session_id, "files": []}

    client = make_client(FakeSession(export_benchmark=export))

    response = client.get("/api/benchmarks/bench_1/export")

    assert response.status_code == 200
    assert response.content == b"PK bundle"
    assert response.headers["content-type"] == "application/zip"
    assert "bench_1.zip" in response.headers["content-disposition"]
    assert not written[0].parent.exists()


def test_unknown_session_is_404_and_a_bad_id_400(make_client):
    def missing(session_id, out):
        raise FileNotFoundError(f"Benchmark session not found: {session_id}")

    def invalid(session_id, out):
        raise ValueError(f"Not a benchmark session id: {session_id}")

    assert make_client(FakeSession(export_benchmark=missing)).get("/api/benchmarks/bench_404/export").status_code == 404
    assert make_client(FakeSession(export_benchmark=invalid)).get("/api/benchmarks/bad..id/export").status_code == 400


def test_sessions_and_views_are_served(make_client):
    session = FakeSession(
        list_benchmarks=[{"session_id": "s_a", "status": "completed"}],
        benchmark_results=lambda ids: [{"repository": "r", "runs": ids}],
        benchmark_steps=lambda ids: {"r": [{"step": "Node", "score": 1.0}]},
        benchmark_flips=lambda ids, repo: [{"source": f"{repo}:{len(ids)}"}],
        benchmark_inspector=lambda ids, repo: {"repository": repo, "runs": ids},
    )
    client = make_client(session)

    assert client.get("/api/benchmarks?limit=5").json() == [{"session_id": "s_a", "status": "completed"}]
    assert session.called("list_benchmarks") == [((5,), {})]
    assert client.get("/api/benchmarks/results?sessions=s_a,s_b").json() == [{"repository": "r", "runs": ["s_a", "s_b"]}]
    assert client.get("/api/benchmarks/steps?sessions=s_a").json() == {"r": [{"step": "Node", "score": 1.0}]}
    assert client.get("/api/benchmarks/flips?sessions=s_a,s_b&repo=r").json() == [{"source": "r:2"}]
    assert client.get("/api/benchmarks/inspector?sessions=s_a&repo=r").json() == {"repository": "r", "runs": ["s_a"]}


def test_views_need_sessions_and_report_missing_ones(make_client):
    def missing(ids):
        raise FileNotFoundError(f"Benchmark session not found: {ids[-1]}")

    client = make_client(FakeSession(benchmark_results=missing))

    assert client.get("/api/benchmarks/results?sessions=").status_code == 400
    assert client.get("/api/benchmarks/results?sessions=nope").status_code == 404


def benchmark_session(results):
    """A fake session whose run_benchmark reports two runs through the progress reporter."""

    def run_benchmark(**kwargs):
        progress = kwargs["progress"]
        session_id = results.pop(0)
        progress.start_benchmark(session_id, kwargs["runs"], kwargs["repositories"], kwargs["models"])
        for n in range(1, kwargs["runs"] + 1):
            progress.start_run(n, kwargs["repositories"][0], kwargs["models"][0], n)
            progress.start_phase("extraction", 1)
            progress.start_step("Repository")
            progress.complete_step("1 node")
            progress.complete_run("completed", {"elements": 5})
        progress.complete_benchmark(kwargs["runs"], 0, 1.5)
        return SimpleNamespace(session_id=session_id, runs_completed=kwargs["runs"], runs_failed=0, errors=[])

    return FakeSession(run_benchmark=run_benchmark)


def test_a_benchmark_streams_its_progress_and_names_its_session(make_client):
    session = benchmark_session(["bench_x"])
    client = make_client(session)

    response = client.post("/api/benchmarks", json={"repositories": ["r"], "model": "m", "runs": 2, "stages": ["derivation"]})
    run_id = response.json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    kwargs = session.called("run_benchmark")[0][1]
    assert (kwargs["repositories"], kwargs["models"], kwargs["runs"], kwargs["stages"], kwargs["use_cache"], kwargs["per_repo"]) == (["r"], ["m"], 2, ["derivation"], False, True)
    events = list(client.app.state.runs.events(run_id))
    assert events[0]["data"]["kind"] == "benchmark"
    steps = [(e["data"]["step"], e["data"]["status"]) for e in events if e["event"] == "progress"]
    assert ("run 1 · r · m · 1", "running") in steps
    assert ("Repository", "complete") in steps
    assert events[-1]["event"] == "finished"
    assert events[-1]["data"] == {"sessions": ["bench_x"], "runs_completed": 2, "runs_failed": 0}


def test_separate_sessions_run_one_benchmark_per_run(make_client):
    session = benchmark_session(["bench_1", "bench_2", "bench_3"])
    client = make_client(session)

    run_id = client.post("/api/benchmarks", json={"repositories": ["r"], "model": "m", "runs": 3, "separate_sessions": True}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    assert [c[1]["runs"] for c in session.called("run_benchmark")] == [1, 1, 1]
    assert client.app.state.runs.get(run_id).events[-1]["data"]["sessions"] == ["bench_1", "bench_2", "bench_3"]


def test_cancel_stops_a_benchmark_at_the_next_callback(make_client):
    release = threading.Event()

    def run_benchmark(**kwargs):
        progress = kwargs["progress"]
        progress.start_run(1, "r", "m", 1)
        release.wait(5)
        progress.start_step("Next")
        return SimpleNamespace(session_id="never", runs_completed=1, runs_failed=0, errors=[])

    client = make_client(FakeSession(run_benchmark=run_benchmark))
    run_id = client.post("/api/benchmarks", json={"repositories": ["r"], "model": "m", "runs": 1}).json()["run_id"]
    wait_for(lambda: len(client.app.state.runs.get(run_id).events) >= 2)

    client.post(f"/api/runs/{run_id}/cancel")
    release.set()
    wait_for(lambda: finished(client, run_id))

    run = client.app.state.runs.get(run_id)
    assert run.status == "cancelled"
    assert "Next" not in [e["data"].get("step") for e in run.events]


def test_a_benchmark_request_is_checked(make_client):
    client = make_client(FakeSession())

    assert client.post("/api/benchmarks", json={"repositories": [], "model": "m"}).status_code == 422
    assert client.post("/api/benchmarks", json={"repositories": ["r"], "model": "m", "runs": 0}).status_code == 422


def test_models_are_listed_without_keys(make_client):
    models = {"m": SimpleNamespace(name="m", provider="azure", model="gpt", api_url="https://example.test", api_key="sk-secret", api_key_env="KEY")}
    client = make_client(FakeSession(list_benchmark_models=models))

    response = client.get("/api/benchmarks/models")

    assert response.json() == [{"name": "m", "provider": "azure", "model": "gpt"}]
    assert "sk-secret" not in response.text
