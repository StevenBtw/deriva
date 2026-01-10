"""
PipelineSession - Unified API for CLI and Marimo.

This module provides a single entry point for all pipeline operations,
managing the lifecycle of all managers and exposing both orchestration
methods (run_*) and query methods (get_*) for reactive UI.

Usage (CLI):
    with PipelineSession() as session:
        result = session.run_extraction(repo_name="my-repo")
        session.export_model("output.archimate")

Usage (Marimo):
    session = PipelineSession(auto_connect=True)
    # In reactive cells:
    stats = session.get_graph_stats()
    elements = session.get_archimate_elements()
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, cast

from deriva.common.types import ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import BenchmarkProgressReporter, ProgressReporter

logger = logging.getLogger(__name__)

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter
from deriva.adapters.database import get_connection
from deriva.adapters.graph import GraphManager
from deriva.adapters.neo4j import Neo4jConnection
from deriva.adapters.repository import RepoManager
from deriva.common.logging import RunLogger
from deriva.common.types import HasToDict, RunLoggerProtocol

from . import benchmarking, config, derivation, extraction, pipeline


class PipelineSession:
    """Unified session for CLI and Marimo pipeline operations.

    Manages all manager lifecycles and provides a clean API for:
    - Lifecycle: connect/disconnect, context manager support
    - Queries: get stats, nodes, elements for reactive UI
    - Orchestration: run extraction, derivation (with phases), full pipeline
    - Infrastructure: Neo4j container control, data clearing
    - Export: ArchiMate XML export
    """

    def __init__(
        self,
        db_path: str | None = None,
        auto_connect: bool = False,
        workspace_dir: str | None = None,
    ):
        """Initialize session.

        Args:
            db_path: Path to DuckDB database (default: deriva/adapters/database/sql.db)
            auto_connect: If True, connect immediately (useful for Marimo)
            workspace_dir: Repository workspace directory (default: from env)
        """
        self._db_path = db_path
        self._workspace_dir = workspace_dir or os.getenv("REPOSITORY_WORKSPACE_DIR", "workspace/repositories")

        # Managers (created on connect)
        self._engine: Any | None = None
        self._graph_manager: GraphManager | None = None
        self._archimate_manager: ArchimateManager | None = None
        self._repo_manager: RepoManager | None = None
        self._neo4j_conn: Neo4jConnection | None = None
        self._llm_manager: Any | None = None  # Lazy loaded

        # Test-only mocks (set by tests)
        self._mock_db: Any | None = None
        self._mock_graph: Any | None = None
        self._mock_archimate: Any | None = None
        self._mock_repo: Any | None = None
        self._mock_neo4j: Any | None = None
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

        # Database (get_connection uses DB_PATH from env)
        self._engine = get_connection()

        # Neo4j managers
        self._graph_manager = GraphManager()
        self._graph_manager.connect()

        self._archimate_manager = ArchimateManager()
        self._archimate_manager.connect()

        # Repository manager
        self._repo_manager = RepoManager(workspace_dir=self._workspace_dir)

        # Neo4j connection for container control
        self._neo4j_conn = Neo4jConnection(namespace="Docker")

        self._connected = True

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
        self._neo4j_conn = None
        self._engine: Any | None = None
        self._connected = False

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

    def _get_llm_query_fn(self, no_cache: bool = False) -> Callable[[str, dict], Any] | None:
        """Get LLM query function, lazy loading the manager."""
        if self._llm_manager is None:
            try:
                from deriva.adapters.llm import LLMManager

                self._llm_manager = LLMManager()
            except Exception as e:
                logger.warning("Failed to initialize LLM manager: %s", e)
                return None

        if no_cache:
            self._llm_manager.nocache = True

        def query_fn(
            prompt: str,
            schema: dict,
            temperature: float | None = None,
            max_tokens: int | None = None,
        ) -> Any:
            assert self._llm_manager is not None
            return self._llm_manager.query(
                prompt,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return query_fn

    @property
    def llm_info(self) -> dict[str, str] | None:
        """Get LLM provider info."""
        if self._llm_manager is None:
            self._get_llm_query_fn()
        if self._llm_manager:
            return {
                "provider": str(self._llm_manager.provider),
                "model": str(self._llm_manager.model),
            }
        return None

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

    def get_graph_nodes(self, node_type: str) -> list[dict]:
        """Get nodes of a specific type."""
        self._ensure_connected()
        assert self._graph_manager is not None
        return self._graph_manager.get_nodes_by_type(node_type)

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
                elem_type = getattr(elem, "type", "Unknown")
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
    # INFRASTRUCTURE (Neo4j container control)
    # =========================================================================

    def get_neo4j_status(self) -> dict[str, Any]:
        """Get Neo4j container status."""
        if self._neo4j_conn is None:
            self._neo4j_conn = Neo4jConnection(namespace="Docker")
        return self._neo4j_conn.get_container_status()

    def start_neo4j(self) -> dict[str, Any]:
        """Start Neo4j container."""
        if self._neo4j_conn is None:
            self._neo4j_conn = Neo4jConnection(namespace="Docker")
        return self._neo4j_conn.start_container()

    def stop_neo4j(self) -> dict[str, Any]:
        """Stop Neo4j container."""
        if self._neo4j_conn is None:
            self._neo4j_conn = Neo4jConnection(namespace="Docker")
        return self._neo4j_conn.stop_container()

    def clear_graph(self) -> dict[str, Any]:
        """Clear all graph data."""
        self._ensure_connected()
        assert self._graph_manager is not None
        try:
            self._graph_manager.clear_graph()
            return {"success": True, "message": "Graph layer cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_model(self) -> dict[str, Any]:
        """Clear all ArchiMate model data."""
        self._ensure_connected()
        assert self._archimate_manager is not None
        try:
            self._archimate_manager.clear_model()
            return {"success": True, "message": "ArchiMate model cleared"}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
    ) -> dict[str, Any]:
        """Run extraction pipeline."""
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
        )

    def run_extraction_iter(
        self,
        repo_name: str | None = None,
        verbose: bool = False,
        no_llm: bool = False,
    ) -> Iterator[ProgressUpdate]:
        """
        Run extraction pipeline as a generator, yielding progress updates.

        Designed for use with Marimo's mo.status.progress_bar iterator pattern
        to provide real-time visual feedback during extraction.

        Args:
            repo_name: Specific repo to extract, or None for all
            verbose: Print progress to stdout
            no_llm: Skip LLM-based extraction steps

        Yields:
            ProgressUpdate objects for each step in the pipeline

        Example (Marimo):
            for update in mo.status.progress_bar(
                session.run_extraction_iter(),
                title="Extraction",
                subtitle="Starting...",
            ):
                pass  # Marimo renders between yields

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
            phases: List of phases to run ("enrich", "generate", "refine").
                    Default: all phases.
            progress: Optional progress reporter for visual feedback

        Returns:
            Dict with success, stats, errors, and phase results
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        llm_query_fn = self._get_llm_query_fn()
        if llm_query_fn is None:
            return {
                "success": False,
                "errors": ["LLM not configured. Derivation requires LLM."],
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
    ) -> Iterator[ProgressUpdate]:
        """
        Run derivation pipeline as a generator, yielding progress updates.

        Designed for use with Marimo's mo.status.progress_bar iterator pattern
        to provide real-time visual feedback during derivation.

        Args:
            verbose: Print progress to stdout
            phases: List of phases to run ("enrich", "generate", "refine")

        Yields:
            ProgressUpdate objects for each step in the pipeline
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        llm_query_fn = self._get_llm_query_fn()
        if llm_query_fn is None:
            yield ProgressUpdate(
                phase="derivation",
                status="error",
                message="LLM not configured. Derivation requires LLM.",
            )
            return

        yield from derivation.run_derivation_iter(
            engine=self._engine,
            graph_manager=self._graph_manager,
            archimate_manager=self._archimate_manager,
            llm_query_fn=llm_query_fn,
            verbose=verbose,
            phases=phases,
        )

    def get_derivation_step_count(self, enabled_only: bool = True) -> int:
        """Get total number of derivation steps for progress tracking.

        Args:
            enabled_only: Only count enabled derivation steps

        Returns:
            Total number of steps (enrich + generate phases)
        """
        self._ensure_connected()
        assert self._engine is not None

        enrich_configs = config.get_derivation_configs(self._engine, enabled_only=enabled_only, phase="enrich")
        gen_configs = config.get_derivation_configs(self._engine, enabled_only=enabled_only, phase="generate")
        return len(enrich_configs) + len(gen_configs)

    def run_pipeline(
        self,
        repo_name: str | None = None,
        verbose: bool = False,
        progress: ProgressReporter | None = None,
    ) -> dict[str, Any]:
        """Run full pipeline (extraction → derivation with all phases)."""
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

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
        output_path: str = "workspace/output/model.archimate",
        model_name: str = "Deriva Model",
    ) -> dict[str, Any]:
        """Export ArchiMate model to XML file.

        Only exports enabled elements and their relationships.
        Disabled elements (from refine phase) are excluded.
        """
        self._ensure_connected()
        assert self._archimate_manager is not None

        try:
            # Only export enabled elements
            elements = self._archimate_manager.get_elements(enabled_only=True)
            all_relationships = self._archimate_manager.get_relationships()

            if not elements:
                return {
                    "success": False,
                    "error": "No ArchiMate elements found. Run derivation first.",
                }

            # Filter relationships to only include those between enabled elements
            enabled_ids = {e.identifier for e in elements}
            relationships = [r for r in all_relationships if r.source in enabled_ids and r.target in enabled_ids]

            exporter = ArchiMateXMLExporter()
            exporter.export(
                elements=elements,
                relationships=relationships,
                output_path=output_path,
                model_name=model_name,
            )

            return {
                "success": True,
                "output_path": output_path,
                "elements_exported": len(elements),
                "relationships_exported": len(relationships),
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
        """Clone a repository."""
        self._ensure_connected()
        assert self._repo_manager is not None
        try:
            result = self._repo_manager.clone_repository(repo_url=url, target_name=name, branch=branch, overwrite=overwrite)
            return {"success": True, "name": result.name, "path": str(result.path), "url": result.url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_repository(self, name: str, force: bool = False) -> dict[str, Any]:
        """Delete a repository."""
        self._ensure_connected()
        assert self._repo_manager is not None
        try:
            self._repo_manager.delete_repository(name, force=force)
            return {"success": True, "name": name}
        except Exception as e:
            return {"success": False, "error": str(e)}

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
        input_sources: str | None = None,
    ) -> dict[str, Any]:
        """Save extraction config with version tracking."""
        self._ensure_connected()
        assert self._engine is not None
        return config.create_extraction_config_version(
            self._engine,
            node_type,
            enabled=enabled,
            instruction=instruction,
            input_sources=input_sources,
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

    def save_derivation_config(
        self,
        element_type: str,
        *,
        enabled: bool | None = None,
        input_graph_query: str | None = None,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        """Save derivation config with version tracking."""
        self._ensure_connected()
        assert self._engine is not None
        return config.create_derivation_config_version(
            self._engine,
            element_type,
            enabled=enabled,
            input_graph_query=input_graph_query,
            instruction=instruction,
        )

    def get_config_versions(self) -> dict[str, dict[str, int]]:
        """Get current active versions for all configs."""
        self._ensure_connected()
        assert self._engine is not None
        return config.get_active_config_versions(self._engine)

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

    # =========================================================================
    # BENCHMARKING
    # =========================================================================

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
    ) -> benchmarking.BenchmarkResult:
        """
        Run a full benchmark matrix.

        Args:
            repositories: List of repository names to benchmark
            models: List of model config names (from LLM_BENCH_* env vars)
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

        Returns:
            BenchmarkResult with session details

        Example:
            result = session.run_benchmark(
                repositories=["my-repo"],
                models=["azure-gpt4", "openai-gpt4o"],
                runs=3,
                stages=["extraction", "derivation"],
                nocache_configs=["ApplicationComponent"],  # Test new prompt
            )
        """
        self._ensure_connected()
        assert self._engine is not None
        assert self._graph_manager is not None
        assert self._archimate_manager is not None

        from deriva.services import benchmarking

        bench_config = benchmarking.BenchmarkConfig(
            repositories=repositories,
            models=models,
            runs_per_combination=runs,
            stages=stages or ["classification", "extraction", "derivation"],
            description=description,
            use_cache=use_cache,
            nocache_configs=nocache_configs or [],
            export_models=export_models,
            clear_between_runs=clear_between_runs,
            bench_hash=bench_hash,
        )

        orchestrator = benchmarking.BenchmarkOrchestrator(
            engine=self._engine,
            graph_manager=self._graph_manager,
            archimate_manager=self._archimate_manager,
            config=bench_config,
        )

        return orchestrator.run(verbose=verbose, progress=progress)

    def analyze_benchmark(self, session_id: str) -> benchmarking.BenchmarkAnalyzer:
        """
        Load and analyze a completed benchmark.

        Args:
            session_id: Benchmark session ID to analyze

        Returns:
            BenchmarkAnalyzer instance for computing metrics

        Example:
            analyzer = session.analyze_benchmark("bench_20240115_103000")
            summary = analyzer.compute_full_analysis()
            analyzer.export_summary("analysis.json")
        """
        self._ensure_connected()
        assert self._engine is not None

        return benchmarking.BenchmarkAnalyzer(session_id, self._engine)

    def analyze_config_deviations(self, session_id: str) -> Any:
        """
        Analyze which configs produce deviations across benchmark runs.

        Args:
            session_id: Benchmark session ID to analyze

        Returns:
            ConfigDeviationAnalyzer instance for computing per-config deviation stats

        Example:
            analyzer = session.analyze_config_deviations("bench_20240115_103000")
            report = analyzer.analyze()
            analyzer.export_json("deviations.json")
        """
        self._ensure_connected()
        assert self._engine is not None

        from deriva.services import config_deviation

        return config_deviation.ConfigDeviationAnalyzer(session_id, self._engine)

    def list_benchmarks(self, limit: int = 10) -> list[dict]:
        """
        List recent benchmark sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session dictionaries
        """
        self._ensure_connected()
        assert self._engine is not None

        from deriva.services import benchmarking

        return benchmarking.list_benchmark_sessions(self._engine, limit)
