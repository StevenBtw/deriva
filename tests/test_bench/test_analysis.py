"""Tests for BenchmarkAnalyzer exports."""

from __future__ import annotations

import csv

import pytest

from deriva.bench.analysis import BenchmarkAnalyzer
from deriva.common.ocel import OCELLog


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

    def test_recorded_answers_are_recomputed_from_the_call_logs(self):
        """Where a session kept its LLM calls, decisions come from the answers themselves (the event log's
        hash froze an older rule: a code fence made reworded documentation count as a new decision)."""
        stale = OCELLog()
        for session, stale_hash in (("s1", "h1"), ("s2", "h2")):
            stale.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:repo:m:1"]}, config_id="Step", cache_key="k", decision_hash=stale_hash)
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"s1": stale, "s2": OCELLog()}
        analyzer.repositories = ["repo"]
        fence = '```json\n{{"elements": [{{"name": "Alpha", "documentation": "{}"}}]}}\n```'
        analyzer.call_logs = {
            "s1": [{"run_id": "s1:repo:m:1", "step": "Step", "cache_key": "k", "response": fence.format("One wording")}],
            "s2": [{"run_id": "s2:repo:m:1", "step": "Step", "cache_key": "k", "response": fence.format("Another wording")}],
        }

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"Step": (1, 1)}

    def test_a_call_log_answer_matches_the_event_log_hash_of_another_session(self):
        """Separate sessions are compared with each other: one read from its call log, one from its event log."""
        from deriva.common.ocel import hash_content
        from deriva.modules.analysis import decision_content

        answer = '{"keep": true, "documentation": "One wording"}'
        older = OCELLog()
        older.create_event("LLMQuery", objects={"BenchmarkRun": ["s1:repo:m:1"]}, config_id="Step", cache_key="k", decision_hash=hash_content(decision_content(answer)))
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"s1": older, "s2": OCELLog()}
        analyzer.repositories = ["repo"]
        analyzer.call_logs = {"s2": [{"run_id": "s2:repo:m:1", "step": "Step", "cache_key": "k", "response": answer.replace("One", "Another")}]}

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"Step": (1, 1)}

    def test_runs_with_a_bench_hash_share_their_prompts(self):
        """--bench-hash puts the run into every cache key; read from call logs, one prompt in two runs is one prompt."""
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"s1": OCELLog()}
        analyzer.repositories = ["repo"]
        analyzer.call_logs = {"s1": [{"run_id": f"s1:repo:m:{n}", "step": "Step", "cache_key": f"repo:m:{n}", "prompt": "p", "response": '{"keep": true}'} for n in (1, 2)]}

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"Step": (1, 1)}

    def test_a_failed_call_is_no_answer(self):
        """A failed call records the failure, not an answer: as in the event log, it has no decision."""
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"s1": OCELLog(), "s2": OCELLog()}
        analyzer.repositories = ["repo"]
        analyzer.call_logs = {
            session: [{"run_id": f"{session}:repo:m:1", "step": "Step", "cache_key": "k", "response": f'{{"error": "timeout after {seconds} s"}}', "error": "timeout"}]
            for session, seconds in (("s1", 30), ("s2", 31))
        }

        result = {s.step: (s.prompts, s.identical) for s in analyzer.analyze_answer_stability()["repo"]}

        assert result == {"Step": (1, 1)}


class TestAnswerStabilityPerModel:
    """Sessions of different models are read per model: their prompts differ (the model is part of the key), so mixed they share none."""

    def test_each_model_reports_its_own_steps(self):
        log = OCELLog()
        for session, model, answers in (("s1", "a", ("x", "x")), ("s2", "b", ("y", "z"))):
            log.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:extraction:repo"]}, config_id="Extract", cache_key=f"e_{model}", decision_hash="e")
            for iteration, answer in enumerate(answers, start=1):
                log.create_event("LLMQuery", objects={"BenchmarkRun": [f"{session}:repo:{model}:{iteration}"]}, config_id="Derive", cache_key=f"k_{model}", decision_hash=answer)
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"all": log}
        analyzer.repositories = ["repo"]
        analyzer.session_infos = {"s1": {"config": {"models": ["a"]}}, "s2": {"config": {"models": ["b"]}}}

        result = {key: {s.step: (s.prompts, s.identical) for s in steps} for key, steps in analyzer.analyze_answer_stability().items()}

        # One extraction run per model (one session each) has nothing to be compared with
        assert result == {"repo · a": {"Derive": (1, 1)}, "repo · b": {"Derive": (1, 0)}}


class TestSessionInfo:
    """The analyzer reads the benchmark's session metadata (it was renamed from summary.json)."""

    def test_repositories_come_from_session_metadata(self, tmp_path, monkeypatch):
        import json

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))  # benchmark folders resolve against the home folder
        session_dir = tmp_path / "workspace" / "benchmarks" / "s1"
        session_dir.mkdir(parents=True)
        (session_dir / "session_metadata.json").write_text(json.dumps({"config": {"repositories": ["repo"], "models": ["m"]}}), encoding="utf-8")

        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)

        assert analyzer._load_session_info("s1")["config"]["repositories"] == ["repo"]


class TestRunsOfARepository:
    """Which runs and elements the per-repository reports read."""

    @staticmethod
    def _analyzer(log, repositories, models=("m",)):
        analyzer = BenchmarkAnalyzer.__new__(BenchmarkAnalyzer)
        analyzer.ocel_logs = {"all": log}
        analyzer.repositories = list(repositories)
        analyzer.models = list(models)
        return analyzer

    def test_a_combined_run_counts_for_each_of_its_repositories(self):
        log = OCELLog()
        log.create_event("DeriveElements", objects={"BenchmarkRun": ["s1:alpha_beta:m:1"], "Repository": ["alpha_beta"], "Element": ["ac_one"]})
        analyzer = self._analyzer(log, ["beta", "alpha"])

        assert analyzer._get_objects_by_run("Element", "alpha") == {"s1:alpha_beta:m:1": {"ac_one"}}
        assert [e["id"] for e in analyzer._get_derived_elements("beta")] == ["ac_one"]
        assert analyzer._get_objects_by_run("Element", "gamma") == {}

    def test_runs_can_be_read_for_one_model(self):
        log = OCELLog()
        for model, element in (("m1", "ac_one"), ("m2", "ac_two")):
            log.create_event("DeriveElements", objects={"BenchmarkRun": [f"s1:repo:{model}:1"], "Repository": ["repo"], "Element": [element]})
        analyzer = self._analyzer(log, ["repo"], models=("m1", "m2"))

        assert analyzer._get_objects_by_run("Element", "repo", "m1") == {"s1:repo:m1:1": {"ac_one"}}

    def test_the_derived_elements_are_those_of_the_latest_completed_run(self):
        """Not the union of every run: an element only an earlier or an unfinished run made is not in the model compared."""
        log = OCELLog()
        for run, elements, completed in (("s1:repo:m:1", ["ac_old", "ac_both"], True), ("s1:repo:m:2", ["ac_both", "ac_new"], True), ("s1:repo:m:3", ["ac_broken"], False)):
            log.create_event("DeriveElements", objects={"BenchmarkRun": [run], "Repository": ["repo"], "Element": elements})
            if completed:
                log.create_event("CompleteRun", objects={"BenchmarkRun": [run], "Repository": ["repo"]})
        analyzer = self._analyzer(log, ["repo"])

        assert [e["id"] for e in analyzer._get_derived_elements("repo")] == ["ac_both", "ac_new"]


def test_a_model_filter_keeps_the_extraction_runs_of_the_repository():
    """session:extraction:repo holds the repository where other run ids hold the model."""
    log = OCELLog()
    log.create_event("ExtractNodes", objects={"BenchmarkRun": ["s1:extraction:repo"], "Repository": ["repo"], "GraphNode": ["n1"]})
    log.create_event("ExtractNodes", objects={"BenchmarkRun": ["s1:extraction:other"], "Repository": ["other"], "GraphNode": ["n2"]})
    analyzer = TestRunsOfARepository._analyzer(log, ["repo", "other"], models=("m1", "m2"))

    assert analyzer._get_objects_by_run("GraphNode", "repo", "m1") == {"s1:extraction:repo": {"n1"}}
