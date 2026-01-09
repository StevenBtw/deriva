"""
Pipeline service for Deriva.

Orchestrates the full pipeline:
Classification → Extraction → Derivation (prep/generate/refine) → Export

Used by both Marimo (visual) and CLI (headless).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.graph import GraphManager
from deriva.adapters.repository import RepoManager
from deriva.modules.extraction import classification
from deriva.services import config, derivation, extraction

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter


def run_full_pipeline(
    engine: Any,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[[str, dict], Any],
    repo_name: str | None = None,
    skip_classification: bool = False,
    skip_extraction: bool = False,
    skip_derivation: bool = False,
    verbose: bool = False,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """
    Run the full Deriva pipeline.

    Args:
        engine: DuckDB connection for config
        graph_manager: Connected GraphManager
        archimate_manager: Connected ArchimateManager
        llm_query_fn: Function to call LLM
        repo_name: Specific repo to process, or None for all
        skip_classification: Skip classification step
        skip_extraction: Skip extraction step
        skip_derivation: Skip derivation step (includes all phases)
        verbose: Print progress
        progress: Optional progress reporter for visual feedback

    Returns:
        Dict with success, stats, errors for each stage
    """
    results: dict[str, Any] = {
        "classification": None,
        "extraction": None,
        "derivation": None,
    }
    overall_errors: list[str] = []

    # Stage 1: Classification
    if not skip_classification:
        if verbose:
            print("\n=== Stage 1: Classification ===")

        classification_result = run_classification(engine, repo_name, verbose)
        results["classification"] = classification_result

        if not classification_result["success"]:
            overall_errors.extend(classification_result.get("errors", []))

    # Stage 2: Extraction
    if not skip_extraction:
        if verbose:
            print("\n=== Stage 2: Extraction ===")

        extraction_result = extraction.run_extraction(
            engine=engine,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
            repo_name=repo_name,
            verbose=verbose,
            progress=progress,
        )
        results["extraction"] = extraction_result

        if not extraction_result["success"]:
            overall_errors.extend(extraction_result.get("errors", []))

    # Stage 3: Derivation
    if not skip_derivation:
        if verbose:
            print("\n=== Stage 3: Derivation ===")

        derivation_result = derivation.run_derivation(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            verbose=verbose,
            progress=progress,
        )
        results["derivation"] = derivation_result

        if not derivation_result["success"]:
            overall_errors.extend(derivation_result.get("errors", []))

    return {
        "success": len(overall_errors) == 0,
        "results": results,
        "errors": overall_errors,
    }


def run_classification(
    engine: Any,
    repo_name: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Run the classification stage.

    Args:
        engine: DuckDB connection for file type registry
        repo_name: Specific repo to classify, or None for all
        verbose: Print progress

    Returns:
        Dict with classification results
    """
    stats = {
        "repos_processed": 0,
        "files_classified": 0,
        "files_undefined": 0,
    }
    errors = []
    all_classified = []
    all_undefined = []

    # Get repositories
    repo_mgr = RepoManager()
    repos = repo_mgr.list_repositories(detailed=True)

    if repo_name:
        repos = [r for r in repos if hasattr(r, "name") and r.name == repo_name]

    if not repos:
        return {"success": False, "stats": stats, "errors": ["No repositories found"]}

    # Get file type registry
    file_types = config.get_file_types(engine)
    registry_list = [{"extension": ft.extension, "file_type": ft.file_type, "subtype": ft.subtype} for ft in file_types]

    # Process each repository
    for repo in repos:
        # Skip if not a proper RepositoryInfo object
        if not hasattr(repo, "name") or not hasattr(repo, "path"):
            continue
        if verbose:
            print(f"  Classifying: {repo.name}")

        repo_path = Path(str(repo.path))
        stats["repos_processed"] += 1

        # Get all files
        file_paths = []
        for f in repo_path.rglob("*"):
            if f.is_file() and not any(x in str(f) for x in [".git", "__pycache__", ".pyc"]):
                file_paths.append(str(f.relative_to(repo_path)))

        # Classify files
        result = classification.classify_files(file_paths, registry_list)

        stats["files_classified"] += len(result["classified"])
        stats["files_undefined"] += len(result["undefined"])

        all_classified.extend(result["classified"])
        all_undefined.extend(result["undefined"])

        if result.get("errors"):
            errors.extend(result["errors"])

    # Get unique undefined extensions
    undefined_extensions = classification.get_undefined_extensions(all_undefined)

    return {
        "success": True,
        "stats": stats,
        "errors": errors,
        "classified": all_classified,
        "undefined": all_undefined,
        "undefined_extensions": undefined_extensions,
    }


def get_pipeline_status(engine: Any) -> dict[str, Any]:
    """
    Get current pipeline configuration status.

    Args:
        engine: DuckDB connection

    Returns:
        Dict with status for each stage
    """
    extraction_configs = config.get_extraction_configs(engine)
    derivation_configs = config.get_derivation_configs(engine)

    extraction_enabled = [c for c in extraction_configs if c.enabled]
    derivation_enabled = [c for c in derivation_configs if c.enabled]

    # Group derivation by phase
    prep_enabled = [c for c in derivation_enabled if c.phase == "prep"]
    generate_enabled = [c for c in derivation_enabled if c.phase == "generate"]
    refine_enabled = [c for c in derivation_enabled if c.phase == "refine"]

    return {
        "extraction": {
            "total": len(extraction_configs),
            "enabled": len(extraction_enabled),
            "steps": [c.node_type for c in extraction_enabled],
        },
        "derivation": {
            "total": len(derivation_configs),
            "enabled": len(derivation_enabled),
            "steps": [c.step_name for c in derivation_enabled],
            "by_phase": {
                "prep": len(prep_enabled),
                "generate": len(generate_enabled),
                "refine": len(refine_enabled),
            },
        },
    }
