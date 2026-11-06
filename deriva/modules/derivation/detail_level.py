"""The export's detail level (pure): the members of the architect elements as nested ArchiMate elements.

The architect level is the derived model. Its members, kept as lineage, become detail elements in the export:

- a data domain (DataObject) composes its entities (DataObject);
- a channel interface (ApplicationInterface) composes its endpoint members (ApplicationInterface);
- deployments are no detail elements: a deployment that deploys a unit is that unit's architect-level artifact, and
  one without a unit (a vendor image) is its system software, which the platform node composes;
- a mainframe unit (ApplicationComponent) composes its programs (ApplicationComponent);
- a lifecycle's states stay a property of its process (the hand-off states are already events).

Identities come from structure (the member's source node), so every run gives the same detail level.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from deriva.common.naming import name_key
from deriva.modules.derivation.base import element_identifier


@dataclass(frozen=True)
class DetailLineage:
    """The members the graph holds per architect source node."""

    entities: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # domain id -> (entity id, name)
    programs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # unit id -> (program id, name)
    states: dict[str, list[str]] = field(default_factory=dict)  # lifecycle id -> states in order
    files: dict[str, str] = field(default_factory=dict)  # file node id -> path (members that are files)


@dataclass
class DetailLevel:
    elements: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    properties: dict[str, dict[str, str]] = field(default_factory=dict)  # architect element id -> extra properties


def _relationship(kind: str, source: str, target: str) -> dict[str, Any]:
    return {"identifier": f"rel_detail_{kind.lower()}_{source}_{target}", "source": source, "target": target, "relationship_type": kind}


def _member_names(members: list[dict[str, Any]], files: dict[str, str]) -> dict[str, str]:
    """Each endpoint member's name by its node: a file's name without its extension and with a capital first letter, a
    name two members share with their folders in front (nearest first, each with a capital first letter) until it
    differs; a template whose name starts with an underscore (a partial or layout) is no endpoint and has none. Other
    members keep their names."""
    names: dict[str, str] = {}
    for m in members:
        node, name = str(m.get("source") or ""), str(m.get("name") or m.get("source") or "")
        path = files.get(node)
        if path is None:
            names[node] = name
        elif not PurePosixPath(path).name.startswith("_"):
            stem = PurePosixPath(path).stem
            names[node] = stem[:1].upper() + stem[1:]
    # A name two file members share takes its folders in front, nearest first, until it differs (or its path ends)
    base = dict(names)
    depth: dict[str, int] = {}
    while True:
        repeats = Counter(name_key(n) for n in names.values())
        grow = [n for n, name in names.items() if n in files and repeats[name_key(name)] > 1 and depth.get(n, 0) < len(PurePosixPath(files[n]).parent.parts)]
        if not grow:
            return names
        for node in grow:
            depth[node] = depth.get(node, 0) + 1
            folders = [f[:1].upper() + f[1:] for f in PurePosixPath(files[node]).parent.parts[-depth[node] :]]
            names[node] = " ".join([*folders, base[node]])


def detail_level(elements: list[dict[str, Any]], lineage: DetailLineage) -> DetailLevel:
    """The detail elements, their relationships to the architect elements, and the architect elements' extra properties."""
    out = DetailLevel()
    seen: set[str] = set()

    def member(element_type: str, identity: str, name: str, parent: str, source: str) -> str:
        identifier = element_identifier(element_type, f"detail::{identity}")
        if identifier not in seen:
            seen.add(identifier)
            out.elements.append({"identifier": identifier, "name": name, "element_type": element_type, "properties": {"source": source, "level": "detail", "parent": parent}})
        return identifier

    for e in sorted(elements, key=lambda x: x["identifier"]):
        props = e.get("properties") or {}
        source, kind, parent = str(props.get("source") or ""), e.get("element_type"), e["identifier"]
        extra: dict[str, str] = {}
        if kind == "DataObject":
            for entity, name in lineage.entities.get(source, []):
                out.relationships.append(_relationship("Composition", parent, member("DataObject", entity, name, parent, entity)))
        elif kind == "ApplicationInterface":
            members = sorted((m for m in props.get("members") or [] if m.get("source")), key=lambda m: (str(m.get("name") or ""), str(m.get("source") or "")))
            names = _member_names(members, lineage.files)
            for m in members:
                node = str(m["source"])
                if node in names:
                    child = member("ApplicationInterface", f"{parent}::{node}", names[node], parent, node)
                    out.relationships.append(_relationship("Composition", parent, child))
        elif kind == "ApplicationComponent":
            for program, name in lineage.programs.get(source, []):
                out.relationships.append(_relationship("Composition", parent, member("ApplicationComponent", program, name, parent, program)))
        elif kind == "BusinessProcess" and lineage.states.get(source):
            extra["states"] = ", ".join(lineage.states[source])
        out.properties[parent] = extra
    out.relationships = sorted({r["identifier"]: r for r in out.relationships}.values(), key=lambda r: r["identifier"])
    return out
