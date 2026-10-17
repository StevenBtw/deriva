"""Abstraction levels - Refine Step.

Tags every element and relationship with the abstraction levels it belongs to (``levels``; a relationship whose
ends share no level is ``cross_level``), adds the roll-up Compositions of the component hierarchy (system ->
modules and units -> nested modules) and lets the top-level component realize, at the enterprise level, a service
that a solution-level component realizes. Structural only: the hierarchy comes from the folders of the components'
sources (deployable units, build modules), the levels per type from the step's params. No LLM call.

Refine Step Name: "abstraction_levels"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deriva.common.ocel import hash_content
from deriva.modules.derivation.levels import Component, LevelRules, assign_levels, relationship_levels, rollups, service_lifts

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see docs/architecture.md)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see docs/architecture.md)

logger = logging.getLogger(__name__)

SOURCES = "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.path AS path, labels(n) AS labels, n.isSystem AS system"


def _relationship_id(source: str, relationship_type: str, target: str) -> str:
    """A stable identifier from the ends and the type (the same in every run)."""
    return f"rel-{hash_content(f'{source}|{relationship_type}|{target}')[:16]}"


@register_refine_step("abstraction_levels")
class AbstractionLevelsStep:
    """Levels on elements and relationships, roll-ups and service lifts, from structure."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute the step.

        Args:
            archimate_manager: The model
            graph_manager: The graph (the sources' folders and kinds)
            llm_query_fn: Not used
            params: ``types``: element type -> its levels (a type not listed is enterprise)
        """
        result = RefineResult(success=True, step_name="abstraction_levels")
        types = (params or {}).get("types")
        if not isinstance(types, dict) or not all(isinstance(v, list) and all(level in ("enterprise", "solution") for level in v) for v in types.values()):
            result.success = False
            result.errors.append("abstraction_levels params need types: element type -> a list of enterprise and/or solution")
            return result
        from deriva.adapters.archimate.models import Relationship  # noqa: TID251 - known layer exception (see docs/architecture.md)

        rules = LevelRules(types={str(k): tuple(v) for k, v in types.items()})
        elements = archimate_manager.get_elements()
        by_id = {e.identifier: e for e in elements}
        sources = {e.identifier: str((e.properties or {}).get("source") or "") for e in elements if e.element_type == "ApplicationComponent"}
        wanted = sorted({s for s in sources.values() if s.startswith(("unit::", "module::"))})
        rows = {str(r["id"]): r for r in (graph_manager.query(SOURCES, {"ids": wanted}) if graph_manager and wanted else [])}
        components = []
        for identifier, source in sorted(sources.items()):
            row = rows.get(source)
            if not row or not row.get("path"):
                continue
            kind = "unit" if "DeployableUnit" in (row.get("labels") or []) else ("system" if row.get("system") else "module")
            components.append(Component(identifier=identifier, kind=kind, folder=str(row["path"]).replace(chr(92), "/")))

        levels = assign_levels([{"identifier": e.identifier, "type": e.element_type} for e in elements], components, rules)
        archimate_manager.update_element_properties({identifier: {"levels": sorted(lv)} for identifier, lv in levels.items()})

        relationships = archimate_manager.get_relationships()
        existing = {(r.source, r.relationship_type, r.target) for r in relationships}
        added: list[tuple[str, str, str, str]] = [(p, "Composition", c, "roll_up") for p, c, _, _ in rollups(components, levels)]
        realizations = [
            (r.source, r.target) for r in relationships if r.relationship_type == "Realization" and by_id.get(r.target) and by_id[r.target].element_type == "ApplicationService"
        ]
        added += [(top, "Realization", service, "level_lift") for top, service in service_lifts(components, levels, realizations)]
        for source, relationship_type, target, origin in added:
            if (source, relationship_type, target) in existing:
                continue
            shared, cross = relationship_levels(levels.get(source, frozenset()), levels.get(target, frozenset()))
            archimate_manager.add_relationship(
                Relationship(
                    source=source,
                    target=target,
                    relationship_type=relationship_type,
                    identifier=_relationship_id(source, relationship_type, target),
                    properties={"derived_from": origin, "levels": sorted(shared), "cross_level": cross},
                )
            )
            existing.add((source, relationship_type, target))
            result.relationships_created += 1
        # Every relationship on the levels both its ends share
        updates = {}
        for r in archimate_manager.get_relationships():
            shared, cross = relationship_levels(levels.get(r.source, frozenset()), levels.get(r.target, frozenset()))
            updates[r.identifier] = {"levels": sorted(shared), "cross_level": cross}
        archimate_manager.update_relationship_properties(updates)
        result.report = {
            "components": {kind: sum(1 for c in components if c.kind == kind) for kind in ("system", "module", "unit")},
            "elements": {level: sum(1 for lv in levels.values() if level in lv) for level in ("enterprise", "solution")},
            "relationships": {"cross_level": sum(1 for u in updates.values() if u["cross_level"]), "total": len(updates)},
        }
        return result
