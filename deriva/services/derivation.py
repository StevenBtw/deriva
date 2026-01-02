"""
Derivation service for Deriva.

Orchestrates the derivation pipeline with phases:
1. prep: Pre-derivation graph analysis (pagerank, etc.)
2. generate: LLM-based element and relationship derivation

Used by both Marimo (visual) and CLI (headless).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate import ArchimateManager
from deriva.common.types import PipelineResult

if TYPE_CHECKING:
    from deriva.common.logging import RunLogger
from deriva.adapters.archimate.models import RELATIONSHIP_TYPES, Relationship
from deriva.adapters.graph import GraphManager
from deriva.modules.derivation import (
    RELATIONSHIP_SCHEMA,
    build_relationship_prompt,
    parse_relationship_response,
)
from deriva.modules.derivation.generate import generate_element
from deriva.modules.derivation.prep_pagerank import run_pagerank
from deriva.services import config

logger = logging.getLogger(__name__)

# Valid relationship types in PascalCase for normalization
_VALID_RELATIONSHIP_TYPES = set(RELATIONSHIP_TYPES.keys())


def _normalize_identifier(identifier: str) -> str:
    """Normalize identifier for fuzzy matching (lowercase, replace separators)."""
    return identifier.lower().replace("-", "_").replace(" ", "_")


def _normalize_relationship_type(rel_type: str) -> str:
    """Normalize relationship type to PascalCase."""
    if rel_type in _VALID_RELATIONSHIP_TYPES:
        return rel_type
    rel_lower = rel_type.lower()
    for valid_type in _VALID_RELATIONSHIP_TYPES:
        if valid_type.lower() == rel_lower:
            return valid_type
    return rel_type


# =============================================================================
# PREP STEP REGISTRY
# =============================================================================

PREP_FUNCTIONS = {
    "pagerank": run_pagerank,
}


def _run_prep_step(
    cfg: config.DerivationConfig,
    graph_manager: GraphManager,
) -> PipelineResult:
    """Run a single prep step."""
    step_name = cfg.step_name

    if step_name not in PREP_FUNCTIONS:
        return {"success": False, "errors": [f"Unknown prep step: {step_name}"]}

    # Parse params from config
    params = {}
    if cfg.params:
        try:
            params = json.loads(cfg.params)
        except json.JSONDecodeError:
            pass

    # Run the prep function
    prep_fn = PREP_FUNCTIONS[step_name]
    return prep_fn(graph_manager, params)


# =============================================================================
# DERIVATION FUNCTIONS
# =============================================================================


def run_derivation(
    engine: Any,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[[str, dict], Any] | None = None,
    enabled_only: bool = True,
    verbose: bool = False,
    phases: list[str] | None = None,
    run_logger: RunLogger | None = None,
) -> dict[str, Any]:
    """
    Run the derivation pipeline.

    Args:
        engine: DuckDB connection for config
        graph_manager: Connected GraphManager for querying source nodes
        archimate_manager: Connected ArchimateManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        enabled_only: Only run enabled derivation steps
        verbose: Print progress to stdout
        phases: List of phases to run ("prep", "generate").
        run_logger: Optional RunLogger for structured logging

    Returns:
        Dict with success, stats, errors
    """
    if phases is None:
        phases = ["prep", "generate"]

    stats = {
        "elements_created": 0,
        "relationships_created": 0,
        "steps_completed": 0,
        "steps_skipped": 0,
    }
    errors: list[str] = []
    all_created_elements: list[dict] = []

    # Start phase logging
    if run_logger:
        run_logger.phase_start("derivation", "Starting derivation pipeline")

    # Run prep phase
    if "prep" in phases:
        prep_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="prep")
        if prep_configs and verbose:
            print(f"Running {len(prep_configs)} prep steps...")

        for cfg in prep_configs:
            if verbose:
                print(f"  Prep: {cfg.step_name}")

            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(cfg.step_name, f"Running prep step: {cfg.step_name}")

            result = _run_prep_step(cfg, graph_manager)
            stats["steps_completed"] += 1

            if result.get("errors"):
                errors.extend(result["errors"])
                if step_ctx:
                    step_ctx.error("; ".join(result["errors"]))
            elif step_ctx:
                step_ctx.complete()

            if verbose and result.get("stats"):
                prep_stats = result["stats"]
                if "top_nodes" in prep_stats:
                    print(f"    Top nodes: {[n['id'].split('_')[-1] for n in prep_stats['top_nodes'][:3]]}")

    # Run generate phase
    if "generate" in phases:
        gen_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="generate")

        if verbose:
            if gen_configs:
                print(f"Running {len(gen_configs)} generate steps...")
            else:
                print("No generate phase configs enabled.")

        for cfg in gen_configs:
            if verbose:
                print(f"  Generate: {cfg.step_name}")

            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(cfg.step_name, f"Generating {cfg.element_type} elements")

            try:
                step_result = generate_element(
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=llm_query_fn,
                    element_type=cfg.element_type,
                    query=cfg.input_graph_query or "",
                    instruction=cfg.instruction or "",
                    example=cfg.example or "",
                )

                elements_created = step_result.get("elements_created", 0)
                stats["elements_created"] += elements_created
                stats["steps_completed"] += 1

                if step_ctx:
                    step_ctx.items_created = elements_created
                    step_ctx.complete()

                if step_result.get("created_elements"):
                    all_created_elements.extend(step_result["created_elements"])

                if step_result.get("errors"):
                    errors.extend(step_result["errors"])

            except Exception as e:
                errors.append(f"Error in {cfg.step_name}: {str(e)}")
                stats["steps_skipped"] += 1
                if step_ctx:
                    step_ctx.error(str(e))

        # Derive relationships between created elements
        if all_created_elements and len(all_created_elements) > 1:
            if verbose:
                print(f"  Deriving relationships between {len(all_created_elements)} elements...")

            rel_result = _derive_relationships(
                elements=all_created_elements,
                archimate_manager=archimate_manager,
                llm_query_fn=llm_query_fn,
            )

            stats["relationships_created"] = rel_result.get("relationships_created", 0)
            if rel_result.get("errors"):
                errors.extend(rel_result["errors"])

    # Complete phase logging
    if run_logger:
        if errors:
            run_logger.phase_error("derivation", "; ".join(errors[:3]), "Derivation completed with errors")
        else:
            run_logger.phase_complete("derivation", "Derivation completed successfully", stats=stats)

    return {
        "success": len(errors) == 0,
        "stats": stats,
        "errors": errors,
        "created_elements": all_created_elements,
    }


def _derive_relationships(
    elements: list[dict],
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable | None,
) -> dict[str, Any]:
    """Derive relationships between elements using LLM."""
    relationships_created = 0
    errors = []

    prompt = build_relationship_prompt(elements)

    if llm_query_fn is None:
        return {"relationships_created": 0, "errors": ["LLM not configured"]}

    try:
        response = llm_query_fn(prompt, RELATIONSHIP_SCHEMA)
        response_content = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        return {"relationships_created": 0, "errors": [f"LLM error: {e}"]}

    parse_result = parse_relationship_response(response_content)

    if not parse_result["success"]:
        return {"relationships_created": 0, "errors": parse_result.get("errors", [])}

    element_ids = {e["identifier"] for e in elements}
    # Build normalized lookup for fuzzy matching
    normalized_lookup = {_normalize_identifier(eid): eid for eid in element_ids}

    def resolve_identifier(ref: str) -> str | None:
        """Resolve identifier with fuzzy matching fallback."""
        if ref in element_ids:
            return ref
        # Try normalized matching
        normalized = _normalize_identifier(ref)
        return normalized_lookup.get(normalized)

    for rel_data in parse_result["data"]:
        source_ref = rel_data.get("source")
        target_ref = rel_data.get("target")
        rel_type = _normalize_relationship_type(rel_data.get("relationship_type", "Association"))

        source = resolve_identifier(source_ref)
        target = resolve_identifier(target_ref)

        if source is None:
            errors.append(f"Relationship source not found: {source_ref}")
            continue
        if target is None:
            errors.append(f"Relationship target not found: {target_ref}")
            continue

        relationship = Relationship(
            source=source,
            target=target,
            relationship_type=rel_type,
            name=rel_data.get("name"),
            properties={"confidence": rel_data.get("confidence", 0.5)},
        )

        try:
            archimate_manager.add_relationship(relationship)
            relationships_created += 1
        except Exception as e:
            errors.append(f"Failed to persist relationship: {e}")

    return {
        "relationships_created": relationships_created,
        "errors": errors,
    }
