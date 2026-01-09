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
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph import GraphManager
from deriva.modules.derivation import enrich
from deriva.services import config

# Element generation module registry
# Maps element_type to module with generate() function
_ELEMENT_MODULES: dict[str, Any] = {}


def _load_element_module(element_type: str) -> Any:
    """Lazily load element generation module."""
    if element_type in _ELEMENT_MODULES:
        return _ELEMENT_MODULES[element_type]

    module = None
    # Business Layer
    if element_type == "BusinessObject":
        from deriva.modules.derivation import business_object as module
    elif element_type == "BusinessProcess":
        from deriva.modules.derivation import business_process as module
    elif element_type == "BusinessActor":
        from deriva.modules.derivation import business_actor as module
    elif element_type == "BusinessEvent":
        from deriva.modules.derivation import business_event as module
    elif element_type == "BusinessFunction":
        from deriva.modules.derivation import business_function as module
    # Application Layer
    elif element_type == "ApplicationComponent":
        from deriva.modules.derivation import application_component as module
    elif element_type == "ApplicationService":
        from deriva.modules.derivation import application_service as module
    elif element_type == "ApplicationInterface":
        from deriva.modules.derivation import application_interface as module
    elif element_type == "DataObject":
        from deriva.modules.derivation import data_object as module
    # Technology Layer
    elif element_type == "TechnologyService":
        from deriva.modules.derivation import technology_service as module
    elif element_type == "Node":
        from deriva.modules.derivation import node as module
    elif element_type == "Device":
        from deriva.modules.derivation import device as module
    elif element_type == "SystemSoftware":
        from deriva.modules.derivation import system_software as module

    _ELEMENT_MODULES[element_type] = module
    return module


def generate_element(
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[..., Any],
    element_type: str,
    engine: Any,
    query: str,
    instruction: str,
    example: str,
    max_candidates: int,
    batch_size: int,
    existing_elements: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Generate ArchiMate elements of a specific type (and their relationships).

    Routes to the appropriate module based on element_type.
    All configuration parameters are required - no defaults, no fallbacks.

    Each module now handles both element generation AND relationship derivation
    in a unified flow, creating relationships to/from existing elements.

    Args:
        graph_manager: Connected GraphManager for Cypher queries
        archimate_manager: Connected ArchimateManager for element creation
        llm_query_fn: Function to call LLM (prompt, schema, **kwargs) -> response
        element_type: ArchiMate element type (e.g., 'ApplicationService')
        engine: DuckDB connection for patterns (enrichments read from Neo4j)
        query: Cypher query to get candidate nodes
        instruction: LLM instruction prompt
        example: Example output for LLM
        max_candidates: Maximum candidates to send to LLM
        batch_size: Batch size for LLM processing
        existing_elements: Elements from previous derivation steps (for relationships)
        temperature: Optional LLM temperature override
        max_tokens: Optional LLM max_tokens override

    Returns:
        Dict with success, elements_created, relationships_created, created_elements, errors
    """
    module = _load_element_module(element_type)

    if module is None:
        return {
            "success": False,
            "elements_created": 0,
            "relationships_created": 0,
            "errors": [f"No generation module for element type: {element_type}"],
        }

    try:
        result = module.generate(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            engine=engine,
            llm_query_fn=llm_query_fn,
            query=query,
            instruction=instruction,
            example=example,
            max_candidates=max_candidates,
            batch_size=batch_size,
            existing_elements=existing_elements or [],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "success": result.success,
            "elements_created": result.elements_created,
            "relationships_created": result.relationships_created,
            "created_elements": result.created_elements,
            "created_relationships": result.created_relationships,
            "errors": result.errors,
        }
    except Exception as e:
        return {
            "success": False,
            "elements_created": 0,
            "relationships_created": 0,
            "errors": [f"Generation failed for {element_type}: {e}"],
        }


logger = logging.getLogger(__name__)


# =============================================================================
# PREP STEP REGISTRY
# =============================================================================

# Enrichment algorithm registry - maps step_name to algorithm key for enrich module
ENRICHMENT_ALGORITHMS: dict[str, str] = {
    "pagerank": "pagerank",
    "louvain_communities": "louvain",
    "k_core_filter": "kcore",
    "articulation_points": "articulation_points",
    "degree_centrality": "degree",
}


def _get_graph_edges(graph_manager: GraphManager) -> list[dict[str, str]]:
    """Get all edges from the graph for enrichment algorithms.

    Returns edges in the format expected by enrich module:
    [{"source": "node_id_1", "target": "node_id_2"}, ...]

    Note: Labels in Neo4j are namespaced (e.g., "Graph:Directory", "Graph:File").
    We match any node with a label starting with "Graph:" to get all graph nodes.
    """
    query = """
        MATCH (a)-[r]->(b)
        WHERE any(label IN labels(a) WHERE label STARTS WITH 'Graph:')
          AND any(label IN labels(b) WHERE label STARTS WITH 'Graph:')
          AND a.active = true AND b.active = true
        RETURN a.id as source, b.id as target
    """
    result = graph_manager.query(query)
    return [{"source": row["source"], "target": row["target"]} for row in result]


def _run_prep_step(
    cfg: config.DerivationConfig,
    graph_manager: GraphManager,
) -> PipelineResult:
    """Run a single prep step (graph enrichment algorithm).

    Prep steps compute graph metrics (PageRank, Louvain, k-core, etc.)
    and store them as properties on Neo4j nodes.
    """
    step_name = cfg.step_name
    logger = logging.getLogger(__name__)

    # Check if this is a known enrichment algorithm
    if step_name not in ENRICHMENT_ALGORITHMS:
        return {"success": False, "errors": [f"Unknown prep step: {step_name}"]}

    algorithm = ENRICHMENT_ALGORITHMS[step_name]

    # Parse params from config
    params: dict[str, dict[str, Any]] = {}
    if cfg.params:
        try:
            step_params = json.loads(cfg.params)
            # Remove non-algorithm params like "description"
            step_params = {k: v for k, v in step_params.items() if k not in ["description"]}
            if step_params:
                params[algorithm] = step_params
        except json.JSONDecodeError:
            pass

    logger.info(f"Running enrichment: {step_name} (algorithm: {algorithm})")

    try:
        # Get graph edges
        edges = _get_graph_edges(graph_manager)

        if not edges:
            logger.warning(f"No edges found for enrichment step: {step_name}")
            return {"success": True, "stats": {"nodes_updated": 0}}

        # Run the enrichment algorithm
        enrichments = enrich.enrich_graph(
            edges=edges,
            algorithms=[algorithm],
            params=params,
        )

        if not enrichments:
            return {"success": True, "stats": {"nodes_updated": 0}}

        # Write enrichments to Neo4j
        nodes_updated = graph_manager.batch_update_properties(enrichments)

        logger.info(f"Enrichment {step_name} complete: {nodes_updated} nodes updated")

        return {
            "success": True,
            "stats": {
                "nodes_updated": nodes_updated,
                "algorithm": algorithm,
            },
        }

    except Exception as e:
        logger.error(f"Enrichment {step_name} failed: {e}")
        return {"success": False, "errors": [f"Enrichment failed: {e}"]}


# =============================================================================
# DERIVATION FUNCTIONS
# =============================================================================


def run_derivation(
    engine: Any,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[..., Any] | None = None,
    enabled_only: bool = True,
    verbose: bool = False,
    phases: list[str] | None = None,
    run_logger: RunLoggerProtocol | None = None,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """
    Run the derivation pipeline.

    Each element module now handles both element generation AND relationship
    derivation in a unified flow. Relationships are created to/from existing
    elements as each element type is processed in sequence.

    Args:
        engine: DuckDB connection for config
        graph_manager: Connected GraphManager for querying source nodes
        archimate_manager: Connected ArchimateManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        enabled_only: Only run enabled derivation steps
        verbose: Print progress to stdout
        phases: List of phases to run ("prep", "generate").
        run_logger: Optional RunLogger for structured logging
        progress: Optional progress reporter for visual feedback

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

    # Calculate total steps for progress
    prep_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="prep")
    gen_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="generate")
    total_steps = 0
    if "prep" in phases:
        total_steps += len(prep_configs)
    if "generate" in phases:
        total_steps += len(gen_configs)

    # Start progress tracking
    if progress:
        progress.start_phase("derivation", total_steps)

    # Run prep phase
    if "prep" in phases:
        if prep_configs and verbose:
            print(f"Running {len(prep_configs)} prep steps...")

        for cfg in prep_configs:
            if verbose:
                print(f"  Prep: {cfg.step_name}")

            # Start progress tracking for this step
            if progress:
                progress.start_step(cfg.step_name)

            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(cfg.step_name, f"Running prep step: {cfg.step_name}")

            result = _run_prep_step(cfg, graph_manager)
            stats["steps_completed"] += 1

            if result.get("errors"):
                errors.extend(result["errors"])
                if step_ctx:
                    step_ctx.error("; ".join(result["errors"]))
                if progress:
                    progress.log("; ".join(result["errors"]), level="error")
            elif step_ctx:
                step_ctx.complete()

            # Complete progress tracking for this step
            if progress:
                progress.complete_step()

            if verbose and result.get("stats"):
                prep_stats = result["stats"]
                if "top_nodes" in prep_stats:
                    top_names = [n["id"].split("_")[-1] for n in prep_stats["top_nodes"][:3]]
                    print(f"    Top nodes: {top_names}")

    # Run generate phase
    if "generate" in phases:
        if verbose:
            if gen_configs:
                print(f"Running {len(gen_configs)} generate steps...")
            else:
                print("No generate phase configs enabled.")

        for cfg in gen_configs:
            if verbose:
                print(f"  Generate: {cfg.step_name}")

            # Start progress tracking for this step
            if progress:
                progress.start_step(cfg.step_name)

            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(cfg.step_name, f"Generating {cfg.element_type} elements")

            # Wrap llm_query_fn with per-step temperature/max_tokens overrides
            def step_llm_query_fn(prompt: str, schema: dict) -> Any:
                if llm_query_fn is None:
                    raise ValueError("llm_query_fn is required for generate phase")
                return llm_query_fn(
                    prompt,
                    schema,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )

            # Validate required config parameters
            missing_params = []
            if not cfg.input_graph_query:
                missing_params.append("input_graph_query")
            if not cfg.instruction:
                missing_params.append("instruction")
            if not cfg.example:
                missing_params.append("example")
            if cfg.max_candidates is None:
                missing_params.append("max_candidates")
            if cfg.batch_size is None:
                missing_params.append("batch_size")

            if missing_params:
                error_msg = f"Missing required config for {cfg.step_name}: {', '.join(missing_params)}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1
                if step_ctx:
                    step_ctx.error(error_msg)
                continue

            # Type assertions for validated config (helps type checker)
            assert cfg.input_graph_query is not None
            assert cfg.instruction is not None
            assert cfg.example is not None
            assert cfg.max_candidates is not None
            assert cfg.batch_size is not None

            try:
                step_result = generate_element(
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=step_llm_query_fn,
                    element_type=cfg.element_type,
                    engine=engine,
                    query=cfg.input_graph_query,
                    instruction=cfg.instruction,
                    example=cfg.example,
                    max_candidates=cfg.max_candidates,
                    batch_size=cfg.batch_size,
                    existing_elements=all_created_elements,  # Pass accumulated elements
                )

                elements_created = step_result.get("elements_created", 0)
                relationships_created = step_result.get("relationships_created", 0)
                stats["elements_created"] += elements_created
                stats["relationships_created"] += relationships_created
                stats["steps_completed"] += 1

                step_created_elements = step_result.get("created_elements", [])

                if step_created_elements:
                    all_created_elements.extend(step_created_elements)

                # Complete step logging
                if step_ctx:
                    step_ctx.items_created = elements_created
                    step_ctx.complete()

                # Complete progress tracking for this step
                if progress:
                    msg = f"{elements_created} elements"
                    if relationships_created > 0:
                        msg += f", {relationships_created} relationships"
                    progress.complete_step(msg)

                if verbose and relationships_created > 0:
                    print(f"    + {relationships_created} relationships")

                if step_result.get("errors"):
                    errors.extend(step_result["errors"])

            except Exception as e:
                error_msg = f"Error in {cfg.step_name}: {str(e)}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1
                if step_ctx:
                    step_ctx.error(str(e))
                if progress:
                    progress.log(error_msg, level="error")
                    progress.complete_step()

    # Complete phase logging
    if run_logger:
        if errors:
            run_logger.phase_error(
                "derivation", "; ".join(errors[:3]), "Derivation completed with errors"
            )
        else:
            run_logger.phase_complete(
                "derivation", "Derivation completed successfully", stats=stats
            )

    # Complete progress tracking
    if progress:
        msg = (
            f"Derivation complete: {stats['elements_created']} elements, "
            f"{stats['relationships_created']} relationships"
        )
        progress.complete_phase(msg)

    return {
        "success": len(errors) == 0,
        "stats": stats,
        "errors": errors,
        "created_elements": all_created_elements,
    }



# NOTE: Relationship derivation is now handled within each element module.
# The old _derive_relationships and _derive_element_relationships functions
# have been removed. Each element module's generate() function now handles
# both element creation AND relationship derivation using the unified flow
# in base.py (derive_batch_relationships).
