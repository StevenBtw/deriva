"""One pipeline run at a time in a worker thread; its progress kept as numbered events for live streams.

Each run keeps its folder (<runs_dir>/<run_id>): the summary (run.json), the LLM calls (llm.jsonl), the inputs and the
events (events.jsonl), so a run of an earlier studio process can still be replayed from the history.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deriva.services import about, derivation
from deriva.services.llm_log import LlmCallLog, summarize_call
from deriva.studio.provider import SessionProvider

RUNS_DIR = about.workspace() / "runs"
TERMINAL = ("finished", "cancelled", "error")
EVENTS_FILE = "events.jsonl"
# After each step a followed run leaves the session free this long (less once a view took it), so live views refresh mid-run
VIEW_WINDOW = 0.25


class BenchmarkCancelled(RuntimeError):
    """Raised from a progress callback once a cancel was requested."""


class RunBusy(RuntimeError):
    """A run is already in progress."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run {run_id} is in progress")
        self.run_id = run_id


@dataclass
class RunState:
    run_id: str
    kind: str
    repository: str | None
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_requested: bool = False
    log_path: str | None = None
    followers: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "repository": self.repository,
            "status": self.status,
            "events": len(self.events),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _as_dict(update: Any) -> dict[str, Any]:
    if dataclasses.is_dataclass(update) and not isinstance(update, type):
        return dataclasses.asdict(update)
    return dict(update)


class RunManager:
    """Starts runs, records their events, lets streams follow them; the session lock is taken once per step."""

    def __init__(self, provider: SessionProvider, runs_dir: str | Path = RUNS_DIR) -> None:
        self._provider = provider
        self._runs_dir = Path(runs_dir)
        self._lock = threading.Lock()
        self._changed = threading.Condition()
        self._runs: dict[str, RunState] = {}
        self._current: RunState | None = None

    def start(self, kind: str, repository: str | None = None, no_llm: bool = False) -> str:
        return self._launch(kind, repository, {"kind": kind, "repository": repository}, lambda run: self._work(run, no_llm))

    def start_benchmark(self, settings: dict[str, Any], bench: Callable[[Any], Any]) -> str:
        """Run a benchmark (or, with ``separate_sessions``, one one-run session per run) holding the session throughout.

        ``bench`` turns the held PipelineSession into one with the benchmark operations (``app.state.bench``).
        """
        return self._launch("benchmark", None, {"kind": "benchmark", **settings}, lambda run: self._work_benchmark(run, settings, bench))

    def _launch(self, kind: str, repository: str | None, started: dict[str, Any], work: Any) -> str:
        with self._lock:
            if self._current is not None and self._current.status == "running":
                raise RunBusy(self._current.run_id)
            run = RunState(run_id=uuid.uuid4().hex[:12], kind=kind, repository=repository)
            self._runs[run.run_id] = run
            self._current = run
        self._emit(run, "started", started)
        threading.Thread(target=work, args=(run,), name=f"studio-run-{run.run_id}", daemon=True).start()
        return run.run_id

    def while_idle(self, action: Callable[[], Any]) -> Any:
        """Run ``action`` with no run in progress, under the lock that starts runs (none can start meanwhile)."""
        with self._lock:
            if self._current is not None and self._current.status == "running":
                raise RunBusy(self._current.run_id)
            return action()

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def _folder(self, run_id: str) -> Path | None:
        """A run's folder in the runs folder (None for an id that would name a path elsewhere)."""
        if not run_id or run_id in (".", "..") or any(sep in run_id for sep in ("/", "\\")):
            return None
        return self._runs_dir / run_id

    def log_path(self, run_id: str) -> str | None:
        """The run's call log: of a run of this process, else the one a run left in its folder (before a restart)."""
        run = self._runs.get(run_id)
        if run is not None:
            return run.log_path
        folder = self._folder(run_id)
        path = folder / "llm.jsonl" if folder is not None else None
        return str(path) if path is not None and path.is_file() else None

    def known(self, run_id: str) -> bool:
        """Whether the studio knows the run: of this process, or one whose folder kept its summary, events or calls."""
        folder = self._folder(run_id)
        return run_id in self._runs or (folder is not None and any((folder / name).is_file() for name in ("run.json", EVENTS_FILE, "llm.jsonl")))

    def events_kept(self, run_id: str) -> bool:
        """Whether the run's events can be streamed: a run of this process, or one whose folder kept them."""
        folder = self._folder(run_id)
        return run_id in self._runs or (folder is not None and (folder / EVENTS_FILE).is_file())

    def current(self) -> dict[str, Any] | None:
        return self._current.summary() if self._current is not None else None

    def history(self, limit: int = 10) -> list[dict[str, Any]]:
        """The studio's runs, newest first: its latest run (in progress or just ended), then the summaries runs left in their folders."""
        rows: dict[str, dict[str, Any]] = {}
        for path in self._runs_dir.glob("*/run.json"):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            if isinstance(row, dict) and row.get("run_id"):
                rows[str(row["run_id"])] = row | {"events_kept": self.events_kept(str(row["run_id"]))}
        # The latest run from memory, also once it ended: its summary is written after its status changes (or not at all
        # when the write fails), and memory is never older than the file
        current = self._current
        if current is not None:
            rows[current.run_id] = current.summary() | {"events_kept": True}
        return sorted(rows.values(), key=lambda row: row.get("started_at") or 0, reverse=True)[:limit]

    def cancel(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        return True

    def stop(self, timeout: float) -> bool:
        """Cancel the run in progress and wait up to ``timeout`` seconds for it to end (studio shutdown); True when none runs."""
        run = self._current
        if run is None or run.status in TERMINAL:
            return True
        run.cancel_requested = True
        with self._changed:
            return self._changed.wait_for(lambda: run.status in TERMINAL, timeout)

    def events(self, run_id: str, after: int = 0, poll: float = 0.5) -> Iterator[dict[str, Any]]:
        """Events with seq > after, waiting for new ones until the run has ended and all were sent; a run of an earlier
        studio process replays the events its folder kept (it ended, or ended with that process)."""
        run = self._runs.get(run_id)
        if run is None:
            yield from (e for e in self._stored_events(run_id) if e["seq"] > after)
            return
        sent = after
        with self._changed:
            run.followers += 1
        try:
            while True:
                with self._changed:
                    pending = [e for e in run.events if e["seq"] > sent]
                    if not pending and run.status in TERMINAL:
                        return
                    if not pending:
                        self._changed.wait(poll)
                        continue
                for event in pending:
                    sent = event["seq"]
                    yield event
        finally:
            with self._changed:
                run.followers -= 1

    def _stored_events(self, run_id: str) -> list[dict[str, Any]]:
        """The events a run's folder kept, in order (a line that cannot be read ends them: the process stopped mid-write)."""
        folder = self._folder(run_id)
        events: list[dict[str, Any]] = []
        try:
            lines = (folder / EVENTS_FILE).read_text(encoding="utf-8").splitlines() if folder is not None else []
        except OSError:
            return events
        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                break
            if not isinstance(event, dict) or event.get("seq") != len(events) + 1:
                break
            events.append(event)
        return events

    def _emit(self, run: RunState, event: str, data: dict[str, Any]) -> None:
        with self._changed:
            entry = {"seq": len(run.events) + 1, "event": event, "data": data, "ts": time.time()}
            run.events.append(entry)
            # Kept in the run's folder as it happens, so the history can replay it after a restart (best effort)
            try:
                folder = self._runs_dir / run.run_id
                folder.mkdir(parents=True, exist_ok=True)
                with open(folder / EVENTS_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, default=str) + "\n")
            except OSError:
                pass
            self._changed.notify_all()

    def _finish(self, run: RunState, status: str, data: dict[str, Any]) -> None:
        self._emit(run, status, data)
        with self._changed:
            run.status = status
            run.finished_at = time.time()
            self._changed.notify_all()
        # The run's summary stays in its folder: the studio's run history, also after a restart
        try:
            folder = self._runs_dir / run.run_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "run.json").write_text(json.dumps(run.summary(), indent=2), encoding="utf-8")
        except OSError:
            pass

    def _steps(self, session: Any, run: RunState, no_llm: bool) -> Generator[Any]:
        if run.kind in ("all", "extraction"):
            yield from session.run_extraction_iter(repo_name=run.repository, no_llm=no_llm)
        if run.kind in ("all", "derivation"):
            # A step's candidates, before its LLM calls: the studio pulses them in the graph
            def candidates(step: str, ids: list[str]) -> None:
                self._emit(run, "progress", {"phase": "derivation", "step": step, "status": "processing", "candidates": ids[:300]})

            if no_llm:
                # Structural steps only: derivation's phases without LLM calls, and the model stays
                yield from session.run_derivation_iter(phases=list(derivation.STRUCTURAL_PHASES), on_candidates=candidates)
                return
            # The studio's derivation scopes are full runs: they start from an empty model unless the setting is off
            if derivation.start_full_derivation(session):
                yield {"phase": "derivation", "step": "Clear model", "status": "complete", "message": "model cleared before the full run"}
            yield from session.run_derivation_iter(on_candidates=candidates)

    def _open_log(self, session: Any, run: RunState) -> LlmCallLog:
        """A call log for this run (<runs_dir>/<run_id>/llm.jsonl), attached to the session; live calls become ``llm`` events."""
        path = self._runs_dir / run.run_id / "llm.jsonl"
        log = LlmCallLog(path, run.run_id)
        log.add_listener(lambda call: self._emit(run, "llm", summarize_call(call)))
        session.attach_call_log(log)
        run.log_path = str(path)
        return log

    def _work(self, run: RunState, no_llm: bool) -> None:
        log: LlmCallLog | None = None
        try:
            with self._provider.session(wait=None) as session:
                if run.repository:
                    session.use_repository(run.repository)
                log = self._open_log(session, run)
                # What the run is about to run on, next to its call log
                session.write_run_inputs(self._runs_dir / run.run_id, run.run_id)
                steps = self._steps(session, run, no_llm)
            while True:
                if run.cancel_requested:
                    steps.close()
                    self._close_log(log)
                    self._finish(run, "cancelled", {})
                    return
                with self._provider.session(wait=None):
                    try:
                        update = next(steps)
                    except StopIteration:
                        break
                data = _as_dict(update)
                # A step that failed and let the run go on keeps its calls too (else the next step would get them)
                if log is not None and data.get("status") in ("complete", "error") and data.get("step"):
                    log.assign_step(data["step"])
                entries = self._provider.entries
                self._emit(run, "progress", data)
                # A completed step refreshes the studio's views: let their requests in before the next step
                if data.get("status") == "complete" and run.followers:
                    self._provider.wait_for_entry(entries, VIEW_WINDOW)
            self._close_log(log)
            self._finish(run, "finished", {})
        except Exception as exc:
            self._close_log(log)
            self._finish(run, "error", {"message": str(exc)})

    def _work_benchmark(self, run: RunState, settings: dict[str, Any], bench: Callable[[Any], Any]) -> None:
        reporter = BenchmarkEvents(lambda data: self._emit(run, "progress", data), lambda: run.cancel_requested)
        separate = bool(settings.get("separate_sessions"))
        rounds, runs_each = (settings["runs"], 1) if separate else (1, settings["runs"])
        sessions: list[str] = []
        completed = failed = 0
        try:
            with self._provider.session(wait=None) as session:
                for _ in range(rounds):
                    result = bench(session).run_benchmark(
                        repositories=settings["repositories"],
                        models=[settings["model"]],
                        runs=runs_each,
                        stages=settings.get("stages"),
                        description=settings.get("description", ""),
                        use_cache=settings.get("use_cache", False),
                        per_repo=settings.get("per_repo", True),
                        no_cache_extraction=settings.get("no_cache_extraction", False),
                        progress=reporter,
                    )
                    sessions.append(result.session_id)
                    completed += result.runs_completed
                    failed += result.runs_failed
                    if run.cancel_requested:
                        break
            status = "cancelled" if run.cancel_requested else "finished"
            self._finish(run, status, {"sessions": sessions, "runs_completed": completed, "runs_failed": failed})
        except BenchmarkCancelled:
            self._finish(run, "cancelled", {"sessions": sessions, "runs_completed": completed, "runs_failed": failed})
        except Exception as exc:
            self._finish(run, "error", {"message": str(exc), "sessions": sessions})

    def _close_log(self, log: LlmCallLog | None) -> None:
        if log is None:
            return
        log.close()
        with self._provider.session(wait=None) as session:
            session.detach_call_log()


class BenchmarkEvents:
    """A benchmark progress reporter that turns callbacks into run events; a requested cancel stops at the next callback."""

    def __init__(self, emit: Any, cancelled: Any) -> None:
        self._emit = emit
        self._cancelled = cancelled
        self._phase = "benchmark"
        self._step: str | None = None
        self._run = ""

    def _check(self) -> None:
        if self._cancelled():
            raise BenchmarkCancelled("Benchmark cancelled")

    def _progress(self, phase: str | None = None, **data: Any) -> None:
        self._emit({"phase": phase or self._phase, **data})

    def start_benchmark(self, session_id: str, total_runs: int, repositories: list[str], models: list[str]) -> None:
        self._check()
        self._progress("benchmark", step=session_id, status="running", message=f"{total_runs} runs · {', '.join(repositories)} · {', '.join(models)}")

    def start_run(self, run_number: int, repository: str, model: str, iteration: int) -> None:
        self._check()
        self._run = f"run {run_number} · {repository} · {model} · {iteration}"
        self._progress("benchmark", step=self._run, status="running")

    def complete_run(self, status: str, stats: dict[str, Any] | None = None) -> None:
        self._progress("benchmark", step=self._run, status="complete", message=status, stats=stats or {})

    def complete_benchmark(self, runs_completed: int, runs_failed: int, duration_seconds: float) -> None:
        self._progress("benchmark", step="session", status="complete", message=f"{runs_completed} completed, {runs_failed} failed, {duration_seconds:.0f} s")

    def start_phase(self, name: str, total_steps: int) -> None:
        self._check()
        self._phase = name

    def start_step(self, name: str, total_items: int | None = None) -> None:
        self._check()
        self._step = name
        self._progress(step=name, status="running")

    def update(self, current: int | None = None, message: str = "") -> None:
        self._check()

    def advance(self, amount: int = 1) -> None:
        self._check()

    def complete_step(self, message: str = "") -> None:
        self._progress(step=self._step, status="complete", message=message)

    def complete_phase(self, message: str = "") -> None:
        self._phase = "benchmark"

    def log(self, message: str, level: str = "info") -> None:
        if level in ("warning", "error"):
            self._progress(step=self._step, status=level, message=message)
