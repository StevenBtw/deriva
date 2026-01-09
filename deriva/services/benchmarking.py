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
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deriva.adapters.archimate import ArchimateManager

if TYPE_CHECKING:
    from deriva.common.types import RunLoggerProtocol
from deriva.adapters.graph import GraphManager
from deriva.adapters.llm import LLMManager
from deriva.adapters.llm.manager import load_benchmark_models
from deriva.adapters.llm.models import BenchmarkModelConfig
from deriva.common.ocel import OCELLog, create_run_id, hash_content
from deriva.services import derivation, extraction

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
    ):
        self.ocel_log = ocel_log
        self.run_id = run_id
        self.session_id = session_id
        self.model = model
        self.repo = repo
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

        self.ocel_log.create_event(
            activity=activity,
            objects=objects_dict,
            config_type=config_type,
            config_id=config_id,
            objects_created=len(objects_created),
            edges_created=len(edges_created) if edges_created else 0,
            relationships_created=len(relationships_created) if relationships_created else 0,
            stats=stats or {},
            errors=errors or [],
        )


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

    def complete(self, message: str = "") -> None:
        """Mark step as completed and log to OCEL."""
        self._completed = True
        config_type = "extraction" if self.logger._current_phase == "extraction" else "derivation"
        self.logger.log_config_result(
            config_type=config_type,
            config_id=self.step,
            objects_created=self._created_objects,
            edges_created=self._created_edges if self._created_edges else None,
            relationships_created=self._created_relationships if self._created_relationships else None,
            stats={"items_created": self.items_created, "items_processed": self.items_processed},
            errors=[],
        )

    def error(self, error: str, message: str = "") -> None:
        """Mark step as errored."""
        self._completed = True
        config_type = "extraction" if self.logger._current_phase == "extraction" else "derivation"
        self.logger.log_config_result(
            config_type=config_type,
            config_id=self.step,
            objects_created=self._created_objects,
            edges_created=self._created_edges if self._created_edges else None,
            relationships_created=self._created_relationships if self._created_relationships else None,
            stats={"items_created": self.items_created, "items_failed": self.items_failed},
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

    def total_runs(self) -> int:
        """Calculate total number of runs in the matrix."""
        return len(self.repositories) * len(self.models) * self.runs_per_combination

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return asdict(self)


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
    repository: str
    model: str
    iteration: int
    status: str  # completed, failed
    stats: dict[str, Any]
    errors: list[str]
    duration_seconds: float


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
        import requests

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
                response = requests.post(
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

            except requests.exceptions.RequestException as e:
                error_msg = f"Failed to preload {name}: {e}"
                errors.append(error_msg)
                if verbose:
                    print(f"FAILED: {e}")

        return errors

    def run(self, verbose: bool = False) -> BenchmarkResult:
        """
        Execute the full benchmark matrix.

        Args:
            verbose: Print progress to stdout

        Returns:
            BenchmarkResult with session details and metrics
        """
        self.session_start = datetime.now()
        self.session_id = f"bench_{self.session_start.strftime('%Y%m%d_%H%M%S')}"

        errors: list[str] = []
        runs_completed = 0
        runs_failed = 0

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
        assert self.session_id is not None, "session_id must be set after _create_session"

        # Log benchmark start
        self.ocel_log.create_event(
            activity="StartBenchmark",
            objects={"BenchmarkSession": [self.session_id]},
            repositories=self.config.repositories,
            models=self.config.models,
            runs_per_combination=self.config.runs_per_combination,
            stages=self.config.stages,
        )

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"BENCHMARK SESSION: {self.session_id}")
            print(f"{'=' * 60}")
            print(f"Repositories: {self.config.repositories}")
            print(f"Models: {self.config.models}")
            print(f"Runs per combination: {self.config.runs_per_combination}")
            print(f"Total runs: {self.config.total_runs()}")
            print(f"{'=' * 60}\n")

        # Execute the matrix
        run_number = 0
        total_runs = self.config.total_runs()

        for repo_name in self.config.repositories:
            for model_name in self.config.models:
                for iteration in range(1, self.config.runs_per_combination + 1):
                    run_number += 1

                    if verbose:
                        print(f"\n--- Run {run_number}/{total_runs} ---")
                        print(f"Repository: {repo_name}")
                        print(f"Model: {model_name}")
                        print(f"Iteration: {iteration}")

                    try:
                        result = self._run_single(
                            repo_name=repo_name,
                            model_name=model_name,
                            iteration=iteration,
                            verbose=verbose,
                        )

                        if result.status == "completed":
                            runs_completed += 1
                            if verbose:
                                print(f"[OK] Completed: {result.stats}")
                        else:
                            runs_failed += 1
                            errors.extend(result.errors)
                            if verbose:
                                print(f"[FAIL] Failed: {result.errors}")

                    except Exception as e:
                        runs_failed += 1
                        error_msg = f"Run failed ({repo_name}/{model_name}/{iteration}): {e}"
                        errors.append(error_msg)
                        if verbose:
                            print(f"[FAIL] Exception: {e}")

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

        if verbose:
            print(f"\n{'=' * 60}")
            print("BENCHMARK COMPLETE")
            print(f"{'=' * 60}")
            print(f"Runs completed: {runs_completed}")
            print(f"Runs failed: {runs_failed}")
            print(f"Duration: {duration:.1f}s")
            print(f"OCEL log: {ocel_path}")
            print(f"{'=' * 60}\n")

        return BenchmarkResult(
            session_id=self.session_id,
            config=self.config,
            runs_completed=runs_completed,
            runs_failed=runs_failed,
            ocel_path=ocel_path,
            duration_seconds=duration,
            errors=errors,
        )

    def _run_single(
        self,
        repo_name: str,
        model_name: str,
        iteration: int,
        verbose: bool = False,
    ) -> RunResult:
        """
        Execute a single benchmark run.

        Args:
            repo_name: Repository to process
            model_name: Model config name to use
            iteration: Run iteration number

        Returns:
            RunResult with run details
        """
        run_start = datetime.now()
        assert self.session_id is not None, "session_id must be set before executing runs"
        run_id = create_run_id(self.session_id, repo_name, model_name, iteration)

        # Set current context
        self._current_run_id = run_id
        self._current_model = model_name
        self._current_repo = repo_name

        # Create run in database
        self._create_run(run_id, repo_name, model_name, iteration)

        # Log run start
        session_id = self.session_id  # Validated above
        self.ocel_log.create_event(
            activity="StartRun",
            objects={
                "BenchmarkSession": [session_id],
                "BenchmarkRun": [run_id],
                "Repository": [repo_name],
                "Model": [model_name],
            },
            iteration=iteration,
        )

        errors: list[str] = []
        stats: dict[str, Any] = {}

        try:
            # Clear graph/model if configured
            if self.config.clear_between_runs:
                self.graph_manager.clear_graph()
                self.archimate_manager.clear_model()

            # Create OCEL run logger for per-config event tracking
            ocel_run_logger = OCELRunLogger(
                ocel_log=self.ocel_log,
                run_id=run_id,
                session_id=session_id,
                model=model_name,
                repo=repo_name,
            )

            # Create LLM managers for this model
            # - cached_llm: uses cache (for stable configs)
            # - nocache_llm: skips cache (for configs being optimized)
            model_config = self._model_configs[model_name]
            global_nocache = not self.config.use_cache

            if global_nocache:
                # Cache disabled globally - single manager
                llm_manager = LLMManager.from_config(model_config, nocache=True)
                nocache_llm_manager = llm_manager
            else:
                # Cache enabled - create both managers for per-config control
                llm_manager = LLMManager.from_config(model_config, nocache=False)
                nocache_llm_manager = LLMManager.from_config(model_config, nocache=True)

            # Create wrapped query function with per-config cache control
            llm_query_fn = self._create_logging_query_fn(
                cached_llm=llm_manager,
                nocache_llm=nocache_llm_manager,
                run_logger=ocel_run_logger,
            )

            # Determine which stages to run
            stages = self.config.stages

            # Run pipeline stages
            if "extraction" in stages:
                result = extraction.run_extraction(
                    engine=self.engine,
                    graph_manager=self.graph_manager,
                    llm_query_fn=llm_query_fn,
                    repo_name=repo_name,
                    verbose=False,
                    run_logger=cast("RunLoggerProtocol", ocel_run_logger),
                )
                stats["extraction"] = result.get("stats", {})
                self._log_extraction_results(result)
                if not result.get("success"):
                    errors.extend(result.get("errors", []))

            if "derivation" in stages:
                result = derivation.run_derivation(
                    engine=self.engine,
                    graph_manager=self.graph_manager,
                    archimate_manager=self.archimate_manager,
                    llm_query_fn=llm_query_fn,
                    verbose=False,
                    run_logger=cast("RunLoggerProtocol", ocel_run_logger),
                )
                stats["derivation"] = result.get("stats", {})
                self._log_derivation_results(result)
                if not result.get("success"):
                    errors.extend(result.get("errors", []))

            status = "completed" if not errors else "failed"

        except Exception as e:
            status = "failed"
            errors.append(str(e))

        # Calculate duration
        duration = (datetime.now() - run_start).total_seconds()

        # Log run complete
        self.ocel_log.create_event(
            activity="CompleteRun",
            objects={
                "BenchmarkSession": [session_id],
                "BenchmarkRun": [run_id],
                "Repository": [repo_name],
                "Model": [model_name],
            },
            status=status,
            duration_seconds=duration,
            stats=stats,
        )

        # Update run in database
        self._complete_run(run_id, status, stats)

        return RunResult(
            run_id=run_id,
            repository=repo_name,
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
    ) -> Callable[..., Any]:
        """
        Create an LLM query function with per-config cache control.

        Args:
            cached_llm: LLM manager with cache enabled
            nocache_llm: LLM manager with cache disabled
            run_logger: OCEL run logger tracking current config

        Returns:
            Wrapped query function that selects appropriate LLM based on config
        """
        nocache_configs = self.config.nocache_configs

        def query_fn(
            prompt: str,
            schema: dict,
            temperature: float | None = None,
            max_tokens: int | None = None,
        ) -> Any:
            # Check if current config should skip cache
            current_config = run_logger.current_config
            skip_cache = current_config in nocache_configs if current_config else False

            # Select appropriate LLM manager
            llm = nocache_llm if skip_cache else cached_llm

            # Call the actual LLM with optional parameters
            response = llm.query(prompt, schema=schema, temperature=temperature, max_tokens=max_tokens)

            # Log the query as an OCEL event (metadata only)
            usage = getattr(response, "usage", None) or {}
            content = getattr(response, "content", "")
            cache_hit = getattr(response, "response_type", None) == "cached"

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
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                cache_hit=cache_hit,
                cache_skipped=skip_cache,
                response_hash=hash_content(content) if content else None,
            )

            return response

        return query_fn

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

    # =========================================================================
    # DATABASE OPERATIONS
    # =========================================================================

    def _create_session(self) -> None:
        """Create benchmark session in database."""
        assert self.session_start is not None, "session_start must be set"
        self.engine.execute(
            """
            INSERT INTO benchmark_sessions
            (session_id, description, config, started_at, status)
            VALUES (?, ?, ?, ?, 'running')
            """,
            [
                self.session_id,
                self.config.description,
                json.dumps(self.config.to_dict()),
                self.session_start.isoformat(),
            ],
        )

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

    def _export_ocel(self) -> str:
        """Export OCEL log to files."""
        # Create benchmark output directory
        session_id = self.session_id or "unknown"
        output_dir = Path("workspace/benchmarks") / session_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # Export OCEL JSON
        ocel_json_path = output_dir / "events.ocel.json"
        self.ocel_log.export_json(ocel_json_path)

        # Export JSONL for streaming
        ocel_jsonl_path = output_dir / "events.jsonl"
        self.ocel_log.export_jsonl(ocel_jsonl_path)

        # Export summary
        summary = {
            "session_id": self.session_id,
            "config": self.config.to_dict(),
            "started_at": self.session_start.isoformat() if self.session_start else None,
            "completed_at": datetime.now().isoformat(),
            "total_events": len(self.ocel_log.events),
            "object_types": list(self.ocel_log.object_types),
        }
        with open(output_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        return str(ocel_json_path)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def list_benchmark_sessions(engine: Any, limit: int = 10) -> list[dict[str, Any]]:
    """
    List recent benchmark sessions.

    Args:
        engine: DuckDB connection
        limit: Maximum number of sessions to return

    Returns:
        List of session dictionaries
    """
    rows = engine.execute(
        """
        SELECT session_id, description, status, started_at, completed_at
        FROM benchmark_sessions
        ORDER BY started_at DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()

    return [
        {
            "session_id": row[0],
            "description": row[1],
            "status": row[2],
            "started_at": row[3],
            "completed_at": row[4],
        }
        for row in rows
    ]


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

    # Edge consistency (extraction phase)
    edge_counts: list[int] = field(default_factory=list)
    edge_count_variance: float = 0.0
    edge_consistency: float = 100.0  # % of edges in ALL runs
    stable_edges: list[str] = field(default_factory=list)
    unstable_edges: dict[str, int] = field(default_factory=dict)
    edge_type_breakdown: dict[str, float] = field(default_factory=dict)  # CONTAINS: 95%, etc.

    # Relationship consistency (derivation phase)
    relationship_counts: list[int] = field(default_factory=list)
    relationship_count_variance: float = 0.0
    relationship_consistency: float = 100.0  # % of relationships in ALL runs
    stable_relationships: list[str] = field(default_factory=list)
    unstable_relationships: dict[str, int] = field(default_factory=dict)
    relationship_type_breakdown: dict[str, float] = field(default_factory=dict)  # Serving: 90%, etc.

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class InterModelMetrics:
    """Comparison metrics across models for the same repository."""

    repository: str
    models: list[str]
    elements_by_model: dict[str, list[str]]
    overlap: list[str]  # Elements in ALL models
    unique_by_model: dict[str, list[str]]  # Elements unique to each model
    jaccard_similarity: float

    # Edge comparison (extraction phase)
    edges_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_overlap: list[str] = field(default_factory=list)  # Edges in ALL models
    edge_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_jaccard: float = 1.0

    # Relationship comparison (derivation phase)
    relationships_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_overlap: list[str] = field(default_factory=list)  # Relationships in ALL models
    relationship_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_jaccard: float = 1.0

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


@dataclass
class AnalysisSummary:
    """Complete analysis summary."""

    session_id: str
    analyzed_at: str
    intra_model: list[IntraModelMetrics]
    inter_model: list[InterModelMetrics]
    localization: InconsistencyLocalization
    overall_consistency: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "analyzed_at": self.analyzed_at,
            "intra_model": [m.to_dict() for m in self.intra_model],
            "inter_model": [m.to_dict() for m in self.inter_model],
            "localization": self.localization.to_dict(),
            "overall_consistency": self.overall_consistency,
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

        # Load run data (reuse convenience function)
        self.runs = get_benchmark_runs(engine, session_id)

    def _load_ocel(self) -> OCELLog:
        """Load OCEL log from file."""
        ocel_path = Path("workspace/benchmarks") / self.session_id / "events.ocel.json"

        if ocel_path.exists():
            return OCELLog.from_json(ocel_path)

        # Try JSONL format
        jsonl_path = Path("workspace/benchmarks") / self.session_id / "events.jsonl"
        if jsonl_path.exists():
            return OCELLog.from_jsonl(jsonl_path)

        # Return empty log if files not found
        return OCELLog()

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

            edge_consistency = len(stable_edges) / len(all_edges) * 100 if all_edges else 100.0

            # Compute per-type breakdown for edges
            edge_type_breakdown = self._compute_type_breakdown(edges_by_run)

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

            rel_consistency = len(stable_relationships) / len(all_relationships) * 100 if all_relationships else 100.0

            # Compute per-type breakdown for relationships
            relationship_type_breakdown = self._compute_type_breakdown(relationships_by_run)

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
                )
            )

        return results

    def _get_elements_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Get derived elements grouped by run for a model/repo combination."""
        result: dict[str, set[str]] = {}

        for event in self.ocel_log.events:
            if event.activity != "DeriveElements":
                continue

            event_model = event.objects.get("Model", [None])[0]
            event_repo = event.objects.get("Repository", [None])[0]
            runs = event.objects.get("BenchmarkRun", [])

            if event_model == model and event_repo == repo:
                for run_id in runs:
                    if run_id not in result:
                        result[run_id] = set()
                    # Elements would be in the Element object type
                    elements = event.objects.get("Element", [])
                    result[run_id].update(elements)

        return result

    def _get_edges_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Get extracted edges grouped by run for a model/repo combination."""
        result: dict[str, set[str]] = {}

        for event in self.ocel_log.events:
            if event.activity != "ExtractConfig":
                continue

            event_model = event.objects.get("Model", [None])[0]
            event_repo = event.objects.get("Repository", [None])[0]
            runs = event.objects.get("BenchmarkRun", [])

            if event_model == model and event_repo == repo:
                for run_id in runs:
                    if run_id not in result:
                        result[run_id] = set()
                    edges = event.objects.get("Edge", [])
                    result[run_id].update(edges)

        return result

    def _get_relationships_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Get derived relationships grouped by run for a model/repo combination."""
        result: dict[str, set[str]] = {}

        for event in self.ocel_log.events:
            if event.activity != "DeriveConfig":
                continue

            event_model = event.objects.get("Model", [None])[0]
            event_repo = event.objects.get("Repository", [None])[0]
            runs = event.objects.get("BenchmarkRun", [])

            if event_model == model and event_repo == repo:
                for run_id in runs:
                    if run_id not in result:
                        result[run_id] = set()
                    relationships = event.objects.get("Relationship", [])
                    result[run_id].update(relationships)

        return result

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
            edge_jaccard = len(edge_overlap) / len(all_edges) if all_edges else 1.0

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
            relationship_jaccard = len(relationship_overlap) / len(all_relationships) if all_relationships else 1.0

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
        # Compute consistency by different dimensions
        by_element_type: dict[str, float] = {}
        by_stage: dict[str, float] = {}
        by_model: dict[str, float] = {}
        by_repository: dict[str, float] = {}

        # Element type consistency from OCEL
        element_consistency = self.ocel_log.compute_consistency_score("Element")
        by_element_type["Element"] = element_consistency

        node_consistency = self.ocel_log.compute_consistency_score("GraphNode")
        by_element_type["GraphNode"] = node_consistency

        # Edge and Relationship consistency from OCEL
        edge_consistency = self.ocel_log.compute_consistency_score("Edge")
        by_element_type["Edge"] = edge_consistency

        relationship_consistency = self.ocel_log.compute_consistency_score("Relationship")
        by_element_type["Relationship"] = relationship_consistency

        # Stage consistency from run stats
        stage_counts: dict[str, list[int]] = {
            "extraction": [],
            "derivation": [],
        }

        for run in self.runs:
            stats = run.get("stats", {})
            if "extraction" in stats:
                stage_counts["extraction"].append(stats["extraction"].get("nodes_created", 0))
            if "derivation" in stats:
                stage_counts["derivation"].append(stats["derivation"].get("elements_created", 0))

        for stage, counts in stage_counts.items():
            if len(counts) >= 2:
                avg = sum(counts) / len(counts)
                variance = sum((c - avg) ** 2 for c in counts) / len(counts)
                # Normalize: lower variance = higher consistency
                cv = (variance**0.5 / avg * 100) if avg > 0 else 0
                by_stage[stage] = max(0, 100 - cv)  # Convert to consistency %
            else:
                by_stage[stage] = 100.0

        # Model consistency
        intra_metrics = self.compute_intra_model_consistency()
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
        )

    def export_summary(self, path: str | None = None, format: str = "json") -> str:
        """
        Export analysis summary to file.

        Args:
            path: Output path (default: workspace/benchmarks/{session}/analysis.json)
            format: Output format (json, markdown)

        Returns:
            Path to exported file
        """
        summary = self.compute_full_analysis()

        if path is None:
            output_dir = Path("workspace/benchmarks") / self.session_id / "analysis"
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
