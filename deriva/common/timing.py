"""Timing collection for run summaries.

- QueryStats: per-query-text totals of graph query time (fed by the grafeo adapter).
- summarize_run_events: per-run timing summary from benchmark OCEL events.
"""

from __future__ import annotations

import threading
from typing import Any


class QueryStats:
    """Thread-safe totals of query time per normalised query text."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: dict[str, list[float]] = {}  # query -> [count, total_ms, max_ms]

    def record(self, query: str, elapsed_ms: float) -> None:
        key = " ".join(query.split())
        with self._lock:
            entry = self._stats.setdefault(key, [0, 0.0, 0.0])
            entry[0] += 1
            entry[1] += elapsed_ms
            entry[2] = max(entry[2], elapsed_ms)

    def top(self, limit: int = 10) -> list[dict[str, Any]]:
        """Queries with the highest total time, highest first."""
        with self._lock:
            rows = sorted(self._stats.items(), key=lambda kv: -kv[1][1])[:limit]
            # Build the result while holding the lock: the lists keep changing after it
            return [
                {
                    "query": q,
                    "count": int(c),
                    "total_ms": round(t, 1),
                    "max_ms": round(m, 1),
                }
                for q, (c, t, m) in rows
            ]

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()


# Process-wide collector used by the grafeo adapter
query_stats = QueryStats()


def summarize_run_events(events: list[Any]) -> dict[str, Any]:
    """Aggregate OCEL events of one run: run time, extraction, slowest steps, LLM totals."""
    summary: dict[str, Any] = {
        "run_seconds": 0.0,
        "extraction": [],
        "steps": [],
        "llm": {},
    }
    llm = {"calls": 0, "cache_hits": 0, "live_calls": 0, "requests": 0, "errors": 0}
    latency_ms = wait_ms = 0.0
    for e in events:
        a = e.attributes
        if e.activity == "CompleteRun":
            summary["run_seconds"] = a.get("duration_seconds", 0.0)
        elif e.activity == "EnsureExtraction":
            summary["extraction"].append(
                {
                    "repository": a.get("repository"),
                    "cached": a.get("cached"),
                    "seconds": a.get("duration_seconds", 0.0),
                }
            )
        elif e.activity in ("ExtractConfig", "DeriveConfig"):
            summary["steps"].append(
                {"step": a.get("config_id"), "seconds": a.get("duration_seconds", 0.0)}
            )
        elif e.activity == "LLMQuery":
            llm["calls"] += 1
            if a.get("cache_hit"):
                llm["cache_hits"] += 1
            else:
                llm["live_calls"] += 1
            llm["requests"] += a.get("requests", 0) or 0
            llm["errors"] += 1 if a.get("error_type") else 0
            latency_ms += a.get("latency_ms", 0.0) or 0.0
            wait_ms += a.get("wait_ms", 0.0) or 0.0
    summary["steps"].sort(key=lambda s: -s["seconds"])
    # Runs without a CompleteRun event (e.g. extraction) report the total of their steps
    summary["run_seconds"] = round(
        summary["run_seconds"] or sum(step["seconds"] for step in summary["steps"]), 2
    )
    summary["llm"] = {
        **llm,
        "latency_seconds": round(latency_ms / 1000, 2),
        "wait_seconds": round(wait_ms / 1000, 2),
    }
    return summary
