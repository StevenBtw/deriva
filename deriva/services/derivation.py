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

import functools
import json
import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Relationship, validate_relationship_rule
from deriva.common.types import PipelineResult, ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph import GraphManager
from deriva.adapters.graph.cache import EnrichmentCacheManager
from deriva.modules.derivation import prep
from deriva.modules.derivation.application_component import ApplicationComponentDerivation
from deriva.modules.derivation.application_interface import ApplicationInterfaceDerivation
from deriva.modules.derivation.application_service import ApplicationServiceDerivation
from deriva.modules.derivation.base import (
    ConfigurationRule,
    ContainmentRule,
    DependencyRule,
    ElementPrompt,
    GraphFilter,
    MembershipRule,
    NamingConfig,
    NestedFilter,
    PerCandidateConfig,
    RelationshipLLMConfig,
    RoleConfig,
    UnitFilter,
    derive_consolidated_relationships,
)
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


def _relationship_llm_config(configs: list[Any]) -> RelationshipLLMConfig | None:
    """Build the LLM relationship settings from the enabled relationship-phase row.

    The relationship prompt rules and the confidence cutoff are versioned config.
    No enabled row, or ``params.llm_proposals`` false, means relationships come from
    the graph tiers only.
    """
    if not configs:
        return None
    if len(configs) > 1:
        raise ValueError(f"Only one relationship config may be enabled, found: {', '.join(c.step_name for c in configs)}")
    cfg = configs[0]
    params = json.loads(cfg.params) if cfg.params else {}
    proposals = params.get("llm_proposals", True)
    if not isinstance(proposals, bool):
        raise ValueError(f"Relationship config {cfg.step_name}: params.llm_proposals must be true or false, got {proposals!r}")
    if not proposals:
        return None
    if not cfg.instruction:
        raise ValueError(f"Relationship config {cfg.step_name} has no instruction")
    missing = [name for name in ("min_confidence", "persona") if name not in params]
    if missing:
        raise ValueError(f"Relationship config {cfg.step_name} needs params.{' and params.'.join(missing)}")
    return RelationshipLLMConfig(
        instruction=cfg.instruction,
        min_confidence=float(params["min_confidence"]),
        persona=params["persona"],
        temperature=getattr(cfg, "temperature", None),
    )


def _structural_items(configs: list[Any], key: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """The rule items under ``params.<key>`` of the enabled relationship row, each with the given string fields."""
    if not configs:
        return []
    params = json.loads(configs[0].params) if configs[0].params else {}
    settings = params.get(key)
    if settings is None:
        return []
    if not isinstance(settings, list):
        raise ValueError(f"params.{key} must be a list of rules, got {settings!r}")
    for item in settings:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item.get(k) for k in fields):
            raise ValueError(f"params.{key} rules need {', '.join(fields)}, got {item!r}")
    return settings


def _check_rule(key: str, item: dict[str, str], source: str, relationship: str, target: str) -> None:
    is_valid, message = validate_relationship_rule(source, relationship, target)
    if not is_valid:
        raise ValueError(f"params.{key} rule {item!r} is not valid: {message}")


def _containment_rules(configs: list[Any]) -> list[ContainmentRule]:
    """Type pairs that containment decides, from the enabled relationship row (``params.containment``).

    ``[{"container": "ApplicationComponent", "contained": "ApplicationInterface", "relationship": "Composition"}]``:
    the nearest enclosing component composes each interface. Every rule must be a valid
    relationship in the metamodel. No row or no key: no containment tier.
    """
    rules: list[ContainmentRule] = []
    for item in _structural_items(configs, "containment", ("container", "contained", "relationship")):
        _check_rule("containment", item, item["container"], item["relationship"], item["contained"])
        rules.append(ContainmentRule(container=item["container"], contained=item["contained"], relationship=item["relationship"]))
    return rules


def _membership_rules(configs: list[Any]) -> list[MembershipRule]:
    """Relationships from role membership (``params.membership``).

    ``[{"group": "Node", "member": "SystemSoftware", "relationship": "Composition", "from": "group"}]``:
    a role node composes the system software of its member technologies; ``"from": "member"``
    turns the direction around (system software realizes the technology service of its kind).
    """
    rules: list[MembershipRule] = []
    for item in _structural_items(configs, "membership", ("group", "member", "relationship", "from")):
        if item["from"] not in ("group", "member"):
            raise ValueError(f"params.membership rule {item!r}: from must be group or member")
        from_group = item["from"] == "group"
        source, target = (item["group"], item["member"]) if from_group else (item["member"], item["group"])
        _check_rule("membership", item, source, item["relationship"], target)
        rules.append(MembershipRule(group=item["group"], member=item["member"], relationship=item["relationship"], from_group=from_group))
    return rules


def _configuration_rules(configs: list[Any]) -> list[ConfigurationRule]:
    """Relationships from configuration files (``params.configuration``).

    ``[{"provider": "TechnologyService", "consumer": "ApplicationComponent", "relationship": "Serving"}]``:
    a technology service serves the component whose directory holds a file configuring one
    of its technologies.
    """
    rules: list[ConfigurationRule] = []
    for item in _structural_items(configs, "configuration", ("provider", "consumer", "relationship")):
        _check_rule("configuration", item, item["provider"], item["relationship"], item["consumer"])
        rules.append(ConfigurationRule(provider=item["provider"], consumer=item["consumer"], relationship=item["relationship"]))
    return rules


def _dependency_rules(configs: list[Any]) -> list[DependencyRule]:
    """Dependencies from file imports (``params.dependency``).

    ``[{"provider": "ApplicationComponent", "consumer": "ApplicationComponent", "relationship": "Serving"}]``:
    a component serves the sibling component whose files import its files.
    """
    rules: list[DependencyRule] = []
    for item in _structural_items(configs, "dependency", ("provider", "consumer", "relationship")):
        _check_rule("dependency", item, item["provider"], item["relationship"], item["consumer"])
        rules.append(DependencyRule(provider=item["provider"], consumer=item["consumer"], relationship=item["relationship"]))
    return rules


def _per_candidate_config(params: str | None) -> PerCandidateConfig | None:
    """Read per-candidate naming mode from an element config's params.

    ``{"per_candidate": {"min_pool": 6, "rules": "..."}}`` switches it on; without
    the key the element type is derived in batch mode.
    """
    settings = json.loads(params).get("per_candidate") if params else None
    if settings is None:
        return None
    if "min_pool" not in settings or not settings.get("rules") or not settings.get("persona"):
        raise ValueError("params.per_candidate needs min_pool, rules and persona")
    return PerCandidateConfig(min_pool=int(settings["min_pool"]), rules=settings["rules"], persona=settings["persona"])


def _naming_config(params: str | None) -> NamingConfig | None:
    """Read the isolated naming step from an element config's params.

    ``{"naming": {"instruction": "...", "samples": 1}}`` switches it on; without
    the key elements keep their structure names.
    """
    settings = json.loads(params).get("naming") if params else None
    if settings is None:
        return None
    if not settings.get("instruction"):
        raise ValueError("params.naming needs an instruction")
    return NamingConfig(instruction=settings["instruction"], samples=int(settings.get("samples", 1)))


def _element_prompt(params: str | None) -> ElementPrompt | None:
    """Read the texts of the batch element prompt from an element config's params (``params.prompt``).

    ``{"prompt": {"persona": ..., "candidates": ..., "rules": ..., "abstention": ...}}``; without the
    key the step has no batch prompt (an error once candidates are derived in batches).
    """
    texts = json.loads(params).get("prompt") if params else None
    if texts is None:
        return None
    missing = [name for name in ("persona", "candidates", "rules", "abstention") if name not in texts]
    if missing:
        raise ValueError(f"params.prompt needs {', '.join(missing)}")
    return ElementPrompt(persona=texts["persona"], candidates=texts["candidates"], rules=texts["rules"], abstention=texts["abstention"])


def _role_config(params: str | None) -> RoleConfig | None:
    """Read the role classification from an element config's params (``params.roles``).

    ``{"roles": {"labels": [...], "instruction": "...", "names": {key: name}}}`` switches it on
    (optional ``documentation`` template, ``missing_retries`` and ``element_per``: "role" or
    "candidate"; with "candidate" also ``name_template``, ``container_type`` and
    ``show_path``); without the key every candidate takes the keep and naming path.
    """
    settings = json.loads(params).get("roles") if params else None
    if settings is None:
        return None
    if not settings.get("labels") or not settings.get("instruction") or not settings.get("names"):
        raise ValueError("params.roles needs labels, instruction and names")
    element_per = settings.get("element_per", "role")
    if element_per not in ("role", "candidate"):
        raise ValueError(f"params.roles.element_per must be 'role' or 'candidate', not {element_per!r}")
    name_template = settings.get("name_template", "")
    container_type = settings.get("container_type", "")
    show_path = settings.get("show_path", False)
    if not isinstance(name_template, str) or not isinstance(container_type, str) or not isinstance(show_path, bool):
        raise ValueError("params.roles name_template and container_type must be text, show_path true or false")
    if name_template and element_per != "candidate":
        raise ValueError("params.roles.name_template names one element per candidate: it needs element_per 'candidate'")
    naming_call = settings.get("naming_call", False)
    if not isinstance(naming_call, bool):
        raise ValueError(f"params.roles.naming_call must be true or false, got {naming_call!r}")
    if naming_call and (element_per != "candidate" or not json.loads(params or "{}").get("naming")):
        raise ValueError("params.roles.naming_call renames one element per candidate with the step's naming call: it needs element_per 'candidate' and params.naming")
    return RoleConfig(
        labels=frozenset(settings["labels"]),
        instruction=settings["instruction"],
        names=dict(settings["names"]),
        documentation=settings.get("documentation", ""),
        missing_retries=int(settings.get("missing_retries", 0)),
        element_per=element_per,
        name_template=name_template,
        container_type=container_type,
        show_path=show_path,
        naming_call=naming_call,
    )


def _skip_when_directory_is(params: str | None) -> frozenset[str] | None:
    """Element types whose sources take a directory's candidates out (``params.skip_when_directory_is``).

    One structural source, one element: a candidate that a directory represents is left out
    when that directory is already the source of an element of one of these types. Without
    the key nothing is left out this way.
    """
    types = json.loads(params).get("skip_when_directory_is") if params else None
    return frozenset(types) if types is not None else None


def _pattern_labels(params: str | None) -> frozenset[str] | None:
    """Graph labels of the candidates the step's name patterns filter (``params.pattern_labels``).

    Candidates with none of these labels were chosen by the query on structure (for example a
    technology by its category) and are not filtered by name. Without the key the patterns
    filter every candidate.
    """
    labels = json.loads(params).get("pattern_labels") if params else None
    return frozenset(labels) if labels is not None else None


def _skip_subtypes(params: str | None) -> bool:
    """Whether candidate types that inherit from another candidate type are left out (``params.skip_subtypes``).

    One element per contract: the base type represents its subtypes (implementations,
    subclasses). Without the key no candidate is left out this way.
    """
    value = json.loads(params).get("skip_subtypes", False) if params else False
    if not isinstance(value, bool):
        raise ValueError(f"params.skip_subtypes must be true or false, got {value!r}")
    return value


def _skip_nested(params: str | None, engine: Any = None) -> NestedFilter | None:
    """The file type and share that make a nested directory candidate leave (``params.skip_nested``).

    ``{"file_type": "source", "min_share": 0.9}`` leaves out a selected directory that holds at
    least 90% of the source files below its nearest selected ancestor directory, which represents
    it. Without the key no candidate is left out this way. With ``engine`` the file type
    must be a registered one (``config filetype list``): an unknown type would count no
    files and silently leave nothing out.
    """
    settings = json.loads(params).get("skip_nested") if params else None
    if settings is None:
        return None
    file_type = settings.get("file_type") if isinstance(settings, dict) else None
    share = settings.get("min_share") if isinstance(settings, dict) else None
    if not isinstance(file_type, str) or not file_type:
        raise ValueError(f"params.skip_nested needs a file_type, got {settings!r}")
    if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < share <= 1:
        raise ValueError(f"params.skip_nested needs a min_share above 0 and at most 1, got {settings!r}")
    if engine is not None and file_type not in {ft.file_type for ft in config.get_file_types(engine)}:
        raise ValueError(f"params.skip_nested names file type {file_type!r}, which is not a registered file type")
    return NestedFilter(file_type=file_type, min_share=float(share))


def _deployable_units(params: str | None) -> UnitFilter | None:
    """The files that make a directory a deployable unit, and how many units a repository needs (``params.deployable_units``).

    ``{"file_names": ["pom.xml", "build.gradle", "package.json"], "min_units": 2}``: when at least two
    outermost directory candidates directly hold one of those files, those units are the candidates.
    File names match without regard to case. Without the key the candidates stay.
    """
    settings = json.loads(params).get("deployable_units") if params else None
    if settings is None:
        return None
    names = settings.get("file_names") if isinstance(settings, dict) else None
    minimum = settings.get("min_units") if isinstance(settings, dict) else None
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
        raise ValueError(f"params.deployable_units needs a non-empty list of file_names, got {settings!r}")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ValueError(f"params.deployable_units needs a min_units of at least 1, got {settings!r}")
    return UnitFilter(file_names=frozenset(n.lower() for n in names), min_units=minimum)


def _graph_filter(params: str | None) -> GraphFilter | None:
    """The step's k-core threshold and the labels it applies to (``params.graph_filter``).

    ``{"min_kcore_percentile": 30, "labels": ["File"]}`` leaves out candidates with the
    label File below the 30th k-core percentile; candidates without one of the labels pass.
    Without ``labels`` the threshold applies to every candidate; without the key there is none.
    """
    settings = json.loads(params).get("graph_filter") if params else None
    if settings is None:
        return None
    threshold = settings.get("min_kcore_percentile") if isinstance(settings, dict) else None
    labels = settings.get("labels") if isinstance(settings, dict) else None
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError(f"params.graph_filter needs a numeric min_kcore_percentile, got {settings!r}")
    if labels is not None and (not isinstance(labels, list) or not all(isinstance(label, str) for label in labels)):
        raise ValueError(f"params.graph_filter labels must be a list of graph labels, got {labels!r}")
    return GraphFilter(min_kcore_percentile=float(threshold), labels=frozenset(labels) if labels is not None else None)


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
    relationship_config: RelationshipLLMConfig | None = None,
    per_candidate: PerCandidateConfig | None = None,
    naming: NamingConfig | None = None,
    pattern_labels: frozenset[str] | None = None,
    roles: RoleConfig | None = None,
    skip_when_directory_is: frozenset[str] | None = None,
    prompt: ElementPrompt | None = None,
    graph_filter: GraphFilter | None = None,
    skip_subtypes: bool = False,
    skip_nested: NestedFilter | None = None,
    deployable_units: UnitFilter | None = None,
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
        engine: DuckDB connection for patterns (enrichments read from graph)
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
        relationship_config: Relationship config row settings (None skips the LLM relationship pass)
        per_candidate: Per-candidate naming mode from the element config (None uses batch mode)
        naming: Isolated naming step from the element config (None keeps structure names)
        pattern_labels: Labels of the candidates the name patterns filter (None: every candidate)
        roles: Candidates classified into roles, one element per role (None: no role path)
        skip_when_directory_is: Element types whose sources take a directory's candidates out
        prompt: The texts of the batch element prompt (``params.prompt``)
        graph_filter: The step's k-core threshold (``params.graph_filter``; None: none)
        skip_subtypes: Leave out candidate types that inherit from another candidate (``params.skip_subtypes``)
        skip_nested: Leave out directories nested in a selected ancestor that holds nearly the same files (``params.skip_nested``)
        deployable_units: With enough outermost deployable units, only those units are candidates (``params.deployable_units``)

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

    # Include/exclude patterns of the step (pattern-based modules filter on them)
    try:
        patterns = config.get_derivation_patterns(engine, element_type)
    except ValueError:
        logger.debug("No derivation patterns found for %s, using empty sets", element_type)
        patterns = {}
    if pattern_labels is not None:
        patterns = {**patterns, "labels": set(pattern_labels)}

    try:
        result = derivation.generate(
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
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
            relationship_config=relationship_config,
            per_candidate=per_candidate,
            naming=naming,
            patterns=patterns,
            roles=roles,
            skip_when_directory_is=skip_when_directory_is,
            prompt=prompt,
            graph_filter=graph_filter,
            skip_subtypes=skip_subtypes,
            skip_nested=skip_nested,
            deployable_units=deployable_units,
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

# Step name of the consolidated relationship pass in ``run_derivation(steps=...)``
RELATIONSHIP_STEP = "ConsolidatedRelationships"


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

    Note: Labels are separate (e.g., ['Graph', 'Directory'], not 'Graph:Directory').
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
    and store them as properties on graph nodes.
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

        # Write enrichments to graph
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
    steps: list[str] | None = None,
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
        steps: Only these steps (config step names, ``RELATIONSHIP_STEP`` for the consolidated
            relationship pass); None runs every step of the phases. A step run alone works on the
            model its input already holds, as it would in a full run.
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
        phases = ["prep", "generate", "refine"]

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
        relationship_configs = config.get_derivation_configs_by_version(engine, version_map, enabled_only=enabled_only, phase="relationship")
    else:
        prep_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="prep")
        gen_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="generate")
        refine_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="refine")
        relationship_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="relationship")
    if steps is not None:
        prep_configs = [c for c in prep_configs if c.step_name in steps]
        gen_configs = [c for c in gen_configs if c.step_name in steps]
        refine_configs = [c for c in refine_configs if c.step_name in steps]
    relationship_pass = defer_relationships and (steps is None or RELATIONSHIP_STEP in steps)
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

    # Relationship pass settings: used by generate and by the deferred relationship pass,
    # read on first use so runs that derive no relationships never parse the row
    relationship_config = functools.cache(lambda: _relationship_llm_config(relationship_configs))

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
                    relationship_config=relationship_config(),
                    per_candidate=_per_candidate_config(cfg.params),
                    naming=_naming_config(cfg.params),
                    pattern_labels=_pattern_labels(cfg.params),
                    roles=_role_config(cfg.params),
                    skip_when_directory_is=_skip_when_directory_is(cfg.params),
                    prompt=_element_prompt(cfg.params),
                    graph_filter=_graph_filter(cfg.params),
                    skip_subtypes=_skip_subtypes(cfg.params),
                    skip_nested=_skip_nested(cfg.params, engine),
                    deployable_units=_deployable_units(cfg.params),
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
    # If no elements were created in this run, use existing elements from the model
    elements_for_relationships = all_created_elements
    if relationship_pass and not all_created_elements:
        # Fetch existing elements from the model for relationship derivation
        existing_elements = archimate_manager.get_elements(enabled_only=True)
        if existing_elements:
            elements_for_relationships = [
                {
                    "identifier": e.identifier,
                    "name": e.name,
                    "element_type": e.element_type,
                    "properties": e.properties or {},
                }
                for e in existing_elements
            ]
            if verbose:
                print(f"  Using {len(elements_for_relationships)} existing elements for relationship derivation...")

    if relationship_pass and elements_for_relationships:
        if verbose and all_created_elements:
            print(f"  Deriving relationships for {len(elements_for_relationships)} elements...")

        # Start progress tracking
        if progress:
            progress.start_step(RELATIONSHIP_STEP)
        rel_ctx = run_logger.step_start(RELATIONSHIP_STEP, "Deriving relationships") if run_logger else None

        try:
            relationship_rules = _collect_relationship_rules()
            relationships = derive_consolidated_relationships(
                all_elements=elements_for_relationships,
                relationship_rules=relationship_rules,
                llm_query_fn=llm_query_fn,
                graph_manager=graph_manager,
                llm_config=relationship_config(),
                temperature=getattr(relationship_config(), "temperature", None),
                containment=_containment_rules(relationship_configs),
                membership=_membership_rules(relationship_configs),
                configuration=_configuration_rules(relationship_configs),
                dependency=_dependency_rules(relationship_configs),
            )

            # Persist relationships to archimate model with graph metadata for stability analysis
            for rel_data in relationships:
                source_props = _get_element_props(elements_for_relationships, rel_data["source"])
                target_props = _get_element_props(elements_for_relationships, rel_data["target"])

                relationship = Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    relationship_type=rel_data["relationship_type"],
                    properties={
                        "confidence": rel_data.get("confidence", 0.5),
                        "derived_from": rel_data.get("derived_from"),
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
            if rel_ctx:
                rel_ctx.items_created = rel_count
                rel_ctx.complete()

        except Exception as e:
            error_msg = f"Error in consolidated relationships: {str(e)}"
            errors.append(error_msg)
            if rel_ctx:
                rel_ctx.error(error_msg)
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
        phases = ["prep", "generate", "refine"]

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
    relationship_configs = config.get_derivation_configs(engine, enabled_only=enabled_only, phase="relationship")
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

    # Relationship pass settings: used by generate and by the deferred relationship pass,
    # read on first use so runs that derive no relationships never parse the row
    relationship_config = functools.cache(lambda: _relationship_llm_config(relationship_configs))

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
                    relationship_config=relationship_config(),
                    per_candidate=_per_candidate_config(cfg.params),
                    naming=_naming_config(cfg.params),
                    pattern_labels=_pattern_labels(cfg.params),
                    roles=_role_config(cfg.params),
                    skip_when_directory_is=_skip_when_directory_is(cfg.params),
                    prompt=_element_prompt(cfg.params),
                    graph_filter=_graph_filter(cfg.params),
                    skip_subtypes=_skip_subtypes(cfg.params),
                    skip_nested=_skip_nested(cfg.params, engine),
                    deployable_units=_deployable_units(cfg.params),
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

    # Run consolidated relationship derivation if deferred
    # If no elements were created in this run, use existing elements from the model
    elements_for_relationships = all_created_elements
    if defer_relationships and not all_created_elements:
        # Fetch existing elements from the model for relationship derivation
        existing_elements = archimate_manager.get_elements(enabled_only=True)
        if existing_elements:
            elements_for_relationships = [
                {
                    "identifier": e.identifier,
                    "name": e.name,
                    "element_type": e.element_type,
                    "properties": e.properties or {},
                }
                for e in existing_elements
            ]
            if verbose:
                print(f"  Using {len(elements_for_relationships)} existing elements for relationship derivation...")

    if defer_relationships and elements_for_relationships:
        current_step += 1
        if verbose and all_created_elements:
            print(f"  Deriving relationships for {len(elements_for_relationships)} elements...")

        try:
            relationship_rules = _collect_relationship_rules()
            relationships = derive_consolidated_relationships(
                all_elements=elements_for_relationships,
                relationship_rules=relationship_rules,
                llm_query_fn=llm_query_fn,
                graph_manager=graph_manager,
                llm_config=relationship_config(),
                temperature=getattr(relationship_config(), "temperature", None),
                containment=_containment_rules(relationship_configs),
                membership=_membership_rules(relationship_configs),
                configuration=_configuration_rules(relationship_configs),
                dependency=_dependency_rules(relationship_configs),
            )

            # Persist relationships to archimate model
            for rel_data in relationships:
                source_props = _get_element_props(elements_for_relationships, rel_data["source"])
                target_props = _get_element_props(elements_for_relationships, rel_data["target"])

                relationship = Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    relationship_type=rel_data["relationship_type"],
                    properties={
                        "confidence": rel_data.get("confidence", 0.5),
                        "derived_from": rel_data.get("derived_from"),
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

            yield ProgressUpdate(
                phase="derivation",
                step=RELATIONSHIP_STEP,
                status="complete",
                current=current_step,
                total=total_steps,
                message=f"{rel_count} relationships derived",
                stats={"relationships_created": rel_count},
            )

        except Exception as e:
            error_msg = f"Error in consolidated relationships: {str(e)}"
            errors.append(error_msg)

            yield ProgressUpdate(
                phase="derivation",
                step=RELATIONSHIP_STEP,
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
