"""Extraction per run: every run extracts with its own model on its own graph, and the reports split the variance."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deriva.bench.benchmarking import BenchmarkConfig, BenchmarkOrchestrator, RunResult


def _orchestrator(**config):
    orchestrator = BenchmarkOrchestrator(
        engine=MagicMock(),
        graph_manager=MagicMock(),
        archimate_manager=MagicMock(),
        config=BenchmarkConfig(repositories=["a"], models=["m1", "m2"], runs_per_combination=1, **config),
    )
    orchestrator.session_id = "s"
    return orchestrator


class TestSessionLoop:
    def test_per_run_mode_skips_the_shared_extraction(self):
        orchestrator = _orchestrator(per_repo=True, extract_per_run=True, use_cache=False)
        orchestrator._ensure_extraction = MagicMock(return_value=[])  # type: ignore[method-assign]
        orchestrator._run_combined = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda repositories, model_name, **kw: RunResult(
                run_id="r", repositories=repositories, model=model_name, iteration=1, status="completed", stats={}, errors=[], duration_seconds=0.0
            )
        )
        with (
            patch("deriva.bench.benchmarking.load_benchmark_models", return_value={"m1": MagicMock(provider="openai"), "m2": MagicMock(provider="openai")}),
            patch("deriva.bench.benchmarking.use_database"),
            patch.object(orchestrator, "_create_session"),
            patch.object(orchestrator, "_complete_session"),
            patch.object(orchestrator, "_export_ocel", return_value="x"),
            patch.object(orchestrator, "_export_ocel_incremental"),
        ):
            result = orchestrator.run()

        orchestrator._ensure_extraction.assert_not_called()
        assert result.runs_completed == 2


class TestRun:
    def test_a_run_extracts_with_its_own_model_on_its_own_graph_and_keeps_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))
        orchestrator = _orchestrator(per_repo=True, extract_per_run=True, use_cache=False, export_models=False)
        orchestrator._model_configs = {"m1": MagicMock(model="x1"), "m2": MagicMock(model="x2")}
        graphs = tmp_path / "graphs"
        graphs.mkdir()
        keys: list[str] = []

        def use(key):
            keys.append(key)
            (graphs / f"{key}.grafeo").write_bytes(b"graph")

        step_stats = {"a": {"BusinessConcept": {"decisions": {"x": "entity"}}}}
        extract = MagicMock(return_value={"success": True, "stats": {"nodes_created": 5, "edges_created": 7}, "step_stats": step_stats})
        with (
            patch("deriva.bench.benchmarking.use_database", side_effect=use),
            patch("deriva.bench.benchmarking.close_database"),
            patch("deriva.bench.benchmarking.database_file", side_effect=lambda key: str(graphs / f"{key}.grafeo")),
            patch("deriva.bench.benchmarking.LLMManager.from_config"),
            patch("deriva.bench.benchmarking.derivation.run_derivation", return_value={"success": True, "stats": {}}),
            patch.object(orchestrator, "_extract_repo", extract),
            patch.object(orchestrator, "_create_run"),
            patch.object(orchestrator, "_complete_run"),
        ):
            result = orchestrator._run_combined(repositories=["a"], model_name="m2", iteration=2)

        assert result.status == "completed"
        assert keys == ["a__s__m2__run2"]
        (call,) = extract.call_args_list
        assert call.args[0] == "a" and call.kwargs["model_name"] == "m2" and call.kwargs["run_id"] == result.run_id
        assert result.stats["extraction"]["nodes_created"] == 5
        # The run's graph is kept with the session, under the run's file name; the key's file is gone
        assert (tmp_path / "workspace" / "benchmarks" / "s" / "graphs" / "a_m2_run2.grafeo").read_bytes() == b"graph"
        assert not (graphs / "a__s__m2__run2.grafeo").exists()

    def test_extraction_uses_the_named_model(self):
        orchestrator = _orchestrator()
        orchestrator._model_configs = {"m1": MagicMock(model="x1"), "m2": MagicMock(model="x2")}
        with (
            patch("deriva.bench.benchmarking.LLMManager.from_config") as from_config,
            patch("deriva.bench.benchmarking.extraction.run_extraction", return_value={"success": True, "stats": {}}),
        ):
            orchestrator._extract_repo("a", None, model_name="m2", run_id="s:a:m2:1")

        assert {c.args[0].model for c in from_config.call_args_list} == {"x2"}


def _snapshot(path: Path, elements, relationships=(), nodes=(), decisions=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "elements": [{"identifier": i, "type": "DataObject", "name": i, "source": s} for i, s in elements],
        "relationships": [{"source": s, "target": t, "type": "Access"} for s, t in relationships],
        "graph": {"node_ids": sorted(nodes)},
    }
    if decisions is not None:
        payload["extraction_decisions"] = decisions
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestVarianceSplit:
    def test_an_element_missing_with_its_source_node_is_extraction_else_derivation(self, tmp_path):
        from deriva.bench.benchmarking import variance_split_for_session

        models = tmp_path / "models"
        # e1 in both runs; e2 only in run 1, its node missing in run 2 (extraction);
        # e3 only in run 1, its node present in run 2 (derivation)
        _snapshot(models / "a_m_run1.json", [("e1", "n1"), ("e2", "n2"), ("e3", "n3")], [("e1", "e2"), ("e1", "e3")], nodes=["n1", "n2", "n3"])
        _snapshot(models / "a_m_run2.json", [("e1", "n1")], [], nodes=["n1", "n3"])

        (row,) = variance_split_for_session(tmp_path, ["a"], ["m"])

        assert (row["runs"], row["elements"]["extraction"], row["elements"]["derivation"]) == (2, 1, 1)
        assert row["elements"]["extraction_share"] == 0.5
        # A relationship follows its endpoints: e1-e2 (extraction), e1-e3 (derivation)
        assert (row["relationships"]["extraction"], row["relationships"]["derivation"]) == (1, 1)

    def test_runs_without_graph_node_ids_give_no_split(self, tmp_path):
        from deriva.bench.benchmarking import variance_split_for_session

        models = tmp_path / "models"
        for run in (1, 2):
            (models).mkdir(exist_ok=True)
            (models / f"a_m_run{run}.json").write_text(json.dumps({"elements": [], "relationships": []}), encoding="utf-8")

        assert variance_split_for_session(tmp_path, ["a"], ["m"]) == []


class TestExtractionStability:
    def test_decision_stability_per_extraction_step_over_the_runs(self, tmp_path):
        from deriva.bench.benchmarking import extraction_stability_for_session

        models = tmp_path / "models"
        _snapshot(models / "a_m_run1.json", [], decisions={"BusinessConcept": {"x": "entity", "y": "reject"}, "Technology": {"t": "db"}})
        _snapshot(models / "a_m_run2.json", [], decisions={"BusinessConcept": {"x": "entity", "y": "entity"}, "Technology": {"t": "db"}})

        (row,) = extraction_stability_for_session(tmp_path, ["a"], ["m"])

        assert row["steps"] == {"BusinessConcept": {"items": 2, "stable": 1}, "Technology": {"items": 1, "stable": 1}}


@pytest.mark.parametrize(
    ("stages", "use_cache", "error"),
    [(["derivation"], False, "extraction"), (["extraction", "derivation"], True, "--no-cache")],
)
def test_per_run_mode_needs_both_stages_and_no_cache(stages, use_cache, error):
    from deriva.bench.benchmarking import validate_config

    with pytest.raises(ValueError, match=error):
        validate_config(BenchmarkConfig(repositories=["a"], models=["m"], stages=stages, use_cache=use_cache, extract_per_run=True))


class TestNamingFallbacks:
    def test_unusable_name_choices_are_counted_per_model(self, tmp_path):
        """An answer that is no JSON or names no candidate takes the structural first candidate: counted per model."""
        from deriva.bench.benchmarking import naming_fallbacks_for_session

        prompt = 'Choose.\n\n## Candidates\n- "Order Handling"\n- "Order Processing"\n\nReturn {"name": "..."} with one candidate exactly as written.'
        calls = [
            {"model": "x1", "schema": "element_name_choice", "prompt": prompt, "response": '{"name": "Order Handling"}'},
            {"model": "x1", "schema": "element_name_choice", "prompt": prompt, "response": '{"name": "Orders"}\n\nNote: closest is {"name": "Order Processing"}'},
            {"model": "x1", "schema": "element_name_choice", "prompt": prompt, "response": '{"name": "Something Else"}'},
            {"model": "x1", "schema": "business_concept_classification", "prompt": "p", "response": "not json"},
        ]
        folder = tmp_path / "llm"
        folder.mkdir()
        (folder / "s_r_m_1.jsonl").write_text("\n".join(json.dumps(c) for c in calls) + "\n", encoding="utf-8")

        assert naming_fallbacks_for_session(tmp_path) == [{"model": "x1", "choices": 3, "unusable": 2, "unparsable": 1, "outside": 1}]
