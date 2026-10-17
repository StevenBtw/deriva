"""Abstraction levels - Refine Step.

Tags every element and relationship with the abstraction levels it belongs to (``levels``; a relationship whose
ends share no level is ``cross_level``), adds the roll-up Compositions of the component hierarchy (system ->
modules and units -> nested modules), lets the top-level component realize, at the enterprise level, a service
that a solution-level component realizes, and hands an interface to the module it lies in where its unit builds
several modules (the module composes it instead of the unit). A Composition against the hierarchy (a unit composing
the module that holds it) is removed. Structural only: the hierarchy comes from the folders of the components'
sources (deployable units, build modules), the levels per type from the step's params. No LLM call.

Refine Step Name: "abstraction_levels"
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from deriva.common.ocel import hash_content
from deriva.modules.derivation.levels import Component, LevelRules, assign_levels, component_parents, interface_owners, relationship_levels, rollups, service_lifts

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see docs/architecture.md)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see docs/architecture.md)

logger = logging.getLogger(__name__)

SOURCES = "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.path AS path, labels(n) AS labels, n.isSystem AS system"
BUILT = "MATCH (u:Graph:DeployableUnit)-[:`Graph:BUILDS`]->(m:Graph:BuildModule) WHERE u.id IN $ids RETURN u.id AS unit, m.id AS module"
OWN_FILES = "MATCH (m:Graph:BuildModule)-[:`Graph:INCLUDES`]->(f:Graph:File) WHERE m.id IN $ids RETURN m.id AS module, f.filePath AS path"
UNITS = "MATCH (u:Graph:DeployableUnit) WHERE u.active = true RETURN u.id AS id, u.path AS path, labels(u) AS labels"
MEMBER_FILES = "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.filePath AS path"


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
            params: ``types``: element type -> its levels (a type not listed is enterprise); ``roles`` (optional):
                element type -> role -> the levels of that type's elements of that role
        """
        result = RefineResult(success=True, step_name="abstraction_levels")
        types, roles = (params or {}).get("types"), (params or {}).get("roles", {})
        is_levels = lambda v: isinstance(v, list) and all(level in ("enterprise", "solution") for level in v)  # noqa: E731 - a one-line helper
        if not isinstance(types, dict) or not all(is_levels(v) for v in types.values()):
            result.success = False
            result.errors.append("abstraction_levels params need types: element type -> a list of enterprise and/or solution")
            return result
        if not isinstance(roles, dict) or not all(isinstance(r, dict) and all(is_levels(v) for v in r.values()) for r in roles.values()):
            result.success = False
            result.errors.append("abstraction_levels params roles: element type -> role -> a list of enterprise and/or solution")
            return result
        from deriva.adapters.archimate.models import Relationship  # noqa: TID251 - known layer exception (see docs/architecture.md)

        rules = LevelRules(types={str(k): tuple(v) for k, v in types.items()}, roles={str(t): {str(r): tuple(v) for r, v in by.items()} for t, by in roles.items()})
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

        # The units per folder from structure: a unit that became no element still counts
        unit_rows = graph_manager.query(UNITS) if graph_manager and components else []
        units_at = Counter(str(r["path"]).replace(chr(92), "/") for r in unit_rows if "DeployableUnit" in (r.get("labels") or []) and r.get("path"))
        # The units that build each module (graph BUILDS): a unit composes the modules it builds
        component_of_source = {source: identifier for identifier, source in sources.items()}
        unit_sources = sorted(sources[c.identifier] for c in components if c.kind == "unit")
        built_by: dict[str, list[str]] = {}
        for row in graph_manager.query(BUILT, {"ids": unit_sources}) if graph_manager and unit_sources else []:
            unit, module = component_of_source.get(str(row.get("unit") or "")), component_of_source.get(str(row.get("module") or ""))
            if unit and module:
                built_by.setdefault(module, []).append(unit)
        levels = assign_levels(
            [{"identifier": e.identifier, "type": e.element_type, "role": str((e.properties or {}).get("role") or "")} for e in elements], components, rules, units_at, built_by
        )
        archimate_manager.update_element_properties({identifier: {"levels": sorted(lv)} for identifier, lv in levels.items()})

        relationships = archimate_manager.get_relationships()
        moved = self._interface_owners(elements, components, sources, graph_manager) if graph_manager else {}
        # The module composes the interface instead of its unit (the unit reaches it through its roll-up)
        unit_of = {e.identifier: str((e.properties or {}).get("source") or "") for e in elements if e.identifier in moved}
        component_of = {source: identifier for identifier, source in sources.items()}
        dropped = [r for r in relationships if r.relationship_type == "Composition" and r.target in moved and r.source == component_of.get(unit_of[r.target])]
        rolled = [(p, "Composition", c, "roll_up") for p, c, _, _ in rollups(components, levels, units_at, built_by)]
        # The hierarchy alone composes one component into another: any other Composition between components is removed
        parents = component_parents(components, units_at, built_by)
        reversed_ = [r for r in relationships if r.relationship_type == "Composition" and r.source in parents and r.target in parents and parents[r.target] != r.source]
        if dropped or reversed_:
            archimate_manager.delete_relationships([r.identifier for r in dropped + reversed_])
            relationships = archimate_manager.get_relationships()
        existing = {(r.source, r.relationship_type, r.target) for r in relationships}
        added: list[tuple[str, str, str, str]] = list(rolled)
        added += [(moved[i], "Composition", i, "interface_owner") for i in sorted({r.target for r in dropped})]
        realizations = [
            (r.source, r.target) for r in relationships if r.relationship_type == "Realization" and by_id.get(r.target) and by_id[r.target].element_type == "ApplicationService"
        ]
        added += [(top, "Realization", service, "level_lift") for top, service in service_lifts(components, levels, realizations, units_at, built_by)]
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
            "interfaces_moved": len(dropped),
            "reversed": len(reversed_),
        }
        return result

    @staticmethod
    def _interface_owners(elements: list[Any], components: list[Component], sources: dict[str, str], graph_manager: GraphManager) -> dict[str, str]:
        """Interface -> the module component that composes it instead of its unit (``levels.interface_owners``)."""
        component_of = {source: identifier for identifier, source in sources.items()}
        kinds = {c.identifier: c.kind for c in components}
        interfaces = [e for e in elements if e.element_type == "ApplicationInterface" and str((e.properties or {}).get("source") or "") in component_of]
        units = sorted({str(e.properties["source"]) for e in interfaces})
        if not units:
            return {}
        builds: dict[str, list[str]] = {}
        for row in graph_manager.query(BUILT, {"ids": units}):
            unit, module = component_of.get(str(row.get("unit") or "")), component_of.get(str(row.get("module") or ""))
            if unit and module:
                builds.setdefault(unit, []).append(module)
        modules = sorted({sources[m] for built in builds.values() for m in built})
        own_files: dict[str, set[str]] = {}
        for row in graph_manager.query(OWN_FILES, {"ids": modules}) if modules else []:
            if row.get("module") in component_of and row.get("path"):
                own_files.setdefault(component_of[row["module"]], set()).add(str(row["path"]).replace(chr(92), "/"))
        members = sorted({str(m) for e in interfaces for m in (e.properties or {}).get("sources") or []})
        paths = {
            str(r["id"]): str(r["path"]).replace(chr(92), "/") for r in (graph_manager.query(MEMBER_FILES, {"ids": members}) if members else []) if r.get("id") and r.get("path")
        }
        candidates = {}
        for e in interfaces:
            listed = [str(m) for m in (e.properties or {}).get("sources") or []]
            # Every member must have a file: an interface with a member outside the files stays with its unit
            if listed and all(m in paths for m in listed):
                candidates[e.identifier] = (component_of[str(e.properties["source"])], frozenset(paths[m] for m in listed))
        return interface_owners(candidates, builds, kinds, {m: frozenset(p) for m, p in own_files.items()})
