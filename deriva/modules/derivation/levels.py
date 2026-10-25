"""Abstraction levels of the derived model, from structure only (no LLM).

Two levels: ``enterprise`` (the semantic abstraction: the business layer, application and technology services, the
top-level components, the platform node) and ``solution`` (close to the code: units, modules and libraries,
interfaces, data objects, system software). Which types sit on which level is a versioned table (the step's params).

Components form a hierarchy by folder: a component's parent is the nearest component whose folder holds its folder;
at one folder a system holds the rest, the only unit there holds a module (system, units, modules, libraries), and a
module holds the units when there are several (the entry points of one package). A module that one unit alone builds
(graph BUILDS) and that the folders put under a system is that unit's. A component without a parent is top-level: on
both levels when it is a unit or a module, on the enterprise level when it is a system. Every other component is on
the solution level. A relationship is on the levels both its ends share; with none shared it is a cross-level link.

The enterprise level stands on its own: its relationships between enterprise elements are the ones a closed,
versioned viewpoint table draws, each derived by the metamodel's valid derivation rules from direct relationships.

Pure functions: the caller passes the components (with their kind and folder), the elements and the relationships;
the metamodel's tiers and derivation rules are injected.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from deriva.modules.derivation.derivation_rules import Derived, derive, rules_from

ENTERPRISE, SOLUTION = "enterprise", "solution"
BOTH = frozenset({ENTERPRISE, SOLUTION})
RANK = {"system": 3, "module": 2, "unit": 1}  # At one folder the higher rank holds the lower (see _ranks for a lone unit)


@dataclass(frozen=True)
class LevelRules:
    """The levels per element type (components are placed by the hierarchy); a type not listed is enterprise. ``roles``:
    per type, the levels of the elements of one role (a service node is solution, the platform node enterprise)."""

    types: dict[str, tuple[str, ...]] = field(default_factory=dict)
    roles: dict[str, dict[str, tuple[str, ...]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Component:
    identifier: str  # The element's identifier
    kind: str  # system, module or unit
    folder: str  # The source's folder (repository folder first)


def _ranks(components: list[Component], units_at: dict[str, int] | None = None) -> dict[str, float]:
    """Each component's rank within its folder: ``RANK``, except that the only unit at a folder ranks above a module there.
    ``units_at``: the deployable units per folder from structure (default: the unit components)."""
    units = units_at if units_at is not None else Counter(c.folder for c in components if c.kind == "unit")
    return {c.identifier: RANK["module"] + 0.5 if c.kind == "unit" and units[c.folder] == 1 else float(RANK.get(c.kind, 0)) for c in components}


def component_parents(components: list[Component], units_at: dict[str, int] | None = None, built_by: dict[str, list[str]] | None = None) -> dict[str, str | None]:
    """Each component's parent: the nearest component whose folder holds its folder. Within one folder the next higher
    rank (``_ranks``); from a folder below, the highest ``RANK`` at the nearest holding folder (a nested module's module)."""
    rank = _ranks(components, units_at)
    parents: dict[str, str | None] = {}
    for c in components:
        inside = [o for o in components if o.identifier != c.identifier and o.folder == c.folder and rank[o.identifier] > rank[c.identifier]]
        above = [o for o in components if c.folder.startswith(o.folder + "/")]
        if inside:
            best = min(inside, key=lambda o: (rank[o.identifier], o.identifier))
        else:
            best = max(above, key=lambda o: (len(o.folder), RANK.get(o.kind, 0), o.identifier), default=None)
        parents[c.identifier] = best.identifier if best else None
    # A unit composes the modules it builds: a module the folders put under a system, built by one unit, is that unit's
    kinds, folders = {c.identifier: c.kind for c in components}, {c.identifier: c.folder for c in components}
    for c in components:
        builders = [u for u in (built_by or {}).get(c.identifier, []) if kinds.get(u) == "unit" and u != c.identifier]
        parent = parents[c.identifier]
        if c.kind == "module" and len(builders) == 1 and (parent is None or kinds.get(parent) == "system"):
            unit = builders[0]
            if (c.folder == folders[unit] or c.folder.startswith(folders[unit] + "/")) and parents.get(unit) != c.identifier:
                parents[c.identifier] = unit
    return parents


def assign_levels(
    elements: list[dict[str, str]], components: list[Component], rules: LevelRules, units_at: dict[str, int] | None = None, built_by: dict[str, list[str]] | None = None
) -> dict[str, frozenset[str]]:
    """The levels of every element: components by their place in the hierarchy, other types by the table."""
    parents = component_parents(components, units_at, built_by)
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
            by_role = rules.roles.get(element_type, {}).get(str(e.get("role") or ""))
            levels[identifier] = frozenset(by_role if by_role is not None else rules.types.get(element_type, (ENTERPRISE,)))
    return levels


def relationship_levels(source: frozenset[str], target: frozenset[str]) -> tuple[frozenset[str], bool]:
    """(levels, cross_level): the levels both ends share; none shared is a cross-level link."""
    shared = source & target
    return shared, not shared


def rollups(
    components: list[Component], levels: dict[str, frozenset[str]], units_at: dict[str, int] | None = None, built_by: dict[str, list[str]] | None = None
) -> list[tuple[str, str, frozenset[str], bool]]:
    """(parent, child, levels, cross_level) per parent link of the hierarchy, sorted: the roll-up Compositions."""
    out = []
    for child, parent in component_parents(components, units_at, built_by).items():
        if parent is not None:
            shared, cross = relationship_levels(levels.get(parent, frozenset()), levels.get(child, frozenset()))
            out.append((parent, child, shared, cross))
    return sorted(out, key=lambda r: (r[0], r[1]))


def ancestors(identifier: str, parents: dict[str, str | None]) -> list[str]:
    """The components above a component, nearest first."""
    out: list[str] = []
    while (parent := parents.get(identifier)) is not None and parent not in out and parent != identifier:
        out.append(parent)
        identifier = parent
    return out


def interface_owners(
    interfaces: dict[str, tuple[str, frozenset[str]]], builds: dict[str, list[str]], kinds: dict[str, str], own_files: dict[str, frozenset[str]]
) -> dict[str, str]:
    """interface -> the module that composes it instead of its unit: where the unit builds several modules, the one
    module it builds whose own files hold all the interface's member files (a system is no solution component).

    Args:
        interfaces: Interface -> (its unit's component, its member file paths)
        builds: A unit's component -> the components of the modules and systems it builds
        kinds: Component -> its kind (system, module, unit)
        own_files: A module's component -> its own file paths
    """
    owners = {}
    for interface, (unit, paths) in sorted(interfaces.items()):
        built = builds.get(unit, [])
        if len(built) < 2 or not paths:
            continue
        holding = [m for m in built if kinds.get(m) == "module" and paths <= own_files.get(m, frozenset())]
        if len(holding) == 1:
            owners[interface] = holding[0]
    return owners


def enterprise_derivations(
    relationships: list[tuple[str, str, str, str]],
    levels: dict[str, frozenset[str]],
    types: dict[str, str],
    patterns: list[tuple[str, str, str]],
    rules: Iterable[tuple[str, Iterable[str], Iterable[str], str, str]],
    strength: tuple[str, ...],
    tier: Callable[[str, str, str], str | None],
) -> list[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]]:
    """(source, type, target, chain, rules) per relationship the enterprise viewpoint draws: one the metamodel's valid
    derivation rules derive from a chain of the model's direct-tier relationships (``derivation_rules.derive``, the
    code that scores against a reference), between two enterprise elements, whose (source type, type, target type)
    is one of the viewpoint's ``patterns``. One per pair, the weaker structural type first (``strength``, weakest
    first), then the shorter chain; a pair the model already relates gets none. Sorted.

    Args:
        relationships: (identifier, source, type, target) of the model's relationships
        levels: Element -> its levels
        types: Element -> its element type
        patterns: The viewpoint's (source type, relationship type, target type) triples
        rules: The metamodel's valid derivation rules as data (``derivation_rules.rules_from``)
        strength: The structural relationship types, weakest first
        tier: (source type, relationship type, target type) -> "direct", "derived" or None (not allowed)
    """
    direct = [r for r in relationships if tier(types.get(r[1], ""), r[2], types.get(r[3], "")) == "direct"]
    derived = derive(direct, types, rules_from(rules), strength, lambda s, k, t: tier(s, k, t) is not None)
    wanted, related = set(patterns), {(s, t) for _, s, _, t in relationships}
    best: dict[tuple[str, str], tuple[tuple[int, int, tuple[str, ...]], Derived]] = {}
    for d in derived.values():
        if ENTERPRISE not in levels.get(d.source, frozenset()) or ENTERPRISE not in levels.get(d.target, frozenset()):
            continue
        if (types.get(d.source), d.relationship_type, types.get(d.target)) not in wanted or (d.source, d.target) in related:
            continue
        rank = strength.index(d.relationship_type) if d.relationship_type in strength else len(strength)
        key = (rank, len(d.chain), d.chain)
        if (d.source, d.target) not in best or key < best[(d.source, d.target)][0]:
            best[(d.source, d.target)] = (key, d)
    return sorted((d.source, d.relationship_type, d.target, d.chain, d.rules) for _, d in best.values())
