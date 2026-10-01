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


class TestAnswerStability:
    """Raw LLM answer stability per repository, next to output consistency."""

    def test_extraction_and_derivation_runs_are_compared_separately(self):
        log = OCELLog()

        def query(run, step, key, answer):
            log.create_event("LLMQuery", objects={"BenchmarkRun": [run]}, config_id=step, cache_key=key, response_hash=answer)

        # Two end-to-end sessions: each has one extraction run and one derivation run
        for session, extraction_answer, derivation_answer in (("s1", "e1", "d1"), ("s2", "e1", "d2")):
            query(f"{session}:extraction:repo", "ExtractStep", "k_extract", extraction_answer)
            query(f"{session}:repo:m:1", "DeriveStep", "k_derive", derivation_answer)
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"all": log}
        analyzer.repositories = ["repo"]

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"ExtractStep": (1, 1), "DeriveStep": (1, 0)}

    def test_decisions_are_compared_when_recorded(self):
        """Sessions record a decision hash; older sessions only the full response hash."""
        log = OCELLog()
        for session, response, decision in (("s1", "r1", "d"), ("s2", "r2", "d")):
            log.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:repo:m:1"]}, config_id="New", cache_key="k1", response_hash=response, decision_hash=decision)
            log.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:repo:m:1"]}, config_id="Old", cache_key="k2", response_hash=response)
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"all": log}
        analyzer.repositories = ["repo"]

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"New": (1, 1), "Old": (1, 0)}

    def test_a_combined_session_reports_its_derivation_under_the_joined_name(self):
        """Combined runs derive once over all repositories: their run ids carry the joined repository name."""
        log = OCELLog()
        for session in ("s1", "s2"):
            log.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:alpha_beta:m:1"]}, config_id="DeriveStep", cache_key="k", decision_hash="d")
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"all": log}
        analyzer.repositories = ["beta", "alpha"]

        result = analyzer.analyze_answer_stability()

        assert {s.step: (s.prompts, s.identical) for s in result["alpha_beta"]} == {"DeriveStep": (1, 1)}


class TestSessionInfo:
    """The analyzer reads the benchmark's session metadata (it was renamed from summary.json)."""

    def test_repositories_come_from_session_metadata(self, tmp_path, monkeypatch):
        import json

        monkeypatch.chdir(tmp_path)
        session_dir = tmp_path / "workspace" / "benchmarks" / "s1"
        session_dir.mkdir(parents=True)
        (session_dir / "session_metadata.json").write_text(json.dumps({"config": {"repositories": ["repo"], "models": ["m"]}}), encoding="utf-8")

        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)

        assert analyzer._load_session_info("s1")["config"]["repositories"] == ["repo"]
