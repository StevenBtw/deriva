"""Query timing collector and run summary aggregation."""

from __future__ import annotations

from deriva.common.ocel import OCELLog
from deriva.common.timing import QueryStats, summarize_run_events


class TestQueryStats:
    def test_groups_by_normalised_query_text(self):
        stats = QueryStats()
        stats.record("MATCH (n)\n   RETURN n", 10.0)
        stats.record("MATCH (n) RETURN n", 30.0)
        stats.record("MATCH (m) RETURN m", 5.0)

        top = stats.top()

        assert top[0] == {"query": "MATCH (n) RETURN n", "count": 2, "total_ms": 40.0, "max_ms": 30.0}
        assert top[1]["query"] == "MATCH (m) RETURN m"

    def test_top_is_limited_and_reset_clears(self):
        stats = QueryStats()
        for i in range(5):
            stats.record(f"Q{i}", float(i))

        assert [q["query"] for q in stats.top(2)] == ["Q4", "Q3"]
        stats.reset()
        assert stats.top() == []


class TestSummarizeRunEvents:
    def test_aggregates_steps_llm_and_extraction(self):
        log = OCELLog()
        log.create_event(activity="EnsureExtraction", objects={}, repository="r", cached=True, duration_seconds=0.5)
        log.create_event(activity="DeriveConfig", objects={}, config_id="pagerank", duration_seconds=1.25)
        log.create_event(activity="DeriveConfig", objects={}, config_id="ApplicationComponent", duration_seconds=4.0)
        log.create_event(activity="LLMQuery", objects={}, config_id="ApplicationComponent", cache_hit=True, latency_ms=0.0, wait_ms=0.0, requests=0, error_type=None)
        log.create_event(activity="LLMQuery", objects={}, config_id="ApplicationComponent", cache_hit=False, latency_ms=900.0, wait_ms=100.0, requests=2, error_type=None)
        log.create_event(activity="LLMQuery", objects={}, config_id="Node", cache_hit=False, latency_ms=50.0, wait_ms=0.0, requests=1, error_type="RuntimeError")
        log.create_event(activity="CompleteRun", objects={}, duration_seconds=12.0)

        summary = summarize_run_events(log.events)

        assert summary["run_seconds"] == 12.0
        assert summary["extraction"] == [{"repository": "r", "cached": True, "seconds": 0.5}]
        assert summary["steps"][0] == {"step": "ApplicationComponent", "seconds": 4.0}
        assert summary["llm"] == {
            "calls": 3,
            "cache_hits": 1,
            "live_calls": 2,
            "requests": 3,
            "errors": 1,
            "latency_seconds": 0.95,
            "wait_seconds": 0.1,
        }
