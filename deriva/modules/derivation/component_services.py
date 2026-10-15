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
    member_min_names: int = 1  # Code names carrying a business object's words that make a member reach it
    max_groups: int = 0  # At most this many services (0: no limit); the most similar groups merge first
    # An object that at least this share of the members reach does not decide the grouping (1: every object decides);
    # a member that reaches only such objects groups by them
    ubiquity: float = 1.0


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
) -> list[dict[str, Any]]:
    """One ApplicationService per capability: the members of the interfaces (``properties.members``) grouped by the objects they reach.

    A member reaches the data objects defined in its file or a file it imports, the objects that a node linked to it
    (``member_links``: (node, member), such as a program and the screen it sends) reaches through ``object_links``, and
    the business objects whose words at least ``member_min_names`` code names in those files carry. Members whose objects
    overlap (Jaccard of the object names, at least ``overlap``) are one service; a member that reaches nothing stays with
    its interface's other members; above ``max_groups`` the most similar groups merge. Identity and relationships come
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
        pairs = [(_jaccard(keys(a), keys(b)), i, j) for i, a in enumerate(groups) for j, b in enumerate(groups) if i < j]
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
