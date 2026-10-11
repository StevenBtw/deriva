"""Benchmark operations on a connected PipelineSession (deriva-dev)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deriva.adapters.grafeo import use_database
from deriva.bench import benchmark_views, benchmarking
from deriva.common.paths import workspace
from deriva.services import config, export_bundle

if TYPE_CHECKING:
    from deriva.bench import step_benchmark
    from deriva.common.types import BenchmarkProgressReporter
    from deriva.services.session import PipelineSession

BENCHMARKS_DIR = workspace() / "benchmarks"


def _folder(benchmarks_dir: str | Path | None) -> Path:
    """The folder given, else the benchmark folder (read when called, so it can be pointed elsewhere)."""
    return Path(benchmarks_dir) if benchmarks_dir is not None else Path(BENCHMARKS_DIR)


def _check_session_id(session_id: str) -> None:
    """Session ids name folders under the benchmarks folder; anything that could leave it is refused."""
    if not re.fullmatch(r"[\w.-]+", session_id) or set(session_id) == {"."}:
        raise ValueError(f"Not a benchmark session id: {session_id}")


def _pipeline_order(engine: Any) -> Any:
    """A sort key for step names in pipeline order: extraction by sequence, then derivation by phase and sequence.

    A sub-call (``ApplicationComponent.naming``) follows its step; steps without a config come last, by name.
    """
    extraction = {c.node_type: c.sequence for c in config.get_extraction_configs(engine)}
    phases = {phase: i for i, phase in enumerate(config.DERIVATION_PHASES)}
    derivation = {c.step_name: (phases.get(c.phase, len(phases)), c.sequence) for c in config.get_derivation_configs(engine)}

    def key(step: str) -> tuple[int, int, int, str]:
        base = step.split(".", 1)[0]
        if base in extraction:
            return (0, 0, extraction[base], step)
        if base in derivation:
            return (1, *derivation[base], step)
        return (2, 0, 0, step)

    return key


class BenchmarkSession:
    """A PipelineSession with the benchmark operations; everything else is the wrapped session's."""

    def __init__(self, session: PipelineSession) -> None:
        self.session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    def run_benchmark(
        self,
        repositories: list[str],
        models: list[str],
        runs: int = 3,
        stages: list[str] | None = None,
        description: str = "",
        verbose: bool = False,
        use_cache: bool = True,
        nocache_configs: list[str] | None = None,
        progress: BenchmarkProgressReporter | None = None,
        export_models: bool = True,
        clear_between_runs: bool = True,
        bench_hash: bool = False,
        defer_relationships: bool = True,
        per_repo: bool = False,
        no_cache_extraction: bool = False,
        no_cache_extraction_llm: bool = False,
    ) -> benchmarking.BenchmarkResult:
        """
        Run a full benchmark matrix.

        Args:
            repositories: List of repository names to benchmark
            models: List of model config names (the LLM_{NAME}_* models of .env)
            runs: Number of runs per (repo, model) combination
            stages: Pipeline stages to run (default: all)
            description: Optional description for the session
            verbose: Print progress
            use_cache: Enable LLM response caching (default: True)
            nocache_configs: List of config names to skip cache for (for A/B testing)
            progress: Optional progress reporter for visual feedback
            export_models: Export ArchiMate model file after each run (default: True)
            clear_between_runs: Clear graph/model between runs (default: True)
            bench_hash: Include repo/model/run in cache key for per-run isolation (default: False)
            defer_relationships: Two-phase derivation: create elements first, then relationships (default: False)
            per_repo: Run each repository as a separate benchmark instead of combined (default: False)

        Returns:
            BenchmarkResult with session details

        Example:
            result = BenchmarkSession(session).run_benchmark(
                repositories=["my-repo"],
                models=["azure-gpt4", "openai-gpt4o"],
                runs=3,
                stages=["extraction", "derivation"],
                nocache_configs=["ApplicationComponent"],  # Test new prompt
            )
        """
        engine, graph_manager, archimate_manager = self.session.managers()

        bench_config = benchmarking.BenchmarkConfig(
            repositories=repositories,
            models=models,
            runs_per_combination=runs,
            stages=stages or ["extraction", "derivation"],
            description=description,
            use_cache=use_cache,
            nocache_configs=nocache_configs or [],
            export_models=export_models,
            clear_between_runs=clear_between_runs,
            bench_hash=bench_hash,
            defer_relationships=defer_relationships,
            per_repo=per_repo,
            no_cache_extraction=no_cache_extraction,
            no_cache_extraction_llm=no_cache_extraction_llm,
        )

        orchestrator = benchmarking.BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=bench_config,
        )

        try:
            return orchestrator.run(verbose=verbose, progress=progress)
        finally:
            # The benchmark switched to each repository's database
            use_database(self.session.repository)

    def run_step_benchmark(self, step: str, repositories: list[str], model: str, runs: int = 3, verbose: bool = False) -> step_benchmark.StepBenchmarkResult:
        """Repeat one extraction step on a fixed input per repository and compare its outputs.

        The input is built once from the LLM cache; each run starts from a copy of it and
        calls the LLM for the step without the cache (see ``bench.step_benchmark``).
        """
        engine, graph_manager, archimate_manager = self.session.managers()

        from deriva.bench import step_benchmark

        benchmark = step_benchmark.StepBenchmark(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=benchmarking.BenchmarkConfig(repositories=repositories, models=[model], runs_per_combination=runs, per_repo=True),
        )
        try:
            return benchmark.run_step(step, verbose=verbose)
        finally:
            # The benchmark switched to (and closed) its work databases
            use_database(self.session.repository)

    def analyze_benchmark(self, session_id: str) -> benchmarking.BenchmarkAnalyzer:
        """
        Load and analyze a completed benchmark.

        Args:
            session_id: Benchmark session ID to analyze

        Returns:
            BenchmarkAnalyzer instance for computing metrics

        Example:
            analyzer = BenchmarkSession(session).analyze_benchmark("bench_20240115_103000")
            summary = analyzer.compute_full_analysis()
            analyzer.export_summary("analysis.json")
        """
        engine, _, _ = self.session.managers()

        return benchmarking.BenchmarkAnalyzer(session_id, engine)

    def analyze_config_deviations(self, session_id: str) -> Any:
        """
        Analyze which configs produce deviations across benchmark runs.

        Args:
            session_id: Benchmark session ID to analyze

        Returns:
            ConfigDeviationAnalyzer instance for computing per-config deviation stats

        Example:
            analyzer = BenchmarkSession(session).analyze_config_deviations("bench_20240115_103000")
            report = analyzer.analyze()
            analyzer.export_json("deviations.json")
        """
        engine, _, _ = self.session.managers()

        from deriva.bench import config_deviation

        return config_deviation.ConfigDeviationAnalyzer(session_id, engine)

    def mark_benchmark_failed(self, session_id: str) -> int:
        """End a session whose process stopped without finishing as failed (its files stay); returns the runs marked."""
        _check_session_id(session_id)
        engine, _, _ = self.session.managers()
        return benchmarking.mark_session_failed(engine, session_id)

    def export_process_logs(self, session_ids: list[str], out_dir: str | Path, benchmarks_dir: str | Path | None = None) -> list[Path]:
        """The event logs of the sessions as OCEL 2.0 and a flat case log (CSV, XES) in one folder."""
        for session_id in session_ids:
            _check_session_id(session_id)
        return benchmarking.export_process_logs(_folder(benchmarks_dir), session_ids, out_dir)

    def export_benchmark(self, session_id: str, out_path: str | Path, benchmarks_dir: str | Path | None = None) -> dict[str, Any]:
        """Export a benchmark session as one verifiable zip.

        Holds the session folder (event logs, LLM call logs, models, step results), the full
        config texts at the session's versions, and the environment (versions, git commit,
        grafeo build, model configs without keys). Returns the manifest (sha256 per file).
        """
        _check_session_id(session_id)
        engine, _, _ = self.session.managers()
        row = engine.execute("SELECT config, config_versions_snapshot FROM benchmark_sessions WHERE session_id = ?", [session_id]).fetchone()
        settings = json.loads(row[0]) if row and row[0] else {}
        versions = json.loads(row[1]) if row and row[1] else {}
        extraction_versions = versions.get("extraction") or {}
        derivation_versions = versions.get("derivation") or {}
        snapshot = {
            "session_id": session_id,
            "versions": versions or None,
            "extraction": [{**vars(c), "version": extraction_versions[c.node_type]} for c in config.get_extraction_configs_by_version(engine, extraction_versions)]
            if extraction_versions
            else [],
            "derivation": [{**vars(c), "version": derivation_versions[c.step_name]} for c in config.get_derivation_configs_by_version(engine, derivation_versions)]
            if derivation_versions
            else [],
        }
        models = self.session.list_benchmark_models()
        used = {name: models[name] for name in settings.get("models", []) if name in models}
        extras = {"config_snapshot.json": snapshot, "environment.json": export_bundle.environment_info(models=used)}
        return export_bundle.export_session(_folder(benchmarks_dir) / session_id, out_path, extras)

    def _benchmark_models(self, session_ids: list[str]) -> list[str]:
        """Model config names of the sessions (from their recorded config), else the configured ones."""
        engine, _, _ = self.session.managers()
        names: set[str] = set()
        for session_id in session_ids:
            row = engine.execute("SELECT config FROM benchmark_sessions WHERE session_id = ?", [session_id]).fetchone()
            if row and row[0]:
                names |= set(json.loads(row[0]).get("models", []))
        return sorted(names or set(self.session.list_benchmark_models()))

    def benchmark_results(self, session_ids: list[str], benchmarks_dir: str | Path | None = None) -> list[dict[str, Any]]:
        """Consistency per repository and model over the runs of one or more sessions (by name and by source)."""
        for session_id in session_ids:
            _check_session_id(session_id)
        return benchmark_views.results(_folder(benchmarks_dir), session_ids, self._benchmark_models(session_ids))

    def benchmark_flips(self, session_ids: list[str], repository: str, benchmarks_dir: str | Path | None = None) -> list[dict[str, Any]]:
        """Elements of a repository that are not in every run, with the cause per missing run."""
        for session_id in session_ids:
            _check_session_id(session_id)
        return benchmark_views.flips(_folder(benchmarks_dir), session_ids, self._benchmark_models(session_ids), repository)

    def benchmark_inspector(self, session_ids: list[str], repository: str, benchmarks_dir: str | Path | None = None, model: str | None = None) -> dict[str, Any]:
        """Element and relationship occurrences per run of a repository (of one model when given), for the model inspector."""
        for session_id in session_ids:
            _check_session_id(session_id)
        return benchmark_views.inspector(_folder(benchmarks_dir), session_ids, self._benchmark_models(session_ids), repository, model)

    def benchmark_trace(
        self, session_ids: list[str], repository: str, element_type: str, source: str, benchmarks_dir: str | Path | None = None, model: str | None = None
    ) -> list[dict[str, Any]]:
        """Per run of the sessions (of one model when given), why an element (by type and source) is or is not in the model, with its deciding calls."""
        for session_id in session_ids:
            _check_session_id(session_id)
        return benchmark_views.element_trace(_folder(benchmarks_dir), session_ids, self._benchmark_models(session_ids), repository, element_type, source, model)

    def benchmark_steps(self, session_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Raw LLM answer stability per step and repository (same prompt, same decision in every run)."""
        for session_id in session_ids:
            _check_session_id(session_id)
        engine, _, _ = self.session.managers()
        from deriva.bench import analysis

        stability = analysis.BenchmarkAnalyzer(session_ids, engine).analyze_answer_stability()
        order = _pipeline_order(engine)
        return {repo: [s.to_dict() for s in sorted(steps, key=lambda s: order(s.step))] for repo, steps in stability.items()}

    def list_benchmarks(self, limit: int = 10) -> list[dict]:
        """
        List recent benchmark sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session dictionaries
        """
        engine, _, _ = self.session.managers()

        return benchmarking.list_benchmark_sessions(engine, limit)
