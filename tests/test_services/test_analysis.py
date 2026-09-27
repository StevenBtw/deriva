"""Tests for BenchmarkAnalyzer exports."""

from __future__ import annotations

import csv

import pytest

from deriva.common.ocel import OCELLog
from deriva.services.analysis import BenchmarkAnalyzer


class TestExecutionMetricsCsv:
    """execution_metrics.csv counts LLM calls under every activity name sessions have used."""

    @pytest.mark.parametrize("activity", ["LLMQuery", "LLMRequest", "llm_request"])
    def test_llm_calls_are_counted(self, activity, tmp_path):
        log = OCELLog()
        log.create_event("StartRun", objects={"BenchmarkRun": ["s:repo:m:1"], "Repository": ["repo"], "Model": ["m"]})
        log.create_event(activity, objects={"BenchmarkRun": ["s:repo:m:1"]}, tokens_in=3, tokens_out=2)
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"s": log}

        path = analyzer.export_execution_metrics_csv(tmp_path / "metrics.csv")

        with open(path, encoding="utf-8") as f:
            (row,) = csv.DictReader(f)
        assert (row["api_calls"], row["tokens_in"], row["tokens_out"]) == ("1", "3", "2")
