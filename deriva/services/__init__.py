"""
Services layer for Deriva.

This module provides shared orchestration for both Marimo (visual UI) and CLI (headless).
All pipeline operations should go through PipelineSession rather than directly accessing
managers or modules.

Primary API:
    PipelineSession: Unified session for CLI and Marimo
        - Lifecycle: connect(), disconnect(), context manager
        - Queries: get_graph_stats(), get_archimate_elements(), etc.
        - Orchestration: run_extraction(), run_derivation(), run_pipeline()
        - Infrastructure: start_neo4j(), stop_neo4j(), clear_graph()
        - Export: export_model()

Usage (CLI):
    from deriva.services.session import PipelineSession

    with PipelineSession() as session:
        result = session.run_extraction(repo_name="my-repo")
        session.export_model("output.archimate")

Usage (Marimo):
    from deriva.services.session import PipelineSession

    session = PipelineSession(auto_connect=True)
    stats = session.get_graph_stats()
    elements = session.get_archimate_elements()

Internal services (used by PipelineSession):
    config: Configuration CRUD
    extraction: Extraction orchestration
    derivation: Derivation and validation orchestration
    pipeline: Full pipeline orchestration
    benchmarking: Multi-model benchmarking with OCEL logging and analysis
"""

from __future__ import annotations

from . import config, derivation, extraction, pipeline
from .session import PipelineSession

__all__ = [
    "PipelineSession",
    "config",
    "extraction",
    "derivation",
    "pipeline",
]
