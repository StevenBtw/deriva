"""The export's two levels: the architect level (the derived model) and the detail level (its members, from the graph).

One exchange file holds both: every element carries a ``level`` property (architect or detail), lifecycle states
are a property of their process, and the views show each viewpoint per level. The benchmark measures the
architect level; the detail level is reported on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.views import View, build_views
from deriva.modules.derivation.detail_level import DetailLevel, DetailLineage, detail_level

ENTITIES = "MATCH (d:Graph:DataDomain)-[:`Graph:INCLUDES`]->(e:Graph:DataEntity) RETURN d.id AS d, e.id AS e, e.name AS n"
DEPLOYMENTS = "MATCH (v:Graph:Environment)-[:`Graph:RUNS`]->(d:Graph:Deployment) OPTIONAL MATCH (d)-[:`Graph:DEPLOYS`]->(u) RETURN v.id AS v, d.id AS d, d.name AS n, u.id AS u"
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
        deployments=_grouped(graph_manager.query(DEPLOYMENTS), "v", "d", "n", "u"),
        programs=_grouped(graph_manager.query(PROGRAMS), "u", "t", "n"),
        states={str(r["l"]): list(r.get("s") or []) for r in graph_manager.query(STATES) if r.get("l") and r.get("s")},
    )


def leveled_model(elements: list[Element], relationships: list[Relationship], lineage: DetailLineage) -> LeveledModel:
    """The architect elements and relationships plus the detail level, the exported properties and the views."""
    detail = detail_level([e.to_dict() for e in elements], lineage)
    properties: dict[str, dict[str, str]] = {e.identifier: {"level": "architect", **detail.properties.get(e.identifier, {})} for e in elements}
    detail_elements = [Element.from_dict(d) for d in detail.elements]
    properties |= {e.identifier: {"level": "detail"} for e in detail_elements}
    all_elements = list(elements) + detail_elements
    all_relationships = list(relationships) + [Relationship.from_dict(r) for r in detail.relationships]
    return LeveledModel(
        elements=all_elements,
        relationships=all_relationships,
        properties=properties,
        views=build_views(all_elements, all_relationships),
        detail=detail,
        architect_count=len(elements),
    )
