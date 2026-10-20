"""
Derivation service for Deriva.

Orchestrates the derivation pipeline with phases:
1. prep: Pre-derivation graph analysis (pagerank, louvain, k-core)
2. generate: LLM-based element and relationship derivation
3. refine: Post-generation model refinement (dedup, orphans, etc.)

Used by both the studio (web UI) and the CLI (headless).

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
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship, validate_relationship_rule
from deriva.common.naming import name_key
from deriva.common.paths import workspace
from deriva.common.types import PipelineResult, ProgressUpdate

if TYPE_CHECKING:
    from deriva.common.types import ProgressReporter, RunLoggerProtocol
from deriva.adapters.graph import GraphManager
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
    GraphLinkRule,
    ListedMembersRule,
    MembershipRule,
    NamedInCodeRule,
    NameGuards,
    NamingConfig,
    NestedFilter,
    PerCandidateConfig,
    RelationshipLLMConfig,
    RoleConfig,
    SameNameRule,
    UnitFilter,
    code_names_with_paths,
    derive_consolidated_relationships,
    element_source_paths,
    file_imports,
    get_enrichments_from_graph,
    graph_link_pairs,
    source_concept_names,
    unit_scopes,
)
from deriva.modules.derivation.business_actor import BusinessActorDerivation
from deriva.modules.derivation.business_event import BusinessEventDerivation
from deriva.modules.derivation.business_function import BusinessFunctionDerivation

# Derivation class imports
from deriva.modules.derivation.business_object import BusinessObjectDerivation
from deriva.modules.derivation.business_process import BusinessProcessDerivation
from deriva.modules.derivation.component_services import ComponentServicesConfig, derive_component_services, derive_member_services, derive_unit_services
from deriva.modules.derivation.data_object import DataObjectDerivation
from deriva.modules.derivation.device import DeviceDerivation
from deriva.modules.derivation.element_base import ElementDerivationBase
from deriva.modules.derivation.function_model import (
    EvidenceRules,
    ServiceItem,
    classify_services,
    component_documentation,
    function_elements,
    header_notes,
    is_technical,
    operations_of,
    parse_function_model,
    shown_operations,
)
from deriva.modules.derivation.node import NodeDerivation
from deriva.modules.derivation.refine import run_refine_step
from deriva.modules.derivation.system_software import SystemSoftwareDerivation
from deriva.modules.derivation.technology_service import TechnologyServiceDerivation
from deriva.services import config


class _SettingsAndModel(Protocol):
    def get_setting(self, key: str) -> str | None: ...

    def clear_model(self) -> dict[str, Any]: ...


# The derivation phases that make no LLM call: what a run without an LLM (--no-llm, the studio's
# structural steps) derives. generate calls the LLM; refine steps may (params llm)
STRUCTURAL_PHASES = ("prep",)


def needs_llm(phases: list[str] | None) -> bool:
    """Whether derivation over ``phases`` (None: every phase) can call the LLM."""
    return phases is None or not set(phases) <= set(STRUCTURAL_PHASES)


def start_full_derivation(session: _SettingsAndModel) -> bool:
    """Before a full derivation run (every phase, every enabled step): clear the model unless the setting is off.

    Callers decide what a full run is: the CLI without --phase or --only-step, the studio's run scopes.
    Benchmarks clear the model themselves before each run. Returns whether the model was cleared.
    """
    if not config.clear_model_before_derivation(session.get_setting(config.CLEAR_MODEL_SETTING)):
        return False
    session.clear_model()
    return True


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
    if "persona" not in params:
        raise ValueError(f"Relationship config {cfg.step_name} needs params.persona")
    return RelationshipLLMConfig(
        instruction=cfg.instruction,
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


def _name_match_skip(configs: list[Any]) -> set[tuple[str, str]]:
    """(source type, target type) pairs the name-matching tier never links (``params.name_match_skip``)."""
    return {(item["source"], item["target"]) for item in _structural_items(configs, "name_match_skip", ("source", "target"))}


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


def _same_name_rules(configs: list[Any]) -> list[SameNameRule]:
    """Relationships between elements whose structural sources carry the same name (``params.same_name``).

    ``[{"source": "DataObject", "target": "BusinessObject", "relationship": "Realization", "strip_suffixes": ["Impl"]}]``:
    a data object realizes the business object its type names, the type name without the suffix.
    """
    rules: list[SameNameRule] = []
    for item in _structural_items(configs, "same_name", ("source", "target", "relationship")):
        _check_rule("same_name", item, item["source"], item["relationship"], item["target"])
        suffixes = item.get("strip_suffixes", [])
        if not isinstance(suffixes, list) or not all(isinstance(x, str) and x for x in suffixes):
            raise ValueError(f"params.same_name rule {item!r}: strip_suffixes must be a list of names")
        rules.append(SameNameRule(source=item["source"], target=item["target"], relationship=item["relationship"], strip_suffixes=tuple(suffixes)))
    return rules


def _graph_link_rules(configs: list[Any]) -> list[GraphLinkRule]:
    """Relationships from links the graph holds between source nodes (``params.graph_links``).

    ``[{"source": "ApplicationComponent", "target": "ApplicationInterface", "relationship": "Composition", "query": "MATCH ... RETURN x.id AS a, y.id AS b"}]``:
    the component made from node a composes the interface made from node b. ``"exclusive": true``: only the
    graph relates the two types by that relationship type (either direction), no other tier adds one.
    """
    rules: list[GraphLinkRule] = []
    for item in _structural_items(configs, "graph_links", ("source", "target", "relationship", "query")):
        _check_rule("graph_links", item, item["source"], item["relationship"], item["target"])
        on_channel = item.get("source_channel", False)
        if not isinstance(on_channel, bool):
            raise ValueError(f"graph_links: source_channel must be true or false, got {on_channel!r}")
        exclusive = item.get("exclusive", False)
        if not isinstance(exclusive, bool):
            raise ValueError(f"graph_links: exclusive must be true or false, got {exclusive!r}")
        rules.append(
            GraphLinkRule(source=item["source"], target=item["target"], relationship=item["relationship"], query=item["query"], source_channel=on_channel, exclusive=exclusive)
        )
    return rules


def _listed_members_rules(configs: list[Any]) -> list[ListedMembersRule]:
    """Relationships between an element and the members it lists (``params.listed_members``).

    ``[{"holder": "ApplicationService", "list": "sources", "member": "ApplicationComponent", "relationship": "Realization", "by": "source"}]``:
    the components a service lists realize it; ``"from_holder": true`` turns the direction (a service accesses its objects).
    """
    rules: list[ListedMembersRule] = []
    for item in _structural_items(configs, "listed_members", ("holder", "list", "member", "relationship")):
        by, from_holder = item.get("by", "identifier"), item.get("from_holder", False)
        if by not in ("source", "identifier") or not isinstance(from_holder, bool):
            raise ValueError(f"params.listed_members rule {item!r}: by is 'source' or 'identifier', from_holder true or false")
        source, target = (item["holder"], item["member"]) if from_holder else (item["member"], item["holder"])
        _check_rule("listed_members", item, source, item["relationship"], target)
        rules.append(ListedMembersRule(holder=item["holder"], list_property=item["list"], member=item["member"], relationship=item["relationship"], by=by, from_holder=from_holder))
    return rules


def _named_in_code_rules(configs: list[Any]) -> list[NamedInCodeRule]:
    """Relationships from the code that names a concept (``params.named_in_code``).

    ``[{"owner": "ApplicationComponent", "named": "BusinessObject", "relationship": "Access", "min_names": 2, "share": 0.5}]``:
    the component whose directory holds the most type and directory names carrying the object's words accesses it,
    and so does every component with at least that share of the most.
    """
    rules: list[NamedInCodeRule] = []
    for item in _structural_items(configs, "named_in_code", ("owner", "named", "relationship")):
        _check_rule("named_in_code", item, item["owner"], item["relationship"], item["named"])
        min_names = item.get("min_names", 2)
        if not isinstance(min_names, int) or isinstance(min_names, bool) or min_names < 1:
            raise ValueError(f"params.named_in_code rule {item!r}: min_names must be a whole number of at least 1")
        share = item.get("share", 1.0)
        if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share <= 1:
            raise ValueError(f"params.named_in_code rule {item!r}: share must be a number above 0 and at most 1")
        rules.append(NamedInCodeRule(owner=item["owner"], named=item["named"], relationship=item["relationship"], min_names=min_names, share=float(share)))
    return rules


def _component_services_config(params: str | None) -> ComponentServicesConfig | None:
    """Services per offering component (``params.component_services``).

    ``{"component_services": {"min_names": 3, "share": 0.5, "overlap": 0.5, "max_doc_lines": 12}}``
    switches it on: one service per group of components that expose an interface (grouped by the
    business objects their code names), named in one call each from structure and documentation;
    the step's graph query is then not used. Without the key the step derives from graph candidates.
    ``interface_links`` and ``object_links`` list graph queries returning source node id pairs
    (``a``: the component's, ``b``: the interface's or object's) that give a component its
    interfaces and objects where the graph links them. ``group_by: "members"`` groups the
    interfaces' members instead; ``ubiquity``, ``member_min_names`` and ``max_groups`` apply only there.
    """
    settings = json.loads(params).get("component_services") if params else None
    if settings is None:
        return None
    if not isinstance(settings, dict):
        raise ValueError(f"params.component_services must be an object, got {settings!r}")
    defaults = ComponentServicesConfig()
    min_names, max_doc_lines = settings.get("min_names", defaults.min_names), settings.get("max_doc_lines", defaults.max_doc_lines)
    share, overlap = settings.get("share", defaults.share), settings.get("overlap", defaults.overlap)
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= minimum for n, minimum in ((min_names, 1), (max_doc_lines, 0))):
        raise ValueError("params.component_services: min_names is a whole number of at least 1, max_doc_lines of at least 0")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 < x <= 1 for x in (share, overlap)):
        raise ValueError("params.component_services: share and overlap are numbers above 0 and at most 1")
    for key in ("interface_links", "object_links"):
        if not isinstance(settings.get(key, []), list) or not all(isinstance(q, str) and q for q in settings.get(key, [])):
            raise ValueError(f"params.component_services.{key} must be a list of graph queries")
    ubiquity = settings.get("ubiquity", defaults.ubiquity)
    if not isinstance(ubiquity, (int, float)) or isinstance(ubiquity, bool) or not 0 < ubiquity <= 1:
        raise ValueError("params.component_services: ubiquity is a number above 0 and at most 1")
    group_by = settings.get("group_by", defaults.group_by)
    member_min_names, max_groups = settings.get("member_min_names", defaults.member_min_names), settings.get("max_groups", defaults.max_groups)
    if group_by not in ("components", "members", "unit"):
        raise ValueError(f"params.component_services.group_by is 'components', 'members' or 'unit', not {group_by!r}")
    whole = {k: settings.get(k, getattr(defaults, k)) for k in ("min_members", "max_per_component", "min_family", "max_candidates")}
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in whole.values()):
        raise ValueError(f"params.component_services: {sorted(whole)} are whole numbers of at least 1")
    max_hops = settings.get("max_hops", defaults.max_hops)
    markers = settings.get("endpoint_markers", [])
    if not isinstance(max_hops, int) or isinstance(max_hops, bool) or max_hops < 0 or not isinstance(markers, list) or not all(isinstance(m, str) and m for m in markers):
        raise ValueError("params.component_services: max_hops is a whole number of at least 0, endpoint_markers a list of patterns")
    for marker in markers:
        try:
            re.compile(marker)
        except re.error as exc:
            raise ValueError(f"params.component_services: endpoint marker {marker!r} is no valid pattern: {exc}") from exc
    words = {
        k: settings.get(k, list(getattr(defaults, k)))
        for k in ("kind_words", "generic_names", "service_templates", "function_templates", "function_nouns", "activity_words", "activity_suffixes")
    }
    if not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v) for v in words.values()):
        raise ValueError(f"params.component_services: {sorted(words)} are lists of strings")
    if any("{object}" not in t for t in words["service_templates"] + words["function_templates"]):
        raise ValueError("params.component_services: name templates hold {object}")
    if group_by == "unit" and not isinstance(settings.get("choose_instruction"), str):
        raise ValueError("params.component_services.choose_instruction (the closed-set naming instruction) is needed for group_by 'unit'")
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= minimum for n, minimum in ((member_min_names, 1), (max_groups, 0))):
        raise ValueError("params.component_services: member_min_names is a whole number of at least 1, max_groups of at least 0")
    business_functions = settings.get("business_functions", defaults.business_functions)
    if not isinstance(business_functions, bool):
        raise ValueError(f"params.component_services.business_functions must be true or false, got {business_functions!r}")
    return ComponentServicesConfig(
        **whole,
        **{k: tuple(v) for k, v in words.items()},
        max_hops=max_hops,
        endpoint_markers=tuple(markers),
        choose_instruction=str(settings.get("choose_instruction") or ""),
        group_by=group_by,
        ubiquity=float(ubiquity),
        member_min_names=member_min_names,
        max_groups=max_groups,
        min_names=min_names,
        share=float(share),
        overlap=float(overlap),
        max_doc_lines=max_doc_lines,
        interface_links=tuple(settings.get("interface_links", [])),
        object_links=tuple(settings.get("object_links", [])),
        business_functions=business_functions,
    )


def _documentation_files(graph_manager: GraphManager, max_bytes: int = 200_000) -> dict[str, str]:
    """Repository path -> text of the repository's documentation files (file type docs), read from the checkout."""
    root = workspace() / "repositories"
    documents: dict[str, str] = {}
    for row in graph_manager.query("MATCH (f:Graph:File) WHERE f.active = true AND f.fileType = 'docs' RETURN f.filePath AS path"):
        path = str(row.get("path") or "").replace(chr(92), "/")
        file = root / path
        try:
            # A link that leads out of the checkout is not followed: its text would go to the model
            if path and file.is_file() and file.resolve().is_relative_to(root.resolve()) and file.stat().st_size <= max_bytes:
                documents[path] = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return documents


def _component_services_step(
    config: ComponentServicesConfig,
    instruction: str,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[..., Any],
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive and store the services the components offer; the result has the shape of ``generate_element``'s."""
    # Member and object links are pairs (no channel)
    interface_links = [(link[0], link[1]) for query in config.interface_links for link in graph_link_pairs(graph_manager, query)]
    object_links = [(link[0], link[1]) for query in config.object_links for link in graph_link_pairs(graph_manager, query)]
    if config.group_by == "unit":
        nodes = {str(m.get("source")) for e in elements for m in (e.get("properties") or {}).get("members") or [] if m.get("source")}
        nodes |= {a for a, _ in interface_links} | {a for a, _ in object_links}
        domains = graph_manager.query("MATCH (d:Graph:DataDomain) WHERE d.active = true RETURN d.id AS id, d.name AS name, d.businessObject AS bo, d.exception AS exception")
        bases: dict[str, set[str]] = defaultdict(set)
        for row in graph_manager.query("MATCH (t:Graph:TypeDefinition)-[:`Graph:INHERITS`]->(b) RETURN t.id AS t, b.typeName AS name, b.id AS id"):
            if row.get("t"):
                bases[row["t"]].add(str(row.get("name") or str(row.get("id") or "").split("::")[-1]))
        cooperation = graph_manager.query(
            "MATCH (a:Graph:DeployableUnit)-[r]->(b:Graph:DeployableUnit) WHERE type(r) IN ['Graph:CONSUMES', 'Graph:SENDS_TO'] "
            "RETURN DISTINCT a.id AS a, b.id AS b, type(r) AS kind"
        )
        lines = {(row["a"], row["b"]) for row in cooperation}
        consumes = {(row["a"], row["b"]) for row in cooperation if str(row.get("kind") or "").endswith("CONSUMES")}
        norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
        type_names: dict[str, set[str]] = defaultdict(set)
        for row in graph_manager.query("MATCH (t:Graph:TypeDefinition) WHERE t.active = true RETURN t.filePath AS path, t.typeName AS name"):
            if row.get("path") and row.get("name"):
                type_names[norm(row["path"])].add(name_key(str(row["name"])))
        domain_names: dict[str, set[str]] = defaultdict(set)
        for row in graph_manager.query(
            "MATCH (d:Graph:DataDomain)-[:`Graph:INCLUDES`]->(m) OPTIONAL MATCH (m)-[:`Graph:INCLUDES`]->(t:Graph:TypeDefinition) "
            "RETURN d.id AS d, m.name AS entity, m.typeName AS member, t.typeName AS type"
        ):
            for value in (row.get("entity"), row.get("member"), row.get("type")):
                if value:
                    domain_names[str(row["d"])].add(name_key(str(value)))
        # Endpoint types: a type whose own or whose methods' decorators match a marker, in the unit that includes its file
        endpoint_types: dict[str, tuple[str, str]] = {}
        if config.endpoint_markers:
            marker = re.compile("|".join(f"(?:{m})" for m in config.endpoint_markers))
            for row in graph_manager.query(
                "MATCH (t:Graph:TypeDefinition) WHERE t.active = true RETURN t.id AS id, t.typeName AS name, t.filePath AS path, t.decorators AS decorators"
            ):
                if any(marker.fullmatch(str(d)) for d in row.get("decorators") or []):
                    endpoint_types[row["id"]] = (str(row["name"]), norm(row["path"]))
            for row in graph_manager.query(
                "MATCH (t:Graph:TypeDefinition)-[:`Graph:CONTAINS`]->(m:Graph:Method) RETURN t.id AS id, t.typeName AS name, t.filePath AS path, m.decorators AS decorators"
            ):
                if any(marker.fullmatch(str(d)) for d in row.get("decorators") or []):
                    endpoint_types[row["id"]] = (str(row["name"]), norm(row["path"]))
        scopes = unit_scopes(graph_manager)
        endpoints: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for node, (type_name, path) in sorted(endpoint_types.items()):
            for unit, unit_files in scopes.files.items():
                if path in unit_files:
                    endpoints[unit].append((node, type_name))
                    nodes.add(node)
        lifecycle_rows = graph_manager.query("MATCH (l:Graph:Lifecycle) WHERE l.active = true RETURN l.id AS id, l.sites AS sites, l.stateSites AS stateSites")
        services, functions = derive_unit_services(
            elements,
            element_source_paths(graph_manager, [{"properties": {"source": n}} for n in sorted(nodes)]),
            file_imports(graph_manager),
            config,
            config.choose_instruction,
            llm_query_fn,
            scopes=scopes,
            deciding={str(r["id"]) for r in domains if r.get("bo") or r.get("exception")},
            business_objects={str(r["id"]): str(r["bo"]) for r in domains if r.get("bo")},
            bases=dict(bases),
            lines=lines,
            documents=_documentation_files(graph_manager),
            member_links=interface_links,
            object_links=object_links,
            type_names=dict(type_names),
            domain_names=dict(domain_names),
            endpoints=dict(endpoints),
            domain_anchors={str(r["id"]): str(r["name"]) for r in domains if r.get("name")},
            consumes=consumes,
            lifecycle_sites={str(r["id"]): {norm(p) for p in r.get("sites") or []} for r in lifecycle_rows},
            lifecycle_state_sites={str(r["id"]): _state_sites(r.get("stateSites") or [], norm) for r in lifecycle_rows},
        )
        return _stored_services(services + functions, archimate_manager)
    if config.group_by == "members":
        # The paths of the interfaces' members, of the nodes linked to them and of the objects' sources
        nodes = {str(m.get("source")) for e in elements for m in (e.get("properties") or {}).get("members") or [] if m.get("source")}
        nodes |= {a for a, _ in interface_links} | {a for a, _ in object_links}
        nodes |= {src for e in elements if (src := (e.get("properties") or {}).get("source"))}
        services = derive_member_services(
            elements,
            element_source_paths(graph_manager, [{"properties": {"source": n}} for n in sorted(nodes)]),
            file_imports(graph_manager),
            code_names_with_paths(graph_manager),
            # The member services' prompts read no documentation (yet): nothing is read from the checkout
            {},
            config,
            instruction,
            llm_query_fn,
            source_concept_names(graph_manager, elements),
            member_links=interface_links,
            object_links=object_links,
            scopes=unit_scopes(graph_manager),
        )
        return _stored_services(services, archimate_manager)
    services = derive_component_services(
        elements,
        element_source_paths(graph_manager, elements),
        code_names_with_paths(graph_manager),
        _documentation_files(graph_manager),
        config,
        instruction,
        llm_query_fn,
        source_concept_names(graph_manager, elements),
        interface_links=interface_links,
        object_links=object_links,
    )
    return _stored_services(services, archimate_manager)


@dataclass(frozen=True)
class FunctionModelConfig:
    """A supplied business function model the services are classified into (element config ``params.function_model``)."""

    name: str  # Names the model in the element identities (function::<name>::<id>)
    path: str  # The CSV file: a bundled model's file name, or a path to a user-supplied file
    exclude: tuple[str, ...] = ()  # Function ids left out of the closed set, with everything below them
    levels: int = 2
    batch_size: int = 10  # Services per classification call
    # Which services are classified: "business" (their data includes a business domain) or "data_or_endpoints"
    # (their component has a data object, or they offer endpoint operations; never a purely technical service)
    services: str = "business"
    evidence: EvidenceRules = EvidenceRules()


def _function_model_config(params: str | None) -> FunctionModelConfig | None:
    """``{"function_model": {"name": "pcf-8.0", "path": "pcf-8.0-cross-industry.csv", "exclude": ["20607"], "batch_size": 10,
    "services": "data_or_endpoints", "evidence": {"operation_patterns": [...], "summary_patterns": [...], "header_fields": [...],
    "technical_words": [...], "max_operations": 15, "max_members": 20, "max_doc_chars": 500, "max_notes": 5}}}``."""
    settings = json.loads(params).get("function_model") if isinstance(params, str) and params else None
    if settings is None:
        return None
    if not isinstance(settings, dict) or not isinstance(settings.get("name"), str) or not settings["name"] or not isinstance(settings.get("path"), str) or not settings["path"]:
        raise ValueError("params.function_model needs a name and a path (strings)")
    exclude = settings.get("exclude", [])
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise ValueError("params.function_model.exclude is a list of function ids")
    levels, batch = settings.get("levels", 2), settings.get("batch_size", 10)
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in (levels, batch)) or levels > 2:
        raise ValueError("params.function_model: levels is 1 or 2, batch_size a whole number of at least 1")
    services = settings.get("services", "business")
    if services not in ("business", "data_or_endpoints"):
        raise ValueError(f"params.function_model.services is 'business' or 'data_or_endpoints', not {services!r}")
    raw = settings.get("evidence", {})
    if not isinstance(raw, dict):
        raise ValueError("params.function_model.evidence must be an object")
    defaults = EvidenceRules()
    lists = {k: raw.get(k, list(getattr(defaults, k))) for k in ("operation_patterns", "summary_patterns", "header_fields", "technical_words", "member_links")}
    if not all(isinstance(v, list) and all(isinstance(x, str) and x for x in v) for v in lists.values()):
        raise ValueError(f"params.function_model.evidence: {sorted(lists)} are lists of strings")
    for pattern in lists["operation_patterns"] + lists["summary_patterns"]:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"params.function_model.evidence: {pattern!r} is no valid pattern: {exc}") from exc
    caps = {k: raw.get(k, getattr(defaults, k)) for k in ("max_operations", "max_members", "max_doc_chars", "max_notes")}
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in caps.values()):
        raise ValueError(f"params.function_model.evidence: {sorted(caps)} are whole numbers of at least 0")
    return FunctionModelConfig(
        name=settings["name"],
        path=settings["path"],
        exclude=tuple(exclude),
        levels=levels,
        batch_size=batch,
        services=services,
        evidence=EvidenceRules(
            operation_patterns=tuple(lists["operation_patterns"]),
            summary_patterns=tuple(lists["summary_patterns"]),
            header_fields=tuple(lists["header_fields"]),
            technical_words=tuple(lists["technical_words"]),
            member_links=tuple(lists["member_links"]),
            max_operations=caps["max_operations"],
            max_members=caps["max_members"],
            max_doc_chars=caps["max_doc_chars"],
            max_notes=caps["max_notes"],
        ),
    )


def _function_model_file(path: str) -> Path:
    """The model file: a bundled model by its file name, else the path as given (absolute or from the working directory)."""
    from deriva.adapters.database import FUNCTION_MODELS_DIR

    bundled = FUNCTION_MODELS_DIR / path
    found = bundled if not Path(path).is_absolute() and bundled.is_file() else Path(path)
    if not found.is_file():
        raise ValueError(f"params.function_model.path: no function model file {path!r} (bundled in {FUNCTION_MODELS_DIR} or a path)")
    return found


def _checkout_text(path: str, max_bytes: int = 200_000) -> str:
    """A repository file's text from the checkout ("" when missing, too large, or outside the checkout)."""
    root = workspace() / "repositories"
    file = root / path
    try:
        if path and file.is_file() and file.resolve().is_relative_to(root.resolve()) and file.stat().st_size <= max_bytes:
            return file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _member_evidence(graph_manager: GraphManager, members: list[str], rules: EvidenceRules) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Member node -> its endpoint operations, and member node -> the named fields of its file's header comment."""
    if not members:
        return {}, {}
    norm = lambda p: str(p or "").replace(chr(92), "/")  # noqa: E731 - a one-line helper
    paths = element_source_paths(graph_manager, [{"properties": {"source": m}} for m in members])
    type_rows = graph_manager.query("MATCH (t:Graph:TypeDefinition) WHERE t.id IN $ids RETURN t.id AS id, t.decorators AS decorators, t.typeName AS name", {"ids": members})
    type_decorators = {str(r["id"]): list(r.get("decorators") or []) for r in type_rows}
    type_names = {str(r["id"]): str(r.get("name") or "") for r in type_rows}
    # Nodes that describe a member (a program and the screen it sends): their header notes count for the member
    describing: dict[str, set[str]] = defaultdict(set)
    for query in rules.member_links:
        for a, b, *_ in graph_link_pairs(graph_manager, query):
            describing[b].add(a)
    linked_paths = element_source_paths(graph_manager, [{"properties": {"source": n}} for n in sorted({n for ns in describing.values() for n in ns})])
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in graph_manager.query(
        "MATCH (t:Graph:TypeDefinition)-[:`Graph:CONTAINS`]->(m:Graph:Method) WHERE t.id IN $ids "
        "RETURN t.id AS t, m.methodName AS name, m.decorators AS decorators, m.startLine AS line",
        {"ids": members},
    ):
        by_type[str(r["t"])].append(r)
    files = {m: paths[m] for m in members if m not in type_decorators and m in paths}
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if files:
        for r in graph_manager.query(
            "MATCH (m:Graph:Method) WHERE m.active = true RETURN m.filePath AS path, m.methodName AS name, m.decorators AS decorators, m.startLine AS line"
        ):
            by_file[norm(r.get("path"))].append(r)
    operations: dict[str, list[str]] = {}
    notes: dict[str, list[str]] = {}
    for member in members:
        methods = by_type.get(member) if member in type_decorators else by_file.get(norm(files.get(member)), [])
        ordered = sorted(methods or [], key=lambda r: (int(r.get("line") or 0), str(r.get("name") or "")))
        operations[member] = operations_of(
            [{"name": r.get("name"), "decorators": r.get("decorators")} for r in ordered], type_decorators.get(member, []), rules, type_name=type_names.get(member, "")
        )
        sources = [paths.get(member, "")] + sorted(linked_paths.get(n, "") for n in describing.get(member, ()))
        notes[member] = list(dict.fromkeys(note for path in sources if path for note in header_notes(_checkout_text(path), rules)))
    return operations, notes


def _function_model_step(
    config: FunctionModelConfig,
    instruction: str,
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    llm_query_fn: Callable[..., Any],
    elements: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify the services into the function model, level by level, and store the chosen functions; the result
    has the shape of ``generate_element``'s. Which services and what evidence: ``config.services`` and ``config.evidence``."""
    rules = config.evidence
    model = parse_function_model(_function_model_file(config.path).read_text(encoding="utf-8"), config.name, config.exclude, max_level=config.levels)
    business = {str(r["id"]) for r in graph_manager.query("MATCH (d:Graph:DataDomain) WHERE d.active = true RETURN d.id AS id, d.businessObject AS bo") if r.get("bo")}
    data_objects = {e["identifier"]: e for e in elements if e.get("element_type") == "DataObject"}
    roles = {e["identifier"]: str((e.get("properties") or {}).get("role") or "") for e in elements if e.get("element_type") == "ApplicationInterface"}
    unit_rows = graph_manager.query("MATCH (u:Graph:DeployableUnit) RETURN u.id AS id, u.name AS name, u.path AS path")
    units = {str(r["id"]): str(r["name"]) for r in unit_rows if r.get("name")}
    documents = _documentation_files(graph_manager) if config.services == "data_or_endpoints" else {}
    unit_docs = {
        str(r["id"]): component_documentation(str(r.get("path") or "").replace(chr(92), "/").rstrip("/"), str(r.get("name") or ""), documents, rules.max_doc_chars)
        for r in unit_rows
    }
    lifecycles = {str(r["id"]): str(r["name"]) for r in graph_manager.query("MATCH (l:Graph:Lifecycle) WHERE l.active = true RETURN l.id AS id, l.name AS name")}
    services = sorted((e for e in elements if e.get("element_type") == "ApplicationService"), key=lambda e: e["identifier"])
    with_data = {str(((e.get("properties") or {}).get("sources") or [""])[0]) for e in services if (e.get("properties") or {}).get("objects")}
    member_ids = sorted({str(m.get("source")) for e in services for m in (e.get("properties") or {}).get("members") or [] if m.get("source")})
    member_ops, member_notes = _member_evidence(graph_manager, member_ids, rules) if config.services == "data_or_endpoints" else ({}, {})
    items: list[ServiceItem] = []
    processes: dict[str, list[str]] = {}
    for service in services:
        props = service.get("properties") or {}
        objects = [data_objects[o] for o in props.get("objects") or [] if o in data_objects]
        touches_business = any(str((o.get("properties") or {}).get("source") or "") in business for o in objects)
        unit = str((props.get("sources") or [""])[0])
        members = sorted(props.get("members") or [], key=lambda m: (str(m.get("name") or ""), str(m.get("source") or "")))
        operations = [op for m in members for op in member_ops.get(str(m.get("source")), [])]
        member_names = [str(m.get("name") or "") for m in members]
        if config.services == "business":
            if not touches_business:
                continue  # Only a service that touches a business domain names a business function
        elif not touches_business and (is_technical(operations, member_names, rules) or not (unit in with_data or operations)):
            continue  # A purely technical service, or one without data and endpoints, names no business function
        states = []
        for entry in props.get("states") or []:
            life, _, state = str(entry).rpartition("::")
            states.append(f"{lifecycles.get(life, life)}: {state}")
        notes = list(dict.fromkeys(n for m in members for n in member_notes.get(str(m.get("source")), [])))[: rules.max_notes]
        items.append(
            ServiceItem(
                key=service["identifier"],
                component=units.get(unit, unit.rsplit("::", 1)[-1]),
                members=member_names[: rules.max_members],
                data=sorted(str(o["name"]) for o in objects),
                processes=sorted(lifecycles.get(str(p), str(p)) for p in props.get("processes") or []),
                interfaces=sorted({roles[i] for i in props.get("interfaces") or [] if roles.get(i)}) if config.services == "data_or_endpoints" else [],
                operations=shown_operations(operations, rules)[: rules.max_operations],
                states=states if config.services == "data_or_endpoints" else [],
                documentation=unit_docs.get(unit, "") if config.services == "data_or_endpoints" else "",
                notes=notes,
            )
        )
        processes[service["identifier"]] = list(props.get("processes") or [])
    decisions = classify_services(items, model, instruction, llm_query_fn, config.batch_size)
    result = _stored_services(function_elements(decisions, model, processes), archimate_manager)
    result["function_decisions"] = decisions
    return result


def _state_sites(rows: list[str], norm: Callable[[str], str]) -> dict[str, set[str]]:
    """State -> the files that set it, from a lifecycle's "STATE>path" entries."""
    found: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        state, _, path = str(row).partition(">")
        if path:
            found[state].add(norm(path))
    return dict(found)


def _stored_services(services: list[dict[str, Any]], archimate_manager: ArchimateManager) -> dict[str, Any]:
    """Store the derived services; the result has the shape of ``generate_element``'s."""
    errors: list[str] = []
    created: list[dict[str, Any]] = []
    for service in services:
        try:
            archimate_manager.add_element(
                Element(
                    name=service["name"],
                    element_type=service["element_type"],
                    identifier=service["identifier"],
                    documentation=service.get("documentation"),
                    properties=service["properties"],
                )
            )
            created.append(service)
        except Exception as exc:
            errors.append(f"Failed to create service {service['name']}: {exc}")
    return {
        "success": not errors,
        "elements_created": len(created),
        "relationships_created": 0,
        "created_elements": created,
        "created_relationships": [],
        "candidate_decisions": [],
        "errors": errors,
    }


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
    decorators = settings.get("decorators")
    if decorators is not None:
        if not isinstance(decorators, str) or not decorators:
            raise ValueError(f"params.per_candidate.decorators must be a non-empty pattern, got {decorators!r}")
        try:
            re.compile(decorators)
        except re.error as e:
            raise ValueError(f"params.per_candidate.decorators is not a valid pattern: {e}") from e
    return PerCandidateConfig(min_pool=int(settings["min_pool"]), rules=settings["rules"], persona=settings["persona"], decorators=decorators)


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
    guards = settings.get("guards", {})
    if not isinstance(guards, dict):
        raise ValueError("params.naming.guards must be an object")
    words, nouns, labels = guards.get("generic_words", []), guards.get("kind_nouns", {}), guards.get("reserved_labels", [])
    if (
        not isinstance(words, list)
        or not all(isinstance(w, str) and w for w in words)
        or not isinstance(nouns, dict)
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in nouns.items())
        or not isinstance(labels, list)
        or not all(isinstance(label, str) and label for label in labels)
    ):
        raise ValueError("params.naming.guards: generic_words and reserved_labels are lists of strings, kind_nouns maps a unit kind to a noun")
    choose = settings.get("choose_instruction", "")
    if not isinstance(choose, str):
        raise ValueError("params.naming.choose_instruction is the instruction text of closed-set naming (a string)")
    return NamingConfig(
        instruction=settings["instruction"],
        samples=int(settings.get("samples", 1)),
        choose_instruction=choose,
        guards=NameGuards(generic_words=frozenset(w.lower() for w in words), kind_nouns=dict(nouns), reserved_labels=tuple(labels)),
    )


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
    (optional ``documentation`` template, ``missing_retries`` and ``element_per``: "role",
    "candidate" or "unit"; with "candidate" also ``name_template``, ``container_type`` and
    ``show_path``; "unit" needs a ``container_type`` and a ``name_template`` with ``{container}``
    and may list ``unit_roles``; ``structural``: ``[{"property": "decorators", "pattern": "...", "role": key}]``,
    roles the source itself shows, given without a call); without the key every candidate takes
    the keep and naming path.
    """
    settings = json.loads(params).get("roles") if params else None
    if settings is None:
        return None
    classified = settings.get("labels") and settings.get("instruction")
    if not settings.get("names") or not (classified or settings.get("structural")) or bool(settings.get("labels")) != bool(settings.get("instruction")):
        raise ValueError("params.roles needs names and either labels with an instruction (classified roles) or structural rules")
    element_per = settings.get("element_per", "role")
    if element_per not in ("role", "candidate", "unit"):
        raise ValueError(f"params.roles.element_per must be 'role', 'candidate' or 'unit', not {element_per!r}")
    if element_per == "unit" and (not settings.get("container_type") or "{container}" not in str(settings.get("name_template", ""))):
        raise ValueError("params.roles.element_per 'unit' names one element per deployable unit and role: it needs a container_type and a name_template with {container}")
    name_template = settings.get("name_template", "")
    container_type = settings.get("container_type", "")
    show_path = settings.get("show_path", False)
    if not isinstance(name_template, str) or not isinstance(container_type, str) or not isinstance(show_path, bool):
        raise ValueError("params.roles name_template and container_type must be text, show_path true or false")
    if name_template and element_per not in ("candidate", "unit"):
        raise ValueError("params.roles.name_template names one element per candidate or per unit: it needs element_per 'candidate' or 'unit'")
    naming_call, structural_as_written = settings.get("naming_call", False), settings.get("structural_as_written", False)
    if not isinstance(naming_call, bool) or not isinstance(structural_as_written, bool):
        raise ValueError(f"params.roles naming_call and structural_as_written must be true or false, got {naming_call!r} and {structural_as_written!r}")
    if naming_call and (element_per != "candidate" or not json.loads(params or "{}").get("naming")):
        raise ValueError("params.roles.naming_call renames one element per candidate with the step's naming call: it needs element_per 'candidate' and params.naming")
    structural = settings.get("structural", [])
    if not isinstance(structural, list) or not all(
        isinstance(rule, dict) and all(isinstance(rule.get(k), str) and rule.get(k) for k in ("property", "pattern", "role")) and rule["role"] in settings["names"]
        for rule in structural
    ):
        raise ValueError(f"params.roles.structural rules need property, pattern and a role key of names, got {structural!r}")
    for rule in structural:
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            raise ValueError(f"params.roles.structural pattern {rule['pattern']!r} is no valid pattern: {exc}") from exc
    unit_roles = settings.get("unit_roles", [])
    # The property is read in a graph query, so it is a plain property name
    if not isinstance(unit_roles, list) or not all(
        isinstance(rule, dict)
        and all(isinstance(rule.get(k), str) and rule.get(k) for k in ("property", "role"))
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rule["property"])
        and rule["role"] in settings["names"]
        for rule in unit_roles
    ):
        raise ValueError(f"params.roles.unit_roles rules need a unit property (a plain property name) and a role key of names, got {unit_roles!r}")
    if unit_roles and element_per != "unit":
        raise ValueError("params.roles.unit_roles are roles a deployable unit shows itself: they need element_per 'unit'")
    name_priority = settings.get("name_priority", [])
    if not isinstance(name_priority, list) or not all(isinstance(label, str) and label for label in name_priority):
        raise ValueError(f"params.roles.name_priority is a list of graph labels, got {name_priority!r}")
    return RoleConfig(
        name_priority=tuple(name_priority),
        unit_roles=tuple((rule["property"], rule["role"]) for rule in unit_roles),
        structural=tuple((rule["property"], rule["pattern"], rule["role"]) for rule in structural),
        labels=frozenset(settings.get("labels") or []),
        instruction=settings.get("instruction") or "",
        names=dict(settings["names"]),
        documentation=settings.get("documentation", ""),
        missing_retries=int(settings.get("missing_retries", 0)),
        element_per=element_per,
        name_template=name_template,
        container_type=container_type,
        show_path=show_path,
        naming_call=naming_call,
        structural_as_written=structural_as_written,
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
    enrichments: dict[str, dict[str, Any]] | None = None,
    relationship_config: RelationshipLLMConfig | None = None,
    per_candidate: PerCandidateConfig | None = None,
    naming: NamingConfig | None = None,
    pattern_labels: frozenset[str] | None = None,
    name_match_skip: set[tuple[str, str]] | None = None,
    roles: RoleConfig | None = None,
    skip_when_directory_is: frozenset[str] | None = None,
    prompt: ElementPrompt | None = None,
    graph_filter: GraphFilter | None = None,
    skip_subtypes: bool = False,
    skip_nested: NestedFilter | None = None,
    deployable_units: UnitFilter | None = None,
    on_candidates: Callable[[list[str]], None] | None = None,
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
        enrichments: The run's graph enrichment values by node id (read from the graph when None)
        relationship_config: Relationship config row settings (None skips the LLM relationship pass)
        per_candidate: Per-candidate naming mode from the element config (None uses batch mode)
        naming: Isolated naming step from the element config (None keeps structure names)
        pattern_labels: Labels of the candidates the name patterns filter (None: every candidate)
        name_match_skip: (source type, target type) pairs the per-batch name matching never links (``params.name_match_skip``)
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
            enrichments=enrichments,
            relationship_config=relationship_config,
            name_match_skip=name_match_skip,
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
            on_candidates=on_candidates,
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

JOINT_STEP = "joint_consistency"


def _model_signature(archimate_manager: Any) -> tuple[frozenset[str], frozenset[tuple[str, str, str, str]]]:
    """The enabled elements and the relationships of the model (identities only; properties such as tags may change)."""
    elements = frozenset(str(e.identifier) for e in archimate_manager.get_elements(enabled_only=True))
    relationships = frozenset((str(r.identifier), str(r.source), str(r.relationship_type), str(r.target)) for r in archimate_manager.get_relationships())
    return elements, relationships


def _relationship_keys(archimate_manager: Any) -> set[tuple[str, str, str]]:
    """(type, source, target) of every relationship in the model: the run log's relationship identity."""
    return {(str(r.relationship_type), str(r.source), str(r.target)) for r in archimate_manager.get_relationships()}


class _SelectionGuard:
    """Nothing changes the model after the joint selection: a refine step after joint_consistency that adds or removes
    an element or a relationship is an error of the run (it may only annotate)."""

    def __init__(self) -> None:
        self.selected: tuple[frozenset[str], frozenset[tuple[str, str, str, str]]] | None = None

    def check(self, step_name: str, archimate_manager: Any) -> str | None:
        if self.selected is None and step_name != JOINT_STEP:
            return None
        now = _model_signature(archimate_manager)
        if step_name == JOINT_STEP:
            self.selected = now
            return None
        assert self.selected is not None
        (elements, relationships), (before_elements, before_relationships) = now, self.selected
        if (elements, relationships) == (before_elements, before_relationships):
            return None
        self.selected = now
        return (
            f"Refine step {step_name} changed the model after the joint selection: elements +{len(elements - before_elements)}/-{len(before_elements - elements)}, "
            f"relationships +{len(relationships - before_relationships)}/-{len(before_relationships - relationships)}"
        )


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


def _graph_metrics(graph_manager: GraphManager, algorithm: str, params: dict[str, Any]) -> prep.GraphMetrics:
    """Run one prep algorithm natively in grafeo on the graph namespace; its raw values by node id.

    PageRank runs on the undirected graph (each connected pair once), like the structural
    importance the derivation steps expect; config params keep their names (``max_iter``, ``tol``).
    """
    if algorithm == "pagerank":
        metric = graph_manager.graph_metric(
            "pagerank",
            directed=False,
            damping=params.get("damping", 0.85),
            max_iterations=params.get("max_iter", 100),
            tolerance=params.get("tol", 1e-6),
        )
        values = {"pagerank": metric["values"]}
    elif algorithm == "louvain":
        metric = graph_manager.graph_metric("louvain", resolution=params.get("resolution", 1.0))
        values = {"communities": metric["values"]}
    elif algorithm == "kcore":
        metric = graph_manager.graph_metric("kcore")
        values = {"core_levels": metric["values"]}
    elif algorithm == "articulation_points":
        metric = graph_manager.graph_metric("articulation_points")
        values = {"articulation_points": metric["values"]}
    elif algorithm == "degree":
        metric = graph_manager.graph_metric("degree_centrality")
        values = {"degrees": metric["values"]}
    else:
        raise ValueError(f"Unknown prep algorithm: {algorithm}")
    return prep.GraphMetrics(node_ids=metric["node_ids"], edge_count=metric["edge_count"], **values)


class _RunEnrichments:
    """The graph enrichment values of one derivation run.

    Prep steps write the values onto the graph nodes; the element steps read them through
    this holder: once, and again after any prep step, so a run never reads values that an
    earlier run, another solver version or other prep parameters produced.
    """

    def __init__(self, graph_manager: GraphManager):
        self._graph_manager = graph_manager
        self._values: dict[str, dict[str, Any]] | None = None

    def get(self) -> dict[str, dict[str, Any]]:
        if self._values is None:
            self._values = get_enrichments_from_graph(self._graph_manager)
        return self._values

    def invalidate(self) -> None:
        self._values = None


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

    # Parse params from config (invalid JSON falls back to the defaults)
    params: dict[str, Any] = {}
    if cfg.params:
        try:
            params = json.loads(cfg.params)
        except json.JSONDecodeError:
            params = {}

    logger.info(f"Running enrichment: {step_name} (algorithm: {algorithm})")

    try:
        # The algorithm runs natively in grafeo on the graph namespace
        metrics = _graph_metrics(graph_manager, algorithm, params)
        if not metrics.node_ids:
            logger.warning(f"Empty graph for enrichment step: {step_name}")
            return {"success": True, "stats": {"nodes_updated": 0}}

        result = prep.enrich_from_metrics(metrics, include_percentiles=True)
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


def _model_totals(archimate_manager: ArchimateManager) -> str:
    """The closing summary: what the model holds, counted as the studio's model stats count it. The step counters
    miss what refine steps add and delete (graph relationships, duplicates), so they stay in ``stats`` only."""
    return f"{len(archimate_manager.get_elements())} elements, {len(archimate_manager.get_relationships())} relationships in the model"


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

    # The graph enrichment values, read once per run and again after a prep step rewrote them
    enrichments = _RunEnrichments(graph_manager)

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
    if relationship_pass:
        total_steps += 1

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
            enrichments.invalidate()
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

            # Validate required config parameters (a function model step reads no candidates: only its instruction)
            try:
                function_model = _function_model_config(cfg.params)
            except ValueError as exc:
                function_model, missing_params = None, [str(exc)]
            else:
                missing_params = []
            if not cfg.instruction:
                missing_params.append("instruction")
            if function_model is None:
                if not cfg.input_graph_query:
                    missing_params.append("input_graph_query")
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

            try:
                assert cfg.instruction is not None
                component_services = _component_services_config(cfg.params) if cfg.element_type == "ApplicationService" else None
                if function_model is not None:
                    step_result = _function_model_step(function_model, cfg.instruction, graph_manager, archimate_manager, step_llm_query_fn, all_created_elements)
                elif component_services is not None:
                    step_result = _component_services_step(component_services, cfg.instruction, graph_manager, archimate_manager, step_llm_query_fn, all_created_elements)
                else:
                    # Type assertions for validated config (helps type checker)
                    assert cfg.input_graph_query is not None
                    assert cfg.example is not None
                    assert cfg.max_candidates is not None
                    assert cfg.batch_size is not None
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
                        enrichments=enrichments.get(),
                        relationship_config=relationship_config(),
                        name_match_skip=_name_match_skip(relationship_configs),
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
                    for element in step_created_elements:
                        if element.get("identifier"):
                            step_ctx.add_object(element["identifier"])
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
                same_name=_same_name_rules(relationship_configs),
                named_in_code=_named_in_code_rules(relationship_configs),
                listed_members=_listed_members_rules(relationship_configs),
                graph_links=_graph_link_rules(relationship_configs),
                name_match_skip=_name_match_skip(relationship_configs),
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
                for rel_data in relationships:
                    rel_ctx.add_relationship(f"{rel_data['relationship_type']}_{rel_data['source']}_{rel_data['target']}")
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

        guard = _SelectionGuard()
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

                # The relationships before the step: those it adds are named in the run log
                before = _relationship_keys(archimate_manager) if step_ctx else set()

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
                if refine_result.report is not None:
                    cast("dict[str, Any]", stats).setdefault("refine_reports", {})[cfg.step_name] = refine_result.report

                if step_ctx:
                    for relationship_type, source, target in sorted(_relationship_keys(archimate_manager) - before):
                        step_ctx.add_relationship(f"{relationship_type}_{source}_{target}")
                    step_ctx.complete()

                if progress:
                    msg = f"Refine: {refine_result.issues_found} issues"
                    if refine_result.elements_disabled > 0:
                        msg += f", {refine_result.elements_disabled} disabled"
                    progress.complete_step(msg)

                if refine_result.errors:
                    errors.extend(refine_result.errors)
                if changed := guard.check(cfg.step_name, archimate_manager):
                    errors.append(changed)

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
        msg = f"Derivation complete: {_model_totals(archimate_manager)}"
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
    on_candidates: Callable[[str, list[str]], None] | None = None,
) -> Iterator[ProgressUpdate]:
    """
    Run derivation pipeline as a generator, yielding progress updates.

    This is the generator version of run_derivation() the studio streams its
    updates to the browser as run events.

    Args:
        engine: DuckDB connection for config
        defer_relationships: If True, skip per-batch relationship derivation.
        graph_manager: Connected GraphManager for querying source nodes
        archimate_manager: Connected ArchimateManager for persistence
        llm_query_fn: Function to call LLM (prompt, schema) -> response
        enabled_only: Only run enabled derivation steps
        verbose: Print progress to stdout
        phases: List of phases to run ("prep", "generate", "refine")

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

    # The graph enrichment values, read once per run and again after a prep step rewrote them
    enrichments = _RunEnrichments(graph_manager)

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
    # The deferred relationship pass is a step of its own (it runs when the model has elements)
    if defer_relationships:
        total_steps += 1

    current_step = 0

    # Run prep phase
    if "prep" in phases:
        for cfg in prep_configs:
            current_step += 1

            if verbose:
                print(f"  Prep: {cfg.step_name}")

            result = _run_prep_step(cfg, graph_manager)
            enrichments.invalidate()
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

            # Validate required config parameters (a function model step reads no candidates: only its instruction)
            try:
                function_model = _function_model_config(cfg.params)
            except ValueError as exc:
                function_model, missing_params = None, [str(exc)]
            else:
                missing_params = []
            if not cfg.instruction:
                missing_params.append("instruction")
            if function_model is None:
                if not cfg.input_graph_query:
                    missing_params.append("input_graph_query")
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

            try:
                assert cfg.instruction is not None
                component_services = _component_services_config(cfg.params) if cfg.element_type == "ApplicationService" else None
                if function_model is not None:
                    step_result = _function_model_step(function_model, cfg.instruction, graph_manager, archimate_manager, step_llm_query_fn, all_created_elements)
                elif component_services is not None:
                    step_result = _component_services_step(component_services, cfg.instruction, graph_manager, archimate_manager, step_llm_query_fn, all_created_elements)
                else:
                    # Type assertions for validated config
                    assert cfg.input_graph_query is not None
                    assert cfg.example is not None
                    assert cfg.max_candidates is not None
                    assert cfg.batch_size is not None
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
                        enrichments=enrichments.get(),
                        relationship_config=relationship_config(),
                        name_match_skip=_name_match_skip(relationship_configs),
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
                        on_candidates=(lambda ids, step=cfg.step_name: on_candidates(step, ids)) if on_candidates else None,
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
                same_name=_same_name_rules(relationship_configs),
                named_in_code=_named_in_code_rules(relationship_configs),
                listed_members=_listed_members_rules(relationship_configs),
                graph_links=_graph_link_rules(relationship_configs),
                name_match_skip=_name_match_skip(relationship_configs),
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
        guard = _SelectionGuard()
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
                if refine_result.report is not None:
                    cast("dict[str, Any]", stats).setdefault("refine_reports", {})[cfg.step_name] = refine_result.report

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
                if changed := guard.check(cfg.step_name, archimate_manager):
                    errors.append(changed)

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
    final_message = _model_totals(archimate_manager)
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
