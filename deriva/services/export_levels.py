"""The export's levels: the derived model's abstraction levels (enterprise, solution) and the detail level (its
members, from the graph).

One exchange file holds them all: every element carries a ``level`` property, the set of its levels (``enterprise``,
``solution``, ``enterprise solution``; ``detail`` for a member), and so does every relationship (the levels both its
ends share; ``cross-level`` without one). Relationship ids come from the ends, the type and the level, so they are
the same in every run. Lifecycle states are a property of their process, and the views show each viewpoint per
level. The benchmark measures the derived model; the detail level is reported on its own.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.views import View, build_views
from deriva.common.ocel import hash_content
from deriva.modules.derivation.detail_level import DetailLevel, DetailLineage, detail_level

ENTITIES = "MATCH (d:Graph:DataDomain)-[:`Graph:INCLUDES`]->(e:Graph:DataEntity) RETURN d.id AS d, e.id AS e, e.name AS n"
PROGRAMS = "MATCH (u:Graph:DeployableUnit)-[:`Graph:INCLUDES`]->(t:Graph:TypeDefinition) WHERE t.category = 'program' RETURN u.id AS u, t.id AS t, t.typeName AS n"
STATES = "MATCH (l:Graph:Lifecycle) RETURN l.id AS l, l.states AS s"


@dataclass
class LeveledModel:
    elements: list[Element]  # architect elements first, then the detail elements
    relationships: list[Relationship]
    properties: dict[str, dict[str, str]]  # exported properties per element id (level, states)
    views: list[View]
    detail: DetailLevel = field(default_factory=DetailLevel)
    architect_count: int = 0
    relationship_properties: dict[str, dict[str, str]] = field(default_factory=dict)  # exported properties per relationship id (level)

    def summary(self) -> dict[str, int]:
        return {"architect_elements": self.architect_count, "detail_elements": len(self.detail.elements), "detail_relationships": len(self.detail.relationships)}


def _grouped(rows: list[dict[str, Any]], key: str, *values: str) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for row in rows:
        if row.get(key):
            out.setdefault(str(row[key]), []).append(tuple(row.get(v) for v in values))
    return {k: sorted(set(v), key=lambda t: tuple(str(x) for x in t)) for k, v in sorted(out.items())}


def detail_lineage(graph_manager: Any | None) -> DetailLineage:
    """The members of the architect elements' source nodes, from the repository's graph (no LLM; none without a graph)."""
    if graph_manager is None:
        return DetailLineage()
    return DetailLineage(
        entities=_grouped(graph_manager.query(ENTITIES), "d", "e", "n"),
        programs=_grouped(graph_manager.query(PROGRAMS), "u", "t", "n"),
        states={str(r["l"]): list(r.get("s") or []) for r in graph_manager.query(STATES) if r.get("l") and r.get("s")},
    )


def _level_set(properties: dict[str, Any] | None) -> str:
    """An element's exported level: its levels as one value (none recorded: enterprise)."""
    levels = (properties or {}).get("levels")
    return " ".join(sorted(str(v) for v in levels)) if isinstance(levels, list) and levels else "enterprise"


def _relationship_level(relationship: Relationship, detail: bool) -> str:
    if detail:
        return "detail"
    properties = relationship.properties or {}
    levels = properties.get("levels")
    if properties.get("cross_level") or (isinstance(levels, list) and not levels):
        return "cross-level"
    return " ".join(sorted(str(v) for v in levels)) if isinstance(levels, list) else "enterprise"


def _view_levels(level: str) -> frozenset[str]:
    """The levels a relationship's exported ``level`` names (cross-level: none)."""
    return frozenset() if level == "cross-level" else frozenset(level.split())


def stable_ids(relationships: list[tuple[Relationship, str]]) -> list[Relationship]:
    """The relationships with ids from their ends, type and level (a repeat of all four gets its position appended)."""
    seen: dict[str, int] = {}
    out = []
    for relationship, level in relationships:
        base = f"rel-{hash_content(f'{relationship.source}|{relationship.relationship_type}|{relationship.target}|{level}')[:16]}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        renamed = copy.copy(relationship)
        renamed.identifier = base if count == 0 else f"{base}-{count + 1}"
        out.append(renamed)
    return out


def leveled_model(elements: list[Element], relationships: list[Relationship], lineage: DetailLineage) -> LeveledModel:
    """The derived elements and relationships plus the detail level, the exported properties, stable relationship ids and the views."""
    detail = detail_level([e.to_dict() for e in elements], lineage)
    properties: dict[str, dict[str, str]] = {e.identifier: {"level": _level_set(e.properties), **detail.properties.get(e.identifier, {})} for e in elements}
    detail_elements = [Element.from_dict(d) for d in detail.elements]
    properties |= {e.identifier: {"level": "detail"} for e in detail_elements}
    all_elements = list(elements) + detail_elements
    leveled = [(r, _relationship_level(r, False)) for r in relationships] + [(Relationship.from_dict(r), "detail") for r in detail.relationships]
    all_relationships = stable_ids(leveled)
    relationship_properties = {r.identifier: {"level": level} for r, (_, level) in zip(all_relationships, leveled, strict=True)}
    return LeveledModel(
        elements=all_elements,
        relationships=all_relationships,
        properties=properties,
        views=build_views(
            all_elements, all_relationships, {r.identifier: _view_levels(p["level"]) for r, p in ((r, relationship_properties[r.identifier]) for r in all_relationships)}
        ),
        detail=detail,
        architect_count=len(elements),
        relationship_properties=relationship_properties,
    )
