"""
Benchmarking service for Deriva.

Orchestrates multi-model, multi-repository benchmarking with OCEL event logging
for process mining analysis.

Test Matrix Example:
    3 repositories × 3 LLM models × 3 runs = 27 total executions

Metrics Tracked:
    - Intra-model consistency: How stable is each model on the same repo?
    - Inter-model consistency: How do different models compare on the same repo?
    - Inconsistency localization: WHERE do things diverge?

Usage:
    config = BenchmarkConfig(
        repositories=["repo1", "repo2"],
        models=["azure-gpt4", "openai-gpt4o"],
        runs_per_combination=3,
        stages=["extraction", "derivation"],
    )

    orchestrator = BenchmarkOrchestrator(engine, graph_manager, archimate_manager, config)
    result = orchestrator.run(verbose=True)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.graph import GraphManager
from deriva.adapters.llm import LLMManager
from deriva.adapters.llm.manager import load_benchmark_models
from deriva.adapters.llm.models import BenchmarkModelConfig
from deriva.common.ocel import OCELLog, create_run_id, hash_content
from deriva.services import derivation, extraction


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark session."""

    repositories: list[str]
    models: list[str]  # Model config names (from env)
    runs_per_combination: int = 3
    stages: list[str] = field(default_factory=lambda: ["extraction", "derivation"])
    description: str = ""
    clear_between_runs: bool = True

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

            # Create LLM manager for this model
            model_config = self._model_configs[model_name]
            llm_manager = LLMManager.from_config(model_config, nocache=True)

            # Create wrapped query function that logs OCEL events
            llm_query_fn = self._create_logging_query_fn(llm_manager)

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

    def _create_logging_query_fn(self, llm_manager: LLMManager) -> Callable[[str, dict], Any]:
        """
        Create an LLM query function that logs OCEL events.

        Args:
            llm_manager: The LLM manager to use

        Returns:
            Wrapped query function
        """

        def query_fn(prompt: str, schema: dict) -> Any:
            # Call the actual LLM
            response = llm_manager.query(prompt, schema=schema)

            # Log the query as an OCEL event (metadata only)
            usage = getattr(response, "usage", None) or {}
            content = getattr(response, "content", "")
            cache_hit = getattr(response, "response_type", None) == "cached"

            # These are set before query_fn is called
            current_run_id = self._current_run_id or ""
            current_model = self._current_model or ""

            self.ocel_log.create_event(
                activity="LLMQuery",
                objects={
                    "BenchmarkRun": [current_run_id],
                    "Model": [current_model],
                },
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                cache_hit=cache_hit,
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
