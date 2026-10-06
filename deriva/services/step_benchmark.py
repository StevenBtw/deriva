"""Step benchmark: repeat one pipeline step on a fixed input and compare its outputs.

Consistency is worked on one step at a time. The step's input (graph and model) is
built once from every earlier step, with the LLM cache (so upstream answers are the
ones already cached), and kept in the session folder. Each run copies that input into
a separate work database, runs only the step without the LLM cache, and records what
the step added, changed or removed. The runs are then compared object by object.

Steps are extraction steps and derivation steps in pipeline order: the prep steps,
the element (generate) steps, the consolidated relationship pass and the refine steps.
``prep`` stands for the whole prep phase.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deriva.adapters.grafeo import close_database, database_file, use_database
from deriva.adapters.graph import GraphManager
from deriva.common.timing import query_stats
from deriva.modules.analysis import AnswerStability, DecisionStability, StepConsistency, compare_step_outputs, decision_stability
from deriva.services import benchmarking, derivation
from deriva.services import config as config_service
from deriva.services.analysis import BenchmarkAnalyzer

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.common.types import RunLoggerProtocol

# Properties that record when or how a value was stored, not what the step decided
VOLATILE_PROPERTIES = frozenset({"created_at", "extracted_at", "derived_at"})

# Element properties an element step reports but does not score in exact: no later step
# reads them for identity (documentation is open text, the LLM's own name is unused and
# confidence only gates creation)
UNSCORED_ELEMENT_PROPERTIES = frozenset({"documentation", "llm_name", "confidence"})


def _decided(props: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in props.items() if name not in VOLATILE_PROPERTIES}


def graph_outputs(graph_manager: GraphManager) -> dict[tuple[str, str], dict[str, Any]]:
    """Every node and edge of the graph namespace as (type, key) -> properties.

    Nodes are keyed by id under their type label, edges by ``source -> target`` under
    their relationship type, each with its stored properties; timestamps and the edge id
    are left out.
    """
    ns = graph_manager.namespace
    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    for row in graph_manager.query(f"MATCH (n:{ns}) RETURN labels(n) AS labels, properties(n) AS props"):
        props = row["props"]
        label = next((name for name in sorted(row["labels"]) if name != ns), ns)
        outputs[(label, props["id"])] = _decided(props)
    for row in graph_manager.query(f"MATCH (a:{ns})-[r]->(b:{ns}) RETURN a.id AS source, type(r) AS rel, b.id AS target, properties(r) AS props"):
        relationship = row["rel"].rsplit(":", 1)[-1]
        props = {name: value for name, value in (row["props"] or {}).items() if name != "id"}
        outputs[(relationship, f"{row['source']} -> {row['target']}")] = _decided(props)
    return outputs


def model_outputs(archimate_manager: ArchimateManager) -> dict[tuple[str, str], dict[str, Any]]:
    """Every element and relationship of the model as (type, key) -> what later steps read.

    Elements are keyed by identifier (disabled ones included: refine steps disable),
    relationships by ``source -> target`` under their type, since their identifiers are
    generated per run.
    """
    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    for element in archimate_manager.get_elements():
        props = {"name": element.name, "documentation": element.documentation, "enabled": element.enabled, **element.properties}
        outputs[(element.element_type, element.identifier)] = _decided(props)
    for relationship in archimate_manager.get_relationships():
        props = {"name": relationship.name, "documentation": relationship.documentation, **relationship.properties}
        outputs[(relationship.relationship_type, f"{relationship.source} -> {relationship.target}")] = _decided(props)
    return outputs


def step_output(before: dict[tuple[str, str], dict[str, Any]], after: dict[tuple[str, str], dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """What a step added or changed (with its properties), and what it removed."""
    output = {key: props for key, props in after.items() if before.get(key) != props}
    output.update({(f"{group} (removed)", key): {} for group, key in before if (group, key) not in after})
    return output


@dataclass(frozen=True)
class _Plan:
    """The steps that build a step's input (from the cache) and the steps each run repeats."""

    extraction_input: list[str]
    derivation_input: list[str]
    extraction_step: list[str]
    derivation_step: list[str]
    unscored: frozenset[str] = frozenset()


@dataclass
class StepBenchmarkResult:
    """Per repository: the consistency of the step's outputs, its answer and decision stability and live LLM calls."""

    session_id: str
    step: str
    repositories: dict[str, StepConsistency] = field(default_factory=dict)
    answer_stability: dict[str, list[AnswerStability]] = field(default_factory=dict)
    # Steps that report one decision per item (their stats' ``decisions``)
    decision_stability: dict[str, DecisionStability] = field(default_factory=dict)
    llm_calls: dict[str, list[int]] = field(default_factory=dict)  # live calls per run
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    unscored: list[str] = field(default_factory=list)  # properties reported but not scored in exact

    def average(self, score: str) -> float | None:
        """Mean of ``presence_score`` or ``exact_score`` over the repositories."""
        scores = [getattr(consistency, score) for consistency in self.repositories.values()]
        return sum(scores) / len(scores) if scores else None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "step": self.step,
            "average": {"presence": self.average("presence_score"), "exact": self.average("exact_score")},
            "repositories": {
                repo: {
                    "consistency": consistency.to_dict(),
                    "llm_calls": self.llm_calls.get(repo, []),
                    "answer_stability": [s.to_dict() for s in self.answer_stability.get(repo, [])],
                    "decision_stability": self.decision_stability[repo].to_dict() if repo in self.decision_stability else None,
                }
                for repo, consistency in self.repositories.items()
            },
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
            "unscored_properties": self.unscored,
        }


class StepBenchmark(benchmarking.BenchmarkOrchestrator):
    """Repeat one pipeline step on a fixed input (see the module docstring)."""

    def run_step(self, step: str, verbose: bool = False) -> StepBenchmarkResult:
        """Measure one step on every configured repository, ``runs_per_combination`` runs each."""
        started = time.perf_counter()
        self.session_start = datetime.now()
        self.session_id = f"bench_{self.session_start.strftime('%Y%m%d_%H%M%S')}"
        query_stats.reset()
        result = StepBenchmarkResult(session_id=self.session_id, step=step)

        self._model_configs = benchmarking.load_benchmark_models()
        missing = [m for m in self.config.models if m not in self._model_configs]
        if missing:
            result.errors.append(f"Missing model configs: {missing}")
            return result
        plan = self._plan(step)
        if plan is None:
            result.errors.append(f"Unknown or disabled step: {step}")
            return result
        result.unscored = sorted(plan.unscored)

        self._create_session()
        self.ocel_log.create_event(
            activity="StartBenchmark",
            objects={"BenchmarkSession": [self.session_id]},
            repositories=self.config.repositories,
            models=self.config.models,
            runs_per_combination=self.config.runs_per_combination,
            step=step,
        )
        if verbose:
            print(f"\nSTEP BENCHMARK {self.session_id}: {step}, {self.config.runs_per_combination} runs per repository")
        for repo in self.config.repositories:
            try:
                result.repositories[repo], decisions = self._repeat(repo, step, plan, verbose)
                if decisions:
                    result.decision_stability[repo] = decision_stability(decisions)
                result.llm_calls[repo] = self._live_calls(repo, step)
            except Exception as e:
                result.errors.append(f"{repo}: {e}")
                if verbose:
                    print(f"  {repo}: ERROR: {e}")

        self._export_ocel()
        result.answer_stability = BenchmarkAnalyzer([self.session_id], self.engine).analyze_answer_stability()
        result.duration_seconds = round(time.perf_counter() - started, 1)
        session_dir = Path("workspace/benchmarks") / self.session_id
        (session_dir / "step_results.json").write_text(json.dumps(result.to_dict(), indent=1), encoding="utf-8")
        self._complete_session(len(result.repositories), len(result.errors))
        return result

    def _run_id(self, repo: str, step: str, run: int) -> str:
        return f"{self.session_id}:{repo}:{step}:{run}"

    def _plan(self, step: str) -> _Plan | None:
        """Every enabled step before ``step`` in pipeline order is its input; None for an unknown step."""
        extraction_steps = [c.node_type for c in config_service.get_extraction_configs(self.engine, enabled_only=True)]
        if step in extraction_steps:
            return _Plan(extraction_steps[: extraction_steps.index(step)], [], [step], [])
        phases = {phase: [c.step_name for c in config_service.get_derivation_configs(self.engine, enabled_only=True, phase=phase)] for phase in ("prep", "generate", "refine")}
        if step == "prep":
            return _Plan(extraction_steps, [], [], phases["prep"])
        # The relationship pass only runs when relationships are deferred (run_derivation)
        relationship_pass = [derivation.RELATIONSHIP_STEP] if self.config.defer_relationships else []
        order = phases["prep"] + phases["generate"] + relationship_pass + phases["refine"]
        if step not in order:
            return None
        unscored = UNSCORED_ELEMENT_PROPERTIES if step in phases["generate"] else frozenset()
        return _Plan(extraction_steps, order[: order.index(step)], [], [step], unscored)

    def _outputs(self, plan: _Plan) -> dict[tuple[str, str], dict[str, Any]]:
        outputs = graph_outputs(self.graph_manager)
        if plan.derivation_input or plan.derivation_step:
            outputs.update(model_outputs(self.archimate_manager))
        return outputs

    def _repeat(self, repo: str, step: str, plan: _Plan, verbose: bool) -> tuple[StepConsistency, list[dict[str, Any]]]:
        """Build the step's input once, then run the step on a fresh copy of it each time.

        Returns the consistency of the outputs and, when the step reports them in every run,
        its per-item decisions per run (else an empty list).
        """
        work_key = f"{repo}.step"
        work_file = database_file(work_key)
        if work_file is None:
            raise RuntimeError("the step benchmark needs GRAFEO_DB_DIR: it copies the input database for every run")
        input_file = Path("workspace/benchmarks") / str(self.session_id) / "steps" / f"{repo}_input.grafeo"
        input_file.parent.mkdir(parents=True, exist_ok=True)
        versions = getattr(self, "_config_versions_snapshot", None)

        # The input: every earlier step, answered from the LLM cache
        close_database()
        Path(work_file).unlink(missing_ok=True)
        try:
            use_database(work_key)
            self.config.nocache_configs = []
            built = [self._extract_repo(repo, versions, steps=plan.extraction_input, verbose=verbose)] if plan.extraction_input else []
            if plan.derivation_input:
                built.append(self._derive_repo(repo, versions, steps=plan.derivation_input, verbose=verbose))
            failed = [b.get("errors") for b in built if not b.get("success")]
            if failed:
                raise RuntimeError(f"building the input failed: {failed}")
            before = self._outputs(plan)
            close_database()
            shutil.copyfile(work_file, input_file)

            # The step alone, without the LLM cache, on a fresh copy of the input each run
            self.config.nocache_configs = plan.extraction_step + plan.derivation_step
            outputs = []
            decisions: list[dict[str, Any] | None] = []
            for run in range(1, self.config.runs_per_combination + 1):
                close_database()
                shutil.copyfile(input_file, work_file)
                use_database(work_key)
                run_id = self._run_id(repo, step, run)
                if plan.extraction_step:
                    done = self._extract_repo(repo, versions, steps=plan.extraction_step, run_id=run_id, verbose=verbose)
                else:
                    done = self._derive_repo(repo, versions, steps=plan.derivation_step, run_id=run_id, verbose=verbose)
                if not done.get("success"):
                    raise RuntimeError(f"run {run} failed: {done.get('errors')}")
                outputs.append(step_output(before, self._outputs(plan)))
                if plan.extraction_step:
                    decisions.append((done.get("step_stats") or {}).get(repo, {}).get(step, {}).get("decisions"))
                else:
                    # An element step decides per candidate: the stage it reached and the element it became
                    decisions.append({d["node_id"]: [d["stage"], d.get("element_id")] for d in done.get("candidate_decisions") or []} or None)
                # Each run's output, for investigating what differs
                objects = [{"type": group, "key": key, "properties": props} for (group, key), props in sorted(outputs[-1].items())]
                (input_file.parent / f"{repo}_run{run}.json").write_text(json.dumps(objects, indent=1, default=str), encoding="utf-8")
                self._export_ocel_incremental()
                if verbose:
                    print(f"  {repo} run {run}/{self.config.runs_per_combination}: {len(outputs[-1])} objects")
        finally:
            # The work database goes, also when building the input or a run fails
            close_database()
            Path(work_file).unlink(missing_ok=True)

        consistency = compare_step_outputs(outputs, unscored=plan.unscored)
        if verbose:
            print(f"  {repo}: presence {consistency.presence_score:.1%} ({consistency.present}/{consistency.total}), exact {consistency.exact_score:.1%}")
        reported = [d for d in decisions if d is not None]
        return consistency, reported if len(reported) == len(decisions) else []

    def _derive_repo(self, repo_name: str, config_versions: dict[str, dict[str, int]] | None, steps: list[str], verbose: bool = False, run_id: str | None = None) -> dict[str, Any]:
        """Run the named derivation steps on the current model, logging their steps and LLM calls."""
        run_logger = benchmarking.OCELRunLogger(
            ocel_log=self.ocel_log,
            run_id=run_id or f"{self.session_id}:derivation:{repo_name}",
            session_id=self.session_id or "",
            model=self._model_configs[self.config.models[0]].model,
            repo=repo_name,
            verbose=verbose,
        )
        previous_run_id, self._current_run_id = self._current_run_id, run_logger.run_id
        previous_model, self._current_model = self._current_model, self.config.models[0]
        try:
            return derivation.run_derivation(
                engine=self.engine,
                graph_manager=self.graph_manager,
                archimate_manager=self.archimate_manager,
                llm_query_fn=self._make_extraction_llm_fn(run_logger),
                steps=steps,
                run_logger=cast("RunLoggerProtocol", run_logger),
                defer_relationships=self.config.defer_relationships,
                config_versions=config_versions,
            )
        finally:
            self._current_run_id = previous_run_id
            self._current_model = previous_model

    def _live_calls(self, repo: str, step: str) -> list[int]:
        """LLM calls answered live (not from the cache) in each run of the step."""
        return [
            sum(
                1
                for event in self.ocel_log.events
                if event.activity == "LLMQuery" and self._run_id(repo, step, run) in event.objects.get("BenchmarkRun", []) and not event.attributes.get("cache_hit")
            )
            for run in range(1, self.config.runs_per_combination + 1)
        ]
