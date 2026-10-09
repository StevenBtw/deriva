"""Runs: one at a time, progress events, cancel, errors, resume after a dropped stream, busy reads."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from tests.test_studio.conftest import FakeSession


@dataclass
class Update:
    phase: str = "extraction"
    step: str = ""
    status: str = "complete"
    current: int = 0
    total: int = 3
    message: str = ""
    stats: dict = field(default_factory=dict)


def steps(n: int, phase: str = "extraction"):
    def iterate(*args, **kwargs):
        for i in range(1, n + 1):
            yield Update(phase=phase, step=f"S{i}", current=i, total=n, message=f"{i} created")

    return iterate


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def finished(client, run_id: str) -> bool:
    return client.app.state.runs.get(run_id).status != "running"


def test_extraction_run_emits_progress_then_finished(make_client):
    session = FakeSession(run_extraction_iter=steps(3), use_repository=None)
    client = make_client(session)

    run_id = client.post("/api/runs", json={"kind": "extraction", "repository": "deriva"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    events = list(client.app.state.runs.events(run_id))
    assert [e["event"] for e in events] == ["started", "progress", "progress", "progress", "finished"]
    assert events[1]["data"]["step"] == "S1"
    assert events[3]["data"]["message"] == "3 created"
    assert session.called("use_repository") == [(("deriva",), {})]
    assert session.called("run_extraction_iter")[0][1] == {"repo_name": "deriva", "no_llm": False}


def test_all_runs_extraction_then_derivation(make_client):
    session = FakeSession(run_extraction_iter=steps(1), run_derivation_iter=steps(2, "derivation"), use_repository=None)
    client = make_client(session)

    run_id = client.post("/api/runs", json={"kind": "all", "repository": "deriva"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    phases = [e["data"]["phase"] for e in client.app.state.runs.events(run_id) if e["event"] == "progress"]
    assert phases == ["extraction", "derivation", "derivation"]


def test_a_second_run_while_one_runs_is_409(make_client):
    release = threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        release.wait(5)
        yield Update(step="S2")

    client = make_client(FakeSession(run_extraction_iter=blocking, use_repository=None))
    first = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]

    response = client.post("/api/runs", json={"kind": "extraction"})

    assert response.status_code == 409
    assert response.json()["run_id"] == first
    release.set()
    wait_for(lambda: finished(client, first))


def test_cancel_stops_after_the_current_step(make_client):
    release = threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        release.wait(5)
        yield Update(step="S2")
        yield Update(step="S3")

    client = make_client(FakeSession(run_extraction_iter=blocking, use_repository=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: len(client.app.state.runs.get(run_id).events) >= 2)

    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    release.set()
    wait_for(lambda: finished(client, run_id))

    run = client.app.state.runs.get(run_id)
    assert run.status == "cancelled"
    assert [e["data"].get("step") for e in run.events if e["event"] == "progress"] == ["S1", "S2"]


def test_failing_step_ends_the_run_with_an_error_event(make_client):
    def failing(*args, **kwargs):
        yield Update(step="S1")
        raise RuntimeError("LLM provider unavailable")

    session = FakeSession(run_extraction_iter=failing, use_repository=None)
    client = make_client(session)
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    run = client.app.state.runs.get(run_id)
    assert run.status == "error"
    assert run.events[-1]["event"] == "error"
    assert run.events[-1]["data"]["message"] == "LLM provider unavailable"
    session.returns["run_extraction_iter"] = steps(1)
    assert client.post("/api/runs", json={"kind": "extraction"}).status_code == 202


def test_events_stream_as_server_sent_events(make_client):
    client = make_client(FakeSession(run_extraction_iter=steps(2), use_repository=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        body = "".join(response.iter_text())

    assert response.headers["content-type"].startswith("text/event-stream")
    assert body.count("event: progress") == 2
    assert "id: 1\nevent: started\ndata: " in body
    assert body.rstrip().endswith("}")
    assert "event: finished" in body


def test_events_resume_after_last_event_id(make_client):
    client = make_client(FakeSession(run_extraction_iter=steps(3), use_repository=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    with client.stream("GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "3"}) as response:
        body = "".join(response.iter_text())

    assert "id: 3\n" not in body
    assert "id: 4\nevent: progress" in body
    assert "id: 5\nevent: finished" in body


def test_api_read_during_a_step_answers_busy(make_client):
    in_step = threading.Event()
    release = threading.Event()

    def slow(*args, **kwargs):
        in_step.set()
        release.wait(5)
        yield Update(step="S1")

    client = make_client(FakeSession(run_extraction_iter=slow, use_repository=None, get_graph_stats={"total_nodes": 0}))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    in_step.wait(5)

    response = client.get("/api/graph/stats")

    assert response.status_code == 503
    assert response.json()["busy"] is True
    release.set()
    wait_for(lambda: finished(client, run_id))
    assert client.get("/api/graph/stats").status_code == 200


def test_current_run_and_history(make_client):
    client = make_client(FakeSession(run_extraction_iter=steps(1), use_repository=None, get_runs=[{"run_id": 7, "description": "x"}]))

    assert client.get("/api/runs/current").json() is None
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    assert client.get("/api/runs/current").json()["run_id"] == run_id
    assert client.get("/api/runs/history?limit=5").json() == [{"run_id": 7, "description": "x"}]


def llm_session():
    """A fake session whose extraction makes two LLM calls in step S1 and one in S2, through the attached log."""
    logs = []

    def iterate(*args, **kwargs):
        logs[0].record(prompt="classify a", response='{"a": 1}', cache_hit=False, latency_ms=10.0, tokens_in=50, tokens_out=5)
        logs[0].record(prompt="classify b", response='{"b": 2}', cache_hit=True, latency_ms=0.1, tokens_in=50, tokens_out=5)
        yield Update(step="S1", current=1, total=2)
        logs[0].record(prompt="name it", response="{}", cache_hit=False, latency_ms=8.0, tokens_in=20, tokens_out=3)
        yield Update(step="S2", current=2, total=2)

    return FakeSession(run_extraction_iter=iterate, use_repository=None, attach_call_log=logs.append, detach_call_log=None)


def test_llm_calls_stream_with_their_step_before_the_step_completes(make_client):
    client = make_client(llm_session())

    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    events = [(e["event"], e["data"].get("step")) for e in client.app.state.runs.events(run_id)]
    assert events == [("started", None), ("llm", "S1"), ("llm", "S1"), ("progress", "S1"), ("llm", "S2"), ("progress", "S2"), ("finished", None)]
    llm = [e["data"] for e in client.app.state.runs.events(run_id) if e["event"] == "llm"]
    assert llm[1]["cache_hit"] is True
    assert "prompt" not in llm[0]


def test_run_calls_are_kept_on_disk_and_served(make_client, tmp_path):
    client = make_client(llm_session())
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    calls = client.get(f"/api/runs/{run_id}/calls").json()
    assert [(c["step"], c["seq"]) for c in calls] == [("S1", 1), ("S1", 2), ("S2", 3)]
    assert "prompt" not in calls[0]
    detail = client.get(f"/api/runs/{run_id}/calls/{calls[2]['call_id']}").json()
    assert detail["prompt"] == "name it"
    assert (tmp_path / "runs" / run_id / "llm.jsonl").exists()
    assert client.get(f"/api/runs/{run_id}/calls/unknown").status_code == 404


def test_a_run_records_its_inputs_in_its_folder_before_the_first_step(make_client, tmp_path):
    session = llm_session()
    client = make_client(session)

    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    ((args, _),) = session.called("write_run_inputs")
    assert args == (tmp_path / "runs" / run_id, run_id)
    names = [name for name, _, _ in session.calls]
    assert names.index("write_run_inputs") < names.index("run_extraction_iter")


def test_unknown_run_and_kind(make_client):
    client = make_client(FakeSession())

    assert client.post("/api/runs/nope/cancel").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404
    assert client.post("/api/runs", json={"kind": "everything"}).status_code == 422
