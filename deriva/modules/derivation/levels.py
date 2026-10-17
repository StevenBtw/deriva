"""Abstraction levels of the derived model, from structure only (no LLM).

Two levels: ``enterprise`` (the semantic abstraction: the business layer, application and technology services, the
top-level components, the platform node) and ``solution`` (close to the code: units, modules and libraries,
interfaces, data objects, system software). Which types sit on which level is a versioned table (the step's params).

Components form a hierarchy by folder: a component's parent is the nearest component whose folder holds its folder;
at one folder a system holds a module and a module holds a unit. A component without a parent is top-level: on
both levels when it is a unit or a module, on the enterprise level when it is a system. Every other component is on
the solution level. A relationship is on the levels both its ends share; with none shared it is a cross-level link.

Pure functions: the caller passes the components (with their kind and folder), the elements and the realizations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ENTERPRISE, SOLUTION = "enterprise", "solution"
BOTH = frozenset({ENTERPRISE, SOLUTION})
RANK = {"system": 3, "module": 2, "unit": 1}  # At one folder the higher rank holds the lower


@dataclass(frozen=True)
class LevelRules:
    """The levels per element type (components are placed by the hierarchy); a type not listed is enterprise."""

    types: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class Component:
    identifier: str  # The element's identifier
    kind: str  # system, module or unit
    folder: str  # The source's folder (repository folder first)


def component_parents(components: list[Component]) -> dict[str, str | None]:
    """Each component's parent: the nearest component whose folder holds its folder (at one folder: a higher rank)."""
    parents: dict[str, str | None] = {}
    for c in components:
        holders = [
            o for o in components if o.identifier != c.identifier and (c.folder.startswith(o.folder + "/") or (o.folder == c.folder and RANK.get(o.kind, 0) > RANK.get(c.kind, 0)))
        ]
        best = max(holders, key=lambda o: (len(o.folder), RANK.get(o.kind, 0), o.identifier), default=None)
        parents[c.identifier] = best.identifier if best else None
    return parents


def assign_levels(elements: list[dict[str, str]], components: list[Component], rules: LevelRules) -> dict[str, frozenset[str]]:
    """The levels of every element: components by their place in the hierarchy, other types by the table."""
    parents = component_parents(components)
    kinds = {c.identifier: c.kind for c in components}
    levels: dict[str, frozenset[str]] = {}
    for e in elements:
        identifier, element_type = e["identifier"], e["type"]
        if identifier in kinds:
            if parents[identifier] is not None:
                levels[identifier] = frozenset({SOLUTION})
            else:
                levels[identifier] = frozenset({ENTERPRISE}) if kinds[identifier] == "system" else BOTH
        else:
            levels[identifier] = frozenset(rules.types.get(element_type, (ENTERPRISE,)))
    return levels


def relationship_levels(source: frozenset[str], target: frozenset[str]) -> tuple[frozenset[str], bool]:
    """(levels, cross_level): the levels both ends share; none shared is a cross-level link."""
    shared = source & target
    return shared, not shared


def rollups(components: list[Component], levels: dict[str, frozenset[str]]) -> list[tuple[str, str, frozenset[str], bool]]:
    """(parent, child, levels, cross_level) per parent link of the hierarchy, sorted: the roll-up Compositions."""
    out = []
    for child, parent in component_parents(components).items():
        if parent is not None:
            shared, cross = relationship_levels(levels.get(parent, frozenset()), levels.get(child, frozenset()))
            out.append((parent, child, shared, cross))
    return sorted(out, key=lambda r: (r[0], r[1]))


def top_level(identifier: str, parents: dict[str, str | None]) -> str:
    """The top-level component above a component (itself when it has no parent)."""
    seen = {identifier}
    while (parent := parents.get(identifier)) is not None and parent not in seen:
        seen.add(parent)
        identifier = parent
    return identifier


def service_lifts(components: list[Component], levels: dict[str, frozenset[str]], realizations: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """(top-level component, service) for each service a component off the enterprise level realizes: the
    enterprise level stands on its own. Sorted, without duplicates or a realization that already exists."""
    parents = component_parents(components)
    existing = set(realizations)
    lifts = set()
    for component, service in realizations:
        if component in parents and ENTERPRISE not in levels.get(component, frozenset()):
            top = top_level(component, parents)
            if top != component and ENTERPRISE in levels.get(top, frozenset()) and (top, service) not in existing:
                lifts.add((top, service))
    return sorted(lifts)
