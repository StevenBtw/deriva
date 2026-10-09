"""Per-run log of every LLM call: prompt, answer and metrics, as append-only JSON lines.

The LLM cache keeps one answer per prompt (the last one), so repeated runs overwrite each
other there; this log keeps every call of every run. Calls made before their step is known
wait in memory and are written, in order, once ``assign_step`` names the step (the studio's
runs report a step only when it completes; steps run one after another).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

Listener = Callable[[dict[str, Any]], None]

# What lists of calls show; prompt, system prompt and answer are fetched per call
SUMMARY_FIELDS = ("call_id", "seq", "step", "schema", "cache_hit", "latency_ms", "tokens_in", "tokens_out", "temperature", "error")


def summarize_call(call: dict[str, Any]) -> dict[str, Any]:
    return {key: call.get(key) for key in SUMMARY_FIELDS}


class LlmCallLog:
    """Append-only call log for one run."""

    def __init__(self, path: str | Path, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._seq = 0
        self._pending: list[dict[str, Any]] = []
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def record(self, step: str | None = None, **fields: Any) -> dict[str, Any]:
        """Add one call; written at once when ``step`` is given, otherwise when the step is assigned."""
        with self._lock:
            self._seq += 1
            call = {"call_id": uuid.uuid4().hex[:16], "run_id": self.run_id, "seq": self._seq, "ts": time.time(), "step": step, **fields}
            if step is None:
                self._pending.append(call)
                return call
            self._write([call])
        self._notify([call])
        return call

    def assign_step(self, step: str | None) -> list[dict[str, Any]]:
        """Stamp the waiting calls with ``step`` and append them to the file."""
        with self._lock:
            calls, self._pending = self._pending, []
            for call in calls:
                call["step"] = step
            self._write(calls)
        self._notify(calls)
        return calls

    def close(self) -> None:
        """Write calls still waiting for a step (without one)."""
        self.assign_step(None)

    def _write(self, calls: list[dict[str, Any]]) -> None:
        if not calls:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for call in calls:
                handle.write(json.dumps(call, ensure_ascii=False, default=str) + "\n")

    def _notify(self, calls: list[dict[str, Any]]) -> None:
        for call in calls:
            for listener in self._listeners:
                listener(call)

    @staticmethod
    def read(path: str | Path) -> list[dict[str, Any]]:
        """All calls of a log file, in file order (empty when the file does not exist)."""
        file = Path(path)
        if not file.exists():
            return []
        with file.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    @staticmethod
    def find(path: str | Path, call_id: str) -> dict[str, Any] | None:
        return next((call for call in LlmCallLog.read(path) if call["call_id"] == call_id), None)


def run_log_path(directory: str | Path, run_id: str) -> Path:
    """The call log file of one run in ``directory`` (run ids hold ':', which file names cannot)."""
    return Path(directory) / f"{re.sub(r'[^A-Za-z0-9._-]+', '_', run_id)}.jsonl"


def record_call(
    log: LlmCallLog,
    metrics: dict[str, Any],
    *,
    prompt: str,
    schema: dict | None,
    system_prompt: str | None,
    response: Any,
    error: str | None = None,
    step: str | None = None,
) -> dict[str, Any]:
    """Record one LLM call with the manager's ``last_call`` metrics; the output schema's name tells the call kind."""
    content = getattr(response, "content", None)
    if content is None and response is not None:
        content = response.model_dump_json() if hasattr(response, "model_dump_json") else str(response)
    return log.record(
        step=step,
        prompt=prompt,
        system_prompt=system_prompt,
        schema=schema.get("name") if isinstance(schema, dict) else None,
        response=content,
        error=error or getattr(response, "error", None),
        cache_key=metrics.get("cache_key"),
        provider=metrics.get("provider"),
        model=metrics.get("model"),
        temperature=metrics.get("temperature"),
        max_tokens=metrics.get("max_tokens"),
        cache_hit=metrics.get("cache_hit"),
        latency_ms=metrics.get("latency_ms"),
        tokens_in=metrics.get("input_tokens"),
        tokens_out=metrics.get("output_tokens"),
    )
