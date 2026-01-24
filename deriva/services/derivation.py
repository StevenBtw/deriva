"""
Derivation service for Deriva.

Orchestrates the derivation pipeline with phases:
1. prep: Pre-derivation graph analysis (pagerank, louvain, k-core)
2. generate: LLM-based element and relationship derivation
3. refine: Post-generation model refinement (dedup, orphans, etc.)

Used by both Marimo (visual) and CLI (headless).

Usage:
    from deriva.services import derivation
    from deriva.adapters.graph import GraphManager
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.database import get_connection

    engine = get_connection()

    with GraphManager() as gm, ArchimateManager() as am:
        # Run full derivation (all phases)
        result = derivation.run_derivation(
            engine=engine,
            graph_manager=gm,
            archimate_manager=am,
            llm_query_fn=my_llm_query,
            verbose=True,
        )

        # Or run individual phases
        prep_result = derivation.run_prep_phase(gm, engine)
        generate_result = derivation.run_generate_phase(gm, am, engine, llm_query_fn)
        refine_result = derivation.run_refine_phase(am, gm, engine)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Relationship
from deriva.common.types import PipelineResult, ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph import GraphManager
from deriva.adapters.graph.cache import EnrichmentCacheManager
from deriva.modules.derivation import prep
from deriva.modules.derivation.application_component import ApplicationComponentDerivation
from deriva.modules.derivation.application_interface import ApplicationInterfaceDerivation
from deriva.modules.derivation.application_service import ApplicationServiceDerivation
from deriva.modules.derivation.base import derive_consolidated_relationships
from deriva.modules.derivation.business_actor import BusinessActorDerivation
from deriva.modules.derivation.business_event import BusinessEventDerivation
from deriva.modules.derivation.business_function import BusinessFunctionDerivation

# Derivation class imports
from deriva.modules.derivation.business_object import BusinessObjectDerivation
from deriva.modules.derivation.business_process import BusinessProcessDerivation
from deriva.modules.derivation.data_object import DataObjectDerivation
from deriva.modules.derivation.device import DeviceDerivation
from deriva.modules.derivation.element_base import ElementDerivationBase
from deriva.modules.derivation.node import NodeDerivation
from deriva.modules.derivation.refine import run_refine_step
from deriva.modules.derivation.system_software import SystemSoftwareDerivation
from deriva.modules.derivation.technology_service import TechnologyServiceDerivation
from deriva.services import config

# Registry: element_type -> derivation class
DERIVATION_REGISTRY: dict[str, type[ElementDerivationBase]] = {
    "BusinessObject": BusinessObjectDerivation,
    "BusinessProcess": BusinessProcessDerivation,
    "BusinessActor": BusinessActorDerivation,
    "BusinessEvent": BusinessEventDerivation,
    "BusinessFunction": BusinessFunctionDerivation,
    "ApplicationComponent": ApplicationComponentDerivation,
    "ApplicationService": ApplicationServiceDerivation,
    "ApplicationInterface": ApplicationInterfaceDerivation,
    "DataObject": DataObjectDerivation,
    "TechnologyService": TechnologyServiceDerivation,
    "Node": NodeDerivation,
    "Device": DeviceDerivation,
    "SystemSoftware": SystemSoftwareDerivation,
}

# Instance cache for reuse
_DERIVATION_INSTANCES: dict[str, ElementDerivationBase] = {}


def _get_derivation(element_type: str) -> ElementDerivationBase | None:
    """Get or create a derivation instance for an element type."""
    if element_type not in DERIVATION_REGISTRY:
        return None
    if element_type not in _DERIVATION_INSTANCES:
        _DERIVATION_INSTANCES[element_type] = DERIVATION_REGISTRY[element_type]()
    return _DERIVATION_INSTANCES[element_type]


def _collect_relationship_rules() -> dict[str, tuple[list[Any], list[Any]]]:
    """Collect relationship rules from all derivation classes."""
    rules: dict[str, tuple[list[Any], list[Any]]] = {}
    for element_type, cls in DERIVATION_REGISTRY.items():
        outbound = cls.OUTBOUND_RULES
        inbound = cls.INBOUND_RULES
        if outbound or inbound:
            rules[element_type] = (outbound, inbound)
    return rules


def _get_element_props(elements: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    """Get properties for an element by identifier.

    Used to propagate graph properties to relationships for stability analysis.
    """
    for elem in elements:
        if elem.get("identifier") == identifier:
            return elem.get("properties", {})
    return {}


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
    defer_relationships: bool = True,
    cache_manager: EnrichmentCacheManager | None = None,
) -> dict[str, Any]:
    """
    Generate ArchiMate elements of a specific type (and optionally their relationships).

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
        defer_relationships: If True, skip relationship derivation (for separated phases mode)
        cache_manager: Optional EnrichmentCacheManager for controlled caching

    Returns:
        Dict with success, elements_created, relationships_created, created_elements, errors
    """
    derivation = _get_derivation(element_type)

    if derivation is None:
        return {
            "success": False,
            "elements_created": 0,
            "relationships_created": 0,
            "errors": [f"No derivation class for element type: {element_type}"],
        }

    try:
        result = derivation.generate(
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
            defer_relationships=defer_relationships,
            cache_manager=cache_manager,
        )
        return {
            "success": result.success,
            "elements_created": result.elements_created,
            "relationships_created": result.relationships_created,
            "created_elements": result.created_elements,
            "created_relationships": result.created_relationships,
            "errors": result.errors,
            # Candidate tracking for threshold optimization
            "candidates_queried": result.candidates_queried,
            "candidates_filtered": result.candidates_filtered,
            "candidates_to_llm": result.candidates_to_llm,
            "candidate_decisions": [d.to_dict() for d in result.candidate_decisions],
        }
    except Exception as e:
        return {
            "success": False,
            "elements_created": 0,
            "relationships_created": 0,
            "errors": [f"Generation failed for {element_type} | exception={type(e).__name__}: {e}"],
        }


logger = logging.getLogger(__name__)


# =============================================================================
# PREP STEP REGISTRY
# =============================================================================

# Enrichment algorithm registry - maps step_name to algorithm key for prep module
ENRICHMENT_ALGORITHMS: dict[str, str] = {
    "pagerank": "pagerank",
    "louvain_communities": "louvain",
    "k_core_filter": "kcore",
    "articulation_points": "articulation_points",
    "degree_centrality": "degree",
}


def _get_graph_edges(
    graph_manager: GraphManager,
    repository_name: str | None = None,
) -> list[dict[str, str]]:
    """Get edges from the graph for enrichment algorithms.

    Returns edges in the format expected by prep module:
    [{"source": "node_id_1", "target": "node_id_2"}, ...]

    Args:
        graph_manager: Connected GraphManager
        repository_name: Optional repo name to filter edges.
            If provided, only returns edges where both nodes belong to this repo.
            This enables per-repository enrichment isolation in multi-repo setups.

    Note: Labels in Neo4j are separate (e.g., ['Graph', 'Directory'], not 'Graph:Directory').
    We match any node with the 'Graph' label to get all graph nodes.
    """
    if repository_name:
        # Filter to edges within a single repository
        query = """
            MATCH (a)-[r]->(b)
            WHERE 'Graph' IN labels(a)
              AND 'Graph' IN labels(b)
              AND a.active = true AND b.active = true
              AND a.repository_name = $repo_name
              AND b.repository_name = $repo_name
            RETURN a.id as source, b.id as target
        """
        result = graph_manager.query(query, {"repo_name": repository_name})
    else:
        # Default: get all edges
        query = """
            MATCH (a)-[r]->(b)
            WHERE 'Graph' IN labels(a)
              AND 'Graph' IN labels(b)
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

    Enrich steps compute graph metrics (PageRank, Louvain, k-core, etc.)
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
        result = prep.enrich_graph(
            edges=edges,
            algorithms=[algorithm],
            params=params,
            include_percentiles=True,
        )

        if not result.enrichments:
            return {"success": True, "stats": {"nodes_updated": 0}}

        # Write enrichments to Neo4j
        nodes_updated = graph_manager.batch_update_properties(result.enrichments)

        logger.info(
            "Enrichment %s complete: %d nodes updated (graph: %d nodes, %d edges)",
            step_name,
            nodes_updated,
            result.metadata.total_nodes,
            result.metadata.total_edges,
        )

        return {
            "success": True,
            "stats": {
                "nodes_updated": nodes_updated,
                "algorithm": algorithm,
                "graph_metadata": result.metadata.to_dict(),
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
    defer_relationships: bool = True,
    config_versions: dict[str, dict[str, int]] | None = None,
    use_enrichment_cache: bool = True,
    nocache_enrichment_configs: list[str] | None = None,
    enrichment_bench_hash: str | None = None,
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
        phases: List of phases to run ("prep", "generate", "refine").
        run_logger: Optional RunLogger for structured logging
        progress: Optional progress reporter for visual feedback
        defer_relationships: If True, skip per-batch relationship derivation.
                            Elements will be created but relationships will not
                            be derived. Use for A/B testing or separated phases.
        config_versions: Optional config version snapshot (for benchmark consistency).
                        Dict with {"derivation": {step_name: version}}
        use_enrichment_cache: Enable/disable graph enrichment caching (default True).
        nocache_enrichment_configs: List of config names to skip enrichment cache for.
        enrichment_bench_hash: Optional benchmark hash for per-run cache isolation.

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
    all_candidate_decisions: list[dict] = []  # For threshold optimization analysis

    # Create enrichment cache manager with control settings
    enrichment_cache = EnrichmentCacheManager(
        use_cache=use_enrichment_cache,
        nocache_configs=nocache_enrichment_configs,
        bench_hash=enrichment_bench_hash,
    )

    # Accumulate graph metadata from prep phase for use in refine steps
    graph_metadata: dict[str, Any] = {}

    # Start phase logging
    if run_logger:
        run_logger.phase_start("derivation", "Starting derivation pipeline")

    # Calculate total steps for progress - use snapshot versions if provided
    version_map = config_versions.get("derivation", {}) if config_versions else {}
    if version_map:
        prep_configs = config.get_derivation_configs_by_version(engine, version_map, enabled_only=enabled_only, phase="prep")
        gen_configs = config.get_derivation_configs_by_version(engine, version_map, enabled_only=enabled_only, phase="generate")
        refine_configs = config.get_derivation_configs_by_version(engine, version_map, enabled_only=enabled_only, phase="refine")
    else:
        prep_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="prep")
        gen_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="generate")
        refine_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="refine")
    total_steps = 0
    if "prep" in phases:
        total_steps += len(prep_configs)
    if "generate" in phases:
        total_steps += len(gen_configs)
    if "refine" in phases:
        total_steps += len(refine_configs)

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

            # Capture graph metadata for refine steps
            if result.get("stats", {}).get("graph_metadata"):
                graph_metadata.update(result["stats"]["graph_metadata"])

            if result.get("errors"):
                # Add step context to errors
                contextualized = [f"[Derivation - {cfg.step_name}] {e}" for e in result["errors"]]
                errors.extend(contextualized)
                for err in contextualized:
                    logger.error(err)
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
                    defer_relationships=defer_relationships,
                    cache_manager=enrichment_cache,
                )

                elements_created = step_result.get("elements_created", 0)
                relationships_created = step_result.get("relationships_created", 0)
                stats["elements_created"] += elements_created
                stats["relationships_created"] += relationships_created
                stats["steps_completed"] += 1

                step_created_elements = step_result.get("created_elements", [])

                if step_created_elements:
                    all_created_elements.extend(step_created_elements)

                # Collect candidate decisions for threshold optimization
                step_candidate_decisions = step_result.get("candidate_decisions", [])
                if step_candidate_decisions:
                    all_candidate_decisions.extend(step_candidate_decisions)

                # Track created relationships for OCEL logging
                step_created_relationships = step_result.get("created_relationships", [])
                if step_ctx and step_created_relationships:
                    for rel_data in step_created_relationships:
                        # Build deterministic relationship ID: {Type}_{Source}_{Target}
                        rel_id = f"{rel_data['relationship_type']}_{rel_data['source']}_{rel_data['target']}"
                        step_ctx.add_relationship(rel_id)

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
                    # Add step context to errors
                    contextualized = [f"[Derivation - {cfg.step_name}] {e}" for e in step_result["errors"]]
                    errors.extend(contextualized)
                    for err in contextualized:
                        logger.error(err)

            except Exception as e:
                error_msg = f"[Derivation - {cfg.step_name}] {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                stats["steps_skipped"] += 1
                if step_ctx:
                    step_ctx.error(str(e))
                if progress:
                    progress.log(error_msg, level="error")
                    progress.complete_step()

    # Run consolidated relationship derivation if deferred
    if defer_relationships and all_created_elements:
        if verbose:
            print(f"  Deriving relationships for {len(all_created_elements)} elements...")

        # Start progress tracking
        if progress:
            progress.start_step("ConsolidatedRelationships")

        try:
            relationship_rules = _collect_relationship_rules()
            relationships = derive_consolidated_relationships(
                all_elements=all_created_elements,
                relationship_rules=relationship_rules,
                llm_query_fn=llm_query_fn,
                graph_manager=graph_manager,
            )

            # Persist relationships to archimate model with graph metadata for stability analysis
            for rel_data in relationships:
                source_props = _get_element_props(all_created_elements, rel_data["source"])
                target_props = _get_element_props(all_created_elements, rel_data["target"])

                relationship = Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    relationship_type=rel_data["relationship_type"],
                    properties={
                        "confidence": rel_data.get("confidence", 0.5),
                        "source_pagerank": source_props.get("source_pagerank"),
                        "source_kcore": source_props.get("source_kcore_level"),
                        "source_community": source_props.get("source_louvain_community"),
                        "target_pagerank": target_props.get("source_pagerank"),
                        "target_kcore": target_props.get("source_kcore_level"),
                        "target_community": target_props.get("source_louvain_community"),
                    },
                )
                archimate_manager.add_relationship(relationship)

            rel_count = len(relationships)
            stats["relationships_created"] += rel_count

            if verbose:
                print(f"    + {rel_count} consolidated relationships")
            if progress:
                progress.complete_step(f"{rel_count} relationships")

        except Exception as e:
            error_msg = f"Error in consolidated relationships: {str(e)}"
            errors.append(error_msg)
            if progress:
                progress.log(error_msg, level="error")
                progress.complete_step()

    # Run refine phase
    if "refine" in phases:
        if refine_configs and verbose:
            print(f"Running {len(refine_configs)} refine steps...")

        for cfg in refine_configs:
            if verbose:
                print(f"  Refine: {cfg.step_name}")

            # Start progress tracking for this step
            if progress:
                progress.start_step(cfg.step_name)

            step_ctx = None
            if run_logger:
                step_ctx = run_logger.step_start(cfg.step_name, f"Running refine step: {cfg.step_name}")

            try:
                # Parse params from config
                refine_params: dict[str, Any] = {}
                if cfg.params:
                    try:
                        import json

                        refine_params = json.loads(cfg.params)
                    except json.JSONDecodeError:
                        pass

                # Inject graph metadata for adaptive thresholds
                if graph_metadata:
                    refine_params["graph_metadata"] = graph_metadata

                # Run the refine step
                refine_result = run_refine_step(
                    step_name=cfg.step_name,
                    archimate_manager=archimate_manager,
                    graph_manager=graph_manager,
                    llm_query_fn=llm_query_fn if cfg.llm else None,
                    params=refine_params,
                )

                stats["steps_completed"] += 1

                # Track refine-specific stats
                if "elements_disabled" not in stats:
                    stats["elements_disabled"] = 0
                if "relationships_deleted" not in stats:
                    stats["relationships_deleted"] = 0
                if "refine_issues_found" not in stats:
                    stats["refine_issues_found"] = 0

                stats["elements_disabled"] += refine_result.elements_disabled
                stats["relationships_deleted"] += refine_result.relationships_deleted
                stats["refine_issues_found"] += refine_result.issues_found

                if step_ctx:
                    step_ctx.complete()

                if progress:
                    msg = f"Refine: {refine_result.issues_found} issues"
                    if refine_result.elements_disabled > 0:
                        msg += f", {refine_result.elements_disabled} disabled"
                    progress.complete_step(msg)

                if refine_result.errors:
                    errors.extend(refine_result.errors)

            except Exception as e:
                error_msg = f"Error in refine step {cfg.step_name}: {str(e)}"
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
            run_logger.phase_error("derivation", "; ".join(errors[:3]), "Derivation completed with errors")
        else:
            run_logger.phase_complete("derivation", "Derivation completed successfully", stats=stats)

    # Complete progress tracking
    if progress:
        msg = f"Derivation complete: {stats['elements_created']} elements, {stats['relationships_created']} relationships"
        if stats.get("elements_disabled", 0) > 0:
            msg += f", {stats['elements_disabled']} disabled"
        progress.complete_phase(msg)

    return {
        "success": len(errors) == 0,
        "stats": stats,
        "errors": errors,
        "created_elements": all_created_elements,
        "candidate_decisions": all_candidate_decisions,  # For threshold optimization
    }


# NOTE: Relationship derivation is now handled within each element module.
# The old _derive_relationships and _derive_element_relationships functions
# have been removed. Each element module's generate() function now handles
# both element creation AND relationship derivation using the unified flow
# in base.py (derive_batch_relationships).


def run_derivation_iter(
    engine: Any,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[..., Any] | None = None,
    enabled_only: bool = True,
    verbose: bool = False,
    phases: list[str] | None = None,
    defer_relationships: bool = True,
    use_enrichment_cache: bool = True,
    nocache_enrichment_configs: list[str] | None = None,
    enrichment_bench_hash: str | None = None,
) -> Iterator[ProgressUpdate]:
    """
    Run derivation pipeline as a generator, yielding progress updates.

    This is the generator version of run_derivation() designed for use with
    Marimo's mo.status.progress_bar iterator pattern.

    Args:
        engine: DuckDB connection for config
        defer_relationships: If True, skip per-batch relationship derivation.
        graph_manager: Connected GraphManager for querying source nodes
        archimate_manager: Connected ArchimateManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        enabled_only: Only run enabled derivation steps
        verbose: Print progress to stdout
        phases: List of phases to run ("prep", "generate", "refine")
        use_enrichment_cache: Enable/disable graph enrichment caching (default True).
        nocache_enrichment_configs: List of config names to skip enrichment cache for.
        enrichment_bench_hash: Optional benchmark hash for per-run cache isolation.

    Yields:
        ProgressUpdate objects for each step in the pipeline
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

    # Create enrichment cache manager with control settings
    enrichment_cache = EnrichmentCacheManager(
        use_cache=use_enrichment_cache,
        nocache_configs=nocache_enrichment_configs,
        bench_hash=enrichment_bench_hash,
    )

    # Calculate total steps for progress
    prep_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="prep")
    gen_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="generate")
    refine_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="refine")
    total_steps = 0
    if "prep" in phases:
        total_steps += len(prep_configs)
    if "generate" in phases:
        total_steps += len(gen_configs)
    if "refine" in phases:
        total_steps += len(refine_configs)

    if total_steps == 0:
        yield ProgressUpdate(
            phase="derivation",
            status="error",
            message="No derivation configs enabled",
            stats=stats,
        )
        return

    current_step = 0

    # Run prep phase
    if "prep" in phases:
        for cfg in prep_configs:
            current_step += 1

            if verbose:
                print(f"  Prep: {cfg.step_name}")

            result = _run_prep_step(cfg, graph_manager)
            stats["steps_completed"] += 1

            if result.get("errors"):
                errors.extend(result["errors"])

            # Yield step complete
            yield ProgressUpdate(
                phase="derivation",
                step=cfg.step_name,
                status="complete",
                current=current_step,
                total=total_steps,
                message="prep complete",
                stats={"prep": True},
            )

    # Run generate phase
    if "generate" in phases:
        for cfg in gen_configs:
            current_step += 1

            if verbose:
                print(f"  Generate: {cfg.step_name}")

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

                yield ProgressUpdate(
                    phase="derivation",
                    step=cfg.step_name,
                    status="error",
                    current=current_step,
                    total=total_steps,
                    message=error_msg,
                )
                continue

            # Type assertions for validated config
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
                    existing_elements=all_created_elements,
                    defer_relationships=defer_relationships,
                    cache_manager=enrichment_cache,
                )

                elements_created = step_result.get("elements_created", 0)
                relationships_created = step_result.get("relationships_created", 0)
                stats["elements_created"] += elements_created
                stats["relationships_created"] += relationships_created
                stats["steps_completed"] += 1

                step_created_elements = step_result.get("created_elements", [])
                if step_created_elements:
                    all_created_elements.extend(step_created_elements)

                msg = f"{elements_created} elements"
                if relationships_created > 0:
                    msg += f", {relationships_created} relationships"

                yield ProgressUpdate(
                    phase="derivation",
                    step=cfg.step_name,
                    status="complete",
                    current=current_step,
                    total=total_steps,
                    message=msg,
                    stats={"elements_created": elements_created, "relationships_created": relationships_created},
                )

                if step_result.get("errors"):
                    errors.extend(step_result["errors"])

            except Exception as e:
                error_msg = f"Error in {cfg.step_name}: {str(e)}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1

                yield ProgressUpdate(
                    phase="derivation",
                    step=cfg.step_name,
                    status="error",
                    current=current_step,
                    total=total_steps,
                    message=error_msg,
                )

    # Run refine phase
    if "refine" in phases:
        for cfg in refine_configs:
            current_step += 1

            if verbose:
                print(f"  Refine: {cfg.step_name}")

            try:
                # Parse params from config
                refine_params = None
                if cfg.params:
                    try:
                        import json

                        refine_params = json.loads(cfg.params)
                    except json.JSONDecodeError:
                        pass

                # Run the refine step
                refine_result = run_refine_step(
                    step_name=cfg.step_name,
                    archimate_manager=archimate_manager,
                    graph_manager=graph_manager,
                    llm_query_fn=llm_query_fn if cfg.llm else None,
                    params=refine_params,
                )

                stats["steps_completed"] += 1

                # Track refine-specific stats
                if "elements_disabled" not in stats:
                    stats["elements_disabled"] = 0
                if "relationships_deleted" not in stats:
                    stats["relationships_deleted"] = 0
                if "refine_issues_found" not in stats:
                    stats["refine_issues_found"] = 0

                stats["elements_disabled"] += refine_result.elements_disabled
                stats["relationships_deleted"] += refine_result.relationships_deleted
                stats["refine_issues_found"] += refine_result.issues_found

                msg = f"Refine: {refine_result.issues_found} issues"
                if refine_result.elements_disabled > 0:
                    msg += f", {refine_result.elements_disabled} disabled"

                yield ProgressUpdate(
                    phase="derivation",
                    step=cfg.step_name,
                    status="complete",
                    current=current_step,
                    total=total_steps,
                    message=msg,
                    stats={"refine": True, "issues_found": refine_result.issues_found},
                )

                if refine_result.errors:
                    errors.extend(refine_result.errors)

            except Exception as e:
                error_msg = f"Error in refine step {cfg.step_name}: {str(e)}"
                errors.append(error_msg)
                stats["steps_skipped"] += 1

                yield ProgressUpdate(
                    phase="derivation",
                    step=cfg.step_name,
                    status="error",
                    current=current_step,
                    total=total_steps,
                    message=error_msg,
                )

    # Yield final completion
    final_message = f"{stats['elements_created']} elements, {stats['relationships_created']} relationships"
    if stats.get("elements_disabled", 0) > 0:
        final_message += f", {stats['elements_disabled']} disabled"
    if errors:
        final_message += f" ({len(errors)} errors)"

    yield ProgressUpdate(
        phase="derivation",
        step="",
        status="complete",
        current=total_steps,
        total=total_steps,
        message=final_message,
        stats={
            "success": len(errors) == 0,
            "stats": stats,
            "errors": errors,
            "created_elements": all_created_elements,
        },
    )
