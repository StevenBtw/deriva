"""
PipelineSession - Unified API for the CLI and the studio.

This module provides a single entry point for all pipeline operations,
managing the lifecycle of all managers and exposing both orchestration
methods (run_*) and query methods (get_*) for reactive UI.

Usage (CLI):
    with PipelineSession() as session:
        result = session.run_extraction(repo_name="my-repo")
        session.export_model("output.xml")

Usage (studio, one session per process):
    session = PipelineSession(auto_connect=True)
    stats = session.get_graph_stats()
    elements = session.get_archimate_elements()
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from deriva.common.types import ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter

logger = logging.getLogger(__name__)

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import layer_of
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter
from deriva.adapters.database import get_connection, run_migrations
from deriva.adapters.grafeo import DEFAULT_DATABASE, close_database, database_bytes, database_exists, delete_database, use_database
from deriva.adapters.graph import GraphManager
from deriva.adapters.repository import RepoManager
from deriva.common.logging import RunLogger
from deriva.common.paths import home, resolve, workspace
from deriva.common.settings import RepositorySettings
from deriva.common.types import HasToDict, RunLoggerProtocol

from . import config, derivation, export_bundle, export_levels, extraction, model_configs, ontology, overfit, pipeline, quality, storage, trace
from .llm_log import record_call


def _plain(value: Any) -> Any:
    """A graph node or edge without the engine's internal keys, labels without the namespace."""
    if isinstance(value, dict) and ("_labels" in value or "_id" in value):
        plain = {k: v for k, v in value.items() if not k.startswith("_")}
        if "_labels" in value:
            return {"labels": [label for label in value["_labels"] if label not in ("Graph", "Model")], **plain}
        return {"type": value.get("_type"), **plain}
    return value


class UnknownRepository(ValueError):
    """A repository name that is neither in the workspace nor has a graph database."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(f"Unknown repository: {name} (known: {', '.join(available) or 'none'})")


class RunCancelled(RuntimeError):
    """The run was cancelled: the session makes no further LLM call until the cancel check is removed."""


class PipelineSession:
    """Unified session for CLI and studio pipeline operations.

    Manages all manager lifecycles and provides a clean API for:
    - Lifecycle: connect/disconnect, context manager support
    - Queries: get stats, nodes, elements for reactive UI
    - Orchestration: run extraction, derivation (with phases), full pipeline
    - Infrastructure: graph database control, data clearing
    - Export: ArchiMate XML export
    """

    def __init__(
        self,
        db_path: str | None = None,
        auto_connect: bool = False,
        workspace_dir: str | None = None,
        repository: str | None = None,
    ):
        """Initialize session.

        Args:
            db_path: Path to DuckDB database (default: deriva/adapters/database/sql.db)
            auto_connect: If True, connect immediately
            workspace_dir: Repository workspace directory (default: from env)
            repository: Graph database to work in: a repository name, or the joined
                names of a combined run (default: the shared "default" database)
        """
        self._db_path = db_path
        self.repository = repository or DEFAULT_DATABASE
        self._workspace_dir = str(resolve(workspace_dir or RepositorySettings().workspace_dir))

        # Managers (created on connect)
        self._engine: Any | None = None
        self._graph_manager: GraphManager | None = None
        self._archimate_manager: ArchimateManager | None = None
        self._repo_manager: RepoManager | None = None
        self._llm_manager: Any | None = None  # Lazy loaded
        self._llm_error: str | None = None  # Why the manager could not start, for the run that needed it
        self._call_log: Any | None = None  # LlmCallLog of the running studio run, if any
        self._cancel_check: Callable[[], bool] | None = None  # True once the running studio run is cancelled

        # Test-only mocks (set by tests)
        self._mock_db: Any | None = None
        self._mock_graph: Any | None = None
        self._mock_archimate: Any | None = None
        self._mock_repo: Any | None = None
        self._mock_engine: Any | None = None
        self._mock_extraction: Any | None = None
        self._mock_derivation: Any | None = None
        self._mock_pipeline: Any | None = None

        # State
        self._connected = False

        if auto_connect:
            self.connect()

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    def connect(self) -> None:
        """Connect all managers."""
        if self._connected:
            return

        # Database (get_connection uses DB_PATH from env); bring older schemas up to date
        self._engine = get_connection()
        run_migrations(self._engine)

        # Graph managers (grafeo embedded), in the session's repository database
        use_database(self.repository)
        self._graph_manager = GraphManager()
        self._graph_manager.connect()

        self._archimate_manager = ArchimateManager()
        self._archimate_manager.connect()

        # Repository manager
        self._repo_manager = RepoManager(workspace_dir=self._workspace_dir)

        self._connected = True

    @staticmethod
    def check_repository(repository: str | None) -> None:
        """Refuse a graph database name before it opens (opening creates its file): the shared default, a repository
        in the workspace (as ``repo list`` shows them) or a key whose database exists (a combined run) are known.

        Raises:
            UnknownRepository: with the known repository names
        """
        if not repository or repository == DEFAULT_DATABASE or database_exists(repository):
            return
        names = sorted(str(r) for r in RepoManager().list_repositories(detailed=False))
        if repository not in names:
            raise UnknownRepository(repository, names)

    def use_repository(self, repository: str) -> None:
        """Switch the graph and model managers to another repository's database."""
        self.repository = repository
        use_database(repository)

    @contextmanager
    def in_repository(self, repository: str) -> Generator[None]:
        """Work in another repository's database for a block; the session reads its own repository again afterwards."""
        previous = self.repository
        if repository != previous:
            self.use_repository(repository)
        try:
            yield
        finally:
            if self.repository != previous:
                self.use_repository(previous)

    def repository_data(self, repository: str) -> dict[str, Any]:
        """What a repository's graph database holds: graph nodes and edges, model elements and relationships, bytes on disk."""
        self._ensure_connected()
        assert self._graph_manager is not None
        # Not extracted yet (or a stale record): nothing to count, and opening the database would create one
        if repository != self.repository and not database_exists(repository):
            return {"repository": repository, "graph": {"nodes": 0, "edges": 0}, "model": {"elements": 0, "relationships": 0}, "database_bytes": 0}
        with self.in_repository(repository):
            nodes = self._graph_manager.query("MATCH (n:Graph) RETURN count(n) AS c")
            edges = self._graph_manager.query("MATCH (:Graph)-[r]->(:Graph) RETURN count(r) AS c")
            model = self.get_archimate_stats()
        return {
            "repository": repository,
            "graph": {"nodes": int(nodes[0]["c"]) if nodes else 0, "edges": int(edges[0]["c"]) if edges else 0},
            "model": {"elements": model["total_elements"], "relationships": model["total_relationships"]},
            "database_bytes": database_bytes(repository),
        }

    def extraction_coverage(self, repository: str) -> dict[str, Any]:
        """What of a repository's checkout reached its graph and whether the extraction is complete (no LLM, no writes).

        Raises:
            RepositoryError: the repository is not in the workspace
        """
        self._ensure_connected()
        assert self._repo_manager is not None
        repo = self._repo_manager.get_repository_info(repository)
        # Not extracted yet: nothing reached a graph, and opening the database would create one
        if repository != self.repository and not database_exists(repository):
            return extraction.extraction_coverage(self._engine, None, repo)
        with self.in_repository(repository):
            return extraction.extraction_coverage(self._engine, self._graph_manager, repo)

    def clear_repository_model(self, repository: str) -> dict[str, Any]:
        """Clear a repository's model (its graph stays; the next derivation builds the model again)."""
        with self.in_repository(repository):
            return self.clear_model()

    def clear_repository_data(self, repository: str) -> dict[str, Any]:
        """Clear a repository's graph and model (the next extraction starts from nothing)."""
        with self.in_repository(repository):
            model = self.clear_model()
            graph = self.clear_graph()
        return graph if not graph.get("success") else model

    def _repository_names(self) -> set[str]:
        self._ensure_connected()
        assert self._repo_manager is not None
        return {str(r) for r in self._repo_manager.list_repositories(detailed=False)}

    def storage_overview(self) -> dict[str, Any]:
        """What the workspace keeps on disk: graph databases (repository, shared, orphaned), LLM cache, exports, benchmark sessions."""
        return storage.overview(repositories=self._repository_names(), active=self.repository)

    def clear_llm_cache(self) -> dict[str, int]:
        """Delete every cached LLM answer; the session's own cache closes first and reopens with the next call."""
        if self._llm_manager is not None:
            self._llm_manager.cache.close()
            self._llm_manager = None
        return storage.clear_llm_cache()

    def delete_exports(self) -> dict[str, int]:
        """Delete the exported exchange files in workspace/output."""
        return storage.delete_exports()

    def delete_graph(self, key: str) -> dict[str, Any]:
        """Delete a graph database that belongs to no repository (see ``storage.delete_graph``)."""
        return storage.delete_graph(key, repositories=self._repository_names(), active=self.repository)

    def update_repository(self, name: str) -> dict[str, Any]:
        """Pull a repository's clone (fast-forward only); its graph is not touched until the next extraction."""
        self._ensure_connected()
        assert self._repo_manager is not None
        try:
            info = self._repo_manager.update_repository(name)
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {"success": True, "repository": info.to_dict()}

    def disconnect(self) -> None:
        """Disconnect all managers."""
        if not self._connected:
            return

        if self._graph_manager:
            self._graph_manager.disconnect()
            self._graph_manager = None

        if self._archimate_manager:
            self._archimate_manager.disconnect()
            self._archimate_manager = None

        self._repo_manager = None
        self._engine: Any | None = None
        self._connected = False

        # Release the shared grafeo database
        close_database()

    def __enter__(self) -> PipelineSession:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.disconnect()

    def is_connected(self) -> bool:
        """Check if session is connected."""
        return self._connected

    # =========================================================================
    # LLM (Lazy loaded)
    # =========================================================================

    def _get_llm_query_fn(self, no_cache: bool = False) -> Callable[..., Any] | None:
        """Get LLM query function, lazy loading the manager."""
        if self._llm_manager is None:
            try:
                from deriva.adapters.llm import LLMManager

                self._llm_manager = LLMManager()
                self._llm_error = None
            except Exception as e:
                logger.warning("Failed to initialize LLM manager: %s", e)
                # Why, for the run that needed it (the manager's errors name variables, never values)
                self._llm_error = str(e)
                return None

        if no_cache:
            self._llm_manager.nocache = True

        def query_fn(
            prompt: str,
            schema: dict | None = None,
            temperature: float | None = None,
            max_tokens: int | None = None,
            system_prompt: str | None = None,
            response_model: type | None = None,
        ) -> Any:
            assert self._llm_manager is not None
            # A cancelled run stops at its next call, also inside a long step
            if self._cancel_check is not None and self._cancel_check():
                raise RunCancelled("run cancelled")
            try:
                response = self._llm_manager.query(
                    prompt,
                    schema=schema,
                    response_model=response_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                )
            except Exception as exc:
                self._record_call(prompt, schema, system_prompt, None, str(exc))
                raise
            self._record_call(prompt, schema, system_prompt, response, None)
            return response

        return query_fn

    def _llm_not_configured(self) -> str:
        return f"LLM not configured: {self._llm_error}" if self._llm_error else "LLM not configured. Derivation requires LLM."

    def attach_call_log(self, log: Any) -> None:
        """Record every LLM call of this session in ``log`` (an LlmCallLog) until detached."""
        self._call_log = log

    def detach_call_log(self) -> None:
        self._call_log = None

    def set_cancel_check(self, check: Callable[[], bool] | None) -> None:
        """Refuse every LLM call while ``check()`` is True (the studio's run cancel); None removes it."""
        self._cancel_check = check

    def _record_call(self, prompt: str, schema: dict | None, system_prompt: str | None, response: Any, error: str | None) -> None:
        log = self._call_log
        if log is None:
            return
        metrics = (getattr(self._llm_manager, "last_call", None) or {}) if self._llm_manager is not None else {}
        record_call(log, metrics, prompt=prompt, schema=schema, system_prompt=system_prompt, response=response, error=error)

    @property
    def llm_info(self) -> dict[str, str] | None:
        """Get LLM provider info."""
        if self._llm_manager is None:
            self._get_llm_query_fn()
        if self._llm_manager:
            return {
                "provider": str(self._llm_manager.provider_name),
                "model": str(self._llm_manager.model),
            }
        return None

    @property
    def llm_error(self) -> str | None:
        """Why the LLM could not start (a missing key variable, the .env read), or None; names variables, never values."""
        return self._llm_error

    def write_run_inputs(self, folder: str | Path, run_id: str) -> Path:
        """Write what a run is about to run on into ``folder/inputs.json``: the active config versions, LLM
        samples, the tables without version history and the environment, with the session's LLM settings
        (provider, model, default temperature and max tokens; no keys). Same format as a benchmark session's inputs."""
        self._ensure_connected()
        if self._llm_manager is None:
            self._get_llm_query_fn()
        manager = self._llm_manager
        settings = (("provider", "provider_name"), ("model", "model"), ("temperature", "temperature"), ("max_tokens", "max_tokens"))
        models = {"session": {key: getattr(manager, attr, None) for key, attr in settings}} if manager is not None else {}
        record = {"run_id": run_id, "captured_at": datetime.now().isoformat(), **export_bundle.run_inputs(self._engine, models)}
        path = Path(folder) / "inputs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        return path

    # =========================================================================
    # QUERIES (for reactive UI)
    # =========================================================================

    def get_graph_stats(self) -> dict[str, Any]:
        """Get graph statistics for display."""
        self._ensure_connected()
        assert self._graph_manager is not None

        node_types = ["Repository", "Directory", "File", "BusinessConcept", "Technology", "TypeDefinition", "Method", "Test", "ExternalDependency"]

        stats: dict[str, Any] = {"total_nodes": 0, "by_type": {}}
        by_type: dict[str, int] = {}
        total = 0
        for node_type in node_types:
            nodes = self._graph_manager.get_nodes_by_type(node_type)
            count = len(nodes)
            by_type[node_type] = count
            total += count

        stats["by_type"] = by_type
        stats["total_nodes"] = total
        return stats

    def get_graph_nodes(self, node_type: str, limit: int | None = None) -> list[dict]:
        """Get nodes of a specific type (the first ``limit`` by id when given)."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return self._graph_manager.get_nodes_by_type(node_type, limit=limit)

    def model_quality(self) -> dict[str, Any]:
        """The quality verdict on the session's model from its structure (orphans, relationship types, layers,
        elements without an artifact behind them); no LLM, no writes."""
        self._ensure_connected()
        return quality.model_quality(self._engine, self._graph_manager, self._archimate_manager)

    def get_archimate_stats(self) -> dict[str, Any]:
        """Get ArchiMate model statistics."""
        self._ensure_connected()
        assert self._archimate_manager is not None

        elements = self._archimate_manager.get_elements()
        relationships = self._archimate_manager.get_relationships()

        # Count by type
        by_type: dict[str, int] = {}
        for elem in elements:
            if isinstance(elem, dict):
                elem_type = cast(dict[str, Any], elem).get("type", "Unknown")
            else:
                elem_type = getattr(elem, "element_type", None) or getattr(elem, "type", "Unknown")
            by_type[elem_type] = by_type.get(elem_type, 0) + 1

        return {
            "total_elements": len(elements),
            "total_relationships": len(relationships),
            "by_type": by_type,
        }

    def get_archimate_elements(self) -> list[dict]:
        """Get all ArchiMate elements."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        elements = self._archimate_manager.get_elements()
        return [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in elements]

    def get_archimate_relationships(self) -> list[dict]:
        """Get all ArchiMate relationships."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        rels = self._archimate_manager.get_relationships()
        return [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in rels]

    def get_model_levels(self) -> dict[str, Any]:
        """The enabled model at both export levels: elements (with ``level`` and ``layer``), relationships and views.

        Each view names its viewpoint, its level (a view with detail elements is a detail view), its element ids and the
        ids of the relationships it shows (those of its level: a cross-level link or another level's relationship
        between two of its elements is not shown).
        """
        self._ensure_connected()
        assert self._archimate_manager is not None
        leveled = self._leveled_model(self._archimate_manager.get_elements(enabled_only=True))
        return {
            "elements": [{**e.to_dict(), "level": leveled.properties[e.identifier]["level"], "layer": layer_of(e.element_type)} for e in leveled.elements],
            "relationships": [{**r.to_dict(), "level": leveled.relationship_properties[r.identifier]["level"]} for r in leveled.relationships],
            "views": [
                {"name": v.name, "viewpoint": v.viewpoint, "level": v.level, "elements": [n.element for n in v.nodes], "relationships": [c.relationship for c in v.connections]}
                for v in leveled.views
            ],
        }

    def _leveled_model(self, elements: list[Any]) -> export_levels.LeveledModel:
        """The enabled elements and the relationships between them, with the detail level from the graph."""
        assert self._archimate_manager is not None
        enabled_ids = {e.identifier for e in elements}
        relationships = [r for r in self._archimate_manager.get_relationships() if r.source in enabled_ids and r.target in enabled_ids]
        return export_levels.leveled_model(elements, relationships, export_levels.detail_lineage(self._graph_manager))

    def query_graph(self, cypher: str) -> list[dict]:
        """Run arbitrary Cypher query on Graph namespace."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return self._graph_manager.query(cypher)

    def query_model(self, cypher: str) -> list[dict]:
        """Run arbitrary Cypher query on Model namespace."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        return self._archimate_manager.query(cypher)

    def query_graph_read_only(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run a user-typed Cypher query on the Graph namespace; writes are rolled back."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return self._graph_manager.query_read_only(cypher, params)

    def query_model_read_only(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Run a user-typed Cypher query on the Model namespace; writes are rolled back."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        return self._archimate_manager.query_read_only(cypher, params)

    def trace_element(self, element_id: str, calls: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """Where a model element comes from: sources, relationships and the given run calls that mention its sources."""
        return trace.trace_element(self, element_id, calls or [])

    def intermediate_ontology(self) -> dict[str, Any]:
        """The graph's node and edge types with the extraction steps that produce them and the derivation steps that read them."""
        return ontology.intermediate_ontology(self)

    def output_ontology(self) -> dict[str, Any]:
        """ArchiMate as Deriva derives it: element types with their steps, relationship types and the allowed relationships."""
        return ontology.output_ontology(self)

    def get_repositories(self, detailed: bool = False) -> list[dict]:
        """Get list of repositories."""
        self._ensure_connected()
        assert self._repo_manager is not None
        repos = self._repo_manager.list_repositories(detailed=detailed)
        result: list[dict] = []
        for r in repos:
            if isinstance(r, str):
                result.append({"name": r})
            elif hasattr(r, "to_dict"):
                result.append(r.to_dict())
            else:
                result.append({"name": str(r)})
        return result

    # =========================================================================
    # INFRASTRUCTURE (graph database control)
    # =========================================================================

    def get_graph_db_status(self) -> dict[str, Any]:
        """Get graph database status (grafeo embedded — always running)."""
        return {
            "running": True,
            "engine": "grafeo_embedded",
            "status": "Running (embedded)",
        }

    def start_graph_db(self) -> dict[str, Any]:
        """Start graph database (no-op — grafeo is embedded)."""
        return {"success": True, "message": "Grafeo is embedded, always available"}

    def stop_graph_db(self) -> dict[str, Any]:
        """Stop graph database (no-op — grafeo is embedded)."""
        return {"success": True, "message": "Grafeo is embedded, no container to stop"}

    def clear_graph(self) -> dict[str, Any]:
        """Clear all graph data."""
        self._ensure_connected()
        assert self._graph_manager is not None
        try:
            self._graph_manager.clear_graph()
            return {"success": True, "message": "Graph layer cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def tag_graph_steps(self, repo_name: str) -> dict[str, Any]:
        """Tag the graph's untagged nodes and edges with the extraction step that wrote them, by rule (no LLM)."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return extraction.tag_steps(self._graph_manager, repo_name)

    def later_extraction_steps(self, step: str) -> list[str]:
        """The enabled extraction steps after ``step`` (they may read what it writes); ``step`` itself may be disabled."""
        self._ensure_connected()
        assert self._engine is not None
        configs = sorted(config.get_extraction_configs(self._engine), key=lambda c: c.sequence)
        current = next((c.sequence for c in configs if c.node_type == step), None)
        return [c.node_type for c in configs if current is not None and c.sequence > current and c.enabled]

    def clear_model(self) -> dict[str, Any]:
        """Clear all ArchiMate model data."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        try:
            self._archimate_manager.clear_model()
            return {"success": True, "message": "ArchiMate model cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_graph_for_repo(self, repo_name: str) -> dict[str, Any]:
        """Clear graph data for a specific repository only."""
        self._ensure_connected()
        assert self._graph_manager is not None
        try:
            deleted = self._graph_manager.clear_graph_for_repo(repo_name)
            return {"success": True, "deleted": deleted, "repository": repo_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def has_extraction(self, repo_name: str) -> bool:
        """Check if extraction data exists for a repository."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return self._graph_manager.has_extraction(repo_name)

    def is_extraction_current(self, repo_name: str) -> bool:
        """Check if extraction data is current (fingerprint matches).

        Compares stored fingerprint against current extraction configs
        and repo commit hash. Returns False if re-extraction is needed.
        """
        self._ensure_connected()
        assert self._graph_manager is not None
        assert self._engine is not None

        stored_fp = self._graph_manager.get_extraction_fingerprint(repo_name)
        if not stored_fp:
            return False

        current_fp = extraction.compute_extraction_fingerprint(self._engine, repo_name)
        return stored_fp == current_fp

    # =========================================================================
    # ORCHESTRATION (pipeline operations)
    # =========================================================================

    def _get_run_logger(self) -> RunLoggerProtocol | None:
        """Get a RunLogger for the currently active run, if one exists."""
        if self._engine is None:
            return None
        try:
            row = self._engine.execute("SELECT run_id FROM runs WHERE is_active = TRUE").fetchone()
            if row:
                return cast(RunLoggerProtocol, RunLogger(run_id=row[0]))
        except Exception as e:
            logger.warning("Failed to get run logger: %s", e)
        return None

    def run_extraction(
        self,
        repo_name: str | None = None,
        verbose: bool = False,
        no_llm: bool = False,
        progress: ProgressReporter | None = None,
        phases: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Run extraction pipeline.

        Args:
            repo_name: Specific repo to extract, or None for all
            verbose: Print progress to stdout
            no_llm: Skip LLM-based extraction steps
            progress: Optional progress reporter for tracking
            phases: List of phases to run (classify, parse), or None for all

        Returns:
            Dict with extraction results
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None

        llm_query_fn = None if no_llm else self._get_llm_query_fn()
        run_logger = self._get_run_logger()

        return extraction.run_extraction(
            engine=self._engine,
            graph_manager=self._graph_manager,
            llm_query_fn=llm_query_fn,
            repo_name=repo_name,
            verbose=verbose,
            run_logger=run_logger,
            progress=progress,
            phases=phases,
        )

    def run_extraction_iter(
        self,
        repo_name: str | None = None,
        verbose: bool = False,
        no_llm: bool = False,
    ) -> Iterator[ProgressUpdate]:
        """
        Run extraction pipeline as a generator, yielding progress updates.

        The studio's run manager iterates it and streams each update to the browser.

        Args:
            repo_name: Specific repo to extract, or None for all
            verbose: Print progress to stdout
            no_llm: Skip LLM-based extraction steps

        Yields:
            ProgressUpdate objects for each step in the pipeline

        Example:
            for update in session.run_extraction_iter():
                print(update)

            # Get final result from last update
            final_stats = update.stats
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None

        llm_query_fn = None if no_llm else self._get_llm_query_fn()

        yield from extraction.run_extraction_iter(
            engine=self._engine,
            graph_manager=self._graph_manager,
            llm_query_fn=llm_query_fn,
            repo_name=repo_name,
            verbose=verbose,
        )

    def run_derivation(
        self,
        verbose: bool = False,
        phases: list[str] | None = None,
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        """Run derivation pipeline.

        Args:
            verbose: Print progress to stdout
            phases: List of phases to run ("prep", "generate", "refine").
                    Default: all phases.
            progress: Optional progress reporter for visual feedback

        Returns:
            Dict with success, stats, errors, and phase results
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        # The prep phase (graph metrics) makes no LLM call
        llm_query_fn = self._get_llm_query_fn() if derivation.needs_llm(phases) else None
        if llm_query_fn is None and derivation.needs_llm(phases):
            return {
                "success": False,
                "errors": [self._llm_not_configured()],
                "stats": {},
            }

        run_logger = self._get_run_logger()

        return derivation.run_derivation(
            engine=self._engine,
            graph_manager=self._graph_manager,
            archimate_manager=self._archimate_manager,
            llm_query_fn=llm_query_fn,
            verbose=verbose,
            phases=phases,
            run_logger=run_logger,
            progress=progress,
        )

    def run_derivation_iter(
        self,
        verbose: bool = False,
        phases: list[str] | None = None,
        on_candidates: Callable[[str, list[str]], None] | None = None,
    ) -> Iterator[ProgressUpdate]:
        """
        Run derivation pipeline as a generator, yielding progress updates.

        The studio's run manager iterates it and streams each update to the browser.

        Args:
            verbose: Print progress to stdout
            phases: List of phases to run ("prep", "generate", "refine")
            on_candidates: Called with (step, candidate node ids) when an element step has chosen
                its candidates, before its LLM calls (the studio pulses them)

        Yields:
            ProgressUpdate objects for each step in the pipeline
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        llm_query_fn = self._get_llm_query_fn() if derivation.needs_llm(phases) else None
        if llm_query_fn is None and derivation.needs_llm(phases):
            yield ProgressUpdate(
                phase="derivation",
                status="error",
                message=self._llm_not_configured(),
            )
            return

        yield from derivation.run_derivation_iter(
            engine=self._engine,
            graph_manager=self._graph_manager,
            archimate_manager=self._archimate_manager,
            llm_query_fn=llm_query_fn,
            verbose=verbose,
            phases=phases,
            on_candidates=on_candidates,
        )

    def get_derivation_step_count(self, enabled_only: bool = True) -> int:
        """Get total number of derivation steps for progress tracking.

        Args:
            enabled_only: Only count enabled derivation steps

        Returns:
            Total number of steps (prep + generate phases)
        """
        self._ensure_connected()
        assert self._engine is not None

        prep_configs = config.get_derivation_configs(self._engine, enabled_only=enabled_only, phase="prep")
        gen_configs = config.get_derivation_configs(self._engine, enabled_only=enabled_only, phase="generate")
        return len(prep_configs) + len(gen_configs)

    def run_pipeline(
        self,
        repo_name: str | None = None,
        verbose: bool = False,
        progress: ProgressReporter | None = None,
        no_llm: bool = False,
    ) -> dict[str, Any]:
        """Run full pipeline (extraction → derivation with all phases).

        ``no_llm``: no LLM call at all; extraction runs its structural steps and derivation its prep phase.
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        if no_llm:
            return pipeline.run_full_pipeline(
                engine=self._engine,
                graph_manager=self._graph_manager,
                archimate_manager=self._archimate_manager,
                llm_query_fn=None,
                repo_name=repo_name,
                verbose=verbose,
                progress=progress,
                derivation_phases=list(derivation.STRUCTURAL_PHASES),
            )

        llm_query_fn = self._get_llm_query_fn()
        if llm_query_fn is None:

            def noop_llm(prompt: str, schema: dict) -> None:
                return None

            llm_query_fn = noop_llm

        return pipeline.run_full_pipeline(
            engine=self._engine,
            graph_manager=self._graph_manager,
            archimate_manager=self._archimate_manager,
            llm_query_fn=llm_query_fn,
            repo_name=repo_name,
            verbose=verbose,
            progress=progress,
        )

    # =========================================================================
    # EXPORT
    # =========================================================================

    def export_model(
        self,
        output_path: str | None = None,
        model_name: str = "Deriva Model",
        confined: bool = False,
    ) -> dict[str, Any]:
        """Export ArchiMate model to XML file (default: workspace/output/model.xml in the Deriva home folder).

        Only exports enabled elements and their relationships.
        Disabled elements (from refine phase) are excluded. With ``confined`` (the studio), a
        relative path is read from the home folder and the file must land in workspace/output.
        """
        output_path = output_path or str(workspace() / "output" / "model.xml")
        if confined:
            target = Path(output_path) if Path(output_path).is_absolute() else home() / output_path
            if not target.resolve().is_relative_to((workspace() / "output").resolve()):
                raise ValueError(f"The studio exports into {workspace() / 'output'} only: {output_path}")
            output_path = str(target.resolve())
        self._ensure_connected()
        assert self._archimate_manager is not None

        try:
            # Only export enabled elements
            elements = self._archimate_manager.get_elements(enabled_only=True)

            if not elements:
                return {
                    "success": False,
                    "error": "No ArchiMate elements found. Run derivation first.",
                }

            # One file, two levels: the architect elements and their members (detail), with views per level
            # (relationships only between enabled elements)
            leveled = self._leveled_model(elements)
            exporter = ArchiMateXMLExporter()
            exporter.export(
                elements=leveled.elements,
                relationships=leveled.relationships,
                output_path=output_path,
                model_name=model_name,
                properties=leveled.properties,
                views=leveled.views,
                relationship_properties=leveled.relationship_properties,
            )

            return {
                "success": True,
                "output_path": output_path,
                "elements_exported": len(elements),
                "relationships_exported": len(leveled.relationships) - len(leveled.detail.relationships),
                **leveled.summary(),
                "views_exported": len(leveled.views),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # CONFIG (passthrough to config service)
    # =========================================================================

    def list_steps(self, step_type: str, enabled_only: bool = False) -> list[dict]:
        """List pipeline steps of a given type."""
        self._ensure_connected()
        assert self._engine is not None
        return config.list_steps(self._engine, step_type, enabled_only=enabled_only)

    def enable_step(self, step_type: str, name: str) -> bool:
        """Enable a pipeline step."""
        self._ensure_connected()
        assert self._engine is not None
        return config.enable_step(self._engine, step_type, name)

    def disable_step(self, step_type: str, name: str) -> bool:
        """Disable a pipeline step."""
        self._ensure_connected()
        assert self._engine is not None
        return config.disable_step(self._engine, step_type, name)

    @contextmanager
    def only_step(self, step_type: str, name: str) -> Generator[None]:
        """Enable only `name` for the duration of the block, then restore the exact prior state."""
        if step_type == "extraction":
            configs, key = self.get_extraction_configs(), "node_type"
        elif step_type == "derivation":
            configs, key = self.get_derivation_configs(), "element_type"
        else:
            raise ValueError(f"step_type must be 'extraction' or 'derivation', got {step_type!r}")
        names = [c[key] for c in configs if c.get(key)]
        if name not in names:
            raise ValueError(f"Unknown {step_type} step: {name}")
        enabled_before = {c[key] for c in configs if c.get(key) and c.get("enabled")}
        try:
            for n in names:
                if n == name:
                    self.enable_step(step_type, n)
                else:
                    self.disable_step(step_type, n)
            yield
        finally:
            for n in names:
                if n in enabled_before:
                    self.enable_step(step_type, n)
                else:
                    self.disable_step(step_type, n)

    def get_file_types(self) -> list[dict]:
        """Get file type registry."""
        self._ensure_connected()
        assert self._engine is not None
        file_types = config.get_file_types(self._engine)
        result: list[dict] = []
        for ft in file_types:
            if isinstance(ft, HasToDict):
                result.append(ft.to_dict())
            elif hasattr(ft, "__dict__"):
                result.append(vars(ft))
            else:
                result.append({"value": str(ft)})
        return result

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _ensure_connected(self) -> None:
        """Raise if not connected."""
        if not self._connected:
            raise RuntimeError("Session not connected. Call connect() first or use auto_connect=True.")

    def managers(self) -> tuple[Any, GraphManager, ArchimateManager]:
        """The config database engine and the graph and model managers of the connected session (for benchmarking)."""
        self._ensure_connected()
        assert self._engine is not None and self._graph_manager is not None and self._archimate_manager is not None
        return self._engine, self._graph_manager, self._archimate_manager

    # =========================================================================
    # REPOSITORY MANAGEMENT
    # =========================================================================

    def clone_repository(
        self,
        url: str,
        name: str | None = None,
        branch: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Clone a repository (no database is needed, so a session that is not connected clones too)."""
        repos = self._repo_manager or RepoManager(workspace_dir=self._workspace_dir)
        try:
            result = repos.clone_repository(repo_url=url, target_name=name, branch=branch, overwrite=overwrite)
            return {
                "success": True,
                "name": result.name,
                "path": str(result.path),
                "url": result.url,
                "branch": result.branch,
                "last_commit": result.last_commit,
                "size_mb": result.size_mb,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def unregistered_repositories(self) -> list[str]:
        """Git folders in the workspace without a record (a lost record, a checkout put there by hand); no database needed."""
        return (self._repo_manager or RepoManager(workspace_dir=self._workspace_dir)).unregistered()

    def register_repository(self, name: str) -> dict[str, Any]:
        """Record a git folder in the workspace that has no record, so it can be run (no database is needed)."""
        repos = self._repo_manager or RepoManager(workspace_dir=self._workspace_dir)
        try:
            result = repos.register_repository(name)
        except Exception as e:
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "name": result.name,
            "path": str(result.path),
            "url": result.url,
            "branch": result.branch,
            "last_commit": result.last_commit,
            "size_mb": result.size_mb,
        }

    def delete_repository(self, name: str, force: bool = False, with_data: bool = False) -> dict[str, Any]:
        """Delete a repository's clone; ``with_data`` also deletes its graph database (graph and model)."""
        self._ensure_connected()
        assert self._repo_manager is not None
        try:
            self._repo_manager.delete_repository(name, force=force)
        except Exception as e:
            return {"success": False, "error": str(e)}
        # A deleted repository cannot stay the one the session reads
        if name == self.repository:
            self.use_repository(DEFAULT_DATABASE)
        return {"success": True, "name": name, "data_deleted": delete_database(name) if with_data else False}

    def get_repository_info(self, name: str) -> dict[str, Any] | None:
        """Get detailed repository information."""
        self._ensure_connected()
        assert self._repo_manager is not None
        try:
            info = self._repo_manager.get_repository_info(name)
            return info.to_dict() if info else None
        except Exception as e:
            logger.warning("Failed to get repository info for '%s': %s", name, e)
            return None

    @property
    def workspace_dir(self) -> str:
        """Get the repository workspace directory."""
        return self._workspace_dir

    # =========================================================================
    # RUN MANAGEMENT
    # =========================================================================

    def get_runs(self, limit: int = 10) -> list[dict]:
        """Get list of pipeline runs."""
        self._ensure_connected()
        assert self._engine is not None
        rows = self._engine.execute(
            "SELECT run_id, description, is_active, started_at, ended_at FROM runs ORDER BY started_at DESC LIMIT ?",
            [limit],
        ).fetchall()
        return [{"run_id": r[0], "description": r[1], "is_active": r[2], "started_at": str(r[3]) if r[3] else None, "ended_at": str(r[4]) if r[4] else None} for r in rows]

    def get_active_run(self) -> dict | None:
        """Get the currently active run."""
        self._ensure_connected()
        assert self._engine is not None
        row = self._engine.execute("SELECT run_id, description, started_at FROM runs WHERE is_active = TRUE").fetchone()
        return {"run_id": row[0], "description": row[1], "started_at": str(row[2]) if row[2] else None} if row else None

    def create_run(self, description: str) -> dict[str, Any]:
        """Create a new pipeline run."""
        self._ensure_connected()
        assert self._engine is not None
        try:
            self._engine.execute("UPDATE runs SET is_active = FALSE WHERE is_active = TRUE")
            row = self._engine.execute("SELECT COALESCE(MAX(run_id), 0) FROM runs").fetchone()
            max_id = row[0] if row else 0
            new_id = max_id + 1
            self._engine.execute(
                "INSERT INTO runs (run_id, description, is_active, started_at) VALUES (?, ?, TRUE, CURRENT_TIMESTAMP)",
                [new_id, description],
            )
            return {"success": True, "run_id": new_id, "description": description}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # CONFIG (extended)
    # =========================================================================

    def get_extraction_configs(self, enabled_only: bool = False) -> list[dict]:
        """Get extraction configurations."""
        self._ensure_connected()
        assert self._engine is not None
        configs = config.get_extraction_configs(self._engine, enabled_only=enabled_only)
        return [
            {
                "node_type": c.node_type,
                "sequence": c.sequence,
                "enabled": c.enabled,
                "input_sources": c.input_sources,
                "instruction": c.instruction,
                "example": c.example,
                "extraction_method": c.extraction_method,
                "params": c.params,
                "batch_size": c.batch_size,
            }
            for c in configs
        ]

    def get_extraction_step_count(self, repo_name: str | None = None, enabled_only: bool = True) -> int:
        """Get total number of extraction steps for progress tracking.

        Args:
            repo_name: Specific repo to count, or None for all repos
            enabled_only: Only count enabled extraction steps

        Returns:
            Total number of steps (configs * repos)
        """
        self._ensure_connected()
        assert self._engine is not None

        # Count configs
        configs = config.get_extraction_configs(self._engine, enabled_only=enabled_only)

        # Count repos
        if self._repo_manager is None:
            self._repo_manager = RepoManager()
        repos = self._repo_manager.list_repositories(detailed=True)
        if repo_name:
            repos = [r for r in repos if hasattr(r, "name") and r.name == repo_name]

        return len(configs) * len(repos)

    def update_extraction_config(
        self,
        node_type: str,
        *,
        enabled: bool | None = None,
        instruction: str | None = None,
        example: str | None = None,
        input_sources: str | None = None,
    ) -> bool:
        """Update an extraction configuration."""
        self._ensure_connected()
        assert self._engine is not None
        return config.update_extraction_config(
            self._engine,
            node_type,
            enabled=enabled,
            instruction=instruction,
            example=example,
            input_sources=input_sources,
        )

    def save_extraction_config(
        self,
        node_type: str,
        *,
        enabled: bool | None = None,
        instruction: str | None = None,
        example: str | None = None,
        input_sources: str | None = None,
        params: str | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Save extraction config with version tracking (``params`` must be a JSON object)."""
        if params is not None:
            config.validate_params(params)
        self._ensure_connected()
        assert self._engine is not None
        return config.create_extraction_config_version(
            self._engine,
            node_type,
            enabled=enabled,
            instruction=instruction,
            example=example,
            input_sources=input_sources,
            params=params,
            batch_size=batch_size,
        )

    def get_derivation_configs(self, enabled_only: bool = False) -> list[dict]:
        """Get derivation configurations."""
        self._ensure_connected()
        assert self._engine is not None
        configs = config.get_derivation_configs(self._engine, enabled_only=enabled_only)
        return [
            {
                "element_type": c.element_type,
                "sequence": c.sequence,
                "enabled": c.enabled,
                "input_graph_query": c.input_graph_query,
                "instruction": c.instruction,
                "example": c.example,
                "phase": c.phase,
                "llm": c.llm,
                "params": c.params,
                "batch_size": c.batch_size,
            }
            for c in configs
        ]

    def update_derivation_config(
        self,
        element_type: str,
        *,
        enabled: bool | None = None,
        input_graph_query: str | None = None,
        instruction: str | None = None,
        example: str | None = None,
    ) -> bool:
        """Update a derivation configuration."""
        self._ensure_connected()
        assert self._engine is not None
        return config.update_derivation_config(
            self._engine,
            element_type,
            enabled=enabled,
            input_graph_query=input_graph_query,
            instruction=instruction,
            example=example,
        )

    def add_extraction_step(self, node_type: str, sequence: int, extraction_method: str = "structural", params: str | None = None) -> bool:
        """Add a new extraction step (disabled, version 1)."""
        self._ensure_connected()
        assert self._engine is not None
        return config.add_extraction_step(self._engine, node_type, sequence, extraction_method=extraction_method, params=params)

    def add_derivation_step(self, step_name: str, phase: str, sequence: int, params: str | None = None) -> bool:
        """Add a new derivation step (disabled, version 1)."""
        self._ensure_connected()
        assert self._engine is not None
        return config.add_derivation_step(self._engine, step_name, phase, sequence, params=params)

    def save_derivation_config(
        self,
        element_type: str,
        *,
        enabled: bool | None = None,
        input_graph_query: str | None = None,
        instruction: str | None = None,
        example: str | None = None,
        params: str | None = None,
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Save derivation config with version tracking (``params`` must be a JSON object)."""
        if params is not None:
            config.validate_params(params)
        self._ensure_connected()
        assert self._engine is not None
        return config.create_derivation_config_version(
            self._engine,
            element_type,
            enabled=enabled,
            input_graph_query=input_graph_query,
            instruction=instruction,
            example=example,
            params=params,
            batch_size=batch_size,
        )

    def get_config_history(self, step_type: str, name: str) -> list[dict[str, Any]]:
        """Every version of a step, newest first."""
        self._ensure_connected()
        assert self._engine is not None
        return config.get_config_history(self._engine, step_type, name)

    def restore_config_version(self, step_type: str, name: str, version: int) -> dict[str, Any]:
        """Make an earlier version's content the step's new version (see ``config.restore_config_version``)."""
        self._ensure_connected()
        assert self._engine is not None
        return config.restore_config_version(self._engine, step_type, name, version)

    def scan_prompt_texts(self, texts: dict[str, str]) -> dict[str, Any]:
        """Overfit scan of draft texts (terms of the local scanner, when there is one) before a save."""
        return overfit.scan_texts(texts)

    def dry_run_graph_query(self, cypher: str, limit: int = 20) -> dict[str, Any]:
        """Run a candidate query read-only (writes rolled back, no LLM): the row count and the first rows."""
        rows = self.query_graph_read_only(cypher)
        return {"count": len(rows), "rows": [{k: _plain(v) for k, v in row.items()} for row in rows[:limit]]}

    def get_config_versions(self, include_disabled: bool = False) -> dict[str, dict[str, int]]:
        """Get current active versions for all enabled configs (also the disabled ones with ``include_disabled``)."""
        self._ensure_connected()
        assert self._engine is not None
        return config.get_active_config_versions(self._engine, include_disabled=include_disabled)

    def get_setting(self, key: str) -> str | None:
        """Get a system setting value (None when not set)."""
        self._ensure_connected()
        assert self._engine is not None
        return config.get_setting(self._engine, key)

    def set_setting(self, key: str, value: str) -> None:
        """Set a system setting value."""
        self._ensure_connected()
        assert self._engine is not None
        config.set_setting(self._engine, key, value)

    def add_file_type(self, extension: str, file_type: str, subtype: str) -> bool:
        """Add a file type to the registry."""
        self._ensure_connected()
        assert self._engine is not None
        return config.add_file_type(self._engine, extension, file_type, subtype)

    def update_file_type(self, extension: str, file_type: str, subtype: str) -> bool:
        """Update a file type in the registry."""
        self._ensure_connected()
        assert self._engine is not None
        return config.update_file_type(self._engine, extension, file_type, subtype)

    def delete_file_type(self, extension: str) -> bool:
        """Delete a file type from the registry."""
        self._ensure_connected()
        assert self._engine is not None
        return config.delete_file_type(self._engine, extension)

    def get_file_type_stats(self) -> dict[str, int]:
        """Get file type registry statistics."""
        self._ensure_connected()
        assert self._engine is not None
        row = self._engine.execute("SELECT COUNT(DISTINCT file_type) FROM file_type_registry").fetchone()
        types = row[0] if row else 0
        row = self._engine.execute("SELECT COUNT(DISTINCT subtype) FROM file_type_registry").fetchone()
        subtypes = row[0] if row else 0
        row = self._engine.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        total = row[0] if row else 0
        return {"types": types, "subtypes": subtypes, "total": total}

    # =========================================================================
    # LLM MANAGEMENT
    # =========================================================================

    def get_llm_status(self) -> dict[str, Any]:
        """Get LLM configuration status."""
        info = self.llm_info
        return {"configured": True, **info} if info else {"configured": False}

    def toggle_llm_cache(self, enabled: bool) -> dict[str, Any]:
        """Toggle LLM response caching."""
        self._get_llm_query_fn()
        if self._llm_manager:
            self._llm_manager.nocache = not enabled
            return {"success": True, "cache_enabled": enabled}
        return {"success": False, "error": "LLM not configured"}

    def list_model_configs(self, env_path: str | Path | None = None) -> list[dict[str, Any]]:
        """Model configs in .env, keys masked (no database connection needed)."""
        return model_configs.list_models(env_path or model_configs.default_env_path())

    def save_model_config(
        self,
        name: str,
        *,
        provider: str,
        model: str,
        url: str | None = None,
        key: str | None = None,
        key_env: str | None = None,
        sampling: str | None = None,
        reasoning: str | None = None,
        temperature: str | None = None,
        context: str | None = None,
        env_path: str | Path | None = None,
    ) -> None:
        """Add or change a model config in .env; a blank key keeps the stored key."""
        model_configs.set_model(
            env_path or model_configs.default_env_path(),
            name,
            provider=provider,
            model=model,
            url=url,
            key=key,
            key_env=key_env,
            sampling=sampling,
            reasoning=reasoning,
            temperature=temperature,
            context=context,
        )

    def set_default_model(self, name: str, env_path: str | Path | None = None) -> None:
        """Make a configured model the one Deriva uses (LLM_DEFAULT_MODEL in .env)."""
        model_configs.set_default(env_path or model_configs.default_env_path(), name)

    def check_model_config(self, name: str) -> dict[str, Any]:
        """One small call with a model config: does its key, model id and URL work (see ``model_configs.check_model``)."""
        return model_configs.check_model(name)

    def delete_model_config(self, name: str, env_path: str | Path | None = None) -> None:
        """Remove a model config's keys from .env."""
        model_configs.delete_model(env_path or model_configs.default_env_path(), name)

    def list_benchmark_models(self) -> dict[str, Any]:
        """List available benchmark model configurations.

        Returns:
            Dict mapping model names to their BenchmarkModelConfig.
            Empty dict if no models are configured.
        """
        from deriva.adapters.llm.manager import load_benchmark_models

        return load_benchmark_models()

    # =========================================================================
    # CLASSIFICATION (standalone)
    # =========================================================================

    def run_classification(self, repo_name: str | None = None) -> dict[str, Any]:
        """Run file classification without full extraction."""
        self._ensure_connected()
        assert self._engine is not None
        return pipeline.run_classification(self._engine, repo_name, verbose=False)

    # =========================================================================
    # DATABASE INFO
    # =========================================================================

    def get_database_path(self) -> str:
        """Get the database path."""
        from deriva.adapters.database import DB_PATH

        return str(DB_PATH)

    def execute_sql(self, query: str, params: list | None = None) -> list[tuple]:
        """Execute a SQL query (for config UI)."""
        self._ensure_connected()
        assert self._engine is not None
        if params:
            return self._engine.execute(query, params).fetchall()
        return self._engine.execute(query).fetchall()
