"""Tests for the step benchmark: one pipeline step repeated on a fixed input."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.adapters.graph.models import BusinessConceptNode, DirectoryNode, RepositoryNode
from deriva.services.benchmarking import BenchmarkConfig


@pytest.fixture
def graph_manager():
    from deriva.adapters.grafeo.manager import close_database
    from deriva.adapters.graph import GraphManager

    close_database()
    gm = GraphManager()
    gm.connect()
    yield gm
    gm.disconnect()
    close_database()


@pytest.fixture
def archimate_manager(graph_manager):
    from deriva.adapters.archimate import ArchimateManager

    am = ArchimateManager()
    am.connect()
    yield am
    am.disconnect()


def _concept(name):
    return BusinessConceptNode(name=name, concept_type="entity", description="", origin_source="f", repository_name="r")


class TestModelOutputs:
    """The model as comparable objects: elements by identifier, relationships by type and ends."""

    def test_elements_and_relationships_with_what_later_steps_read(self, archimate_manager):
        from deriva.adapters.archimate.models import Element, Relationship
        from deriva.services.step_benchmark import model_outputs

        archimate_manager.add_element(
            Element(name="Store", element_type="ApplicationComponent", identifier="ac_store", properties={"source": "dir::r::s", "created_at": "t", "derived_at": "t"})
        )
        archimate_manager.add_element(Element(name="Ledger", element_type="DataObject", identifier="do_ledger", enabled=False))
        archimate_manager.add_relationship(
            Relationship(source="ac_store", target="do_ledger", relationship_type="Access", identifier="rel_1", properties={"derived_from": "graph"}), validate=False
        )

        outputs = model_outputs(archimate_manager)

        assert outputs[("ApplicationComponent", "ac_store")] == {"name": "Store", "documentation": None, "enabled": True, "source": "dir::r::s"}
        assert outputs[("DataObject", "do_ledger")]["enabled"] is False
        # Relationship identifiers are generated per run: a relationship is known by its type and its ends
        assert outputs[("Access", "ac_store -> do_ledger")] == {"name": None, "documentation": None, "derived_from": "graph"}


class TestRunDerivationStep:
    """A derivation step runs alone on the whole extraction and every earlier derivation step, built from the cache."""

    DERIVATION = {
        "prep": [SimpleNamespace(step_name="pagerank"), SimpleNamespace(step_name="k_core_filter")],
        "generate": [SimpleNamespace(step_name="ApplicationComponent"), SimpleNamespace(step_name="DataObject"), SimpleNamespace(step_name="BusinessObject")],
        "refine": [SimpleNamespace(step_name="duplicate_elements")],
    }

    @pytest.fixture
    def workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path / "graphs"))
        return tmp_path

    def _run(self, graph_manager, archimate_manager, step, fake_derivation=None, runs=3):
        from deriva.services.step_benchmark import StepBenchmark

        benchmark = StepBenchmark(
            engine=MagicMock(),
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=BenchmarkConfig(repositories=["r"], models=["m"], runs_per_combination=runs),
        )
        fake = fake_derivation or (lambda benchmark, **kwargs: {"success": True, "stats": {}, "errors": []})
        with (
            patch("deriva.services.benchmarking.load_benchmark_models", return_value={"m": SimpleNamespace(model="m", provider="p")}),
            patch("deriva.services.benchmarking.LLMManager.from_config", return_value=MagicMock(last_call={})),
            patch("deriva.services.benchmarking.config_service.get_active_config_versions", return_value={}),
            patch("deriva.services.benchmarking.config_service.llm_samples_per_step", return_value={}),
            patch("deriva.services.step_benchmark.config_service.get_extraction_configs", return_value=[SimpleNamespace(node_type="Repository")]),
            patch("deriva.services.step_benchmark.config_service.get_derivation_configs", side_effect=lambda engine, enabled_only, phase: self.DERIVATION.get(phase, [])),
            patch("deriva.services.benchmarking.extraction.run_extraction", return_value={"success": True, "stats": {}, "errors": []}) as run_extraction,
            patch("deriva.services.step_benchmark.derivation.run_derivation", side_effect=lambda **kwargs: fake(benchmark, **kwargs)) as run_derivation,
        ):
            result = benchmark.run_step(step)
        return result, run_extraction, run_derivation

    def test_an_element_step_runs_alone_after_every_earlier_step(self, workspace, graph_manager, archimate_manager):
        result, run_extraction, run_derivation = self._run(graph_manager, archimate_manager, "DataObject")

        assert result.errors == []
        assert [c.kwargs["steps"] for c in run_extraction.call_args_list] == [["Repository"]]
        assert [c.kwargs["steps"] for c in run_derivation.call_args_list] == [["pagerank", "k_core_filter", "ApplicationComponent"]] + [["DataObject"]] * 3

    def test_prep_is_the_prep_phase_on_the_extraction(self, workspace, graph_manager, archimate_manager):
        _, _, run_derivation = self._run(graph_manager, archimate_manager, "prep")

        assert [c.kwargs["steps"] for c in run_derivation.call_args_list] == [["pagerank", "k_core_filter"]] * 3

    def test_the_relationship_pass_follows_every_element_step(self, workspace, graph_manager, archimate_manager):
        from deriva.services.derivation import RELATIONSHIP_STEP

        _, _, run_derivation = self._run(graph_manager, archimate_manager, RELATIONSHIP_STEP)

        steps = [c.kwargs["steps"] for c in run_derivation.call_args_list]
        assert steps == [["pagerank", "k_core_filter", "ApplicationComponent", "DataObject", "BusinessObject"]] + [[RELATIONSHIP_STEP]] * 3

    def test_the_repeated_step_calls_the_llm_without_the_cache(self, workspace, graph_manager, archimate_manager):
        nocache = []

        def fake(benchmark, **kwargs):
            nocache.append(list(benchmark.config.nocache_configs))
            return {"success": True, "stats": {}, "errors": []}

        self._run(graph_manager, archimate_manager, "DataObject", fake, runs=2)

        assert nocache == [[], ["DataObject"], ["DataObject"]]

    def test_the_elements_a_step_creates_are_compared(self, workspace, graph_manager, archimate_manager):
        from deriva.adapters.archimate.models import Element

        answers = iter([["Ledger", "Journal"], ["Ledger"], ["Ledger", "Journal"]])

        def fake(benchmark, *, archimate_manager, steps, **kwargs):
            if steps == ["DataObject"]:
                for name in next(answers):
                    archimate_manager.add_element(Element(name=name, element_type="DataObject", identifier=f"do_{name.lower()}"))
            return {"success": True, "stats": {}, "errors": []}

        result, _, _ = self._run(graph_manager, archimate_manager, "DataObject", fake)

        consistency = result.repositories["r"]
        assert set(consistency.groups) == {"DataObject"}
        assert (consistency.present, consistency.total, consistency.counts) == (1, 2, [2, 1, 2])

    def test_element_text_and_confidence_are_reported_but_not_scored(self, workspace, graph_manager, archimate_manager):
        """Documentation, the LLM's own name and confidence: no later step reads them for identity."""
        from deriva.adapters.archimate.models import Element

        answers = iter([("one", 0.9), ("two", 0.8), ("three", 0.9)])

        def fake(benchmark, *, archimate_manager, steps, **kwargs):
            if steps == ["DataObject"]:
                documentation, confidence = next(answers)
                element = Element(name="Ledger", element_type="DataObject", identifier="do_ledger", documentation=documentation, properties={"confidence": confidence})
                archimate_manager.add_element(element)
            return {"success": True, "stats": {}, "errors": []}

        result, _, _ = self._run(graph_manager, archimate_manager, "DataObject", fake)

        consistency = result.repositories["r"]
        assert consistency.exact_score == 1.0
        assert consistency.property_differences == {"confidence": 1, "documentation": 1}
        data = json.loads((Path("workspace/benchmarks") / result.session_id / "step_results.json").read_text(encoding="utf-8"))
        assert data["unscored_properties"] == ["confidence", "documentation", "llm_name"]

    def test_other_derivation_steps_score_every_property(self, workspace, graph_manager, archimate_manager):
        result, _, _ = self._run(graph_manager, archimate_manager, "prep")

        assert result.unscored == []

    def test_element_steps_report_decision_stability_per_candidate(self, workspace, graph_manager, archimate_manager):
        """A candidate's decision is the stage it reached and the element it became."""
        runs = iter(
            [
                [{"node_id": "a", "stage": "created", "element_id": "do_a"}, {"node_id": "b", "stage": "llm_rejected", "element_id": None}],
                [{"node_id": "a", "stage": "created", "element_id": "do_a"}, {"node_id": "b", "stage": "created", "element_id": "do_b"}],
                [{"node_id": "a", "stage": "created", "element_id": "do_a"}, {"node_id": "b", "stage": "llm_rejected", "element_id": None}],
            ]
        )

        def fake(benchmark, *, steps, **kwargs):
            decisions = next(runs) if steps == ["DataObject"] else []
            return {"success": True, "stats": {}, "errors": [], "candidate_decisions": decisions}

        result, _, _ = self._run(graph_manager, archimate_manager, "DataObject", fake)

        stability = result.decision_stability["r"]
        assert (stability.items, stability.stable) == (2, 1)

    def test_steps_without_candidates_report_no_decision_stability(self, workspace, graph_manager, archimate_manager):
        result, _, _ = self._run(graph_manager, archimate_manager, "prep")

        assert result.decision_stability == {}


class TestGraphOutputs:
    """The graph as comparable objects: nodes and edges with the properties a step decided."""

    def test_nodes_and_edges_with_their_properties(self, graph_manager):
        from deriva.services.step_benchmark import graph_outputs

        graph_manager.add_node(DirectoryNode(name="d", path="d", repository_name="r"), node_id="dir::r::d")
        graph_manager.add_node(_concept("Alpha"), node_id="concept::r::alpha")
        graph_manager.add_edge("dir::r::d", "concept::r::alpha", "REPRESENTS", properties={"route": "directory", "created_at": "t"})

        outputs = graph_outputs(graph_manager)

        assert outputs[("BusinessConcept", "concept::r::alpha")]["conceptName"] == "Alpha"
        # Timestamps record when, not what: they are left out
        assert outputs[("REPRESENTS", "dir::r::d -> concept::r::alpha")] == {"route": "directory"}

    def test_the_json_copy_of_the_properties_is_left_out(self, graph_manager):
        from deriva.services.step_benchmark import graph_outputs

        graph_manager.add_node(_concept("Alpha"), node_id="concept::r::alpha")

        assert "properties_json" not in graph_outputs(graph_manager)[("BusinessConcept", "concept::r::alpha")]


class TestStepOutput:
    def test_new_changed_and_removed_objects(self):
        from deriva.services.step_benchmark import step_output

        before = {("A", "1"): {"x": 1}, ("A", "2"): {"x": 1}, ("A", "3"): {}}
        after = {("A", "1"): {"x": 1}, ("A", "2"): {"x": 2}, ("B", "4"): {}}

        assert step_output(before, after) == {("A", "2"): {"x": 2}, ("B", "4"): {}, ("A (removed)", "3"): {}}


class TestRunStep:
    """The input is built once from the cache; each run starts from a fresh copy of it."""

    @pytest.fixture
    def workspace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path / "graphs"))
        return tmp_path

    def _run(self, graph_manager, step, fake_extraction, runs=3):
        """Run the step benchmark; ``fake_extraction(benchmark, **kwargs)`` stands in for the extraction service."""
        from deriva.services.step_benchmark import StepBenchmark

        benchmark = StepBenchmark(
            engine=MagicMock(),
            graph_manager=graph_manager,
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["r"], models=["m"], runs_per_combination=runs),
        )
        configs = [SimpleNamespace(node_type="Repository"), SimpleNamespace(node_type="BusinessConcept")]
        with (
            patch("deriva.services.benchmarking.load_benchmark_models", return_value={"m": SimpleNamespace(model="m", provider="p")}),
            patch("deriva.services.benchmarking.LLMManager.from_config", return_value=MagicMock(last_call={})),
            patch("deriva.services.benchmarking.config_service.get_active_config_versions", return_value={}),
            patch("deriva.services.benchmarking.config_service.llm_samples_per_step", return_value={}),
            patch("deriva.services.step_benchmark.config_service.get_extraction_configs", return_value=configs),
            patch("deriva.services.benchmarking.extraction.run_extraction", side_effect=lambda **kwargs: fake_extraction(benchmark, **kwargs)) as run_extraction,
        ):
            result = benchmark.run_step(step)
        return result, run_extraction

    def test_only_the_step_is_repeated_and_its_outputs_compared(self, workspace, graph_manager):
        answers = iter([["Alpha", "Beta"], ["Alpha"], ["Alpha", "Gamma"]])

        def fake_extraction(benchmark, *, graph_manager, steps, **kwargs):
            if steps == ["Repository"]:
                graph_manager.add_node(RepositoryNode(name="r", url="u", created_at=None), node_id="repo::r")
            else:
                for name in next(answers):
                    graph_manager.add_node(_concept(name), node_id=f"concept::r::{name.lower()}")
            return {"success": True, "stats": {}, "errors": []}

        result, run_extraction = self._run(graph_manager, "BusinessConcept", fake_extraction)

        assert [c.kwargs["steps"] for c in run_extraction.call_args_list] == [["Repository"]] + [["BusinessConcept"]] * 3
        consistency = result.repositories["r"]
        # The input (the Repository node) is not part of the step's output
        assert set(consistency.groups) == {"BusinessConcept"}
        assert (consistency.present, consistency.total, consistency.counts) == (1, 3, [2, 1, 2])

    def test_the_step_calls_the_llm_without_the_cache(self, workspace, graph_manager):
        nocache = []

        def fake_extraction(benchmark, **kwargs):
            nocache.append(list(benchmark.config.nocache_configs))
            return {"success": True, "stats": {}, "errors": []}

        self._run(graph_manager, "BusinessConcept", fake_extraction, runs=2)

        # Building the input reads the cache for every step; the repeated step never does
        assert nocache == [[], ["BusinessConcept"], ["BusinessConcept"]]

    def test_the_repository_graph_is_not_touched(self, workspace, graph_manager):
        def fake_extraction(benchmark, **kwargs):
            return {"success": True, "stats": {}, "errors": []}

        self._run(graph_manager, "BusinessConcept", fake_extraction)

        # The runs used a separate work database, removed afterwards; the repository's own file was never opened
        assert not (workspace / "graphs" / "r.grafeo").exists()
        assert not (workspace / "graphs" / "r.step.grafeo").exists()

    def test_results_and_the_input_are_kept_in_the_session(self, workspace, graph_manager):
        def fake_extraction(benchmark, **kwargs):
            return {"success": True, "stats": {}, "errors": []}

        result, _ = self._run(graph_manager, "BusinessConcept", fake_extraction)

        session_dir = Path("workspace/benchmarks") / result.session_id
        data = json.loads((session_dir / "step_results.json").read_text(encoding="utf-8"))
        assert data["step"] == "BusinessConcept"
        assert data["repositories"]["r"]["consistency"]["runs"] == 3
        assert data["unscored_properties"] == []  # extraction steps score every property
        assert (session_dir / "steps" / "r_input.grafeo").exists()

    def test_each_runs_output_is_kept_for_investigation(self, workspace, graph_manager):
        def fake_extraction(benchmark, *, graph_manager, steps, **kwargs):
            if steps == ["BusinessConcept"]:
                graph_manager.add_node(_concept("Alpha"), node_id="concept::r::alpha")
            return {"success": True, "stats": {}, "errors": []}

        result, _ = self._run(graph_manager, "BusinessConcept", fake_extraction, runs=2)

        steps_dir = Path("workspace/benchmarks") / result.session_id / "steps"
        for run in (1, 2):
            (obj,) = json.loads((steps_dir / f"r_run{run}.json").read_text(encoding="utf-8"))
            assert (obj["type"], obj["key"], obj["properties"]["conceptName"]) == ("BusinessConcept", "concept::r::alpha", "Alpha")

    def test_decision_stability_of_a_classification_step(self, workspace, graph_manager):
        """A step that reports one decision per item gets the share of items decided alike in every run."""
        decisions = iter([{"a": "x", "b": "y"}, {"a": "x", "b": "z"}, {"a": "x", "b": "y"}])

        def fake_extraction(benchmark, *, steps, repo_name, **kwargs):
            if steps == ["BusinessConcept"]:
                return {"success": True, "stats": {}, "errors": [], "step_stats": {repo_name: {"BusinessConcept": {"decisions": next(decisions)}}}}
            return {"success": True, "stats": {}, "errors": []}

        result, _ = self._run(graph_manager, "BusinessConcept", fake_extraction)

        stability = result.decision_stability["r"]
        assert (stability.items, stability.stable) == (2, 1)
        data = json.loads((Path("workspace/benchmarks") / result.session_id / "step_results.json").read_text(encoding="utf-8"))
        assert data["repositories"]["r"]["decision_stability"] == {"items": 2, "stable": 1, "score": 0.5}

    def test_a_step_without_decisions_has_no_decision_stability(self, workspace, graph_manager):
        result, _ = self._run(graph_manager, "BusinessConcept", lambda benchmark, **kwargs: {"success": True, "stats": {}, "errors": []})

        assert result.decision_stability == {}
        data = json.loads((Path("workspace/benchmarks") / result.session_id / "step_results.json").read_text(encoding="utf-8"))
        assert data["repositories"]["r"]["decision_stability"] is None

    def test_unknown_step_is_an_error(self, workspace, graph_manager):
        result, run_extraction = self._run(graph_manager, "Nope", lambda benchmark, **kwargs: None)

        assert result.errors and "Nope" in result.errors[0]
        run_extraction.assert_not_called()
