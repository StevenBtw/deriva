"""
Benchmarking service for Deriva.

Orchestrates multi-model, multi-repository benchmarking with OCEL event logging
for process mining analysis, and provides post-run consistency analysis.

Test Matrix Example:
    3 repositories × 3 LLM models × 3 runs = 27 total executions

Metrics Tracked:
    - Intra-model consistency: How stable is each model on the same repo?
    - Inter-model consistency: How do different models compare on the same repo?
    - Inconsistency localization: WHERE do things diverge?

Orchestration Usage:
    config = BenchmarkConfig(
        repositories=["repo1", "repo2"],
        models=["azure-gpt4", "openai-gpt4o"],
        runs_per_combination=3,
        stages=["extraction", "derivation"],
    )

    orchestrator = BenchmarkOrchestrator(engine, graph_manager, archimate_manager, config)
    result = orchestrator.run(verbose=True)

Analysis Usage:
    analyzer = BenchmarkAnalyzer(session_id, engine)

    # Compute metrics
    intra = analyzer.compute_intra_model_consistency()
    inter = analyzer.compute_inter_model_consistency()
    localization = analyzer.localize_inconsistencies()

    # Export
    analyzer.export_summary("analysis.json")
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter

if TYPE_CHECKING:
    from deriva.common.types import BenchmarkProgressReporter, RunLoggerProtocol
from deriva.adapters.grafeo import close_database, database_file, use_database
from deriva.adapters.graph import GraphManager
from deriva.adapters.llm import LLMManager
from deriva.adapters.llm.manager import load_benchmark_models
from deriva.adapters.llm.model_registry import reasoning_settings
from deriva.adapters.llm.models import BenchmarkModelConfig
from deriva.adapters.repository import RepoManager
from deriva.bench import baseline_b1, session_metrics
from deriva.common.json_utils import extract_json_from_response
from deriva.common.ocel import OCELLog, create_run_id, hash_content, load_benchmark_ocel
from deriva.common.paths import workspace
from deriva.common.settings import LlmSettings
from deriva.common.timing import query_stats, summarize_run_events
from deriva.modules.analysis import compute_consistency_score, decision_content, decision_stability
from deriva.modules.analysis.model_quality import compute_model_quality
from deriva.modules.analysis.semantic_matching import parse_archi_xml, parse_exchange_format_xml
from deriva.services import config as config_service
from deriva.services import derivation, export_bundle, export_levels, extraction
from deriva.services.llm_log import LlmCallLog, record_call, run_log_path

logger = logging.getLogger(__name__)

# Per-run LLM call logs: <root>/<session>/llm/<run>.jsonl
LLM_LOG_ROOT = workspace() / "benchmarks"

# =============================================================================
# OCEL RUN LOGGER - Per-config event logging for benchmarks
# =============================================================================


class OCELRunLogger:
    """
    A run logger that creates OCEL events for each config step.

    Implements the RunLogger protocol for use with extraction/derivation services,
    but logs to OCEL format instead of JSONL files.

    Also tracks the current config for per-config cache control.
    """

    def __init__(
        self,
        ocel_log: OCELLog,
        run_id: str,
        session_id: str,
        model: str,
        repo: str,
        verbose: bool = False,
    ):
        self.ocel_log = ocel_log
        self.run_id = run_id
        self.session_id = session_id
        self.model = model
        self.repo = repo
        self.verbose = verbose  # print one line per completed step
        self._current_phase: str | None = None
        self._current_config: str | None = None  # Current config being executed
        self._step_sequence: int = 0

    @property
    def current_config(self) -> str | None:
        """Get the currently executing config (node_type or step_name)."""
        return self._current_config

    def phase_start(self, phase: str, message: str = "") -> None:
        """Log start of a phase."""
        self._current_phase = phase

    def phase_complete(self, phase: str, message: str = "", stats: dict | None = None) -> None:
        """Log completion of a phase."""
        self._current_phase = None
        self._current_config = None

    def phase_error(self, phase: str, error: str, message: str = "") -> None:
        """Log phase error."""
        self._current_phase = None
        self._current_config = None

    def step_start(self, step: str, message: str = "") -> OCELStepContext:
        """
        Log start of a config step (extraction node_type or derivation step_name).

        Sets current_config for per-config cache control.
        Returns a context for tracking step completion.
        """
        self._current_config = step
        self._step_sequence += 1
        return OCELStepContext(self, step, self._step_sequence)

    def log_config_result(
        self,
        config_type: str,  # "extraction" or "derivation"
        config_id: str,  # node_type or step_name
        objects_created: list[str],
        edges_created: list[str] | None = None,
        relationships_created: list[str] | None = None,
        stats: dict | None = None,
        errors: list[str] | None = None,
    ) -> None:
        """
        Log per-config OCEL event with created objects.

        This enables config-deviation correlation in analysis.

        Args:
            config_type: "extraction" or "derivation"
            config_id: node_type or step_name
            objects_created: List of created node/element IDs
            edges_created: List of created edge IDs (extraction only)
            relationships_created: List of created relationship IDs (derivation only)
            stats: Additional statistics
            errors: List of error messages
        """
        activity = "ExtractConfig" if config_type == "extraction" else "DeriveConfig"
        object_type = "GraphNode" if config_type == "extraction" else "Element"

        objects_dict = {
            "BenchmarkSession": [self.session_id],
            "BenchmarkRun": [self.run_id],
            "Repository": [self.repo],
            "Model": [self.model],
            "Config": [config_id],
            object_type: objects_created,
        }

        # Add edges for extraction
        if edges_created:
            objects_dict["Edge"] = edges_created

        # Add relationships for derivation
        if relationships_created:
            objects_dict["Relationship"] = relationships_created

        _stats = stats or {}
        self.ocel_log.create_event(
            activity=activity,
            objects=objects_dict,
            config_type=config_type,
            config_id=config_id,
            objects_created=len(objects_created),
            edges_created=len(edges_created) if edges_created else 0,
            relationships_created=len(relationships_created) if relationships_created else 0,
            duration_seconds=_stats.get("duration_seconds", 0),
            stats=_stats,
            errors=errors or [],
        )


# Incoming edge type -> the extraction route that created the node
_ROUTE_BY_EDGE = {"REPRESENTS": "directory", "REFERENCES": "document"}


def _node_routes(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """The extraction routes that produced each node, read from its incoming edges.

    Directory classification links a concept or technology with REPRESENTS and
    document extraction with REFERENCES. Technology edges (CONFIGURES) carry their
    route (``structural`` or ``llm``); edges written before that stamp count as ``file``.

    Args:
        rows: One row per incoming edge: node ``id``, edge type ``rel``, edge ``props`` (a map)
    """
    routes: dict[str, set[str]] = {}
    for row in rows:
        rel = str(row.get("rel") or "").rsplit(":", 1)[-1]
        route = (row.get("props") or {}).get("route", "file") if rel == "CONFIGURES" else _ROUTE_BY_EDGE.get(rel)
        if route:
            routes.setdefault(row["id"], set()).add(route)
    return {node: sorted(found) for node, found in sorted(routes.items())}


def _candidate_record(decision: dict[str, Any], refined: dict[tuple[str, str], str]) -> dict[str, Any]:
    """A candidate decision for the run snapshot; a created candidate whose element refine disabled names the reason."""
    record = {"type": decision.get("element_type"), "source": decision.get("node_id"), "stage": decision.get("stage")}
    reason = refined.get((str(record["type"]), str(record["source"])))
    if reason and record["stage"] == "created":
        record["refine"] = reason
    return record


def _incoming_routes(graph_manager: GraphManager, label: str) -> dict[str, list[str]]:
    """The extraction routes of every ``Graph:<label>`` node (see ``_node_routes``).

    The labelled node starts the pattern (needed before grafeo 0.5.44, #513, where an
    expand target kept only its first label; both forms work now).
    """
    return _node_routes(graph_manager.query(f"MATCH (n:Graph:{label})<-[r]-() RETURN n.id AS id, type(r) AS rel, properties(r) AS props"))


def _print_timings(timings: dict[str, Any]) -> None:
    """Print the slowest steps, LLM totals and slowest graph queries per run."""
    print("TIMINGS (full detail in timings.json)")
    for item in timings["extraction"]:
        print(f"  extraction {item['repository']}: {item['seconds']}s ({'cached' if item['cached'] else 'extracted'})")
    for run_id, run in timings["runs"].items():
        llm = run["llm"]
        print(f"  {run_id}: {run['run_seconds']}s")
        for step in run["steps"][:5]:
            print(f"    {step['seconds']:>8}s  {step['step']}")
        if llm.get("calls"):
            print(f"    LLM: {llm['calls']} calls ({llm['cache_hits']} cached), {llm['latency_seconds']}s latency, {llm['wait_seconds']}s rate-limit wait, {llm['errors']} errors")
    for q in timings["top_queries"][:5]:
        print(f"  query {q['total_ms'] / 1000:.1f}s x{q['count']}: {q['query'][:100]}")


class OCELStepContext:
    """Context manager for tracking step completion in OCEL."""

    def __init__(self, logger: OCELRunLogger, step: str, sequence: int):
        self.logger = logger
        self.step = step
        self.sequence = sequence
        self.items_processed = 0
        self.items_created = 0
        self.items_failed = 0
        self.stats: dict | None = None
        self._completed = False
        self._created_objects: list[str] = []
        self._created_edges: list[str] = []  # Edge IDs for extraction
        self._created_relationships: list[str] = []  # Relationship IDs for derivation
        # Started here, not in __enter__: pipelines call step_start() without `with`.
        self._start_time = time.perf_counter()

    def __enter__(self) -> OCELStepContext:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.error(str(exc_val))
        elif not self._completed:
            self.complete()

    def add_object(self, object_id: str) -> None:
        """Track a created object ID for OCEL logging."""
        self._created_objects.append(object_id)

    def add_edge(self, edge_id: str) -> None:
        """Track a created edge ID for OCEL logging (extraction)."""
        self._created_edges.append(edge_id)

    def add_relationship(self, relationship_id: str) -> None:
        """Track a created relationship ID for OCEL logging (derivation)."""
        self._created_relationships.append(relationship_id)

    def _elapsed_seconds(self) -> float:
        """The step's duration to the microsecond: the case log derives the start from it, so steps must not overlap."""
        return round(time.perf_counter() - self._start_time, 6)

    def complete(self, message: str = "") -> None:
        """Mark step as completed and log to OCEL."""
        self._completed = True
        if self.logger.verbose:
            print(f"    {self.step}: {self._elapsed_seconds():.2f}s, {self.items_created} created")
        config_type = "extraction" if self.logger._current_phase == "extraction" else "derivation"
        self.logger.log_config_result(
            config_type=config_type,
            config_id=self.step,
            objects_created=self._created_objects,
            edges_created=self._created_edges if self._created_edges else None,
            relationships_created=self._created_relationships if self._created_relationships else None,
            stats={**(self.stats or {}), "items_created": self.items_created, "items_processed": self.items_processed, "duration_seconds": self._elapsed_seconds()},
            errors=[],
        )

    def error(self, error: str, message: str = "") -> None:
        """Mark step as errored."""
        self._completed = True
        if self.logger.verbose:
            print(f"    {self.step}: {self._elapsed_seconds():.2f}s, ERROR {error[:120]}")
        config_type = "extraction" if self.logger._current_phase == "extraction" else "derivation"
        self.logger.log_config_result(
            config_type=config_type,
            config_id=self.step,
            objects_created=self._created_objects,
            edges_created=self._created_edges if self._created_edges else None,
            relationships_created=self._created_relationships if self._created_relationships else None,
            stats={"items_created": self.items_created, "items_failed": self.items_failed, "duration_seconds": self._elapsed_seconds()},
            errors=[error],
        )


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark session."""

    repositories: list[str]
    models: list[str]  # Model config names (from env)
    runs_per_combination: int = 3
    stages: list[str] = field(default_factory=lambda: ["extraction", "derivation"])
    description: str = ""
    clear_between_runs: bool = True
    use_cache: bool = True  # Global cache setting (True = cache enabled)
    nocache_configs: list[str] = field(default_factory=list)  # Configs to always skip cache
    export_models: bool = True  # Export ArchiMate model file after each run
    bench_hash: bool = False  # Include repo/model/run in cache key for per-run isolation
    defer_relationships: bool = True  # Two-phase derivation: elements first, then relationships (recommended)
    per_repo: bool = False  # Run each repo as separate benchmark (vs combined)
    # Enrichment cache settings (mirrors LLM cache patterns)
    # Extraction cache settings
    no_cache_extraction: bool = False  # Force full re-extraction (ignore fingerprint)
    no_cache_extraction_llm: bool = False  # Re-run LLM extraction steps only (keep structural/AST)
    # Every run extracts (its own model, no cache) on its own graph, kept in the session's graphs folder
    extract_per_run: bool = False
    # A baseline instead of Deriva: "b1" (one generation of the whole model from raw repository material)
    baseline: str | None = None

    def total_runs(self) -> int:
        """Calculate total number of runs in the matrix.

        Combined mode: Each (model, iteration) is ONE run - repos are processed together.
        Per-repo mode: Each (repo, model, iteration) is ONE run - repos run separately.
        """
        if self.per_repo:
            return len(self.repositories) * len(self.models) * self.runs_per_combination
        return len(self.models) * self.runs_per_combination

    def get_combined_repo_name(self) -> str:
        """Get alphabetically sorted concatenated repo name for output files."""
        sorted_repos = sorted(self.repositories)
        return "_".join(sorted_repos)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return asdict(self)


def generation_settings(config: Any) -> dict[str, Any]:
    """The generation settings a model config sends with every call: temperature (none when sampling is off), top_p and
    seed (never sent), the reasoning level and the provider settings it becomes (thinking off, reasoning effort)."""
    own, reasoning = getattr(config, "temperature", None), getattr(config, "reasoning", None)
    temperature = (own if own is not None else LlmSettings().temperature) if getattr(config, "sampling", True) else None
    provider = str(getattr(config, "provider", ""))
    return {
        "provider": provider,
        "model": getattr(config, "model", None),
        "temperature": temperature,
        "top_p": None,
        "seed": None,
        "reasoning": reasoning,
        "provider_settings": reasoning_settings(provider, reasoning) if reasoning else {},
    }


def validate_config(config: BenchmarkConfig) -> None:
    """Refuse a configuration that cannot measure what it claims (raises ValueError)."""
    if config.baseline is not None:
        if config.baseline != "b1":
            raise ValueError(f"Unknown baseline {config.baseline!r} (b1)")
        if config.use_cache:
            raise ValueError("--baseline needs --no-cache: every run generates anew")
        if config.extract_per_run:
            raise ValueError("--baseline runs no extraction: leave out --extract-per-run")
    if config.extract_per_run:
        if not {"extraction", "derivation"} <= set(config.stages):
            raise ValueError("--extract-per-run needs the stages extraction and derivation")
        if config.use_cache:
            raise ValueError("--extract-per-run needs --no-cache: every run repeats the pipeline without any cache")


def _run_graph_key(session_id: str, repo: str, model: str, iteration: int) -> str:
    """The graph database key of one run (a plain file name in GRAFEO_DB_DIR)."""
    return f"{repo}__{session_id}__{model}__run{iteration}".replace("/", "_").replace("\\", "_")


@dataclass
class BenchmarkResult:
    """Results from a completed benchmark session."""

    session_id: str
    config: BenchmarkConfig
    runs_completed: int
    runs_failed: int
    ocel_path: str
    duration_seconds: float
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if benchmark completed successfully."""
        return self.runs_failed == 0


@dataclass
class RunResult:
    """Result from a single benchmark run."""

    run_id: str
    repositories: list[str]  # Can be single or multiple repos
    model: str
    iteration: int
    status: str  # completed, failed
    stats: dict[str, Any]
    errors: list[str]
    duration_seconds: float

    @property
    def repository(self) -> str:
        """Legacy property for single repo access."""
        return self.repositories[0] if self.repositories else ""

    @property
    def combined_repo_name(self) -> str:
        """Alphabetically sorted concatenated repo name."""
        return "_".join(sorted(self.repositories))


class BenchmarkOrchestrator:
    """
    Orchestrates benchmark execution across repo × model × run matrix.

    Responsibilities:
    - Load model configurations from environment
    - Create and manage benchmark session in DuckDB
    - Execute pipeline for each (repo, model, iteration) combination
    - Log all events to OCEL format
    - Handle model switching between runs
    """

    def __init__(
        self,
        engine: Any,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        config: BenchmarkConfig,
    ):
        """
        Initialize the orchestrator.

        Args:
            engine: DuckDB connection
            graph_manager: Connected GraphManager instance
            archimate_manager: Connected ArchimateManager instance
            config: Benchmark configuration
        """
        self.engine = engine
        self.graph_manager = graph_manager
        self.archimate_manager = archimate_manager
        self.config = config

        # OCEL event log
        self.ocel_log = OCELLog()

        # Session tracking
        self.session_id: str | None = None
        self.session_start: datetime | None = None

        # Model configs (loaded from env)
        self._model_configs: dict[str, BenchmarkModelConfig] = {}

        # Current context for OCEL events
        self._current_run_id: str | None = None
        # Per-run LLM call logs (prompt and answer of every call), by run id
        self._call_logs: dict[str, LlmCallLog] = {}
        # LLM answers per decision per step, recorded in the session metadata
        self._llm_samples: dict[str, int] = {}
        # The code commit and dirty flag when the session started, recorded in the session metadata
        self._code: dict[str, Any] = {"commit": None, "dirty": None}
        self._current_model: str | None = None
        self._current_repo: str | None = None

    def _preload_ollama_models(self, verbose: bool = False) -> list[str]:
        """
        Preload Ollama models to avoid cold-start 404 errors.

        Ollama models need to be loaded into memory before they can respond.
        This sends a simple warmup request to each Ollama model.

        Returns:
            List of any errors encountered during preloading
        """
        import httpx2

        errors = []
        ollama_models = [(name, cfg) for name, cfg in self._model_configs.items() if cfg.provider == "ollama" and name in self.config.models]

        if not ollama_models:
            return errors

        if verbose:
            print(f"\nPreloading {len(ollama_models)} Ollama model(s)...")

        for name, cfg in ollama_models:
            try:
                if verbose:
                    print(f"  Loading {cfg.model}...", end=" ", flush=True)

                # Send a simple warmup request
                response = httpx2.post(
                    cfg.get_api_url(),
                    json={
                        "model": cfg.model,
                        "messages": [{"role": "user", "content": "Hi"}],
                        "stream": False,
                        "options": {"num_predict": 1},  # Minimal response
                    },
                    timeout=120,  # Allow time for model loading
                )
                response.raise_for_status()

                if verbose:
                    print("OK")

            except httpx2.HTTPError as e:
                error_msg = f"Failed to preload {name}: {e}"
                errors.append(error_msg)
                if verbose:
                    print(f"FAILED: {e}")

        return errors

    def _run_b1(self, repositories: list[str], run_logger: OCELRunLogger, llm_query_fn: Any, verbose: bool = False) -> dict[str, Any]:
        """Baseline B1 for each repository: generate, validate and repair the whole model, then write it to the model."""
        row = config_service.get_derivation_config(self.engine, baseline_b1.CONFIG_STEP)
        if row is None or not row.instruction:
            raise RuntimeError(f"No {baseline_b1.CONFIG_STEP} config row with an instruction (deriva-cli config add derivation {baseline_b1.CONFIG_STEP} --phase baseline)")
        params = baseline_b1.B1Params.from_params(json.loads(row.params) if row.params else {}, config_service.get_excluded_directories(self.engine))
        paths = {str(getattr(r, "name", "")): Path(str(getattr(r, "path", ""))) for r in RepoManager().list_repositories(detailed=True) if hasattr(r, "path")}
        registry = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in config_service.get_file_types(self.engine)]
        report: dict[str, Any] = {}
        for repo in repositories:
            if repo not in paths:
                raise RuntimeError(f"Repository not cloned: {repo}")
            material, manifest = baseline_b1.repository_material(paths[repo], params, registry)
            if verbose:
                print(f"  B1 {repo}: {manifest['chars']} characters ({len(manifest['manifests'])} manifests, {len(manifest['sources'])} sources)")
            step = run_logger.step_start(baseline_b1.CONFIG_STEP)
            model, generated = baseline_b1.generate(llm_query_fn, row.instruction, material, params)
            step.complete()
            elements, relationships = baseline_b1.to_archimate(model)
            for element in elements:
                self.archimate_manager.add_element(element, validate=False)
            for relationship in relationships:
                self.archimate_manager.add_relationship(relationship, validate=False)
            report[repo] = {**generated, "elements": len(elements), "relationships": len(relationships), "material": manifest}
        return report

    def _keep_run_graph(self, key: str, repo_name: str, model_name: str, iteration: int) -> str | None:
        """Close the run's graph database and move its file(s) into the session's ``graphs`` folder."""
        close_database()
        source = database_file(key)
        if not source:
            return None  # in-memory graph: nothing to keep
        folder = workspace() / "benchmarks" / (self.session_id or "unknown") / "graphs"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{repo_name.replace('/', '_')}_{model_name.replace('/', '_')}_run{iteration}"
        kept: str | None = None
        for path in sorted(Path(source).parent.glob(Path(source).name + "*")):
            target = folder / (name + path.name[len(Path(source).stem) :])
            shutil.move(str(path), target)
            if path.name == Path(source).name:
                kept = str(target)
        return kept

    def _make_extraction_llm_fn(self, run_logger: OCELRunLogger, model_name: str | None = None) -> Any:
        """LLM query function for extraction steps, logged like derivation calls (``model_name``: the run's model,
        default the session's first: a shared extraction belongs to it)."""
        model_config = self._model_configs[model_name or self.config.models[0]]
        # --no-cache must reach extraction too, or extraction variance is never measured
        llm_manager = LLMManager.from_config(model_config, nocache=not self.config.use_cache)
        # Configs listed in nocache_configs always get a live call
        nocache_manager = LLMManager.from_config(model_config, nocache=True) if self.config.use_cache else llm_manager
        return self._create_logging_query_fn(llm_manager, nocache_manager, run_logger)

    def _extract_repo(
        self,
        repo_name: str,
        config_versions: dict[str, dict[str, int]] | None,
        extraction_methods: list[str] | None = None,
        verbose: bool = False,
        steps: list[str] | None = None,
        run_id: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """Run extraction for one repo, logging its steps and LLM calls to the event log.

        ``steps`` limits the run to those steps; ``run_id`` names it in the event log
        (default: the session's extraction run of the repo); ``model_name`` is the model that
        extracts (default: the session's first).
        """
        model_name = model_name or self.config.models[0]
        model = self._model_configs[model_name].model
        run_logger = OCELRunLogger(
            ocel_log=self.ocel_log,
            run_id=run_id or f"{self.session_id}:extraction:{repo_name}",
            session_id=self.session_id or "",
            model=model_name,  # the config name, as in the LLM calls and the derivation runs
            repo=repo_name,
            verbose=verbose,
        )
        previous_run_id, self._current_run_id = self._current_run_id, run_logger.run_id
        previous_model, self._current_model = self._current_model, model_name
        try:
            return extraction.run_extraction(
                engine=self.engine,
                graph_manager=self.graph_manager,
                llm_query_fn=self._make_extraction_llm_fn(run_logger, model_name),
                repo_name=repo_name,
                verbose=False,
                run_logger=cast("RunLoggerProtocol", run_logger),
                config_versions=config_versions,
                model=model,
                extraction_methods=extraction_methods,
                steps=steps,
            )
        finally:
            self._current_run_id = previous_run_id
            self._current_model = previous_model

    def _ensure_extraction(self, verbose: bool = False, repositories: list[str] | None = None) -> list[str]:
        """Ensure extraction data exists for all benchmark repositories.

        Supports three cache modes:
        - Default: fingerprint-based caching (skip if configs+repo unchanged)
        - no_cache_extraction: force full re-extraction
        - no_cache_extraction_llm: keep structural/AST data, re-run LLM steps only

        Args:
            verbose: Print progress to stdout

        Returns:
            List of error messages (empty if all succeeded)
        """
        errors: list[str] = []
        config_versions = getattr(self, "_config_versions_snapshot", None)

        if verbose:
            print("\n--- Ensuring extraction data ---")

        for repo_name in repositories if repositories is not None else self.config.repositories:
            start = time.perf_counter()
            result: dict[str, Any] | None = None
            mode = "fingerprint"
            failure: str | None = None
            try:
                current_fp = extraction.compute_extraction_fingerprint(self.engine, repo_name, config_versions)
                stored_fp = self.graph_manager.get_extraction_fingerprint(repo_name)
                fp_match = stored_fp == current_fp

                if self.config.no_cache_extraction:
                    # Mode: Force full re-extraction
                    mode = "forced"
                    if verbose:
                        print(f"  {repo_name}: extracting (forced by --no-cache-extraction)")
                    self.graph_manager.clear_graph_for_repo(repo_name)
                    result = self._extract_repo(repo_name, config_versions, verbose=verbose)

                elif self.config.no_cache_extraction_llm:
                    # Mode: Keep structural/AST, re-run LLM extraction only
                    mode = "llm_only"
                    has_data = self.graph_manager.has_extraction(repo_name)

                    if has_data:
                        # Structural/AST data exists; clear only LLM nodes and re-run LLM steps
                        # Clear exactly what the LLM steps re-create
                        llm_labels = extraction.llm_extraction_labels(self.engine, config_versions)
                        cleared = self.graph_manager.clear_nodes_by_labels(repo_name, llm_labels)
                        if verbose:
                            print(f"  {repo_name}: cleared {cleared} LLM nodes, re-running LLM extraction steps")
                        result = self._extract_repo(repo_name, config_versions, extraction_methods=["llm"], verbose=verbose)
                    else:
                        # No data at all; do full extraction first
                        if verbose:
                            print(f"  {repo_name}: no cached data, running full extraction")
                        result = self._extract_repo(repo_name, config_versions, verbose=verbose)

                elif fp_match:
                    # Default mode: fingerprint-based caching
                    if verbose:
                        print(f"  {repo_name}: extraction cached (fingerprint match)")

                else:
                    reason = "fingerprint mismatch (configs or repo changed)" if stored_fp else "no cached extraction"
                    if verbose:
                        print(f"  {repo_name}: extracting ({reason})")
                    self.graph_manager.clear_graph_for_repo(repo_name)
                    result = self._extract_repo(repo_name, config_versions, verbose=verbose)

                if result is not None and result.get("success"):
                    if verbose:
                        s = result.get("stats", {})
                        print(f"  {repo_name}: extracted {s.get('nodes_created', 0)} nodes, {s.get('edges_created', 0)} edges")
                elif result is not None:
                    repo_errors = result.get("errors", [])
                    errors.extend(repo_errors)
                    if verbose:
                        print(f"  {repo_name}: extraction failed: {repo_errors}")

            except Exception as e:
                error_msg = f"Extraction failed for {repo_name}: {e}"
                failure = error_msg
                errors.append(error_msg)
                if verbose:
                    print(f"  {repo_name}: ERROR: {e}")

            stats = (result or {}).get("stats", {})
            self.ocel_log.create_event(
                activity="EnsureExtraction",
                objects={"BenchmarkSession": [self.session_id or ""], "Repository": [repo_name]},
                repository=repo_name,
                mode=mode,
                cached=result is None and failure is None,
                duration_seconds=round(time.perf_counter() - start, 2),
                nodes_created=stats.get("nodes_created", 0),
                edges_created=stats.get("edges_created", 0),
                errors=(result or {}).get("errors", []) + ([failure] if failure else []),
            )

        if verbose:
            print("--- Extraction phase complete ---\n")

        return errors

    def run(
        self,
        verbose: bool = False,
        progress: BenchmarkProgressReporter | None = None,
    ) -> BenchmarkResult:
        """
        Execute the full benchmark matrix.

        Args:
            verbose: Print progress to stdout
            progress: Optional progress reporter for visual feedback

        Returns:
            BenchmarkResult with session details and metrics
        """
        self.session_start = datetime.now()
        self.session_id = f"bench_{self.session_start.strftime('%Y%m%d_%H%M%S')}"
        query_stats.reset()

        errors: list[str] = []
        validate_config(self.config)

        # Load model configurations
        self._model_configs = load_benchmark_models()
        missing_models = [m for m in self.config.models if m not in self._model_configs]
        if missing_models:
            errors.append(f"Missing model configs: {missing_models}")
            return BenchmarkResult(
                session_id=self.session_id,
                config=self.config,
                runs_completed=0,
                runs_failed=0,
                ocel_path="",
                duration_seconds=0,
                errors=errors,
            )

        # Preload Ollama models to avoid cold-start failures
        preload_errors = self._preload_ollama_models(verbose=verbose)
        if preload_errors:
            errors.extend(preload_errors)
            # Continue anyway - models might still work

        # Create session in database
        self._create_session()
        try:
            return self._run_session(errors, verbose, progress)
        except BaseException:
            # A cancel, Ctrl+C or a crash mid-session: the session ends as failed instead of staying 'running'
            self._fail_session()
            raise

    def _run_session(self, errors: list[str], verbose: bool, progress: BenchmarkProgressReporter | None) -> BenchmarkResult:
        """The session's runs, once its row and inputs record are written; ``errors`` holds the setup's errors so far."""
        assert self.session_id is not None and self.session_start is not None, "session_id must be set after _create_session"
        runs_completed = 0
        runs_failed = 0

        # Log benchmark start
        self.ocel_log.create_event(
            activity="StartBenchmark",
            objects={"BenchmarkSession": [self.session_id]},
            repositories=self.config.repositories,
            models=self.config.models,
            runs_per_combination=self.config.runs_per_combination,
            stages=self.config.stages,
        )

        # Start progress tracking
        if progress:
            progress.start_benchmark(
                session_id=self.session_id,
                total_runs=self.config.total_runs(),
                repositories=self.config.repositories,
                models=self.config.models,
            )

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"BENCHMARK SESSION: {self.session_id}")
            print(f"{'=' * 60}")
            print(f"Repositories: {self.config.repositories}")
            print(f"Models: {self.config.models}")
            print(f"Runs per combination: {self.config.runs_per_combination}")
            print(f"Mode: {'per-repo' if self.config.per_repo else 'combined'}")
            print(f"Total runs: {self.config.total_runs()}")
            print(f"{'=' * 60}\n")

        # Each repo (per-repo mode) or the repo set (combined mode) has its own graph
        # database. Extraction runs once per database (or is skipped if cached), so
        # the benchmark loop only needs to re-derive.
        # With extraction per run (or a baseline), every run opens its own graph instead (``_run_combined``)
        own_graph = self.config.extract_per_run or self.config.baseline is not None
        if not self.config.per_repo and not own_graph:
            use_database(self.config.get_combined_repo_name())
            if "extraction" in self.config.stages:
                errors.extend(self._ensure_extraction(verbose=verbose, repositories=self.config.repositories))

        run_number = 0
        total_runs = self.config.total_runs()

        if self.config.per_repo:
            # Per-repo mode: each repo gets its own benchmark runs
            # Iterate: repo → iteration → model
            for repo_name in self.config.repositories:
                if not own_graph:
                    use_database(repo_name)
                    if "extraction" in self.config.stages:
                        errors.extend(self._ensure_extraction(verbose=verbose, repositories=[repo_name]))
                for iteration in range(1, self.config.runs_per_combination + 1):
                    for model_name in self.config.models:
                        run_number += 1

                        if verbose:
                            print(f"\n--- Run {run_number}/{total_runs} ---")
                            print(f"Repository: {repo_name}")
                            print(f"Model: {model_name}")
                            print(f"Iteration: {iteration}")

                        if progress:
                            progress.start_run(
                                run_number=run_number,
                                repository=repo_name,
                                model=model_name,
                                iteration=iteration,
                            )

                        try:
                            result = self._run_combined(
                                repositories=[repo_name],  # Single repo as list
                                model_name=model_name,
                                iteration=iteration,
                                verbose=verbose,
                                progress=progress,
                            )

                            if result.status == "completed":
                                runs_completed += 1
                                if verbose:
                                    print(f"[OK] Completed: {result.stats}")
                                if progress:
                                    progress.complete_run("completed", result.stats)
                            else:
                                runs_failed += 1
                                errors.extend(result.errors)
                                if verbose:
                                    print(f"[FAIL] Failed: {result.errors}")
                                if progress:
                                    progress.complete_run("failed", result.stats)

                        except Exception as e:
                            runs_failed += 1
                            error_msg = f"Run failed ({repo_name}/{model_name}/{iteration}): {e}"
                            errors.append(error_msg)
                            if verbose:
                                print(f"[FAIL] Exception: {e}")
                            if progress:
                                progress.complete_run("failed")

                        self._export_ocel_incremental()
        else:
            # Combined mode: all repos processed together per run
            # Iterate: iteration → model → [all repos together]
            combined_repo_name = self.config.get_combined_repo_name()

            for iteration in range(1, self.config.runs_per_combination + 1):
                for model_name in self.config.models:
                    run_number += 1

                    if verbose:
                        print(f"\n--- Run {run_number}/{total_runs} ---")
                        print(f"Repositories: {', '.join(self.config.repositories)}")
                        print(f"Model: {model_name}")
                        print(f"Iteration: {iteration}")

                    if progress:
                        progress.start_run(
                            run_number=run_number,
                            repository=combined_repo_name,
                            model=model_name,
                            iteration=iteration,
                        )

                    try:
                        result = self._run_combined(
                            repositories=self.config.repositories,
                            model_name=model_name,
                            iteration=iteration,
                            verbose=verbose,
                            progress=progress,
                        )

                        if result.status == "completed":
                            runs_completed += 1
                            if verbose:
                                print(f"[OK] Completed: {result.stats}")
                            if progress:
                                progress.complete_run("completed", result.stats)
                        else:
                            runs_failed += 1
                            errors.extend(result.errors)
                            if verbose:
                                print(f"[FAIL] Failed: {result.errors}")
                            if progress:
                                progress.complete_run("failed", result.stats)

                    except Exception as e:
                        runs_failed += 1
                        error_msg = f"Run failed ({combined_repo_name}/{model_name}/{iteration}): {e}"
                        errors.append(error_msg)
                        if verbose:
                            print(f"[FAIL] Exception: {e}")
                        if progress:
                            progress.complete_run("failed")

                    self._export_ocel_incremental()

        # Calculate duration
        duration = (datetime.now() - self.session_start).total_seconds()

        # Log benchmark complete
        self.ocel_log.create_event(
            activity="CompleteBenchmark",
            objects={"BenchmarkSession": [self.session_id]},
            runs_completed=runs_completed,
            runs_failed=runs_failed,
            duration_seconds=duration,
        )

        # Export OCEL log
        ocel_path = self._export_ocel()

        # Update session in database
        self._complete_session(runs_completed, runs_failed)

        # Complete progress tracking
        if progress:
            progress.complete_benchmark(
                runs_completed=runs_completed,
                runs_failed=runs_failed,
                duration_seconds=duration,
            )

        if verbose:
            print(f"\n{'=' * 60}")
            print("BENCHMARK COMPLETE")
            print(f"{'=' * 60}")
            print(f"Runs completed: {runs_completed}")
            print(f"Runs failed: {runs_failed}")
            print(f"Duration: {duration:.1f}s")
            print(f"OCEL log: {ocel_path}")
            print(f"{'=' * 60}\n")
            _print_timings(self._timings())

        return BenchmarkResult(
            session_id=self.session_id,
            config=self.config,
            runs_completed=runs_completed,
            runs_failed=runs_failed,
            ocel_path=ocel_path,
            duration_seconds=duration,
            errors=errors,
        )

    def _run_combined(
        self,
        repositories: list[str],
        model_name: str,
        iteration: int,
        verbose: bool = False,
        progress: BenchmarkProgressReporter | None = None,
    ) -> RunResult:
        """
        Execute a combined benchmark run with multiple repositories.

        Processes all repos together: extract all repos → derive combined model → export once.

        Args:
            repositories: List of repositories to process together
            model_name: Model config name to use
            iteration: Run iteration number
            progress: Optional progress reporter for visual feedback

        Returns:
            RunResult with run details
        """
        run_start = datetime.now()
        assert self.session_id is not None, "session_id must be set before executing runs"

        # Create combined repo identifier (alphabetically sorted)
        combined_repo_name = "_".join(sorted(repositories))
        run_id = create_run_id(self.session_id, combined_repo_name, model_name, iteration)

        # Set current context
        self._current_run_id = run_id
        self._current_model = model_name
        self._current_repo = combined_repo_name

        # Create run in database
        self._create_run(run_id, combined_repo_name, model_name, iteration)

        # Log run start with all repositories
        session_id = self.session_id  # Validated above
        self.ocel_log.create_event(
            activity="StartRun",
            objects={
                "BenchmarkSession": [session_id],
                "BenchmarkRun": [run_id],
                "Repository": repositories,  # List all repos
                "Model": [model_name],
            },
            iteration=iteration,
        )

        errors: list[str] = []
        stats: dict[str, Any] = {"extraction": {}, "derivation": {}}

        extraction_decisions: dict[str, dict[str, Any]] = {}
        own_graph = self.config.extract_per_run or self.config.baseline is not None
        run_graph = _run_graph_key(session_id, combined_repo_name, model_name, iteration) if own_graph else None
        result: dict[str, Any] = {}
        try:
            # With extraction per run, the run works in its own (new) graph database
            if run_graph:
                use_database(run_graph)
            # Only clear Model namespace between runs.
            # Extraction data persists (handled by _ensure_extraction before the loop).
            if self.config.clear_between_runs:
                self.archimate_manager.clear_model()

            # Create LLM managers for this model
            # Cache uses default location: workspace/cache/llm
            model_config = self._model_configs[model_name]
            global_nocache = not self.config.use_cache

            if global_nocache:
                # nocache=True skips reading cache but still writes
                llm_manager = LLMManager.from_config(model_config, nocache=True)
                nocache_llm_manager = llm_manager
            else:
                llm_manager = LLMManager.from_config(model_config, nocache=False)
                nocache_llm_manager = LLMManager.from_config(model_config, nocache=True)

            # Create OCEL run logger
            ocel_run_logger = OCELRunLogger(
                ocel_log=self.ocel_log,
                run_id=run_id,
                session_id=session_id,
                model=model_name,
                repo=combined_repo_name,
                verbose=verbose,
            )

            # Build bench_hash if enabled
            bench_hash_str = f"{combined_repo_name}:{model_name}:{iteration}" if self.config.bench_hash else None

            llm_query_fn = self._create_logging_query_fn(
                cached_llm=llm_manager,
                nocache_llm=nocache_llm_manager,
                run_logger=ocel_run_logger,
                bench_hash=bench_hash_str,
            )

            stages = self.config.stages

            if self.config.baseline == "b1":
                stats["baseline"] = self._run_b1(repositories, ocel_run_logger, llm_query_fn, verbose)
            elif self.config.extract_per_run:
                # The complete extraction, live, with the run's model, logged under the run
                totals = {"nodes_created": 0, "edges_created": 0}
                for repo in repositories:
                    if verbose:
                        print(f"  Extracting {repo} ({model_name}, no cache)...")
                    extracted = self._extract_repo(repo, getattr(self, "_config_versions_snapshot", None), verbose=verbose, run_id=run_id, model_name=model_name)
                    for key in totals:
                        totals[key] += (extracted.get("stats") or {}).get(key, 0)
                    for step, step_stats in ((extracted.get("step_stats") or {}).get(repo) or {}).items():
                        if isinstance(step_stats, dict) and step_stats.get("decisions") is not None:
                            extraction_decisions.setdefault(step, {}).update({f"{repo}:{k}" if len(repositories) > 1 else k: v for k, v in step_stats["decisions"].items()})
                    if not extracted.get("success"):
                        errors.extend(extracted.get("errors") or [f"Extraction failed for {repo}"])
                stats["extraction"] = totals
            elif "extraction" in stages:
                # Extraction is handled by _ensure_extraction() before the benchmark loop
                stats["extraction"] = {"skipped": True, "reason": "pre-extracted"}

            # Run derivation ONCE on combined graph
            if "derivation" in stages and self.config.baseline is None:
                if verbose:
                    print("  Deriving combined model...")

                result = derivation.run_derivation(
                    engine=self.engine,
                    graph_manager=self.graph_manager,
                    archimate_manager=self.archimate_manager,
                    llm_query_fn=llm_query_fn,
                    verbose=False,
                    run_logger=cast("RunLoggerProtocol", ocel_run_logger),
                    progress=progress,
                    defer_relationships=self.config.defer_relationships,
                    phases=["prep", "generate", "refine"],  # Include refine for graph_relationships
                    config_versions=getattr(self, "_config_versions_snapshot", None),
                )
                stats["derivation"] = result.get("stats", {})
                self._log_derivation_results(result)
                if not result.get("success"):
                    errors.extend(result.get("errors", []))

            # Export ONCE (combined model)
            if self.config.export_models and ("derivation" in stages or self.config.baseline is not None):
                if verbose:
                    print("  Exporting combined model...")
                model_path = self._export_run_model(
                    combined_repo_name,
                    model_name,
                    iteration,
                    candidate_decisions=result.get("candidate_decisions", []),
                    solve_report=(result.get("stats") or {}).get("refine_reports", {}).get("joint_consistency"),
                    extraction_decisions=extraction_decisions or None,
                )
                if model_path:
                    stats["model_file"] = model_path

            # Determine status
            critical_errors = [
                e
                for e in errors
                if not any(
                    warn in e
                    for warn in [
                        "Missing required field",
                        "Response missing",
                        "Failed to parse",
                    ]
                )
            ]
            status = "completed" if not critical_errors else "failed"

        except Exception as e:
            import traceback

            status = "failed"
            tb_str = traceback.format_exc()
            errors.append(f"{e}\n{tb_str}")

        if run_graph:
            # The run's graph goes with the session (an artifact of the run); its key's file is freed
            try:
                stats["graph_file"] = self._keep_run_graph(run_graph, combined_repo_name, model_name, iteration)
            except OSError as e:
                errors.append(f"Run graph not kept: {e}")

        # Calculate duration
        duration = (datetime.now() - run_start).total_seconds()

        # Log run complete
        self.ocel_log.create_event(
            activity="CompleteRun",
            objects={
                "BenchmarkSession": [session_id],
                "BenchmarkRun": [run_id],
                "Repository": repositories,
                "Model": [model_name],
            },
            status=status,
            duration_seconds=duration,
            stats=stats,
        )

        # Update run in database
        self._complete_run(run_id, status, stats)

        # Copy used LLM cache entries to benchmark session folder for audit trail
        try:
            used_keys = getattr(llm_query_fn, "used_cache_keys", [])
            if used_keys and llm_manager.cache:
                copied = self._copy_used_cache_entries(used_keys, llm_manager.cache.cache_dir, model_name)
                stats["cache_entries_copied"] = copied
        except Exception:
            pass  # Don't fail run if cache copy fails

        return RunResult(
            run_id=run_id,
            repositories=repositories,
            model=model_name,
            iteration=iteration,
            status=status,
            stats=stats,
            errors=errors,
            duration_seconds=duration,
        )

    def _create_logging_query_fn(
        self,
        cached_llm: LLMManager,
        nocache_llm: LLMManager,
        run_logger: OCELRunLogger,
        bench_hash: str | None = None,
    ) -> Callable[..., Any]:
        """
        Create an LLM query function with per-config cache control.

        Args:
            cached_llm: LLM manager with cache enabled
            nocache_llm: LLM manager with cache disabled
            run_logger: OCEL run logger tracking current config
            bench_hash: Optional benchmark hash (repo:model:run) for per-run cache isolation

        Returns:
            Wrapped query function that selects appropriate LLM based on config.
            The function has a `used_cache_keys` attribute for tracking cache entries.
        """
        nocache_configs = self.config.nocache_configs
        used_cache_keys: list[str] = []  # Track cache keys for later copying

        def query_fn(
            prompt: str,
            schema: dict | None = None,
            temperature: float | None = None,
            max_tokens: int | None = None,
            system_prompt: str | None = None,
            response_model: type | None = None,
        ) -> Any:
            # Check if current config should skip cache
            current_config = run_logger.current_config
            skip_cache = current_config in nocache_configs if current_config else False

            # Select appropriate LLM manager
            llm = nocache_llm if skip_cache else cached_llm

            # Call the actual LLM with optional parameters
            # Pass bench_hash for per-run cache isolation if enabled
            kwargs: dict[str, Any] = {
                "schema": schema,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "bench_hash": bench_hash,
                "system_prompt": system_prompt,
            }
            if response_model is not None:
                kwargs["response_model"] = response_model
            try:
                response = llm.query(prompt, **kwargs)
            except Exception as exc:
                self._record_llm_call(llm, current_config, prompt, schema, system_prompt, None, str(exc))
                raise
            self._record_llm_call(llm, current_config, prompt, schema, system_prompt, response, None)

            # Per-call metrics recorded by the manager (cache key, latency, waits, tokens)
            call = llm.last_call or {}
            cache_key = call.get("cache_key")
            if cache_key:
                used_cache_keys.append(cache_key)
            content = getattr(response, "content", "")

            current_run_id = self._current_run_id or ""
            current_model = self._current_model or ""

            self.ocel_log.create_event(
                activity="LLMQuery",
                objects={
                    "BenchmarkRun": [current_run_id],
                    "Model": [current_model],
                    "Config": [current_config] if current_config else [],
                },
                config_id=current_config,
                cache_key=cache_key,
                tokens_in=call.get("input_tokens", 0),
                tokens_out=call.get("output_tokens", 0),
                cache_hit=call.get("cache_hit", False),
                cache_skipped=skip_cache,
                latency_ms=call.get("latency_ms", 0.0),
                wait_ms=call.get("wait_ms", 0.0),
                requests=call.get("requests", 0),
                error_type=call.get("error_type"),
                response_hash=hash_content(content) if content else None,
                decision_hash=hash_content(decision_content(content)) if content else None,
                # keep / naming / relationship / extraction call, from the output schema's name
                call_kind=(schema or {}).get("name"),
            )

            return response

        # Attach cache keys list to function for retrieval after run
        query_fn.used_cache_keys = used_cache_keys  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        return query_fn

    def _record_llm_call(self, llm: Any, step: str | None, prompt: str, schema: dict | None, system_prompt: str | None, response: Any, error: str | None) -> None:
        """Keep the call with prompt and answer in <workspace>/benchmarks/<session>/llm/<run>.jsonl."""
        run_id = self._current_run_id
        if not self.session_id or not run_id:
            return
        log = self._call_logs.get(run_id)
        if log is None:
            log = self._call_logs[run_id] = LlmCallLog(run_log_path(LLM_LOG_ROOT / self.session_id / "llm", run_id), run_id)
        record_call(log, getattr(llm, "last_call", None) or {}, prompt=prompt, schema=schema, system_prompt=system_prompt, response=response, error=error, step=step)
        if step is None:
            log.close()  # no step to wait for: write it now

    def _log_extraction_results(self, result: dict[str, Any]) -> None:
        """Log extraction results as OCEL events."""
        stats = result.get("stats", {})

        # Log aggregate extraction event
        self.ocel_log.create_event(
            activity="ExtractNodes",
            objects={
                "BenchmarkRun": [self._current_run_id or ""],
                "Repository": [self._current_repo or ""],
                "Model": [self._current_model or ""],
            },
            nodes_created=stats.get("nodes_created", 0),
            edges_created=stats.get("edges_created", 0),
            steps_completed=stats.get("steps_completed", 0),
        )

    def _log_derivation_results(self, result: dict[str, Any]) -> None:
        """Log derivation results as OCEL events."""
        stats = result.get("stats", {})
        created_elements = result.get("created_elements", [])

        # Extract element identifiers for consistency tracking
        element_ids = [e.get("identifier", "") for e in created_elements if e.get("identifier")]

        # Log aggregate derivation event
        self.ocel_log.create_event(
            activity="DeriveElements",
            objects={
                "BenchmarkRun": [self._current_run_id or ""],
                "Repository": [self._current_repo or ""],
                "Model": [self._current_model or ""],
                "Element": element_ids,
            },
            elements_created=stats.get("elements_created", 0),
            relationships_created=stats.get("relationships_created", 0),
            steps_completed=stats.get("steps_completed", 0),
        )

    def _export_run_model(
        self,
        repo_name: str,
        model_name: str,
        iteration: int,
        candidate_decisions: list[dict[str, Any]] | None = None,
        solve_report: dict[str, Any] | None = None,
        extraction_decisions: dict[str, dict[str, Any]] | None = None,
    ) -> str | None:
        """
        Export ArchiMate model to file after a benchmark run.

        Creates a uniquely named model file: {repo}_{model}_{iteration}.xml

        Args:
            repo_name: Repository name
            model_name: Model config name
            iteration: Run iteration number (1-based)
            candidate_decisions: The run's candidate decisions (recorded in the JSON snapshot)
            solve_report: The joint_consistency (MILP) solve report of the run (recorded in the JSON snapshot)
            extraction_decisions: The run's own extraction decisions per step (extraction per run), for decision stability

        Returns:
            Path to exported file, or None if export failed
        """
        try:
            # Get only enabled elements and filter relationships accordingly
            elements = self.archimate_manager.get_elements(enabled_only=True)
            all_relationships = self.archimate_manager.get_relationships()

            # A run without elements still gets its (empty) snapshot: it is a result of the session

            # Filter relationships to only include those between enabled elements
            enabled_ids = {e.identifier for e in elements}
            relationships = [r for r in all_relationships if r.source in enabled_ids and r.target in enabled_ids]

            # Create models directory within benchmark session folder
            session_id = self.session_id or "unknown"
            models_dir = workspace() / "benchmarks" / session_id / "models"
            models_dir.mkdir(parents=True, exist_ok=True)

            # Generate unique filename: {repo}_{model}_run{iteration}.xml
            # Sanitize names to be filesystem-safe
            safe_repo = repo_name.replace("/", "_").replace("\\", "_")
            safe_model = model_name.replace("/", "_").replace("\\", "_")
            filename = f"{safe_repo}_{safe_model}_run{iteration}.xml"
            output_path = models_dir / filename

            # Export using ArchiMateXMLExporter: both levels in one file (the benchmark measures the architect level)
            leveled = export_levels.leveled_model(elements, relationships, export_levels.detail_lineage(self.graph_manager))
            exporter = ArchiMateXMLExporter()
            model_display_name = f"{repo_name} - {model_name} - Run {iteration}"
            exporter.export(
                elements=leveled.elements,
                relationships=leveled.relationships,
                output_path=str(output_path),
                model_name=model_display_name,
                properties=leveled.properties,
                views=leveled.views,
                relationship_properties=leveled.relationship_properties,
            )

            # JSON snapshot for consistency analysis: the XML carries no properties,
            # but identity by source node and relationship provenance need them
            concept_rows = self.graph_manager.query("MATCH (n:Graph:BusinessConcept) RETURN n.id AS id, n.conceptTypes AS types, n.conceptName AS name")
            technology_rows = self.graph_manager.query("MATCH (n:Graph:Technology) RETURN n.id AS id, n.techName AS name")
            concept_routes = _incoming_routes(self.graph_manager, "BusinessConcept")
            technology_routes = _incoming_routes(self.graph_manager, "Technology")
            # What refine took out and why: a created candidate can still be missing from the model
            disabled = list(self.archimate_manager.get_disabled_elements())
            refined = {(d["type"], d["source"]): d["reason"] for d in disabled if d.get("source")}
            snapshot = {
                # The MILP's report (safety net): what it was given and what it decided in this run
                "solve": solve_report,
                "elements": [
                    {
                        "identifier": e.identifier,
                        "type": e.element_type,
                        "name": e.name,
                        "source": (e.properties or {}).get("source"),
                        "level": "architect",
                        # The name came from an LLM choice among several candidates (origin split): as the naming
                        # step recorded it, else (steps that record none) several candidates mean a choice
                        "name_choice": bool((e.properties or {})["name_choice"])
                        if "name_choice" in (e.properties or {})
                        else len((e.properties or {}).get("name_candidates") or []) > 1,
                        # The structural name (first candidate) next to the chosen one: what LLM naming adds
                        # (no naming call: the name is the structural one)
                        "structure_name": (e.properties or {}).get("structure_name") or next(iter((e.properties or {}).get("name_candidates") or []), None) or e.name,
                        # A closed-set name's candidates in order (None for a name that is no choice)
                        "name_candidates": list((e.properties or {}).get("name_candidates") or []) or None,
                        # The abstraction levels the abstraction_levels step wrote (None: not tagged, enterprise)
                        "levels": list((e.properties or {})["levels"]) if isinstance((e.properties or {}).get("levels"), list) else None,
                    }
                    for e in elements
                ],
                "relationships": [
                    {
                        "source": r.source,
                        "target": r.target,
                        "type": r.relationship_type,
                        "derived_from": (r.properties or {}).get("derived_from"),
                        "confidence": (r.properties or {}).get("confidence"),
                        # Its levels (those both ends share); a cross-level link (no shared level) counts in the union only
                        "levels": list((r.properties or {})["levels"]) if isinstance((r.properties or {}).get("levels"), list) else None,
                        "cross_level": bool((r.properties or {}).get("cross_level")),
                    }
                    for r in relationships
                ],
                # LLM-created graph nodes, so extraction consistency can be measured on its own;
                # display names keep the word boundaries the ids lost (name normalization analysis)
                "graph": {
                    "concepts": sorted([row["id"], sorted(row.get("types") or [])] for row in concept_rows),
                    "technologies": sorted(row["id"] for row in technology_rows),
                    "concept_names": dict(sorted((row["id"], row.get("name")) for row in concept_rows)),
                    "technology_names": dict(sorted((row["id"], row.get("name")) for row in technology_rows)),
                    # The extraction routes that produced each node, so stability can be measured per route
                    "concept_routes": concept_routes,
                    "technology_routes": technology_routes,
                    # Every active node, so an element missing from a run can be traced to its source node (variance split)
                    "node_ids": sorted({str(row["id"]) for row in self.graph_manager.query(ACTIVE_NODE_IDS) if row.get("id")}),
                },
                "extraction_decisions": extraction_decisions,
                # The export's detail level (members of the architect elements), reported on its own
                "detail": {
                    "elements": [
                        {
                            "identifier": d["identifier"],
                            "type": d["element_type"],
                            "name": d["name"],
                            "source": d["properties"]["source"],
                            "parent": d["properties"]["parent"],
                            "level": "detail",
                        }
                        for d in leveled.detail.elements
                    ],
                    "relationships": [{"source": r["source"], "target": r["target"], "type": r["relationship_type"]} for r in leveled.detail.relationships],
                    "properties": {k: v for k, v in leveled.detail.properties.items() if v},
                },
                "disabled": disabled,
                # Every candidate's fate per element type (created, llm_rejected, filtered_out, ...), for keep rates;
                # "refine" names the rule that disabled the created element afterwards
                "candidates": sorted(
                    (_candidate_record(d, refined) for d in candidate_decisions or []),
                    key=lambda c: (str(c["type"]), str(c["source"]), str(c["stage"])),
                ),
            }
            output_path.with_suffix(".json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")

            return str(output_path)

        except Exception:
            # Don't fail the run if model export fails
            return None

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def _create_session(self) -> None:
        """Create benchmark session in database with config version snapshot."""

        assert self.session_start is not None, "session_start must be set"

        # Capture current config versions as snapshot for consistency during benchmark
        self._config_versions_snapshot = config_service.get_active_config_versions(self.engine)
        self._llm_samples = config_service.llm_samples_per_step(self.engine)

        self.engine.execute(
            """
            INSERT INTO benchmark_sessions
            (session_id, description, config, config_versions_snapshot, started_at, status)
            VALUES (?, ?, ?, ?, ?, 'running')
            """,
            [
                self.session_id,
                self.config.description,
                json.dumps(self.config.to_dict()),
                json.dumps(self._config_versions_snapshot),
                self.session_start.isoformat(),
            ],
        )
        self._capture_code()
        try:
            self._write_session_inputs()
        except Exception as exc:
            # A record that cannot be written does not stop the session (as a failed model export does not fail its run)
            logger.warning("Could not record the inputs of session %s: %s", self.session_id, exc)

    def _capture_code(self) -> None:
        """The commit the session starts on, with a dirty flag (the code may change while the session runs)."""
        try:
            self._code = export_bundle.code_commit()
        except Exception as exc:  # A commit that cannot be read does not stop the session
            logger.warning("Could not read the code commit of session %s: %s", self.session_id, exc)

    def _write_session_inputs(self) -> None:
        """Everything that changes results, as it is when the session starts, into the session folder.

        Config versions, LLM samples per step, the tables without version history (file types, name
        patterns, settings) and the environment (code digest, versions, model configs without secrets).
        Written before the first run, so a session that fails still says what it ran on.
        """
        assert self.session_start is not None, "session_start must be set"
        models = getattr(self, "_model_configs", None) or {}
        record = {
            "session_id": self.session_id,
            "captured_at": self.session_start.isoformat(),
            **export_bundle.run_inputs(
                self.engine,
                {name: models[name] for name in self.config.models if name in models},
                config_versions=self._config_versions_snapshot,
                llm_samples=self._llm_samples,
            ),
        }
        folder = workspace() / "benchmarks" / str(self.session_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "session_inputs.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")

    def _fail_session(self) -> None:
        """End the session as failed (with its unfinished runs) after it stopped part way."""
        try:
            mark_session_failed(self.engine, str(self.session_id))
        except Exception as exc:
            # Never hides why the session stopped
            logger.warning("Could not mark session %s failed: %s", self.session_id, exc)

    def _complete_session(self, runs_completed: int, runs_failed: int) -> None:
        """Mark session as complete in database."""
        self.engine.execute(
            """
            UPDATE benchmark_sessions
            SET completed_at = ?, status = ?
            WHERE session_id = ?
            """,
            [
                datetime.now().isoformat(),
                "completed" if runs_failed == 0 else "failed",
                self.session_id,
            ],
        )

    def _create_run(self, run_id: str, repo_name: str, model_name: str, iteration: int) -> None:
        """Create benchmark run in database."""
        model_config = self._model_configs.get(model_name)
        self.engine.execute(
            """
            INSERT INTO benchmark_runs
            (run_id, session_id, repository, model_provider, model_name, iteration, started_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
            """,
            [
                run_id,
                self.session_id,
                repo_name,
                model_config.provider if model_config else "unknown",
                model_name,
                iteration,
                datetime.now().isoformat(),
            ],
        )

    def _complete_run(self, run_id: str, status: str, stats: dict[str, Any]) -> None:
        """Mark run as complete in database."""
        self.engine.execute(
            """
            UPDATE benchmark_runs
            SET completed_at = ?, status = ?, stats = ?, ocel_events = ?
            WHERE run_id = ?
            """,
            [
                datetime.now().isoformat(),
                status,
                json.dumps(stats),
                len(self.ocel_log.events),
                run_id,
            ],
        )

    def _export_ocel_incremental(self) -> int:
        """
        Export new OCEL events since last export.

        Writes incrementally to JSONL file after each run,
        ensuring partial results are saved even if benchmark fails.

        Returns:
            Number of new events exported
        """
        session_id = self.session_id or "unknown"
        output_dir = workspace() / "benchmarks" / session_id
        ocel_dir = output_dir / "ocel"
        ocel_dir.mkdir(parents=True, exist_ok=True)

        ocel_jsonl_path = ocel_dir / "benchmark_events.jsonl"
        return self.ocel_log.export_jsonl_incremental(ocel_jsonl_path)

    def _export_ocel(self) -> str:
        """Export OCEL log to files."""
        # Create benchmark output directory
        session_id = self.session_id or "unknown"
        output_dir = workspace() / "benchmarks" / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Create ocel subdirectory per BENCHMARK_OUTPUT.md spec
        ocel_dir = output_dir / "ocel"
        ocel_dir.mkdir(parents=True, exist_ok=True)

        # OCEL 2.0 for process mining tools to ocel/benchmark_events.json
        ocel_json_path = ocel_dir / "benchmark_events.json"
        self.ocel_log.export_json(ocel_json_path)

        # The lossless stream Deriva reads back to ocel/benchmark_events.jsonl
        ocel_jsonl_path = ocel_dir / "benchmark_events.jsonl"
        self.ocel_log.export_jsonl(ocel_jsonl_path)

        # The flat case log (case = run) for case-centric tools such as Disco
        self.ocel_log.export_case_csv(ocel_dir / "cases.csv")
        self.ocel_log.export_case_xes(ocel_dir / "cases.xes")

        # Export session metadata (renamed from summary.json)
        summary = {
            "session_id": self.session_id,
            "config": self.config.to_dict(),
            # The code the session ran: its commit and whether the working tree had changes at the start
            "code": self._code,
            "started_at": self.session_start.isoformat() if self.session_start else None,
            "completed_at": datetime.now().isoformat(),
            "total_events": len(self.ocel_log.events),
            "object_types": list(self.ocel_log.object_types),
            # Above 1 means majority voting: consistency is then not single-call behaviour
            "llm_samples": self._llm_samples,
            # What each model was sent, for the settings table (top_p and seed are never sent: provider defaults)
            "generation_settings": {name: generation_settings(config) for name, config in sorted(getattr(self, "_model_configs", {}).items()) if name in self.config.models},
        }
        with open(output_dir / "session_metadata.json", "w") as f:
            json.dump(summary, f, indent=2)

        with open(output_dir / "timings.json", "w") as f:
            json.dump(self._timings(), f, indent=2)

        return str(ocel_json_path)

    def _timings(self) -> dict[str, Any]:
        """Timing summary: extraction per repo, per-run steps and LLM totals, slowest queries."""
        by_run: dict[str, list[Any]] = {}
        for event in self.ocel_log.events:
            for run_id in event.objects.get("BenchmarkRun", []):
                by_run.setdefault(run_id, []).append(event)
        return {
            "session_id": self.session_id,
            "extraction": summarize_run_events([e for e in self.ocel_log.events if e.activity == "EnsureExtraction"])["extraction"],
            "runs": {run_id: summarize_run_events(events) for run_id, events in by_run.items()},
            "top_queries": query_stats.top(15),
        }

    def _copy_used_cache_entries(
        self,
        used_cache_keys: list[str],
        cache_dir: Path,
        model_name: str,
    ) -> int:
        """
        Consolidate used LLM cache entries into single llm_cache.json.

        Per BENCHMARK_OUTPUT.md spec, consolidates all cache entries into a single
        JSON file instead of per-model subdirectories with individual files.

        Args:
            used_cache_keys: List of cache keys (SHA256 hashes) used during the run
            cache_dir: Source cache directory where cache files are stored
            model_name: Name of the model (used for tagging entries)

        Returns:
            Number of cache entries in consolidated file
        """
        session_id = self.session_id or "unknown"
        cache_file = workspace() / "benchmarks" / session_id / "cache" / "llm_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing consolidated cache or create new
        consolidated: dict[str, Any] = {}
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    consolidated = json.load(f)
            except json.JSONDecodeError:
                consolidated = {}

        # Add new entries from this run
        for cache_key in set(used_cache_keys):  # Deduplicate
            src = cache_dir / f"{cache_key}.json"
            if src.exists() and cache_key not in consolidated:
                try:
                    with open(src) as f:
                        data = json.load(f)
                        # Extract fields per BENCHMARK_OUTPUT.md spec
                        # Handle different cache formats
                        prompt = ""
                        response = ""
                        tokens_in = 0
                        tokens_out = 0
                        timestamp = ""

                        if "request" in data:
                            messages = data.get("request", {}).get("messages", [])
                            if messages:
                                prompt = messages[-1].get("content", "")
                        if "response" in data:
                            resp = data.get("response", {})
                            if isinstance(resp, dict):
                                response = resp.get("content", str(resp))
                            else:
                                response = str(resp)
                        if "usage" in data:
                            tokens_in = data["usage"].get("input_tokens", 0)
                            tokens_out = data["usage"].get("output_tokens", 0)
                        timestamp = data.get("created_at", data.get("timestamp", ""))

                        consolidated[cache_key] = {
                            "model": model_name,
                            "prompt": prompt[:500] if prompt else "",  # Truncate for size
                            "response": response[:500] if response else "",  # Truncate
                            "tokens_in": tokens_in,
                            "tokens_out": tokens_out,
                            "timestamp": timestamp,
                        }
                except OSError, json.JSONDecodeError:
                    pass  # Skip on read errors

        # Write consolidated cache
        with open(cache_file, "w") as f:
            json.dump(consolidated, f, indent=2)

        return len(consolidated)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def mark_session_failed(engine: Any, session_id: str) -> int:
    """End a session whose process stopped without finishing (it still says ``running``) as failed.

    Its unfinished runs are marked failed too; the session folder is kept. While a benchmark
    runs it holds the database, so a live session cannot be marked. Returns the number of
    runs marked.
    """
    info = get_benchmark_session(engine, session_id)
    if info is None:
        raise ValueError(f"Benchmark session not found: {session_id}")
    if info["status"] != "running":
        raise ValueError(f"Session {session_id} is {info['status']}, not running")
    now = datetime.now().isoformat()
    (unfinished,) = engine.execute("SELECT count(*) FROM benchmark_runs WHERE session_id = ? AND status = 'running'", [session_id]).fetchone()
    engine.execute("UPDATE benchmark_runs SET completed_at = ?, status = 'failed' WHERE session_id = ? AND status = 'running'", [now, session_id])
    engine.execute("UPDATE benchmark_sessions SET completed_at = ?, status = 'failed' WHERE session_id = ?", [now, session_id])
    return int(unfinished)


def export_process_logs(benchmarks_dir: str | Path, session_ids: list[str], out_dir: str | Path) -> list[Path]:
    """Write the event logs of the sessions as one set of process mining files.

    ``ocel.json`` (OCEL 2.0), ``cases.csv`` and ``cases.xes`` (one case per run) in
    ``out_dir``; the runs of several sessions sit side by side, so models and sessions
    can be compared in one log. Older sessions are read from their own log files.
    """
    merged = OCELLog()
    for session_id in session_ids:
        if not (Path(benchmarks_dir) / session_id).is_dir():
            raise FileNotFoundError(f"Benchmark session not found: {session_id}")
        for event in load_benchmark_ocel(benchmarks_dir, session_id).events:
            merged.add_event(event)

    out = Path(out_dir)
    paths = [out / "ocel.json", out / "cases.csv", out / "cases.xes"]
    merged.export_json(paths[0])
    merged.export_case_csv(paths[1])
    merged.export_case_xes(paths[2])
    return paths


def list_benchmark_sessions(
    engine: Any,
    limit: int = 10,
    offset: int = 0,
    search: str | None = None,
    repository: str | None = None,
    model: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """
    List benchmark sessions, newest first, with the repositories, models and runs they hold.

    Args:
        engine: DuckDB connection
        limit: Maximum number of sessions to return
        offset: Sessions to skip (a page at a time)
        search: Text in the session id or description (any case)
        repository: Only sessions with a run of this repository
        model: Only sessions with a run of this model config
        status: Only sessions with this status (completed, failed, running)

    Returns:
        List of session dictionaries
    """
    where: list[str] = []
    params: list[Any] = []
    if search:
        where.append("(s.session_id ILIKE ? OR coalesce(s.description, '') ILIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if repository:
        where.append("EXISTS (SELECT 1 FROM benchmark_runs r WHERE r.session_id = s.session_id AND r.repository = ?)")
        params.append(repository)
    if model:
        where.append("EXISTS (SELECT 1 FROM benchmark_runs r WHERE r.session_id = s.session_id AND r.model_name = ?)")
        params.append(model)
    if status:
        where.append("s.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = engine.execute(
        f"""
        SELECT s.session_id, s.description, s.status, s.started_at, s.completed_at, s.config,
               count(r.run_id), list(DISTINCT r.repository), list(DISTINCT r.model_name)
        FROM benchmark_sessions s
        LEFT JOIN benchmark_runs r ON r.session_id = s.session_id
        {clause}
        GROUP BY s.session_id, s.description, s.status, s.started_at, s.completed_at, s.config
        ORDER BY s.started_at DESC, s.session_id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()

    def stages(config: Any) -> list[str]:
        try:
            found = json.loads(config) if isinstance(config, str) else (config or {})
        except ValueError:
            return []
        return [str(stage) for stage in found.get("stages") or []] if isinstance(found, dict) else []

    return [
        {
            "session_id": row[0],
            "description": row[1],
            "status": row[2],
            "started_at": row[3],
            "completed_at": row[4],
            "stages": stages(row[5]),
            "runs": int(row[6]),
            "repositories": sorted(x for x in row[7] or [] if x is not None),
            "models": sorted(x for x in row[8] or [] if x is not None),
        }
        for row in rows
    ]


def folder_bytes(folder: Path) -> int:
    """Bytes the files under a folder take (0 when it does not exist)."""
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else 0


def delete_benchmark_session(engine: Any, session_id: str, benchmarks_dir: str | Path) -> dict[str, Any]:
    """Delete a session: its rows (session, runs, metrics) and its folder (event logs, snapshots, inputs).

    Raises:
        KeyError: no such session
        ValueError: the session is still running (mark it failed first when its process stopped)
    """
    info = get_benchmark_session(engine, session_id)
    if info is None:
        raise KeyError(session_id)
    if info["status"] == "running":
        raise ValueError(f"Session {session_id} is running; mark it failed first when its process has stopped")
    (runs,) = engine.execute("SELECT count(*) FROM benchmark_runs WHERE session_id = ?", [session_id]).fetchone()
    for table in ("benchmark_metrics", "benchmark_runs", "benchmark_sessions"):
        engine.execute(f"DELETE FROM {table} WHERE session_id = ?", [session_id])
    folder = Path(benchmarks_dir) / session_id
    size = folder_bytes(folder)
    if folder.is_dir():
        shutil.rmtree(folder)
    return {"session_id": session_id, "runs": int(runs), "bytes": size}


def prune_benchmark_sessions(engine: Any, benchmarks_dir: str | Path, keep: int | None = None, failed: bool = False) -> list[str]:
    """Delete the failed sessions, or every session past the latest ``keep``; running sessions always stay.

    Returns the deleted session ids, newest first.
    """
    rows = engine.execute("SELECT session_id, status FROM benchmark_sessions ORDER BY started_at DESC, session_id DESC").fetchall()
    if failed:
        victims = [sid for sid, status in rows if status == "failed"]
    elif keep is not None:
        victims = [sid for sid, status in rows[max(keep, 0) :] if status != "running"]
    else:
        return []
    for session_id in victims:
        delete_benchmark_session(engine, session_id, benchmarks_dir)
    return victims


def get_benchmark_session(engine: Any, session_id: str) -> dict[str, Any] | None:
    """
    Get details for a specific benchmark session.

    Args:
        engine: DuckDB connection
        session_id: Session ID to retrieve

    Returns:
        Session dictionary or None if not found
    """
    row = engine.execute(
        """
        SELECT session_id, description, config, status, started_at, completed_at
        FROM benchmark_sessions
        WHERE session_id = ?
        """,
        [session_id],
    ).fetchone()

    if not row:
        return None

    return {
        "session_id": row[0],
        "description": row[1],
        "config": json.loads(row[2]) if row[2] else {},
        "status": row[3],
        "started_at": row[4],
        "completed_at": row[5],
    }


def get_benchmark_runs(engine: Any, session_id: str) -> list[dict[str, Any]]:
    """
    Get all runs for a benchmark session.

    Args:
        engine: DuckDB connection
        session_id: Session ID

    Returns:
        List of run dictionaries
    """
    rows = engine.execute(
        """
        SELECT run_id, repository, model_provider, model_name, iteration,
               status, stats, started_at, completed_at
        FROM benchmark_runs
        WHERE session_id = ?
        ORDER BY started_at
        """,
        [session_id],
    ).fetchall()

    return [
        {
            "run_id": row[0],
            "repository": row[1],
            "model_provider": row[2],
            "model_name": row[3],
            "iteration": row[4],
            "status": row[5],
            "stats": json.loads(row[6]) if row[6] else {},
            "started_at": row[7],
            "completed_at": row[8],
        }
        for row in rows
    ]


# =============================================================================
# ANALYSIS DATA CLASSES
# =============================================================================


@dataclass
class ItemStability:
    """Per-item stability with percentage score."""

    item_id: str
    item_type: str  # "Element", "Edge", "Relationship"
    appearances: int
    total_runs: int

    @property
    def stability_score(self) -> float:
        """Percentage of runs where item appeared (0-100)."""
        return (self.appearances / self.total_runs * 100) if self.total_runs > 0 else 0.0

    @property
    def is_stable(self) -> bool:
        """Item appeared in ALL runs."""
        return self.appearances == self.total_runs

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "appearances": self.appearances,
            "total_runs": self.total_runs,
            "stability_score": round(self.stability_score, 2),
            "is_stable": self.is_stable,
        }


@dataclass
class ConnectionStability:
    """Stability of a single connection between elements."""

    element_id: str
    connected_to: str
    relationship_type: str
    appearances: int
    total_runs: int

    @property
    def stability_score(self) -> float:
        """Percentage of runs where this connection existed (0-100)."""
        return (self.appearances / self.total_runs * 100) if self.total_runs > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "element_id": self.element_id,
            "connected_to": self.connected_to,
            "relationship_type": self.relationship_type,
            "appearances": self.appearances,
            "total_runs": self.total_runs,
            "stability_score": round(self.stability_score, 2),
        }


@dataclass
class ElementStructuralStability:
    """All connections for an element with stability scores."""

    element_id: str
    connections: list[ConnectionStability] = field(default_factory=list)

    @property
    def structural_score(self) -> float:
        """Average stability of all connections (0-100)."""
        if not self.connections:
            return 100.0  # No connections = fully stable
        return sum(c.stability_score for c in self.connections) / len(self.connections)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "element_id": self.element_id,
            "structural_score": round(self.structural_score, 2),
            "connections": [c.to_dict() for c in self.connections],
        }


@dataclass
class IntraModelMetrics:
    """Consistency metrics for a single model across runs on the same repo."""

    model: str
    repository: str
    runs: int
    element_counts: list[int]
    count_variance: float
    name_consistency: float  # % of element names in ALL runs
    stable_elements: list[str] = field(default_factory=list)  # Names in all runs
    unstable_elements: dict[str, int] = field(default_factory=dict)  # Name -> count of runs appeared

    # Edge consistency (extraction phase); None: no run logged an edge (the runs of a session share one extraction)
    edge_counts: list[int] = field(default_factory=list)
    edge_count_variance: float = 0.0
    edge_consistency: float | None = None  # % of edges in ALL runs
    stable_edges: list[str] = field(default_factory=list)
    unstable_edges: dict[str, int] = field(default_factory=dict)
    edge_type_breakdown: dict[str, float] = field(default_factory=dict)  # CONTAINS: 95%, etc.

    # Relationship consistency (derivation phase); None: no run logged a relationship
    relationship_counts: list[int] = field(default_factory=list)
    relationship_count_variance: float = 0.0
    relationship_consistency: float | None = None  # % of relationships in ALL runs
    stable_relationships: list[str] = field(default_factory=list)
    unstable_relationships: dict[str, int] = field(default_factory=dict)
    relationship_type_breakdown: dict[str, float] = field(default_factory=dict)  # Serving: 90%, etc.

    # Per-item stability scores (enhanced metrics)
    element_stability: list[ItemStability] = field(default_factory=list)
    edge_stability: list[ItemStability] = field(default_factory=list)
    relationship_stability: list[ItemStability] = field(default_factory=list)

    # Structural stability (connection consistency)
    structural_stability: list[ElementStructuralStability] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base = asdict(self)
        # Convert ItemStability objects to dicts
        base["element_stability"] = [s.to_dict() for s in self.element_stability]
        base["edge_stability"] = [s.to_dict() for s in self.edge_stability]
        base["relationship_stability"] = [s.to_dict() for s in self.relationship_stability]
        base["structural_stability"] = [s.to_dict() for s in self.structural_stability]
        return base


@dataclass
class InterModelMetrics:
    """Comparison metrics across models for the same repository."""

    repository: str
    models: list[str]
    elements_by_model: dict[str, list[str]]
    overlap: list[str]  # Elements in ALL models
    unique_by_model: dict[str, list[str]]  # Elements unique to each model
    jaccard_similarity: float

    # Edge comparison (extraction phase); None: no run of the models logged an edge
    edges_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_overlap: list[str] = field(default_factory=list)  # Edges in ALL models
    edge_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_jaccard: float | None = None

    # Relationship comparison (derivation phase); None: no run of the models logged a relationship
    relationships_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_overlap: list[str] = field(default_factory=list)  # Relationships in ALL models
    relationship_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_jaccard: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class InconsistencyLocalization:
    """Where inconsistencies occur in the pipeline."""

    by_element_type: dict[str, float]  # Type -> inconsistency score
    by_stage: dict[str, float]  # Stage -> inconsistency score
    by_model: dict[str, float]  # Model -> inconsistency score
    by_repository: dict[str, float]  # Repo -> inconsistency score
    hotspots: list[dict[str, Any]]  # Top inconsistent areas

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


def model_quality_for_session(
    session_dir: Path,
    repositories: list[str],
    models: list[str],
    reference_models: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Structural quality of every model a benchmark session exported, one row per run.

    Reads ``models/{repo}_{model}_run{N}.xml`` (for a combined session the repositories'
    joined name) and adds, where a reference model exists, precision and recall of the
    elements against it (indicative: the references are hand-made and partly not
    derivable). Only a name match with the same type counts, and each reference element
    at most once, so a duplicate costs precision.
    """
    if reference_models is None:
        from deriva.bench.analysis import known_reference_models

        reference_models = known_reference_models()
    rows: list[dict[str, Any]] = []
    models_dir = Path(session_dir) / "models"
    names = list(repositories) + (["_".join(sorted(repositories))] if len(repositories) > 1 else [])
    for repo in names:
        reference = _reference_elements(reference_models.get(repo))
        for model in models:
            prefix = f"{repo.replace('/', '_')}_{model.replace('/', '_')}_run"
            files = sorted(models_dir.glob(f"{prefix}*.xml"), key=lambda f: int(f.stem[len(prefix) :]) if f.stem[len(prefix) :].isdigit() else 0)
            for path in files:
                run = path.stem[len(prefix) :]
                if not run.isdigit():
                    continue
                # The architect level: the detail level (members) is reported on its own
                elements, relationships = parse_exchange_format_xml(path, level="architect")
                row: dict[str, Any] = {"repository": repo, "model": model, "run": int(run), **compute_model_quality(elements, relationships).to_dict()}
                snapshot_path = path.with_suffix(".json")
                try:
                    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8")) if snapshot_path.is_file() else {}
                except OSError, ValueError:
                    snapshot = {}
                row["solve"] = snapshot.get("solve")
                row["reference"] = None
                if reference:
                    # Name + type, the user's accepted names and structural refs (sources and lineage from the run's
                    # snapshot: the XML carries none) and derivable labels: the gate's matching (golden_mapping)
                    structure = {str(e.get("identifier")): e for e in snapshot.get("elements", []) if isinstance(e, dict)}
                    derived = [
                        {
                            "id": e.identifier,
                            "name": e.name,
                            "type": e.element_type,
                            "source": structure.get(e.identifier, {}).get("source"),
                            "lineage": structure.get(e.identifier, {}).get("lineage") or [],
                        }
                        for e in elements
                    ]
                    aliases, derivable = session_metrics.manual_inputs(reference_models[repo])
                    row["reference"] = session_metrics.golden_comparison(derived, reference, aliases=aliases, derivable=derivable)
                rows.append(row)
    return rows


# Semantic matches that agree on the name and the type (a match on the type alone does not count)
NAME_MATCHES = {"exact", "fuzzy_name"}


ACTIVE_NODE_IDS = "MATCH (n) WHERE 'Graph' IN labels(n) AND n.active = true RETURN n.id AS id"


def _run_snapshots(session_dir: Path, repositories: list[str], models: list[str]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """The JSON snapshots of every run, per repository (and the combined name) and model, in run order."""
    models_dir = Path(session_dir) / "models"
    names = list(repositories) + (["_".join(sorted(repositories))] if len(repositories) > 1 else [])
    found: list[tuple[str, str, list[dict[str, Any]]]] = []
    for repo in names:
        for model in models:
            prefix = f"{repo.replace('/', '_')}_{model.replace('/', '_')}_run"
            numbered = [(int(p.stem[len(prefix) :]), p) for p in models_dir.glob(f"{prefix}*.json") if p.stem[len(prefix) :].isdigit()]
            snapshots = []
            for _, path in sorted(numbered):
                try:
                    snapshots.append(json.loads(path.read_text(encoding="utf-8")))
                except OSError, ValueError:
                    continue
            if snapshots:
                found.append((repo, model, snapshots))
    return found


def naming_fallbacks_for_session(session_dir: Path) -> list[dict[str, Any]]:
    """Per model, the closed-set name choices whose answer was unusable, so the structural first candidate was taken:
    no readable JSON (``unparsable``) or a name that is none of the candidates in the prompt (``outside``)."""
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted((Path(session_dir) / "llm").glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            try:
                call = json.loads(line)
            except ValueError:
                continue
            if call.get("schema") != "element_name_choice" or call.get("error"):
                continue
            row = rows.setdefault(str(call.get("model")), {"model": str(call.get("model")), "choices": 0, "unusable": 0, "unparsable": 0, "outside": 0})
            row["choices"] += 1
            # The candidates are the "- " lines of the prompt's Candidates section (``build_choice_prompt``)
            listed = str(call.get("prompt") or "").split("## Candidates", 1)[-1].split("\n\nReturn", 1)[0]
            candidates = set()
            for item in listed.splitlines():
                if item.startswith("- "):
                    try:
                        candidates.add(json.loads(item[2:]))
                    except ValueError:
                        continue
            try:
                answer = json.loads(extract_json_from_response(str(call.get("response") or ""))).get("name")
            except ValueError, AttributeError:
                row["unparsable"] += 1
                row["unusable"] += 1
                continue
            if answer not in candidates:
                row["outside"] += 1
                row["unusable"] += 1
    return [rows[m] for m in sorted(rows)]


def variance_split_for_session(session_dir: Path, repositories: list[str], models: list[str]) -> list[dict[str, Any]]:
    """Which share of the run-to-run differences comes from extraction and which from derivation (extraction per run).

    Every time an element is missing from a run that another run has, it counts as *extraction* when its source node
    is missing from that run's graph (``graph.node_ids`` of the snapshot), else as *derivation*: the node is there,
    the element is not. A missing relationship follows its endpoints: extraction when an endpoint's source node is
    missing from the run's graph. Needs node ids in every snapshot (sessions with extraction per run).
    """
    rows: list[dict[str, Any]] = []
    for repo, model, snapshots in _run_snapshots(session_dir, repositories, models):
        if len(snapshots) < 2 or any("node_ids" not in (s.get("graph") or {}) for s in snapshots):
            continue
        nodes = [set(s["graph"]["node_ids"]) for s in snapshots]
        source_of: dict[str, str | None] = {}
        for s in snapshots:
            for e in s.get("elements", []):
                source_of.setdefault(e["identifier"], e.get("source"))
        elements = [{e["identifier"] for e in s.get("elements", [])} for s in snapshots]
        edges = [{(r["source"], r["type"], r["target"]) for r in s.get("relationships", [])} for s in snapshots]

        def split(present: list[set[Any]], sources: Callable[[Any], list[str | None]]) -> dict[str, Any]:
            counts = {"extraction": 0, "derivation": 0}
            for have, graph in zip(present, nodes, strict=True):
                for item in set().union(*present) - have:
                    lost = any(src is not None and src not in graph for src in sources(item))
                    counts["extraction" if lost else "derivation"] += 1
            total = counts["extraction"] + counts["derivation"]
            return {**counts, "extraction_share": round(counts["extraction"] / total, 3) if total else None}

        rows.append(
            {
                "repository": repo,
                "model": model,
                "runs": len(snapshots),
                "elements": split(elements, lambda item: [source_of.get(item)]),
                "relationships": split(edges, lambda item: [source_of.get(item[0]), source_of.get(item[2])]),
            }
        )
    return rows


def extraction_stability_for_session(session_dir: Path, repositories: list[str], models: list[str]) -> list[dict[str, Any]]:
    """Decision stability of the LLM extraction steps over the runs (extraction per run): per step, the items that got
    the same decision in every run, from the snapshots' ``extraction_decisions``."""
    rows: list[dict[str, Any]] = []
    for repo, model, snapshots in _run_snapshots(session_dir, repositories, models):
        decided = [s.get("extraction_decisions") for s in snapshots]
        if len(decided) < 2 or any(not isinstance(d, dict) for d in decided):
            continue
        steps = sorted(set().union(*(d.keys() for d in decided if isinstance(d, dict))))
        result = {}
        for step in steps:
            stability = decision_stability([dict((d or {}).get(step) or {}) for d in decided])
            result[step] = {"items": stability.items, "stable": stability.stable}
        rows.append({"repository": repo, "model": model, "runs": len(snapshots), "steps": result})
    return rows


def detail_level_for_session(session_dir: Path, repositories: list[str], models: list[str]) -> list[dict[str, Any]]:
    """The export's detail level per repository and model, from the run snapshots (apart from the architect level).

    Size (mean detail elements per run, per type) and consistency over the runs: the share of the detail elements
    (and relationships) that every run has, of all the runs have. Runs without a detail section are skipped.
    """
    rows: list[dict[str, Any]] = []
    models_dir = Path(session_dir) / "models"
    names = list(repositories) + (["_".join(sorted(repositories))] if len(repositories) > 1 else [])
    for repo in names:
        for model in models:
            prefix = f"{repo.replace('/', '_')}_{model.replace('/', '_')}_run"
            details = []
            for path in sorted(models_dir.glob(f"{prefix}*.json")):
                if not path.stem[len(prefix) :].isdigit():
                    continue
                try:
                    detail = json.loads(path.read_text(encoding="utf-8")).get("detail")
                except OSError, ValueError:
                    continue
                if detail is not None:
                    details.append(detail)
            if not details:
                continue
            elements = [{e["identifier"] for e in d.get("elements", [])} for d in details]
            edges = [{(r["source"], r["type"], r["target"]) for r in d.get("relationships", [])} for d in details]
            types: dict[str, int] = {}
            for d in details:
                for e in d.get("elements", []):
                    types[e["type"]] = types.get(e["type"], 0) + 1

            def share(sets: list[set[Any]]) -> float:
                union = set().union(*sets)
                return round(len(set.intersection(*sets)) / len(union), 3) if union else 1.0

            rows.append(
                {
                    "repository": repo,
                    "model": model,
                    "runs": len(details),
                    "elements": round(sum(len(s) for s in elements) / len(details), 1),
                    "by_type": {t: round(n / len(details), 1) for t, n in sorted(types.items())},
                    "element_consistency": share(elements),
                    "relationship_consistency": share(edges),
                }
            )
    return rows


def _reference_elements(path: str | None) -> list[Any]:
    """Elements of a reference model (Archi format first, then the exchange format); none when missing."""
    if not path or not Path(path).exists():
        return []
    elements, _ = parse_archi_xml(path)
    return elements or parse_exchange_format_xml(path)[0]


@dataclass
class AnalysisSummary:
    """Complete analysis summary."""

    session_id: str
    analyzed_at: str
    intra_model: list[IntraModelMetrics]
    inter_model: list[InterModelMetrics]
    localization: InconsistencyLocalization
    overall_consistency: float
    model_quality: list[dict[str, Any]] = field(default_factory=list)  # one row per exported run model
    detail_level: list[dict[str, Any]] = field(default_factory=list)  # the export's detail level per repository and model
    variance_split: list[dict[str, Any]] = field(default_factory=list)  # extraction vs derivation share (extraction per run)
    extraction_stability: list[dict[str, Any]] = field(default_factory=list)  # decision stability of the LLM extraction steps
    naming_fallbacks: list[dict[str, Any]] = field(default_factory=list)  # unusable name choices per model (structural fallback)
    metrics: dict[str, Any] = field(default_factory=dict)  # identities, layers/origin, two levels, out of candidates (session_metrics)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "analyzed_at": self.analyzed_at,
            "intra_model": [m.to_dict() for m in self.intra_model],
            "inter_model": [m.to_dict() for m in self.inter_model],
            "localization": self.localization.to_dict(),
            "overall_consistency": self.overall_consistency,
            "model_quality": self.model_quality,
            "detail_level": self.detail_level,
            "variance_split": self.variance_split,
            "extraction_stability": self.extraction_stability,
            "naming_fallbacks": self.naming_fallbacks,
            "metrics": self.metrics,
        }


# =============================================================================
# BENCHMARK ANALYZER
# =============================================================================


class BenchmarkAnalyzer:
    """
    Post-run analysis of benchmark results.

    Loads OCEL logs and computes consistency metrics across
    models, repositories, and pipeline stages.
    """

    def __init__(self, session_id: str, engine: Any):
        """
        Initialize analyzer for a benchmark session.

        Args:
            session_id: Benchmark session ID
            engine: DuckDB connection
        """
        self.session_id = session_id
        self.engine = engine

        # Load session info (reuse convenience function)
        self.session_info = get_benchmark_session(engine, session_id)
        if not self.session_info:
            raise ValueError(f"Benchmark session not found: {session_id}")

        # Load OCEL log
        self.ocel_log = self._load_ocel()
        self._by_run: dict[str, dict[str, set[str]]] = {}  # object type -> run id -> objects

        # Load run data (reuse convenience function)
        self.runs = get_benchmark_runs(engine, session_id)

    def _load_ocel(self) -> OCELLog:
        """Load OCEL log from file."""
        return load_benchmark_ocel(workspace() / "benchmarks", self.session_id)

    # =========================================================================
    # INTRA-MODEL CONSISTENCY
    # =========================================================================

    def compute_intra_model_consistency(self) -> list[IntraModelMetrics]:
        """
        Compute consistency metrics for each model across runs.

        Measures how stable each model is when running on the same repository
        multiple times.

        Returns:
            List of IntraModelMetrics for each (model, repo) combination
        """
        results: list[IntraModelMetrics] = []

        # Group runs by (model, repository)
        grouped: dict[tuple[str, str], list[dict]] = {}
        for run in self.runs:
            key = (run["model_name"], run["repository"])
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(run)

        for (model, repo), runs in grouped.items():
            if len(runs) < 2:
                continue  # Need at least 2 runs to compute consistency

            # Extract element counts from stats
            element_counts = []
            for run in runs:
                stats = run.get("stats", {})
                derivation_stats = stats.get("derivation", {})
                count = derivation_stats.get("elements_created", 0)
                element_counts.append(count)

            # Compute variance
            if element_counts:
                avg = sum(element_counts) / len(element_counts)
                variance = sum((c - avg) ** 2 for c in element_counts) / len(element_counts)
            else:
                variance = 0.0

            # Get elements from OCEL for this model/repo
            elements_by_run = self._get_elements_by_run(model, repo)

            # Compute name consistency
            all_elements = set()
            for elems in elements_by_run.values():
                all_elements.update(elems)

            stable = []
            unstable: dict[str, int] = {}

            for elem in all_elements:
                count = sum(1 for elems in elements_by_run.values() if elem in elems)
                if count == len(runs):
                    stable.append(elem)
                else:
                    unstable[elem] = count

            consistency = len(stable) / len(all_elements) * 100 if all_elements else 100

            # Build per-item stability scores for elements
            element_stability = [
                ItemStability(
                    item_id=elem,
                    item_type="Element",
                    appearances=sum(1 for elems in elements_by_run.values() if elem in elems),
                    total_runs=len(runs),
                )
                for elem in all_elements
            ]

            # =====================================================================
            # Edge consistency (extraction phase)
            # =====================================================================
            edges_by_run = self._get_edges_by_run(model, repo)

            # Extract edge counts from stats
            edge_counts = []
            for run in runs:
                stats = run.get("stats", {})
                extraction_stats = stats.get("extraction", {})
                edge_count = extraction_stats.get("edges_created", 0)
                edge_counts.append(edge_count)

            # Compute edge count variance
            if edge_counts:
                edge_avg = sum(edge_counts) / len(edge_counts)
                edge_variance = sum((c - edge_avg) ** 2 for c in edge_counts) / len(edge_counts)
            else:
                edge_variance = 0.0

            # Compute edge consistency
            all_edges = set()
            for edges in edges_by_run.values():
                all_edges.update(edges)

            stable_edges = []
            unstable_edges: dict[str, int] = {}

            for edge in all_edges:
                count = sum(1 for edges in edges_by_run.values() if edge in edges)
                if count == len(runs):
                    stable_edges.append(edge)
                else:
                    unstable_edges[edge] = count

            edge_consistency = len(stable_edges) / len(all_edges) * 100 if all_edges else None

            # Compute per-type breakdown for edges
            edge_type_breakdown = self._compute_type_breakdown(edges_by_run)

            # Build per-item stability scores for edges
            edge_stability = [
                ItemStability(
                    item_id=edge,
                    item_type="Edge",
                    appearances=sum(1 for edges in edges_by_run.values() if edge in edges),
                    total_runs=len(runs),
                )
                for edge in all_edges
            ]

            # =====================================================================
            # Relationship consistency (derivation phase)
            # =====================================================================
            relationships_by_run = self._get_relationships_by_run(model, repo)

            # Extract relationship counts from stats
            relationship_counts = []
            for run in runs:
                stats = run.get("stats", {})
                derivation_stats = stats.get("derivation", {})
                rel_count = derivation_stats.get("relationships_created", 0)
                relationship_counts.append(rel_count)

            # Compute relationship count variance
            if relationship_counts:
                rel_avg = sum(relationship_counts) / len(relationship_counts)
                rel_variance = sum((c - rel_avg) ** 2 for c in relationship_counts) / len(relationship_counts)
            else:
                rel_variance = 0.0

            # Compute relationship consistency
            all_relationships = set()
            for rels in relationships_by_run.values():
                all_relationships.update(rels)

            stable_relationships = []
            unstable_relationships: dict[str, int] = {}

            for rel in all_relationships:
                count = sum(1 for rels in relationships_by_run.values() if rel in rels)
                if count == len(runs):
                    stable_relationships.append(rel)
                else:
                    unstable_relationships[rel] = count

            rel_consistency = len(stable_relationships) / len(all_relationships) * 100 if all_relationships else None

            # Compute per-type breakdown for relationships
            relationship_type_breakdown = self._compute_type_breakdown(relationships_by_run)

            # Build per-item stability scores for relationships
            relationship_stability = [
                ItemStability(
                    item_id=rel,
                    item_type="Relationship",
                    appearances=sum(1 for rels in relationships_by_run.values() if rel in rels),
                    total_runs=len(runs),
                )
                for rel in all_relationships
            ]

            # Compute structural stability (connection consistency)
            structural_stability = self._compute_structural_stability(
                elements_by_run=elements_by_run,
                relationships_by_run=relationships_by_run,
                total_runs=len(runs),
            )

            results.append(
                IntraModelMetrics(
                    model=model,
                    repository=repo,
                    runs=len(runs),
                    element_counts=element_counts,
                    count_variance=variance,
                    name_consistency=consistency,
                    stable_elements=sorted(stable),
                    unstable_elements=unstable,
                    # Edge consistency
                    edge_counts=edge_counts,
                    edge_count_variance=edge_variance,
                    edge_consistency=edge_consistency,
                    stable_edges=sorted(stable_edges),
                    unstable_edges=unstable_edges,
                    edge_type_breakdown=edge_type_breakdown,
                    # Relationship consistency
                    relationship_counts=relationship_counts,
                    relationship_count_variance=rel_variance,
                    relationship_consistency=rel_consistency,
                    stable_relationships=sorted(stable_relationships),
                    unstable_relationships=unstable_relationships,
                    relationship_type_breakdown=relationship_type_breakdown,
                    # Per-item stability scores
                    element_stability=element_stability,
                    edge_stability=edge_stability,
                    relationship_stability=relationship_stability,
                    # Structural stability
                    structural_stability=structural_stability,
                )
            )

        return results

    def _objects_by_run(self, object_type: str, model: str, repo: str) -> dict[str, set[str]]:
        """The objects of a type that each run of a repository with a model logged.

        The runs are the session's runs (``benchmark_runs``); the shared extraction of a
        repository (``session:extraction:repo``) is not one of them. Every run is a key, also
        one that logged none of the type.
        """
        if object_type not in self._by_run:
            self._by_run[object_type] = self.ocel_log.get_objects_by_run(object_type)
        logged = self._by_run[object_type]
        return {run["run_id"]: logged.get(run["run_id"], set()) for run in self.runs if run["model_name"] == model and run["repository"] == repo}

    def _get_elements_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Derived elements per run of a repository with a model."""
        return self._objects_by_run("Element", model, repo)

    def _get_edges_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Extracted edges per run of a repository with a model (none when the runs share one extraction)."""
        return self._objects_by_run("Edge", model, repo)

    def _get_relationships_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Derived relationships per run of a repository with a model."""
        return self._objects_by_run("Relationship", model, repo)

    def _compute_type_breakdown(
        self,
        objects_by_run: dict[str, set[str]],
    ) -> dict[str, float]:
        """
        Compute consistency per edge/relationship type.

        Edge/relationship IDs have format: {type}_{source}_{target}
        This method extracts the type and computes consistency for each.

        Args:
            objects_by_run: Dict mapping run_id -> set of edge/relationship IDs

        Returns:
            Dict mapping type -> consistency percentage (0-100)
        """
        if not objects_by_run:
            return {}

        # Group objects by type
        type_objects: dict[str, set[str]] = {}
        for run_id, objects in objects_by_run.items():
            for obj_id in objects:
                # Extract type from id: "CONTAINS_dir_a_file_b" -> "CONTAINS"
                parts = obj_id.split("_", 1)
                rel_type = parts[0] if parts else obj_id
                if rel_type not in type_objects:
                    type_objects[rel_type] = set()
                type_objects[rel_type].add(obj_id)

        # Compute consistency for each type
        breakdown: dict[str, float] = {}

        for rel_type, objects in type_objects.items():
            # Count objects that appear in ALL runs
            stable_count = sum(1 for obj in objects if all(obj in run_objs for run_objs in objects_by_run.values()))
            breakdown[rel_type] = (stable_count / len(objects) * 100) if objects else 100.0

        return breakdown

    def _compute_structural_stability(
        self,
        elements_by_run: dict[str, set[str]],
        relationships_by_run: dict[str, set[str]],
        total_runs: int,
    ) -> list[ElementStructuralStability]:
        """
        Compute structural stability - how consistently elements maintain their connections.

        Parses relationship IDs (format: {Type}_{Source}_{Target}) to extract connections,
        then measures how stable each connection is across runs.

        Args:
            elements_by_run: Dict mapping run_id -> set of element IDs
            relationships_by_run: Dict mapping run_id -> set of relationship IDs
            total_runs: Total number of runs

        Returns:
            List of ElementStructuralStability for each element with connections
        """
        if not relationships_by_run or total_runs < 2:
            return []

        # Collect all unique elements
        all_elements: set[str] = set()
        for elems in elements_by_run.values():
            all_elements.update(elems)

        # Parse relationship IDs to extract connections per run
        # Format: {Type}_{Source}_{Target}
        connections_by_run: dict[str, set[tuple[str, str, str]]] = {}  # run -> (source, type, target)

        for run_id, rel_ids in relationships_by_run.items():
            connections_by_run[run_id] = set()
            for rel_id in rel_ids:
                parts = rel_id.split("_", 2)  # Split into [type, source, target]
                if len(parts) >= 3:
                    rel_type, source, target = parts[0], parts[1], parts[2]
                    connections_by_run[run_id].add((source, rel_type, target))

        # Compute structural stability for each element
        result: list[ElementStructuralStability] = []

        for element_id in all_elements:
            # Collect all connections involving this element (as source or target)
            all_connections: set[tuple[str, str, str]] = set()  # (other_element, rel_type, direction)

            for connections in connections_by_run.values():
                for source, rel_type, target in connections:
                    if source == element_id:
                        all_connections.add((target, rel_type, "outbound"))
                    if target == element_id:
                        all_connections.add((source, rel_type, "inbound"))

            if not all_connections:
                continue  # Skip elements with no connections

            # Count appearances for each connection
            connection_stabilities: list[ConnectionStability] = []

            for other_element, rel_type, direction in all_connections:
                if direction == "outbound":
                    # Count runs where this outbound connection exists
                    appearances = sum(1 for run_id, conns in connections_by_run.items() if (element_id, rel_type, other_element) in conns)
                else:  # inbound
                    # Count runs where this inbound connection exists
                    appearances = sum(1 for run_id, conns in connections_by_run.items() if (other_element, rel_type, element_id) in conns)

                connection_stabilities.append(
                    ConnectionStability(
                        element_id=element_id,
                        connected_to=other_element,
                        relationship_type=f"{rel_type}_{direction}",
                        appearances=appearances,
                        total_runs=total_runs,
                    )
                )

            result.append(
                ElementStructuralStability(
                    element_id=element_id,
                    connections=connection_stabilities,
                )
            )

        return result

    # =========================================================================
    # INTER-MODEL CONSISTENCY
    # =========================================================================

    def compute_inter_model_consistency(self) -> list[InterModelMetrics]:
        """
        Compute comparison metrics across models for the same repository.

        Measures how different models compare when processing the same
        repository.

        Returns:
            List of InterModelMetrics for each repository
        """
        results: list[InterModelMetrics] = []

        # Get unique repositories
        repositories = set(run["repository"] for run in self.runs)

        for repo in repositories:
            # Get models that processed this repo
            models_for_repo = set(run["model_name"] for run in self.runs if run["repository"] == repo)

            if len(models_for_repo) < 2:
                continue  # Need at least 2 models to compare

            # Get elements by model (aggregate across runs)
            elements_by_model: dict[str, set[str]] = {}

            for model in models_for_repo:
                elements_by_model[model] = set()
                for run_id, elems in self._get_elements_by_run(model, repo).items():
                    elements_by_model[model].update(elems)

            # Compute overlap (elements in ALL models)
            if elements_by_model:
                overlap = set.intersection(*elements_by_model.values())
            else:
                overlap = set()

            # Compute unique elements per model
            all_elements = set.union(*elements_by_model.values()) if elements_by_model else set()
            unique_by_model = {}
            for model, elems in elements_by_model.items():
                other_elems = set.union(*(e for m, e in elements_by_model.items() if m != model)) if len(elements_by_model) > 1 else set()
                unique_by_model[model] = sorted(elems - other_elems)

            # Compute Jaccard similarity
            if all_elements:
                jaccard = len(overlap) / len(all_elements)
            else:
                jaccard = 1.0

            # =================================================================
            # Edge comparison across models (extraction phase)
            # =================================================================
            edges_by_model: dict[str, set[str]] = {}

            for model in models_for_repo:
                edges_by_model[model] = set()
                for run_id, edges in self._get_edges_by_run(model, repo).items():
                    edges_by_model[model].update(edges)

            # Compute edge overlap (edges in ALL models)
            if edges_by_model and all(edges_by_model.values()):
                edge_overlap = set.intersection(*edges_by_model.values())
            else:
                edge_overlap = set()

            # Compute unique edges per model
            all_edges = set.union(*edges_by_model.values()) if edges_by_model else set()
            edge_unique_by_model = {}
            for model, edges in edges_by_model.items():
                other_edges = set.union(*(e for m, e in edges_by_model.items() if m != model)) if len(edges_by_model) > 1 else set()
                edge_unique_by_model[model] = sorted(edges - other_edges)

            # Compute edge Jaccard similarity
            edge_jaccard = len(edge_overlap) / len(all_edges) if all_edges else None

            # =================================================================
            # Relationship comparison across models (derivation phase)
            # =================================================================
            relationships_by_model: dict[str, set[str]] = {}

            for model in models_for_repo:
                relationships_by_model[model] = set()
                for run_id, rels in self._get_relationships_by_run(model, repo).items():
                    relationships_by_model[model].update(rels)

            # Compute relationship overlap (relationships in ALL models)
            if relationships_by_model and all(relationships_by_model.values()):
                relationship_overlap = set.intersection(*relationships_by_model.values())
            else:
                relationship_overlap = set()

            # Compute unique relationships per model
            all_relationships = set.union(*relationships_by_model.values()) if relationships_by_model else set()
            relationship_unique_by_model = {}
            for model, rels in relationships_by_model.items():
                other_rels = set.union(*(r for m, r in relationships_by_model.items() if m != model)) if len(relationships_by_model) > 1 else set()
                relationship_unique_by_model[model] = sorted(rels - other_rels)

            # Compute relationship Jaccard similarity
            relationship_jaccard = len(relationship_overlap) / len(all_relationships) if all_relationships else None

            results.append(
                InterModelMetrics(
                    repository=repo,
                    models=sorted(models_for_repo),
                    elements_by_model={m: sorted(e) for m, e in elements_by_model.items()},
                    overlap=sorted(overlap),
                    unique_by_model=unique_by_model,
                    jaccard_similarity=jaccard,
                    # Edge comparison
                    edges_by_model={m: sorted(e) for m, e in edges_by_model.items()},
                    edge_overlap=sorted(edge_overlap),
                    edge_unique_by_model=edge_unique_by_model,
                    edge_jaccard=edge_jaccard,
                    # Relationship comparison
                    relationships_by_model={m: sorted(r) for m, r in relationships_by_model.items()},
                    relationship_overlap=sorted(relationship_overlap),
                    relationship_unique_by_model=relationship_unique_by_model,
                    relationship_jaccard=relationship_jaccard,
                )
            )

        return results

    # =========================================================================
    # INCONSISTENCY LOCALIZATION
    # =========================================================================

    def localize_inconsistencies(self) -> InconsistencyLocalization:
        """
        Identify WHERE inconsistencies occur in the pipeline.

        Analyzes inconsistency patterns by:
        - Element type
        - Pipeline stage
        - Model
        - Repository

        Returns:
            InconsistencyLocalization with scores and hotspots
        """
        # Compute consistency by different dimensions. Every score compares the runs of one
        # repository with one model (pairs with 2 runs or more) and is the mean over the pairs;
        # a type or stage none of the runs logged is left out (not measured).
        by_element_type: dict[str, float] = {}
        by_stage: dict[str, float] = {}
        by_model: dict[str, float] = {}
        by_repository: dict[str, float] = {}

        intra_metrics = self.compute_intra_model_consistency()
        pairs = [(metric.model, metric.repository) for metric in intra_metrics]

        # Object type consistency from OCEL (0-1)
        for object_type in ("Element", "GraphNode", "Edge", "Relationship"):
            measured = [by_run for model, repo in pairs if any((by_run := self._objects_by_run(object_type, model, repo)).values())]
            if measured:
                by_element_type[object_type] = sum(compute_consistency_score(by_run) for by_run in measured) / len(measured)

        # Stage consistency from run stats: the spread of the counts (runs that did not extract have no node count)
        for stage, count_key in (("extraction", "nodes_created"), ("derivation", "elements_created")):
            scores: list[float] = []
            for model, repo in pairs:
                counts = [
                    run["stats"][stage][count_key]
                    for run in self.runs
                    if run["model_name"] == model and run["repository"] == repo and count_key in (run.get("stats") or {}).get(stage, {})
                ]
                if len(counts) >= 2:
                    avg = sum(counts) / len(counts)
                    variance = sum((c - avg) ** 2 for c in counts) / len(counts)
                    # Normalize: lower variance = higher consistency
                    cv = (variance**0.5 / avg * 100) if avg > 0 else 0
                    scores.append(max(0, 100 - cv))  # Convert to consistency %
            if scores:
                by_stage[stage] = sum(scores) / len(scores)

        # Model consistency
        model_scores: dict[str, list[float]] = {}
        for metric in intra_metrics:
            if metric.model not in model_scores:
                model_scores[metric.model] = []
            model_scores[metric.model].append(metric.name_consistency)

        by_model = {m: sum(v) / len(v) for m, v in model_scores.items() if v}

        # Repository consistency
        repo_scores: dict[str, list[float]] = {}
        for metric in intra_metrics:
            if metric.repository not in repo_scores:
                repo_scores[metric.repository] = []
            repo_scores[metric.repository].append(metric.name_consistency)

        by_repository = {r: sum(v) / len(v) for r, v in repo_scores.items() if v}

        # Identify hotspots (lowest consistency areas)
        hotspots = []

        for model, score in sorted(by_model.items(), key=lambda x: x[1]):
            if score < 80:
                hotspots.append(
                    {
                        "type": "model",
                        "name": model,
                        "consistency": score,
                        "severity": "high" if score < 50 else "medium",
                    }
                )

        for stage, score in sorted(by_stage.items(), key=lambda x: x[1]):
            if score < 80:
                hotspots.append(
                    {
                        "type": "stage",
                        "name": stage,
                        "consistency": score,
                        "severity": "high" if score < 50 else "medium",
                    }
                )

        # Add hotspots for edge and relationship consistency
        # Note: compute_consistency_score returns 0-1, convert to percentage for comparison
        for obj_type, score in sorted(by_element_type.items(), key=lambda x: x[1]):
            score_pct = score * 100  # Convert to percentage
            if score_pct < 80 and obj_type in ("Edge", "Relationship"):
                hotspots.append(
                    {
                        "type": "object_type",
                        "name": obj_type,
                        "consistency": score_pct,
                        "severity": "high" if score_pct < 50 else "medium",
                    }
                )

        return InconsistencyLocalization(
            by_element_type=by_element_type,
            by_stage=by_stage,
            by_model=by_model,
            by_repository=by_repository,
            hotspots=hotspots[:10],  # Top 10 hotspots
        )

    # =========================================================================
    # OBJECT TRACING
    # =========================================================================

    def trace_element(self, element_id: str) -> list[dict[str, Any]]:
        """
        Get full event history for an element across all runs.

        Args:
            element_id: Element identifier to trace

        Returns:
            List of events involving this element
        """
        events = self.ocel_log.get_events_for_object("Element", element_id)
        return [e.to_jsonl_dict() for e in events]

    def compare_element_across_runs(self, element_name: str) -> dict[str, Any]:
        """
        Compare how an element was derived across different runs/models.

        Args:
            element_name: Element name to compare

        Returns:
            Comparison data across runs
        """
        # Find all runs that produced this element
        runs_with_element: list[str] = []
        runs_without_element: list[str] = []

        for run in self.runs:
            run_id = run["run_id"]
            elements = self.ocel_log.get_events_for_object("BenchmarkRun", run_id)

            # Check if any derivation event includes this element
            has_element = any(element_name in e.objects.get("Element", []) for e in elements if e.activity == "DeriveElements")

            if has_element:
                runs_with_element.append(run_id)
            else:
                runs_without_element.append(run_id)

        return {
            "element_name": element_name,
            "present_in_runs": runs_with_element,
            "absent_from_runs": runs_without_element,
            "consistency": len(runs_with_element) / len(self.runs) * 100 if self.runs else 0,
        }

    # =========================================================================
    # EXPORT
    # =========================================================================

    def compute_full_analysis(self) -> AnalysisSummary:
        """
        Compute complete analysis summary.

        Returns:
            AnalysisSummary with all metrics
        """
        intra = self.compute_intra_model_consistency()
        inter = self.compute_inter_model_consistency()
        localization = self.localize_inconsistencies()

        # Compute overall consistency
        all_consistencies: list[float] = []
        for intra_metric in intra:
            all_consistencies.append(intra_metric.name_consistency)
        for inter_metric in inter:
            all_consistencies.append(inter_metric.jaccard_similarity * 100)

        overall = sum(all_consistencies) / len(all_consistencies) if all_consistencies else 100

        return AnalysisSummary(
            session_id=self.session_id,
            analyzed_at=datetime.now().isoformat(),
            intra_model=intra,
            inter_model=inter,
            localization=localization,
            overall_consistency=overall,
            model_quality=self.compute_model_quality(),
            detail_level=self.compute_detail_level(),
            variance_split=variance_split_for_session(*self._session_scope()),
            extraction_stability=extraction_stability_for_session(*self._session_scope()),
            naming_fallbacks=naming_fallbacks_for_session(self._session_scope()[0]),
            metrics=session_metrics.session_report([self._session_scope()[0]]),
        )

    def compute_model_quality(self) -> list[dict[str, Any]]:
        """Structural quality of every model the session exported (see ``model_quality_for_session``)."""
        config = (self.session_info or {}).get("config", {})
        return model_quality_for_session(workspace() / "benchmarks" / self.session_id, config.get("repositories", []), config.get("models", []))

    def _session_scope(self) -> tuple[Path, list[str], list[str]]:
        """The session folder, its repositories and its models."""
        config = (self.session_info or {}).get("config", {})
        return workspace() / "benchmarks" / (self.session_id or ""), config.get("repositories", []), config.get("models", [])

    def compute_detail_level(self) -> list[dict[str, Any]]:
        """The export's detail level per repository and model (see ``detail_level_for_session``)."""
        config = (self.session_info or {}).get("config", {})
        return detail_level_for_session(workspace() / "benchmarks" / self.session_id, config.get("repositories", []), config.get("models", []))

    def export_summary(self, path: str | None = None, format: str = "json") -> str:
        """
        Export analysis summary to file.

        Args:
            path: Output path (default: <workspace>/benchmarks/{session}/analysis.json)
            format: Output format (json, markdown)

        Returns:
            Path to exported file
        """
        summary = self.compute_full_analysis()

        if path is None:
            output_dir = workspace() / "benchmarks" / self.session_id / "analysis"
            output_dir.mkdir(parents=True, exist_ok=True)
            path = str(output_dir / f"summary.{format}")

        if format == "json":
            with open(path, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)
        elif format == "markdown":
            self._export_markdown(summary, path)
        else:
            raise ValueError(f"Unknown format: {format}")

        return path

    def _export_markdown(self, summary: AnalysisSummary, path: str) -> None:
        """Export summary as markdown report."""
        lines = [
            f"# Benchmark Analysis: {summary.session_id}",
            "",
            f"**Analyzed:** {summary.analyzed_at}",
            f"**Overall Consistency:** {summary.overall_consistency:.1f}%",
            "",
            "## Intra-Model Consistency",
            "",
            "How stable is each model across multiple runs?",
            "",
            "| Model | Repository | Runs | Consistency | Variance |",
            "|-------|------------|------|-------------|----------|",
        ]

        for intra_m in summary.intra_model:
            lines.append(f"| {intra_m.model} | {intra_m.repository} | {intra_m.runs} | {intra_m.name_consistency:.1f}% | {intra_m.count_variance:.2f} |")

        lines.extend(
            [
                "",
                "## Inter-Model Consistency",
                "",
                "How do different models compare on the same repository?",
                "",
                "| Repository | Models | Overlap | Jaccard |",
                "|------------|--------|---------|---------|",
            ]
        )

        for inter_m in summary.inter_model:
            lines.append(f"| {inter_m.repository} | {', '.join(inter_m.models)} | {len(inter_m.overlap)} | {inter_m.jaccard_similarity:.2f} |")

        if summary.model_quality:
            lines.extend(
                [
                    "",
                    "## Model Quality",
                    "",
                    "Structure of each exported model: relationships per element, elements in no relationship, parts composed into more than one whole,",
                    "pairs with several relationship types, elements repeating another (should be 0), and element precision and recall against the reference model (indicative).",
                    "",
                    "| Repository | Model | Run | Elements | Relationships | Per element | Orphan % | Comp. violations | Double pairs | Duplicate elements | Reference P / R |",
                    "|------------|-------|-----|----------|---------------|-------------|----------|------------------------|--------------|--------------------|-----------------|",
                ]
            )
            for q in summary.model_quality:
                ref = q.get("reference")
                ref_text = f"{ref['precision']:.2f} / {ref['recall']:.2f}" if ref else "-"
                lines.append(
                    f"| {q['repository']} | {q['model']} | {q['run']} | {q['elements']} | {q['relationships']} | {q['relationships_per_element']:.2f} | "
                    f"{q['orphan_share']:.0%} | {q['composition_violations']} | {q['duplicate_pairs']} | {q['duplicate_elements']} | {ref_text} |"
                )
            lines.append("")

        lines.extend(
            [
                "",
                "## Inconsistency Hotspots",
                "",
            ]
        )

        if summary.localization.hotspots:
            for hotspot in summary.localization.hotspots:
                lines.append(f"- **{hotspot['type'].title()}:** {hotspot['name']} (consistency: {hotspot['consistency']:.1f}%, severity: {hotspot['severity']})")
        else:
            lines.append("No significant hotspots detected.")

        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_metrics_to_db(self) -> None:
        """Store computed metrics in benchmark_metrics table."""
        summary = self.compute_full_analysis()

        # Clear existing metrics for this session
        self.engine.execute(
            "DELETE FROM benchmark_metrics WHERE session_id = ?",
            [self.session_id],
        )

        # Insert intra-model metrics
        for intra_m in summary.intra_model:
            self.engine.execute(
                """
                INSERT INTO benchmark_metrics
                (session_id, metric_type, metric_key, metric_value, details)
                VALUES (?, 'intra_model', ?, ?, ?)
                """,
                [
                    self.session_id,
                    f"{intra_m.model}:{intra_m.repository}",
                    intra_m.name_consistency,
                    json.dumps(intra_m.to_dict()),
                ],
            )

        # Insert inter-model metrics
        for inter_m in summary.inter_model:
            self.engine.execute(
                """
                INSERT INTO benchmark_metrics
                (session_id, metric_type, metric_key, metric_value, details)
                VALUES (?, 'inter_model', ?, ?, ?)
                """,
                [
                    self.session_id,
                    inter_m.repository,
                    inter_m.jaccard_similarity * 100,
                    json.dumps(inter_m.to_dict()),
                ],
            )

        # Insert overall consistency
        self.engine.execute(
            """
            INSERT INTO benchmark_metrics
            (session_id, metric_type, metric_key, metric_value, details)
            VALUES (?, 'overall', 'consistency', ?, ?)
            """,
            [
                self.session_id,
                summary.overall_consistency,
                json.dumps({"analyzed_at": summary.analyzed_at}),
            ],
        )
