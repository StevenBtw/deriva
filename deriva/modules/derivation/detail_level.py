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

from dataclasses import dataclass, field
from typing import Any

from deriva.modules.derivation.base import element_identifier


@dataclass(frozen=True)
class DetailLineage:
    """The members the graph holds per architect source node."""

    entities: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # domain id -> (entity id, name)
    programs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # unit id -> (program id, name)
    states: dict[str, list[str]] = field(default_factory=dict)  # lifecycle id -> states in order


@dataclass
class DetailLevel:
    elements: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    properties: dict[str, dict[str, str]] = field(default_factory=dict)  # architect element id -> extra properties


def _relationship(kind: str, source: str, target: str) -> dict[str, Any]:
    return {"identifier": f"rel_detail_{kind.lower()}_{source}_{target}", "source": source, "target": target, "relationship_type": kind}


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
            for m in sorted(props.get("members") or [], key=lambda m: (str(m.get("name") or ""), str(m.get("source") or ""))):
                node = str(m.get("source") or "")
                if node:
                    child = member("ApplicationInterface", f"{parent}::{node}", str(m.get("name") or node), parent, node)
                    out.relationships.append(_relationship("Composition", parent, child))
        elif kind == "ApplicationComponent":
            for program, name in lineage.programs.get(source, []):
                out.relationships.append(_relationship("Composition", parent, member("ApplicationComponent", program, name, parent, program)))
        elif kind == "BusinessProcess" and lineage.states.get(source):
            extra["states"] = ", ".join(lineage.states[source])
        out.properties[parent] = extra
    out.relationships = sorted({r["identifier"]: r for r in out.relationships}.values(), key=lambda r: r["identifier"])
    return out
