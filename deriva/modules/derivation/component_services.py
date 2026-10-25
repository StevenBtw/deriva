"""Application services from structure: the capability each component with an interface offers.

Which services exist, their identity and what they relate to come from the model and the graph:
a component offers something when an interface element lies in its directory; components whose
code names the same business objects are one service. The LLM writes only the capability name
and one sentence, from the components, interfaces and business objects involved and the
documentation lines that mention the components. Pure functions: the caller passes the paths,
code names, documents and the query function.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from deriva.common import current_timestamp
from deriva.common.json_utils import extract_json_from_response
from deriva.common.naming import name_key
from deriva.modules.derivation.base import (
    NamedInCodeRule,
    UnitScopes,
    build_choice_prompt,
    choice_schema,
    derive_named_in_code_relationships,
    element_identifier,
    extract_response_content,
)

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "ApplicationService"

SERVICE_SCHEMA: dict[str, Any] = {
    "name": "service_naming",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "documentation": {"type": "string"}},
        "required": ["name", "documentation"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class ComponentServicesConfig:
    """Services per offering component (element config ``params.component_services``)."""

    component_type: str = "ApplicationComponent"
    interface_type: str = "ApplicationInterface"
    object_type: str = "BusinessObject"
    min_names: int = 3  # Code names that make a component work on a business object (as params.named_in_code)
    share: float = 0.5  # ... and the share of the strongest component's names that also counts
    overlap: float = 0.5  # Shared part of two components' business objects (Jaccard) that makes them one service
    max_doc_lines: int = 12  # Documentation lines shown per service
    interface_links: tuple[str, ...] = ()  # Graph queries (a: component source, b: interface source)
    object_links: tuple[str, ...] = ()  # Graph queries (a: component source, b: object source)
    # "components": a service per group of offering components; "members": a service per group of the
    # interfaces' members (endpoints, screens, jobs), grouped across components by the objects they reach
    group_by: str = "components"
    # member_min_names, max_groups and ubiquity apply to group_by "members" only
    member_min_names: int = 1  # Code names carrying a business object's words that make a member reach it
    # At most this many services (0: no limit); the most similar groups merge first, groups that share no object never
    max_groups: int = 0
    # An object that at least this share of the members reach does not decide the grouping (1: only an object that every
    # member reaches is left out); a member that reaches only such objects groups by them
    ubiquity: float = 1.0
    # group_by "unit" (services per component, gap 3): a group of at least min_members members is a service of its own
    min_members: int = 2
    max_per_component: int = 3  # At most this many services per component; the most similar groups merge first
    min_family: int = 3  # Members that extend one base type, at least this many, are one service
    kind_words: tuple[str, ...] = ()  # Words a member's name drops for a service name candidate (Holder, Controller, ...)
    generic_names: tuple[str, ...] = ()  # Member names that never name a service (routes, index, main, ...)
    service_templates: tuple[str, ...] = ()  # Name candidates on the group's business object ("{object} Management")
    function_templates: tuple[str, ...] = ()  # Business function name candidates on its business object
    function_nouns: tuple[str, ...] = ()  # Documentation terms "<object words> <noun>" that name a business function
    max_candidates: int = 8  # Name candidates per service at most
    max_hops: int = 2  # Import hops a member's reach follows (routes -> services -> models)
    # Decorator patterns (full match) that make a type, or a type with such a method, an endpoint of its unit
    endpoint_markers: tuple[str, ...] = ()
    # Naming convention: a behaviour (service, function) is named as an activity, never by a bare object noun. A name
    # is an activity when its last word is in activity_words or ends in one of activity_suffixes (a gerund: "ing")
    activity_words: tuple[str, ...] = ()
    activity_suffixes: tuple[str, ...] = ()
    choose_instruction: str = ""  # The closed-set naming instruction (config text)
    # Business functions from shared domains of cooperating components (gap 3); off when a function model supplies them
    business_functions: bool = True


def _source(element: dict[str, Any]) -> str:
    return str((element.get("properties") or {}).get("source") or "")


def offering_components(
    elements: list[dict[str, Any]], source_paths: dict[str, str], config: ComponentServicesConfig, interface_links: list[tuple[str, str]] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Component identifier -> its interface elements: those a graph link gives it (``interface_links``:
    component source, interface source), else those in its directory (the nearest component above each interface)."""
    by_source: dict[str, list[str]] = defaultdict(list)
    for e in elements:
        if e.get("element_type") == config.component_type and _source(e):
            by_source[_source(e)].append(e["identifier"])
    owners: dict[str, set[str]] = defaultdict(set)  # interface source -> the components linked to it
    for a, b in interface_links or []:
        owners[b].update(by_source.get(a, []))
    components = sorted(
        ((path, e["identifier"]) for e in elements if e.get("element_type") == config.component_type and (path := source_paths.get(_source(e)))),
        key=lambda item: (-len(item[0]), item[1]),
    )
    offering: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for interface in sorted((e for e in elements if e.get("element_type") == config.interface_type), key=lambda e: e["identifier"]):
        if owners.get(_source(interface)):
            for owner in sorted(owners[_source(interface)]):
                offering[owner].append(interface)
            continue
        path = source_paths.get(_source(interface))
        owner = next((identifier for owner_path, identifier in components if path and (path == owner_path or path.startswith(owner_path + "/"))), None)
        if owner:
            offering[owner].append(interface)
    return dict(sorted(offering.items()))


def group_by_shared_objects(objects: dict[str, set[str]], overlap: float) -> list[list[str]]:
    """Components grouped by the business objects they work on: one group where the shared part
    of two components' objects (Jaccard) is at least ``overlap``, directly or through others.
    A component without objects is a group of its own."""
    names = sorted(objects)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            union = objects[a] | objects[b]
            if union and len(objects[a] & objects[b]) / len(union) >= overlap:
                parent[max(find(a), find(b))] = min(find(a), find(b))
    groups: dict[str, list[str]] = defaultdict(list)
    for name in names:
        groups[find(name)].append(name)
    return sorted(groups.values())


def _plain(line: str) -> str:
    return re.sub(r"^[#>*\-\s]+", "", line).strip()


def documentation_lines(component_path: str, documents: dict[str, str], max_lines: int) -> list[str]:
    """The lines that describe a component: those of the documents in its own directory first,
    then the lines of other documents that name its directory (as a word). Markup at the line
    start is dropped; at most ``max_lines`` lines."""
    lines: list[str] = []
    own = sorted(path for path in documents if path.rsplit("/", 1)[0] == component_path)
    for path in own:
        lines += [text for line in documents[path].splitlines() if (text := _plain(line))]
    name = re.escape(component_path.rsplit("/", 1)[-1])
    mention = re.compile(rf"(?<![A-Za-z0-9]){name}(?![A-Za-z0-9])", re.IGNORECASE)
    for path in sorted(p for p in documents if p not in own):
        lines += [text for line in documents[path].splitlines() if (text := _plain(line)) and mention.search(text)]
    unique = list(dict.fromkeys(lines))
    return unique[:max_lines]


def build_service_prompt(evidence: dict[str, Any], instruction: str) -> str:
    """Prompt for naming one service; depends only on the instruction and the evidence."""
    return f"""{instruction}

## The components, their interfaces, the business objects their code names and what the documentation says
```json
{json.dumps(evidence, sort_keys=True, indent=1, ensure_ascii=False)}
```

Return {{"name": "...", "documentation": "..."}}."""


def derive_component_services(
    elements: list[dict[str, Any]],
    source_paths: dict[str, str],
    code_names: list[tuple[str, str]],
    documents: dict[str, str],
    config: ComponentServicesConfig,
    instruction: str,
    llm_query_fn: Callable[..., Any],
    concept_names: dict[str, str] | None = None,
    llm_kwargs: dict[str, Any] | None = None,
    interface_links: list[tuple[str, str]] | None = None,
    object_links: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """One ApplicationService element per group of offering components.

    Args:
        elements: The model's elements so far (components, interfaces, business objects)
        source_paths: Source node id -> repository path (``element_source_paths``)
        code_names: (name, repository path) of types and directories (``code_names_with_paths``)
        documents: Repository path -> text of the documentation files
        config: Thresholds and element types
        instruction: The naming instruction (config text)
        llm_query_fn: Called once per service with (prompt, schema)
        concept_names: Source node id -> concept name of the business objects
        llm_kwargs: Extra arguments of the query function (temperature, max_tokens)
        interface_links: (component source, interface source) pairs the graph links
        object_links: (component source, object source) pairs the graph links; a component
            without an interface joins the service of the components it shares these objects with
    """
    by_id = {e["identifier"]: e for e in elements}
    offering = offering_components(elements, source_paths, config, interface_links)
    if not offering:
        return []
    # The objects a graph link gives a component (any element that is no component, interface or service)
    of_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in elements:
        if _source(e):
            of_source[_source(e)].append(e)
    linked: dict[str, set[str]] = defaultdict(set)
    for a, b in object_links or []:
        for component in (e for e in of_source.get(a, []) if e.get("element_type") == config.component_type):
            linked[component["identifier"]].update(
                e["identifier"] for e in of_source.get(b, []) if e.get("element_type") not in (config.component_type, config.interface_type, ELEMENT_TYPE)
            )
    for component in sorted(c for c, found in linked.items() if found and c not in offering):
        offering[component] = []
    # The business objects each offering component works on: only offering components compete for them
    scoped = [e for e in elements if e.get("element_type") != config.component_type or offering.get(e["identifier"])]
    rule = NamedInCodeRule(owner=config.component_type, named=config.object_type, relationship="Access", min_names=config.min_names, share=config.share)
    objects: dict[str, set[str]] = {component: set() for component in offering}
    for relationship in derive_named_in_code_relationships(scoped, source_paths, code_names, [rule], concept_names):
        objects[relationship["source"]].add(relationship["target"])
    for component, found in linked.items():
        if component in objects:
            objects[component] |= found

    services: list[dict[str, Any]] = []
    for group in group_by_shared_objects(objects, config.overlap):
        components = sorted((by_id[c] for c in group), key=_source)
        interfaces = sorted({i["identifier"] for c in group for i in offering[c]})
        if not interfaces:
            continue  # A service is offered through at least one interface
        group_objects = sorted({o for c in group for o in objects[c]})
        paths = [source_paths.get(_source(c), "") for c in components]
        evidence = {
            "components": [{"name": c["name"], "path": path} for c, path in zip(components, paths, strict=True)],
            "interfaces": [by_id[i]["name"] for i in interfaces],
            "business_objects": [by_id[o]["name"] for o in group_objects if by_id[o].get("element_type") == config.object_type],
            "documentation": list(dict.fromkeys(line for path in paths if path for line in documentation_lines(path, documents, config.max_doc_lines)))[: config.max_doc_lines],
        }
        if other := [by_id[o]["name"] for o in group_objects if by_id[o].get("element_type") != config.object_type]:
            evidence["data_objects"] = other
        name, documentation = components[0]["name"], ""
        try:
            content, error = extract_response_content(llm_query_fn(build_service_prompt(evidence, instruction), SERVICE_SCHEMA, **(llm_kwargs or {})))
            answer = json.loads(extract_json_from_response(content)) if content and not error else {}
            if isinstance(answer, dict) and str(answer.get("name") or "").strip():
                name, documentation = " ".join(str(answer["name"]).split()), str(answer.get("documentation") or "").strip()
            else:
                logger.warning("No service name for %s (%s); the component's name stays", components[0]["name"], error or "empty answer")
        except Exception as exc:
            logger.warning("Service naming failed for %s: %s; the component's name stays", components[0]["name"], exc)
        source = _source(components[0])
        services.append(
            {
                "identifier": element_identifier(ELEMENT_TYPE, source),
                "name": name,
                "element_type": ELEMENT_TYPE,
                "documentation": documentation,
                "properties": {
                    "source": source,
                    "sources": [_source(c) for c in components],
                    "interfaces": interfaces,
                    "objects": group_objects,
                    "confidence": 1.0,
                    "derived_at": current_timestamp(),
                },
            }
        )
    # Names are unique within the type: a later service whose name repeats an earlier one keeps its component's name
    seen: set[str] = set()
    for service in services:
        key = " ".join(service["name"].lower().split())
        if key in seen:
            fallback = by_id_name(by_id, service)
            service["name"], number = fallback, 2
            while " ".join(service["name"].lower().split()) in seen:
                service["name"], number = f"{fallback} {number}", number + 1
        seen.add(" ".join(service["name"].lower().split()))
    return services


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def derive_member_services(
    elements: list[dict[str, Any]],
    node_paths: dict[str, str],
    imports: list[tuple[str, str]],
    code_names: list[tuple[str, str]],
    documents: dict[str, str],
    config: ComponentServicesConfig,
    instruction: str,
    llm_query_fn: Callable[..., Any],
    concept_names: dict[str, str] | None = None,
    llm_kwargs: dict[str, Any] | None = None,
    member_links: list[tuple[str, str]] | None = None,
    object_links: list[tuple[str, str]] | None = None,
    scopes: UnitScopes | None = None,
) -> list[dict[str, Any]]:
    """One ApplicationService per capability: the members of the interfaces (``properties.members``) grouped by the objects they reach.

    A member reaches the data objects defined in its file or a file it imports, the objects that a node linked to it
    (``member_links``: (node, member), such as a program and the screen it sends) reaches through ``object_links``, and
    the business objects whose words at least ``member_min_names`` code names in those files carry. Members whose objects
    overlap (Jaccard of the object names, at least ``overlap``) are one service; a member that reaches nothing stays with
    its interface's other members; above ``max_groups`` the most similar groups merge (groups that share no object never
    merge, so more groups than ``max_groups`` can stay). Identity and relationships come
    from structure; one LLM call per service writes its name and one sentence.

    Args:
        elements: The model's elements (components and interfaces made from deployable units, data and business objects)
        node_paths: Node id -> repository path of the members, of the linked nodes and of the objects' sources
        imports: (importing file, imported file) between files of the repository
        code_names: (name, path) of types and directories (``code_names_with_paths``)
        documents: Repository path -> text of the documentation files
        config: Grouping thresholds and element types
        instruction: The naming instruction (config text)
        llm_query_fn: Called once per service with (prompt, schema)
        concept_names: Source node id -> concept name of the business objects
        llm_kwargs: Extra arguments of the query function
        member_links: (linked node, member) pairs
        object_links: (node, object source) pairs
    """
    by_id = {e["identifier"]: e for e in elements}
    components = {_source(e): e for e in elements if e.get("element_type") == config.component_type}
    interfaces = sorted((e for e in elements if e.get("element_type") == config.interface_type and (e.get("properties") or {}).get("members")), key=lambda e: e["identifier"])
    if not interfaces:
        return []
    objects = [e for e in elements if e.get("element_type") in (config.object_type, "DataObject")]
    by_source: dict[str, list[str]] = defaultdict(list)
    by_path: dict[str, list[str]] = defaultdict(list)
    for e in objects:
        by_source[_source(e)].append(e["identifier"])
        if path := node_paths.get(_source(e)):
            by_path[path].append(e["identifier"])
        # An object made from a data entity is reached through any of the entity's types and their files
        if scopes is not None:
            for node in scopes.entity_nodes.get(_source(e), ()):
                by_source[node].append(e["identifier"])
            for file in scopes.entity_files.get(_source(e), ()):
                by_path[file].append(e["identifier"])
    imported: dict[str, set[str]] = defaultdict(set)
    for a, b in imports:
        imported[a].add(b)
    linked: dict[str, set[str]] = defaultdict(set)
    for node, member in member_links or []:
        linked[member].add(node)
    reaches: dict[str, set[str]] = defaultdict(set)
    for node, target in object_links or []:
        reaches[node].update(by_source.get(target, []))
    names_in: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for name, path in code_names:
        if words := tuple(w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)):
            names_in[path].append(words)
    business = [
        (e["identifier"], tuple(w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", (concept_names or {}).get(_source(e)) or e["name"])))
        for e in objects
        if e.get("element_type") == config.object_type
    ]

    # Members (by source node) with their interfaces and the objects they reach
    member_of: dict[str, dict[str, Any]] = {}
    for interface in interfaces:
        for member in interface["properties"]["members"]:
            source = str(member.get("source") or "")
            entry = member_of.setdefault(source, {"name": member.get("name") or source, "interfaces": set(), "objects": set()})
            entry["interfaces"].add(interface["identifier"])
    for source, entry in member_of.items():
        nodes = {source} | linked.get(source, set())
        files = {p for n in nodes if (p := node_paths.get(n))}
        files |= {t for f in list(files) for t in imported.get(f, ())}
        found = {o for f in files for o in by_path.get(f, [])} | {o for n in nodes for o in reaches.get(n, set())}
        words = [w for f in files for w in names_in.get(f, [])]
        for identifier, part in business:
            if part and sum(1 for w in words if any(w[i : i + len(part)] == part for i in range(len(w) - len(part) + 1))) >= config.member_min_names:
                found.add(identifier)
        entry["objects"] = found

    # Objects most members reach (a session or error record) say nothing about the capability: the others decide
    with_objects = [m for m, entry in member_of.items() if entry["objects"]]
    share = Counter(o for m in with_objects for o in member_of[m]["objects"])
    common = {o for o, n in share.items() if with_objects and n / len(with_objects) >= config.ubiquity}
    for entry in member_of.values():
        entry["objects"] = (entry["objects"] - common) or entry["objects"]

    def keys(member_ids: list[str]) -> set[str]:
        return {name_key(by_id[o]["name"]) for m in member_ids for o in member_of[m]["objects"]}

    # Group the members that reach objects; the others join their interface's group
    reaching = {m: {name_key(by_id[o]["name"]) for o in entry["objects"]} for m, entry in member_of.items() if entry["objects"]}
    groups = group_by_shared_objects(reaching, config.overlap) if reaching else []
    for m in sorted(set(member_of) - set(reaching)):
        home = next((g for g in groups if any(member_of[x]["interfaces"] & member_of[m]["interfaces"] for x in g)), None)
        if home is None:
            groups.append([m])
        else:
            home.append(m)
    groups = [sorted(g) for g in groups]
    while config.max_groups and len(groups) > config.max_groups:
        key_sets = [keys(g) for g in groups]
        pairs = [(_jaccard(key_sets[i], key_sets[j]), i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))]
        best = max(pairs, key=lambda p: (p[0], -p[1], -p[2]))
        if best[0] <= 0:
            break
        _, i, j = best
        groups = [g for k, g in enumerate(groups) if k not in (i, j)] + [sorted(groups[i] + groups[j])]
    groups.sort()

    services: list[dict[str, Any]] = []
    for group in groups:
        group_interfaces = sorted({i for m in group for i in member_of[m]["interfaces"]})
        sources = sorted({_source(by_id[i]) for i in group_interfaces})
        group_objects = sorted({o for m in group for o in member_of[m]["objects"]})
        owners = [components[s] for s in sources if s in components]
        members = sorted(({"name": member_of[m]["name"], "source": m} for m in group), key=lambda x: (x["name"], x["source"]))
        evidence = {
            "components": [c["name"] for c in owners],
            "interfaces": [by_id[i]["name"] for i in group_interfaces],
            "members": [m["name"] for m in members][:30],
            "business_objects": [by_id[o]["name"] for o in group_objects if by_id[o].get("element_type") == config.object_type],
            "documentation": [],
        }
        if other := [by_id[o]["name"] for o in group_objects if by_id[o].get("element_type") != config.object_type]:
            evidence["data_objects"] = other
        fallback = members[0]["name"]
        name, documentation = fallback, ""
        try:
            content, error = extract_response_content(llm_query_fn(build_service_prompt(evidence, instruction), SERVICE_SCHEMA, **(llm_kwargs or {})))
            answer = json.loads(extract_json_from_response(content)) if content and not error else {}
            if isinstance(answer, dict) and str(answer.get("name") or "").strip():
                name, documentation = " ".join(str(answer["name"]).split()), str(answer.get("documentation") or "").strip()
            else:
                logger.warning("No service name for %s (%s); the first member's name stays", fallback, error or "empty answer")
        except Exception as exc:
            logger.warning("Service naming failed for %s: %s; the first member's name stays", fallback, exc)
        services.append(
            {
                "identifier": element_identifier(ELEMENT_TYPE, members[0]["source"]),
                "name": name,
                "element_type": ELEMENT_TYPE,
                "documentation": documentation,
                "properties": {
                    "source": members[0]["source"],
                    "sources": sources,
                    "interfaces": group_interfaces,
                    "objects": group_objects,
                    "members": members,
                    "structure_name": fallback,
                    "confidence": 1.0,
                    "derived_at": current_timestamp(),
                },
            }
        )
    # Names are unique within the type: a repeated name gets its first member's name, then a number
    seen: set[str] = set()
    for service in services:
        if " ".join(service["name"].lower().split()) in seen:
            fallback, number = service["properties"]["structure_name"], 2
            service["name"] = fallback
            while " ".join(service["name"].lower().split()) in seen:
                service["name"], number = f"{fallback} {number}", number + 1
        seen.add(" ".join(service["name"].lower().split()))
    return services


def by_id_name(by_id: dict[str, dict[str, Any]], service: dict[str, Any]) -> str:
    """The name of the service's first component (its structural fallback name)."""
    source = service["properties"]["source"]
    return next((e["name"] for e in by_id.values() if e.get("element_type") != ELEMENT_TYPE and _source(e) == source), service["name"])


# ------------------------------------------------------------------------------------------------ services per component


def _name_words(text: str) -> list[str]:
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", text)


def clean_member_name(name: str, kind_words: tuple[str, ...], generic_names: tuple[str, ...]) -> str | None:
    """A member's name as a service name candidate: the extension and the kind words (prefix or suffix) dropped,
    words spaced and title-cased; None for a generic or empty name."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(name).rsplit("/", 1)[-1])
    if stem.casefold() in {g.casefold() for g in generic_names}:
        return None
    # A single upper-case code identifier (a program or member id such as CBPAUP0J) names no behaviour
    if re.fullmatch(r"[A-Z0-9$#@-]+", stem):
        return None
    words = _name_words(stem)
    kinds: list[list[str]] = sorted((_name_words(k) for k in kind_words), key=lambda words: len(words), reverse=True)
    changed = True
    while changed and words:
        changed = False
        for kind in kinds:
            n = len(kind)
            if n and len(words) > n and [w.casefold() for w in words[-n:]] == [k.casefold() for k in kind]:
                words, changed = words[:-n], True
            elif n and len(words) > n and [w.casefold() for w in words[:n]] == [k.casefold() for k in kind]:
                words, changed = words[n:], True
    if not words or " ".join(words).casefold() in {g.casefold() for g in generic_names}:
        return None
    return " ".join(w if w.isupper() and len(w) > 1 else w[:1].upper() + w[1:] for w in words)


def is_activity(name: str, config: ComponentServicesConfig) -> bool:
    """Whether a name names an activity (no rule configured: every name does)."""
    if not config.activity_words and not config.activity_suffixes:
        return True
    words = [w.casefold() for w in _name_words(name)]
    if not words:
        return False
    last = words[-1]
    # The last word decides: "Risk Computation", "Quote Processing", "User Login"; a suffix only on a long word ("String" is none)
    return last in {w.casefold() for w in config.activity_words} or any(last.endswith(x.casefold()) and len(last) >= len(x) + 4 for x in config.activity_suffixes)


def _choose(candidates: list[str], source: dict[str, Any], element_type: str, instruction: str, llm_query_fn: Callable[..., Any], llm_kwargs: dict[str, Any]) -> str:
    """One of the candidates: the only one without a call, else the LLM's choice (an answer outside the set takes the first)."""
    if len(candidates) == 1:
        return candidates[0]
    try:
        content, error = extract_response_content(llm_query_fn(build_choice_prompt(source, element_type, instruction, candidates), choice_schema(candidates), **llm_kwargs))
        answer = None if error else json.loads(extract_json_from_response(content)).get("name")
    except (ValueError, AttributeError) as exc:
        logger.warning("Unusable name choice for %s %s: %s", element_type, source.get("component") or source.get("name"), exc)
        answer = None
    return answer if answer in candidates else candidates[0]


def derive_unit_services(
    elements: list[dict[str, Any]],
    node_paths: dict[str, str],
    imports: list[tuple[str, str]],
    config: ComponentServicesConfig,
    instruction: str,
    llm_query_fn: Callable[..., Any],
    scopes: UnitScopes,
    deciding: set[str],
    business_objects: dict[str, str],
    bases: dict[str, set[str]],
    lines: set[tuple[str, str]],
    documents: dict[str, str],
    llm_kwargs: dict[str, Any] | None = None,
    member_links: list[tuple[str, str]] | None = None,
    object_links: list[tuple[str, str]] | None = None,
    type_names: dict[str, set[str]] | None = None,
    domain_names: dict[str, set[str]] | None = None,
    endpoints: dict[str, list[tuple[str, str]]] | None = None,
    domain_anchors: dict[str, str] | None = None,
    lifecycle_sites: dict[str, set[str]] | None = None,
    consumes: set[tuple[str, str]] | None = None,
    lifecycle_state_sites: dict[str, dict[str, set[str]]] | None = None,
    domain_entities: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Application services per component and business functions across components (``group_by`` "unit").

    A component's services group the members of its interfaces: members that extend one base type (at least
    ``min_family``) are one group, the others group by the data domain they reach most (only ``deciding``
    domains decide; the rest is one group); Web UI pages join the largest group. Several services only when at
    least two groups hold ``min_members`` members, at most ``max_per_component``. A pure front end (only a Web
    UI, it uses other components, no member reaches a domain) offers no service. A business function is a
    business domain (``business_objects``) whose services of components connected by a cooperation line
    (``lines``: (unit, unit)) access it. Names are closed sets; one candidate needs no call.

    Args:
        elements: The model's elements (components and interfaces made from units, data objects made from domains)
        node_paths: Node id -> repository path of the members, linked nodes and objects' sources
        imports: (importing file, imported file)
        config: Grouping thresholds, kind words, name templates
        instruction: The closed-set naming instruction (config text)
        llm_query_fn: Called once per service or function with several name candidates
        scopes: Units' and domains' members (``unit_scopes``)
        deciding: Domain ids that decide the grouping (business and exception domains)
        business_objects: Domain id -> its BusinessObject's name
        bases: Member node -> the names of its base types
        lines: Cooperation lines between units (either direction)
        documents: Repository path -> documentation text (business function terms)
        llm_kwargs: Extra arguments of the query function
        member_links: (linked node, member) pairs (a program and the screen it sends)
        object_links: (node, object source) pairs (a program and the record it uses)
        type_names: File path -> name keys of the types it defines (a member reaches a domain whose entity it uses)
        domain_names: Domain id -> name keys of its entities and member types
        endpoints: Unit id -> (node, name) of the unit's endpoint types (structural markers), members as well
        domain_anchors: Domain id -> its anchor's name, for the deciding domains without a BusinessObject (templates)
        lifecycle_sites: Lifecycle id -> the files that set its states; a service serves the lifecycles its members reach
        consumes: (consumer unit, provider unit) API lines; a service lists the data objects of the providers its
            component consumes (``consumed_objects``), the data it reads through their APIs
        lifecycle_state_sites: Lifecycle id -> state -> the files that set it; a service lists the states its
            members' reach sets (``states``: "<lifecycle id>::<state>")
        domain_entities: Domain id -> its entity ids, when the data objects are made from entities: members still
            reach (and group by) domains, a service accesses the entities of a reached domain its members reach,
            else all of them (``objects_from_domain``). None: the data objects are made from domains
    """
    llm_kwargs = llm_kwargs or {}
    components = {_source(e): e for e in elements if e.get("element_type") == config.component_type}
    interfaces = sorted((e for e in elements if e.get("element_type") == config.interface_type and (e.get("properties") or {}).get("members")), key=lambda e: e["identifier"])
    data_objects = [e for e in elements if e.get("element_type") == "DataObject"]
    made_from = {_source(e): e for e in data_objects}
    # Domain -> the sources of its data objects: the domain itself, or its entities
    if domain_entities is None:
        entities_of = {d: [d] for d in sorted(made_from)}
    else:
        entities_of = {d: [x for x in [d, *sorted(domain_entities[d])] if x in made_from] for d in sorted(domain_entities)}
    object_of = {d: sorted(made_from[x]["identifier"] for x in sources) for d, sources in entities_of.items()}
    files_of = {d: set(scopes.entity_files.get(d, ())) for d in object_of}
    nodes_of = {d: set(scopes.entity_nodes.get(d, ())) for d in object_of}
    imported: dict[str, set[str]] = defaultdict(set)
    for a, b in imports:
        imported[a].add(b)
    linked: dict[str, set[str]] = defaultdict(set)
    for node, member in member_links or []:
        linked[member].add(node)
    record_links: dict[str, set[str]] = defaultdict(set)
    for node, target in object_links or []:
        record_links[node].add(target)

    names_of = {d: set((domain_names or {}).get(d, ())) for d in object_of}

    def member_files(member: str) -> set[str]:
        """The files a member's reach covers: its own and its linked nodes', then up to max_hops imports."""
        nodes = {member} | linked.get(member, set())
        files = {p for n in nodes if (p := node_paths.get(n))}
        frontier = set(files)
        for _ in range(max(config.max_hops, 0)):
            frontier = {t for f in frontier for t in imported.get(f, ())} - files
            files |= frontier
        return files

    def reached(member: str) -> Counter:
        nodes = {member} | linked.get(member, set())
        files = member_files(member)
        targets = {t for n in nodes for t in record_links.get(n, ())}
        used = {key for f in files for key in (type_names or {}).get(f, ())}
        hits: Counter = Counter()
        for domain in object_of:
            hits[domain] = len(files & files_of[domain]) + len((nodes | targets) & nodes_of[domain]) + len(used & names_of[domain])
        return Counter({d: n for d, n in hits.items() if n})

    def reaches_entity(member: str, entity: str) -> bool:
        nodes = {member} | linked.get(member, set())
        files = member_files(member)
        targets = {t for n in nodes for t in record_links.get(n, ())}
        used = {key for f in files for key in (type_names or {}).get(f, ())}
        in_scope = files & scopes.entity_files.get(entity, frozenset()) or (nodes | targets) & scopes.entity_nodes.get(entity, frozenset())
        return bool(in_scope or name_key(made_from[entity]["name"]) in used)

    def accessed(group: list[str], group_domains: list[str]) -> tuple[list[str], list[str]]:
        """The data objects a group accesses, per reached domain: the entities its members reach, else all of the
        domain's (those domains are returned as well)."""
        found: set[str] = set()
        fallback: list[str] = []
        for d in group_domains:
            sources = entities_of.get(d, [])
            entities = [x for x in sources if x != d]
            own = [x for x in entities if any(reaches_entity(m, x) for m in group)]
            if entities and not own:
                fallback.append(d)
            found |= {made_from[x]["identifier"] for x in (own or sources)}
        return sorted(found), fallback

    # Members per component (through the interfaces made from the component's unit)
    per_unit: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for interface in interfaces:
        unit, role = _source(interface), str(interface["properties"].get("role") or "")
        for member in interface["properties"]["members"]:
            node = str(member.get("source") or "")
            entry = per_unit[unit].setdefault(node, {"name": member.get("name") or node, "interfaces": set(), "roles": set()})
            entry["interfaces"].add(interface["identifier"])
            # A member's own role (one interface per unit merges several); else its interface's
            entry["roles"].add(str(member.get("role") or role))
    # Endpoint types the structure marks join the members, through the unit's interfaces other than its Web UI
    for unit, found in sorted((endpoints or {}).items()):
        own = [i for i in interfaces if _source(i) == unit and str(i["properties"].get("role") or "") != "web"]
        for node, name in found:
            if own and node not in per_unit[unit]:
                per_unit[unit][node] = {"name": name, "interfaces": {i["identifier"] for i in own}, "roles": {str(i["properties"].get("role") or "") for i in own}}
    consumers = {a for a, _ in lines}

    services: list[dict[str, Any]] = []
    for unit, members in sorted(per_unit.items()):
        if unit not in components:
            continue
        reach = {m: reached(m) for m in members}
        all_web = all(entry["roles"] <= {"web"} for entry in members.values())
        if all_web and unit in consumers and not any(reach[m] for m in members):
            continue  # A pure front end presents the services of the components it uses
        pages = {m for m, entry in members.items() if entry["roles"] <= {"web"}}
        groups: dict[str, list[str]] = defaultdict(list)
        family_of: dict[str, str] = {}
        base_count = Counter(b for m in members if m not in pages for b in bases.get(m, ()))
        for m in sorted(members):
            if m in pages:
                continue
            family = sorted(b for b in bases.get(m, ()) if base_count[b] >= config.min_family)
            if family:
                family_of[m] = family[0]
                groups[f"family:{family[0]}"].append(m)
                continue
            deciding_hits = Counter({d: n for d, n in reach[m].items() if d in deciding})
            key = max(sorted(deciding_hits), key=lambda d: deciding_hits[d]) if deciding_hits else "rest"
            groups[key].append(m)

        def domains(group: list[str]) -> set[str]:
            return {d for m in group for d in reach[m] if d in deciding}

        # A group that reaches no domain is no service of its own: it joins the largest group
        big = [k for k, g in groups.items() if k != "rest" and (len(g) >= config.min_members or k.startswith("family:"))]
        if len(big) <= 1:
            merged = {"all": sorted(members)}
        else:
            merged = {k: list(groups[k]) for k in big}
            for k in sorted(k for k in groups if k not in big):
                home = max(sorted(merged), key=lambda h: (len(domains(merged[h]) & domains(groups[k])), len(merged[h])))
                if k == "rest":
                    home = max(sorted(merged), key=lambda h: len(merged[h]))
                merged[home] += groups[k]
            while len(merged) > max(config.max_per_component, 1):
                keys = sorted(merged)
                pairs = [(_jaccard(domains(merged[a]), domains(merged[b])), -len(merged[a]) - len(merged[b]), a, b) for i, a in enumerate(keys) for b in keys[i + 1 :]]
                _, _, a, b = max(pairs)
                merged[a] = merged[a] + merged.pop(b)
            largest = max(sorted(merged), key=lambda k: len(merged[k]))
            merged[largest] += sorted(pages)
        for key, group in sorted(merged.items()):
            group = sorted(set(group))
            group_domains = sorted({d for m in group for d in reach[m]})
            group_objects, from_domain = accessed(group, group_domains)
            group_interfaces = sorted({i for m in group for i in members[m]["interfaces"]})
            candidates: list[str] = []
            if key.startswith("family:"):
                if (family := clean_member_name(key.removeprefix("family:"), config.kind_words, config.generic_names)) and is_activity(family, config):
                    candidates.append(family)
            for m in group:
                # A member name names the service only as an activity (bare object nouns name data and business objects)
                if m not in pages and (name := clean_member_name(members[m]["name"], config.kind_words, config.generic_names)) and is_activity(name, config):
                    candidates.append(name)
            # Templates on every business domain the group reaches: the most reached first, then the larger domain
            weight = Counter()
            for m in group:
                weight.update(reach[m])
            # The object a template names: the BusinessObject, else the anchor of a deciding domain without one
            object_names = {d: n for d, n in (domain_anchors or {}).items() if d in deciding} | business_objects
            reached_objects = sorted(
                (d for d in weight if d in object_names), key=lambda d: (d not in business_objects, -weight[d], -len(names_of.get(d) or files_of.get(d) or ()), d)
            )
            for domain in reached_objects:
                candidates += [t.format(object=object_names[domain]) for t in config.service_templates]
            taken = {name_key(components[unit]["name"])} | {name_key(e["name"]) for e in interfaces if _source(e) == unit}

            def usable(found: list[str]) -> list[str]:
                seen: set[str] = set()
                kept = []
                for c in found:
                    if name_key(c) not in taken and name_key(c) not in seen:
                        seen.add(name_key(c))
                        kept.append(c)
                return kept[: config.max_candidates]

            candidates = usable(candidates)
            if not candidates:
                # Nothing names the behaviour: the templates on the component's own name without its kind words
                stem = clean_member_name(components[unit]["name"], config.kind_words, ())
                stem_names = ([stem] if is_activity(stem, config) and config.activity_words else [t.format(object=stem) for t in config.service_templates]) if stem else []
                # The stem may equal the component's own name only through its kind word: it stays a candidate
                candidates = [c for c in stem_names if name_key(c) != name_key(components[unit]["name"])] or [components[unit]["name"]]
            source = {
                "component": components[unit]["name"],
                "interfaces": [e["name"] for e in interfaces if e["identifier"] in group_interfaces],
                "members": [members[m]["name"] for m in group][:20],
                "data": [e["name"] for e in data_objects if e["identifier"] in group_objects],
            }
            name = _choose(candidates, source, ELEMENT_TYPE, instruction, llm_query_fn, llm_kwargs)
            identity = f"{unit}::{key if len(merged) > 1 else 'all'}"
            services.append(
                {
                    "identifier": element_identifier(ELEMENT_TYPE, identity),
                    "name": name,
                    "element_type": ELEMENT_TYPE,
                    "documentation": "",
                    "properties": {
                        "source": identity,
                        "sources": [unit],
                        "interfaces": group_interfaces,
                        "objects": group_objects,
                        "objects_from_domain": from_domain,
                        "members": sorted(({"name": members[m]["name"], "source": m} for m in group), key=lambda x: (x["name"], x["source"])),
                        "name_candidates": candidates,
                        "processes": sorted(life for life, sites in (lifecycle_sites or {}).items() if sites & {f for m in group for f in member_files(m)}),
                        "states": sorted(
                            f"{life}::{state}"
                            for life, by_state in (lifecycle_state_sites or {}).items()
                            for state, sites in by_state.items()
                            if sites & {f for m in group for f in member_files(m)}
                        ),
                        "structure_name": candidates[0],
                        "confidence": 1.0,
                        "derived_at": current_timestamp(),
                    },
                }
            )

    # The data a component reads through the APIs it consumes: the objects of the providers' services
    provided: dict[str, set[str]] = defaultdict(set)
    for item in services:
        provided[item["properties"]["sources"][0]] |= set(item["properties"]["objects"])
    for item in services:
        unit = item["properties"]["sources"][0]
        reads = {o for a, b in consumes or () if a == unit and b != unit for o in provided.get(b, ())}
        item["properties"]["consumed_objects"] = sorted(reads - set(item["properties"]["objects"]))

    # Services are named (unique within the type) before the functions, so a function never takes a service's name
    used: set[str] = set()
    for item in services:
        if name_key(item["name"]) in used:
            options = [c for c in item["properties"]["name_candidates"] if name_key(c) not in used]
            item["name"] = options[0] if options else f"{item['name']} {len(used) + 1}"
        used.add(name_key(item["name"]))

    # Business functions: a business domain that services of cooperating components access
    undirected = {frozenset(pair) for pair in lines if len(set(pair)) == 2}
    functions: list[dict[str, Any]] = []
    nouns = "|".join(re.escape(n) for n in config.function_nouns)
    for domain, object_name in sorted(business_objects.items()) if config.business_functions else ():
        if not object_of.get(domain):
            continue
        users = sorted({s["properties"]["sources"][0] for s in services if set(object_of[domain]) & set(s["properties"]["objects"])})
        connected = sorted({u for u in users for v in users if u != v and frozenset((u, v)) in undirected})
        if len(connected) < 2:
            continue
        served_by = sorted(s["identifier"] for s in services if s["properties"]["sources"][0] in connected and set(object_of[domain]) & set(s["properties"]["objects"]))
        candidates = [t.format(object=object_name) for t in config.function_templates]
        if nouns:
            for text in documents.values():
                for m in re.finditer(rf"(?i)\b{re.escape(object_name)}\s+({nouns})\b", text):
                    candidates.append(f"{object_name} {m.group(1).lower().capitalize()}")
        seen = set()
        unique = []
        for c in candidates:
            if name_key(c) not in seen:
                seen.add(name_key(c))
                unique.append(c)
        candidates = unique or [object_name]
        # A function never takes a service's name (the same name on two types is a duplicate)
        service_names = {name_key(s["name"]) for s in services}
        candidates = [c for c in candidates if name_key(c) not in service_names] or candidates
        name = _choose(candidates, {"name": object_name, "components": [components[u]["name"] for u in connected]}, "BusinessFunction", instruction, llm_query_fn, llm_kwargs)
        functions.append(
            {
                "identifier": element_identifier("BusinessFunction", f"function::{domain}"),
                "name": name,
                "element_type": "BusinessFunction",
                "documentation": "",
                "properties": {"source": domain, "services": served_by, "name_candidates": candidates, "confidence": 1.0, "derived_at": current_timestamp()},
            }
        )

    # Function names are unique within the type: a repeated name falls back to the next candidate, then a number
    for items in (functions,):
        used = set()
        for item in items:
            if name_key(item["name"]) in used:
                options = [c for c in item["properties"]["name_candidates"] if name_key(c) not in used]
                item["name"] = options[0] if options else f"{item['name']} {len(used) + 1}"
            used.add(name_key(item["name"]))
    return services, functions
