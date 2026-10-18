"""Runs: one at a time, progress events, cancel, errors, resume after a dropped stream, busy reads."""

from __future__ import annotations

import json
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

    steps_seen = [(e["data"]["phase"], e["data"]["step"]) for e in client.app.state.runs.events(run_id) if e["event"] == "progress"]
    # The derivation part is a full run: it clears the model first (the setting's default)
    assert steps_seen == [("extraction", "S1"), ("derivation", "Clear model"), ("derivation", "S1"), ("derivation", "S2")]


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
    release, in_step = threading.Event(), threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        in_step.set()
        release.wait(5)
        yield Update(step="S2")
        yield Update(step="S3")

    client = make_client(FakeSession(run_extraction_iter=blocking, use_repository=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    # Cancel once S2 is under way: a cancel before it would stop the run before S2
    assert in_step.wait(5)

    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
    release.set()
    wait_for(lambda: finished(client, run_id))

    run = client.app.state.runs.get(run_id)
    assert run.status == "cancelled"
    assert [e["data"].get("step") for e in run.events if e["event"] == "progress"] == ["S1", "S2"]


def test_a_cancel_reaches_the_llm_calls_of_the_running_step(make_client):
    """The session's LLM calls see the cancel at once (a step's next call stops it), and the check is removed when the run ends."""
    release, in_step = threading.Event(), threading.Event()

    def blocking(*args, **kwargs):
        in_step.set()
        release.wait(5)
        yield Update(step="S1")

    session = FakeSession(run_extraction_iter=blocking, use_repository=None)
    client = make_client(session)
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    assert in_step.wait(5)
    (check,) = session.called("set_cancel_check")[0][0]
    assert check() is False

    client.post(f"/api/runs/{run_id}/cancel")
    assert check() is True
    release.set()
    wait_for(lambda: finished(client, run_id))

    assert client.app.state.runs.get(run_id).status == "cancelled"
    assert session.called("set_cancel_check")[-1] == ((None,), {})


def test_a_step_stopped_by_the_cancel_ends_the_run_as_cancelled(make_client):
    from deriva.services import RunCancelled

    in_step, cancelled = threading.Event(), threading.Event()

    def stopped(*args, **kwargs):
        yield Update(step="S1")
        in_step.set()
        cancelled.wait(5)
        raise RunCancelled("run cancelled")

    client = make_client(FakeSession(run_extraction_iter=stopped, use_repository=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    assert in_step.wait(5)
    client.post(f"/api/runs/{run_id}/cancel")
    cancelled.set()
    wait_for(lambda: finished(client, run_id))

    assert client.app.state.runs.get(run_id).status == "cancelled"


def test_shutdown_ends_the_event_streams_and_cancels_the_run(make_client):
    """uvicorn waits for open streams before the app's shutdown, and a stream lasts until its run ends: shutdown ends both."""
    release, in_step = threading.Event(), threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        in_step.set()
        release.wait(5)
        yield Update(step="S2")

    client = make_client(FakeSession(run_extraction_iter=blocking, use_repository=None))
    runs = client.app.state.runs
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    assert in_step.wait(5)
    ended = threading.Event()
    threading.Thread(target=lambda: (list(runs.events(run_id)), ended.set()), daemon=True).start()
    wait_for(lambda: runs.get(run_id).followers == 1)

    runs.shutdown()

    assert ended.wait(2)
    assert runs.get(run_id).cancel_requested
    release.set()
    wait_for(lambda: finished(client, run_id))


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
    """History lists the studio's own runs (not the legacy runs table of the config database)."""
    session = FakeSession(run_extraction_iter=steps(1), use_repository=None, get_runs=[{"run_id": 7, "description": "marimo test run"}])
    client = make_client(session)

    assert client.get("/api/runs/current").json() is None
    run_id = client.post("/api/runs", json={"kind": "extraction", "repository": "deriva"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    assert client.get("/api/runs/current").json()["run_id"] == run_id
    history = client.get("/api/runs/history?limit=5").json()
    assert [(h["run_id"], h["kind"], h["repository"], h["status"]) for h in history] == [(run_id, "extraction", "deriva", "finished")]
    assert session.called("get_runs") == []


def test_finished_runs_are_kept_on_disk_newest_first(tmp_path):
    """A run's summary is written when it ends, so the history survives a restart of the studio."""
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    def manager():
        session = FakeSession(run_extraction_iter=steps(1), run_derivation_iter=steps(1, "derivation"), use_repository=None)
        return RunManager(SessionProvider(factory=lambda: session), runs_dir=tmp_path)

    first = manager()
    one = first.start("extraction", "deriva")
    wait_for(lambda: first.get(one).status == "finished")
    two = first.start("derivation", "ToolShed")
    wait_for(lambda: first.get(two).status == "finished")
    (tmp_path / "old-folder-without-summary").mkdir()
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "run.json").write_text("{not json", encoding="utf-8")

    history = manager().history(limit=5)

    assert [(h["run_id"], h["kind"], h["repository"], h["status"]) for h in history] == [(two, "derivation", "ToolShed", "finished"), (one, "extraction", "deriva", "finished")]
    assert history[0]["finished_at"] >= history[0]["started_at"]
    assert len(manager().history(limit=1)) == 1


def test_a_run_the_studio_stopped_on_is_listed_as_interrupted(tmp_path):
    """A run writes its summary when it ends; one whose studio process ended first left only its events."""
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    folder = tmp_path / "crashed12345"
    folder.mkdir()
    events = [
        {"seq": 1, "event": "started", "data": {"kind": "all", "repository": "deriva"}, "ts": 100.0},
        {"seq": 2, "event": "progress", "data": {"step": "S1"}, "ts": 160.5},
    ]
    (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events) + '{"seq": 3, "ev', encoding="utf-8")
    (tmp_path / "no-start").mkdir()
    (tmp_path / "no-start" / "events.jsonl").write_text(json.dumps({"seq": 1, "event": "progress", "data": {}, "ts": 1.0}) + "\n", encoding="utf-8")

    history = RunManager(SessionProvider(factory=lambda: FakeSession()), runs_dir=tmp_path).history()

    assert history == [
        {
            "run_id": "crashed12345",
            "kind": "all",
            "repository": "deriva",
            "status": "interrupted",
            "events": 2,
            "started_at": 100.0,
            "finished_at": 160.5,
            "events_kept": True,
        }
    ]


def test_the_replay_of_an_interrupted_run_ends_with_an_error(tmp_path):
    """Without an end event the browser would reconnect to the replay for ever; the replay ends it (not stored)."""
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    folder = tmp_path / "crashed12345"
    folder.mkdir()
    started = {"seq": 1, "event": "started", "data": {"kind": "all"}, "ts": 100.0}
    (folder / "events.jsonl").write_text(json.dumps(started) + "\n", encoding="utf-8")
    runs = RunManager(SessionProvider(factory=lambda: FakeSession()), runs_dir=tmp_path)

    replay = list(runs.events("crashed12345"))

    assert [(e["seq"], e["event"]) for e in replay] == [(1, "started"), (2, "error")]
    assert replay[1]["data"] == {"message": "The studio stopped before the run ended", "interrupted": True}
    assert list(runs.events("crashed12345", after=2)) == []
    assert (folder / "events.jsonl").read_text(encoding="utf-8").count("\n") == 1


def test_a_finished_run_is_in_the_history_before_and_without_its_summary_on_disk(tmp_path, monkeypatch):
    """The run's status changes before run.json is written (and a failed write is swallowed): history must not lose it."""
    from pathlib import Path

    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    real_write = Path.write_text

    def no_summary(self, *args, **kwargs):
        if self.name == "run.json":
            raise OSError("disk full")
        return real_write(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", no_summary)
    session = FakeSession(run_extraction_iter=steps(1), use_repository=None)
    manager = RunManager(SessionProvider(factory=lambda: session), runs_dir=tmp_path)

    run_id = manager.start("extraction", "deriva")
    wait_for(lambda: manager.get(run_id).status == "finished")

    assert [(h["run_id"], h["status"]) for h in manager.history(limit=5)] == [(run_id, "finished")]


def test_a_running_run_heads_the_history(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    release = threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        release.wait(5)
        yield Update(step="S2")

    runs = RunManager(SessionProvider(factory=lambda: FakeSession(run_extraction_iter=blocking, use_repository=None)), runs_dir=tmp_path)
    run_id = runs.start("extraction", "deriva")
    wait_for(lambda: len(runs.get(run_id).events) >= 2)

    assert [(h["run_id"], h["status"]) for h in runs.history(limit=5)] == [(run_id, "running")]
    release.set()
    wait_for(lambda: runs.get(run_id).status == "finished")
    assert [(h["run_id"], h["status"]) for h in runs.history(limit=5)] == [(run_id, "finished")]


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


def test_the_calls_of_a_run_from_before_a_restart_are_served_from_its_folder(make_client):
    """The studio's history lists runs of earlier processes; their saved calls open under Prompts."""
    first = make_client(llm_session())
    run_id = first.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(first, run_id))

    restarted = make_client(FakeSession())  # a new studio process on the same runs folder
    calls = restarted.get(f"/api/runs/{run_id}/calls").json()

    assert [c["seq"] for c in calls] == [1, 2, 3]
    assert restarted.get(f"/api/runs/{run_id}/calls/{calls[2]['call_id']}").json()["prompt"] == "name it"
    assert restarted.get("/api/runs/nope/calls").status_code == 404


def test_the_live_log_of_a_run_from_before_a_restart_replays_from_its_folder(make_client, tmp_path):
    """A run's events are kept in its folder: a restarted studio replays them (also after a Last-Event-ID), as it serves
    the calls, instead of answering 404 for a run the history lists."""
    first = make_client(FakeSession(run_extraction_iter=steps(2), use_repository=None))
    run_id = first.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(first, run_id))
    with first.stream("GET", f"/api/runs/{run_id}/events") as response:
        live = "".join(response.iter_text())

    restarted = make_client(FakeSession())  # a new studio process on the same runs folder
    with restarted.stream("GET", f"/api/runs/{run_id}/events") as response:
        replayed = "".join(response.iter_text())
    with restarted.stream("GET", f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "3"}) as response:
        resumed = "".join(response.iter_text())

    assert response.status_code == 200 and replayed == live
    assert "id: 3\n" not in resumed and "id: 4\nevent: finished" in resumed
    assert [(h["run_id"], h["events_kept"]) for h in restarted.get("/api/runs/history").json()] == [(run_id, True)]
    assert (tmp_path / "runs" / run_id / "events.jsonl").is_file()


def test_a_run_without_llm_calls_has_no_calls_also_after_a_restart(make_client):
    """A structural run makes no LLM call, so its folder has no call log: a restarted studio answers no calls, not 404."""
    first = make_client(FakeSession(run_derivation_iter=steps(2, "derivation"), use_repository=None))
    run_id = first.post("/api/runs", json={"kind": "derivation", "no_llm": True}).json()["run_id"]
    wait_for(lambda: finished(first, run_id))

    restarted = make_client(FakeSession())

    assert restarted.get(f"/api/runs/{run_id}/calls").json() == []
    assert restarted.get(f"/api/runs/{run_id}/calls/c1").status_code == 404
    assert restarted.get("/api/runs/never-ran/calls").status_code == 404


def test_a_kept_live_log_replays_up_to_its_first_unreadable_line(tmp_path):
    """A studio stopped mid-write leaves a cut line, and a gap means lost events: the replay ends at the last whole event
    in order, then the end of an interrupted run. A log that cannot be read replays nothing."""
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    def event(seq):
        return json.dumps({"seq": seq, "event": "progress", "data": {"step": f"S{seq}"}, "ts": 1.0})

    runs = RunManager(SessionProvider(factory=FakeSession), runs_dir=tmp_path)
    for run_id, lines in {"cut": [event(1), event(2), '{"seq": 3, "ev'], "gap": [event(1), event(3)], "wrong": [event(1), "[1, 2]"]}.items():
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "unreadable" / "events.jsonl").mkdir(parents=True)  # a folder where the log should be

    assert [(e["seq"], e["event"]) for e in runs.events("cut")] == [(1, "progress"), (2, "progress"), (3, "error")]
    assert [e["seq"] for e in runs.events("cut", after=1)] == [2, 3]
    assert [(e["seq"], e["event"]) for e in runs.events("gap")] == [(1, "progress"), (2, "error")]
    assert [(e["seq"], e["event"]) for e in runs.events("wrong")] == [(1, "progress"), (2, "error")]
    assert list(runs.events("unreadable")) == []


def test_a_run_id_never_names_a_path_outside_the_runs_folder(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    (tmp_path / "runs").mkdir()
    (tmp_path / "events.jsonl").write_text("{}\n", encoding="utf-8")  # one level above the runs folder
    runs = RunManager(SessionProvider(factory=FakeSession), runs_dir=tmp_path / "runs")

    for run_id in ("", ".", "..", "../runs", "a/b", "a\\b"):
        assert (runs.known(run_id), runs.events_kept(run_id), runs.log_path(run_id), list(runs.events(run_id))) == (False, False, None, [])


def test_a_run_whose_events_cannot_be_written_still_runs_and_streams(tmp_path, monkeypatch):
    """Keeping the live log is best effort: a run folder that refuses the log (here a folder in its place) changes nothing
    for the run or for the studio following it."""
    from types import SimpleNamespace

    from deriva.studio import runs as runs_module
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    monkeypatch.setattr(runs_module.uuid, "uuid4", lambda: SimpleNamespace(hex="fixedrunid0000"))
    (tmp_path / "fixedrunid00" / "events.jsonl").mkdir(parents=True)
    runs = RunManager(SessionProvider(factory=lambda: FakeSession(run_extraction_iter=steps(2), use_repository=None)), runs_dir=tmp_path)

    run_id = runs.start("extraction", "deriva")
    wait_for(lambda: runs.get(run_id).status != "running")

    assert run_id == "fixedrunid00" and runs.get(run_id).status == "finished"
    assert [e["event"] for e in runs.events(run_id)] == ["started", "progress", "progress", "finished"]


def test_a_run_without_a_kept_live_log_says_so_in_the_history(make_client, tmp_path):
    """A run recorded before live logs were kept has only its summary and calls: the history says the log is not kept, so
    the studio does not ask for it, and its events stay unknown (404). A run id never names a path outside the runs folder."""
    folder = tmp_path / "runs" / "0e27716fc983"
    folder.mkdir(parents=True)
    summary = {"run_id": "0e27716fc983", "kind": "derivation", "repository": "deriva", "status": "finished", "events": 87, "started_at": 1.0, "finished_at": 2.0}
    (folder / "run.json").write_text(json.dumps(summary), encoding="utf-8")
    client = make_client(FakeSession())

    assert [(h["run_id"], h["events_kept"]) for h in client.get("/api/runs/history").json()] == [("0e27716fc983", False)]
    assert client.get("/api/runs/0e27716fc983/events").status_code == 404
    assert client.get("/api/runs/..%2Fruns/events").status_code == 404


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


def test_a_structural_run_derives_the_prep_phase_only_and_keeps_the_model(make_client):
    """Structural steps only (no_llm): no LLM calls, so derivation is its prep phase and the model is not cleared."""
    session = FakeSession(run_extraction_iter=steps(1), run_derivation_iter=steps(1, "derivation"), use_repository=None, get_setting="true")
    client = make_client(session)

    run_id = client.post("/api/runs", json={"kind": "all", "no_llm": True}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    assert session.called("run_extraction_iter")[0][1]["no_llm"] is True
    assert session.called("run_derivation_iter")[0][1]["phases"] == ["prep"]
    assert session.called("clear_model") == []


def test_derivation_candidates_become_processing_events(make_client):
    def derive(on_candidates=None, **kwargs):
        on_candidates("ApplicationComponent", [f"n{i}" for i in range(400)])
        yield Update(phase="derivation", step="ApplicationComponent", current=1, total=1)

    # The model clearing at the start is tested on its own; here only the candidates matter
    client = make_client(FakeSession(run_derivation_iter=derive, get_setting="false"))
    run_id = client.post("/api/runs", json={"kind": "derivation"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    events = list(client.app.state.runs.events(run_id))
    progress = [e["data"] for e in events if e["event"] == "progress"]
    assert [p["status"] for p in progress] == ["processing", "complete"]
    assert progress[0]["step"] == "ApplicationComponent"
    assert progress[0]["candidates"][:2] == ["n0", "n1"]
    assert len(progress[0]["candidates"]) == 300


def test_a_view_requested_after_a_step_completes_is_served_before_the_next_step(tmp_path):
    """A followed run leaves the session free for a moment after each step, so live views refresh during the run."""
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    order: list[str] = []
    started: dict[str, str] = {}

    def recorded(*args, **kwargs):
        # The studio follows its runs from the start; wait for the follower so the test does not race it
        wait_for(lambda: "run" in started and manager.get(started["run"]).followers > 0)
        for i in (1, 2, 3):
            order.append(f"S{i}")
            yield Update(step=f"S{i}")

    provider = SessionProvider(factory=lambda: FakeSession(run_extraction_iter=recorded, use_repository=None))
    manager = RunManager(provider, runs_dir=tmp_path)
    run_id = started["run"] = manager.start("extraction")

    def view_after_first_step() -> None:
        for event in manager.events(run_id, poll=0.05):
            if event["event"] == "progress" and event["data"].get("step") == "S1":
                time.sleep(0.05)  # the browser's round trip
                with provider.session(wait=2.0):
                    order.append("view")

    follower = threading.Thread(target=view_after_first_step)
    follower.start()
    follower.join(10)

    assert order[:3] == ["S1", "view", "S2"]


def test_an_unfollowed_run_does_not_pause_between_steps(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    provider = SessionProvider(factory=lambda: FakeSession(run_extraction_iter=steps(8), use_repository=None))
    manager = RunManager(provider, runs_dir=tmp_path)
    began = time.time()
    run_id = manager.start("extraction")
    wait_for(lambda: manager.get(run_id).status == "finished")

    assert time.time() - began < 5.0


def test_a_derivation_run_starts_from_an_empty_model_and_says_so(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    session = FakeSession(run_derivation_iter=steps(1, phase="derivation"), use_repository=None)
    manager = RunManager(SessionProvider(factory=lambda: session), runs_dir=tmp_path)
    run_id = manager.start("derivation")
    wait_for(lambda: manager.get(run_id).status == "finished")

    assert len(session.called("clear_model")) == 1
    progress = [e["data"] for e in manager.get(run_id).events if e["event"] == "progress"]
    assert progress[0]["step"] == "Clear model" and progress[0]["status"] == "complete"
    assert progress[1]["step"] == "S1"


def test_a_derivation_run_keeps_the_model_when_the_setting_is_off(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    session = FakeSession(run_derivation_iter=steps(1, phase="derivation"), use_repository=None, get_setting="false")
    manager = RunManager(SessionProvider(factory=lambda: session), runs_dir=tmp_path)
    run_id = manager.start("derivation")
    wait_for(lambda: manager.get(run_id).status == "finished")

    assert session.called("clear_model") == []
    assert [e["data"]["step"] for e in manager.get(run_id).events if e["event"] == "progress"] == ["S1"]


def test_an_extraction_run_leaves_the_model_alone(tmp_path):
    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunManager

    session = FakeSession(run_extraction_iter=steps(1), use_repository=None)
    manager = RunManager(SessionProvider(factory=lambda: session), runs_dir=tmp_path)
    run_id = manager.start("extraction")
    wait_for(lambda: manager.get(run_id).status == "finished")

    assert session.called("clear_model") == []


def test_while_idle_runs_only_when_no_run_is_running(tmp_path):
    """The repository switch checks for a run and switches under the lock that starts runs (no run can start in between)."""
    import pytest

    from deriva.studio.provider import SessionProvider
    from deriva.studio.runs import RunBusy, RunManager, RunState

    manager = RunManager(SessionProvider(factory=lambda: FakeSession()), tmp_path)
    assert manager.while_idle(lambda: "switched") == "switched"

    manager._current = RunState(run_id="r1", kind="all", repository=None)
    with pytest.raises(RunBusy):
        manager.while_idle(lambda: "switched")


def test_the_calls_of_a_step_that_fails_keep_that_steps_name(make_client):
    """A step that reports an error and lets the run go on: its calls are not stamped with the next step's name."""
    logs = []

    def iterate(*args, **kwargs):
        logs[0].record(prompt="classify a", response="{}")
        yield Update(step="S1", status="error", message="LLM call failed")
        logs[0].record(prompt="name it", response="{}")
        yield Update(step="S2")

    client = make_client(FakeSession(run_extraction_iter=iterate, use_repository=None, attach_call_log=logs.append, detach_call_log=None))
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    calls = client.get(f"/api/runs/{run_id}/calls").json()
    assert [(c["step"], c["seq"]) for c in calls] == [("S1", 1), ("S2", 2)]


def test_shutdown_cancels_the_run_and_does_not_hang_on_a_long_step(tmp_path, monkeypatch):
    """Stopping the studio mid-run asks the run to stop and closes the session if it frees in time; it never waits a whole step."""
    from fastapi.testclient import TestClient

    from deriva.studio import app as studio_app
    from deriva.studio.provider import SessionProvider

    monkeypatch.setattr(studio_app, "SHUTDOWN_WAIT", 0.2)
    release, in_step = threading.Event(), threading.Event()

    def blocking(*args, **kwargs):
        yield Update(step="S1")
        in_step.set()
        release.wait(10)
        yield Update(step="S2")

    client = TestClient(
        studio_app.create_app(provider=SessionProvider(factory=lambda: FakeSession(run_extraction_iter=blocking, use_repository=None)), static_dir=None, runs_dir=tmp_path)
    )
    client.__enter__()
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    assert in_step.wait(5)

    began = time.time()
    client.__exit__(None, None, None)

    assert time.time() - began < 3
    run = client.app.state.runs.get(run_id)
    assert run.cancel_requested
    release.set()
    wait_for(lambda: run.status == "cancelled")


def test_closing_the_provider_gives_up_after_its_timeout_while_the_session_is_held(tmp_path):
    from deriva.studio.provider import SessionProvider

    provider = SessionProvider(factory=lambda: FakeSession())
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with provider.session(wait=None):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)

    assert provider.close(timeout=0.1) is False
    release.set()
    holder.join(5)
    assert provider.close(timeout=1.0) is True
