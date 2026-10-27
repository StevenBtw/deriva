"""Joint consistency core: exact, tiered selection of relationships and duplicate merges.

Metamodel-agnostic: the target metamodel is injected as a `Metamodel` value.
Every relationship proposal and merge candidate is a 0/1 variable. Named hard
constraints:

- H1 at most one relationship per ordered (source, target) pair
- H2 at most one incoming relationship of a single-parent type per element
- H3 no cycles in acyclic relationship types (lazy cuts on the merged model)
- H4 a kept relationship between u and v excludes merging u and v
- H5 merges must keep H1/H2 true after redirection (one merge, or two that join both ends)
- H6 no merge chains without direct evidence (transitivity)

Tiers are optimised in strict order (tier 1 first, fixed, then tier 2, then 3),
then a lexicographic maximum over the variables in a canonical order: relationships
by (tier, source, type, target), merges by (tier, first, second); each variable in
turn is fixed to 1 when that is still feasible. No weights and no confidence, so the
selection does not depend on identifiers or on the input order. Pure: no I/O, no LLM.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from solvor import solve_milp
from solvor.types import Status

MAX_CYCLE_ROUNDS = 20
# Evidence tier per relationship origin (``derived_from``): 1 direct structure, 2 indirect structure, 3 word
# overlap and LLM. The joint_consistency step takes the table from its params (versioned config); this is the default.
DEFAULT_ORIGIN_TIERS: dict[str, int] = {
    "containment": 1,
    "graph_link": 1,
    "listed_members": 1,
    "membership": 1,
    "configuration": 1,
    "dependency": 1,
    "same_name": 1,
    "named_in_code": 2,
    "graph_neighbor": 2,
    "community": 2,
    "rule": 3,
}


def origin_tier(derived_from: str | None, tiers: dict[str, int] | None = None) -> int:
    """Evidence tier of a relationship from its `derived_from` origin tag: a graph edge is tier 1, else the table; unknown 3."""
    if derived_from and (derived_from.startswith("Graph:") or derived_from.endswith("_edge")):
        return 1
    return (DEFAULT_ORIGIN_TIERS if tiers is None else tiers).get(derived_from or "", 3)


@dataclass(frozen=True)
class Metamodel:
    """Target metamodel rules, supplied by the adapter that owns them."""

    is_valid: Callable[[str, str, str], bool]
    single_parent_types: frozenset[str] = frozenset()
    acyclic_types: frozenset[str] = frozenset()


@dataclass(frozen=True)
class JointElement:
    identifier: str
    element_type: str
    pagerank: float = 0.0
    doc_length: int = 0


@dataclass(frozen=True)
class Proposal:
    identifier: str
    source: str
    target: str
    relationship_type: str
    tier: int


def canonical_key(p: Proposal) -> tuple[int, str, str, str, str]:
    """The canonical order of a relationship: (tier, source, type, target), then its identifier for exact repeats."""
    return (p.tier, p.source, p.relationship_type, p.target, p.identifier)


@dataclass(frozen=True)
class MergeCandidate:
    first: str
    second: str
    tier: int
    score: float = 0.0
    evidence: str = ""


@dataclass
class JointDecision:
    status: str
    kept: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)
    merges: dict[str, str] = field(default_factory=dict)
    redirects: dict[str, tuple[str, str]] = field(default_factory=dict)
    # The solve report: proposals, constraint rows by name (H1-H6), cycle cuts, parts, and what changed
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "optimal"


@dataclass
class _Row:
    name: str
    coef: dict[int, float]
    rhs: float


def solve(
    elements: list[JointElement],
    proposals: list[Proposal],
    merge_candidates: list[MergeCandidate],
    metamodel: Metamodel,
) -> JointDecision:
    """Return the jointly optimal, constraint-satisfying selection."""
    types = {e.identifier: e.element_type for e in elements}
    dropped: dict[str, str] = {}
    valid: list[Proposal] = []
    for p in sorted(proposals, key=canonical_key):
        if p.source == p.target:
            dropped[p.identifier] = "self_loop"
        elif p.source not in types or p.target not in types or not metamodel.is_valid(types[p.source], p.relationship_type, types[p.target]):
            dropped[p.identifier] = "invalid_metamodel"
        else:
            valid.append(p)

    merges = _canonical_merges(merge_candidates, types)
    prefilter = dict(Counter(dropped.values()))
    if not valid and not merges:
        return _reported(JointDecision(status="optimal", dropped=dropped), proposals, valid, merges, prefilter, [])

    status, chosen, rows = _select(valid, merges, metamodel)
    if status != "optimal":
        return _reported(JointDecision(status=status, dropped=dropped), proposals, valid, merges, prefilter, rows)
    return _reported(_decision(elements, valid, merges, rows, chosen, dropped), proposals, valid, merges, prefilter, rows)


def _reported(
    decision: JointDecision, proposals: list[Proposal], valid: list[Proposal], merges: list[MergeCandidate], prefilter: dict[str, int], rows: list[_Row]
) -> JointDecision:
    """The decision with its solve report (logged for the benchmark; the MILP as a safety net)."""
    parts = _parts(valid, merges)
    part_of = {v: k for k, variables in enumerate(parts) for v in variables}
    decision.stats = {
        "proposals": len(proposals),
        "valid": len(valid),
        "merge_candidates": len(merges),
        "variables": len(valid) + len(merges),
        "constraints": len(rows),
        "prefilter": prefilter,
        "rows": dict(Counter(row.name for row in rows if row.name != "H3")),
        "cycle_cuts": sum(1 for row in rows if row.name == "H3"),
        "parts": len(parts),
        "constrained_parts": len({part_of[next(iter(row.coef))] for row in rows if row.coef}),
        "kept": len(decision.kept),
        "dropped": len(decision.dropped),
        "merges": len(decision.merges),
        "redirects": len(decision.redirects),
    }
    return decision


def _select(props: list[Proposal], merges: list[MergeCandidate], metamodel: Metamodel) -> tuple[str, set[int], list[_Row]]:
    """The optimal variables (proposals first, then merges), with the status and all rows incl. cuts.

    Every constraint and every cycle stays within one connected part of the model
    (elements linked by proposals and merge candidates), and all objectives are sums
    over variables, so each part is solved on its own: the same optimum as one solve
    over everything, without a search over combinations of unrelated parts.
    """
    tiers = [p.tier for p in props] + [m.tier for m in merges]
    position = {v: k for k, v in enumerate(_canonical_order(props, merges))}
    rows = _build_rows(props, merges, metamodel.single_parent_types)
    parts = _parts(props, merges)
    part_of = {v: k for k, variables in enumerate(parts) for v in variables}
    rows_of: dict[int, list[_Row]] = defaultdict(list)
    for row in rows:
        rows_of[part_of[next(iter(row.coef))]].append(row)

    chosen: set[int] = set()
    cuts: list[_Row] = []
    for k, variables in enumerate(parts):
        ordered = sorted(variables, key=position.__getitem__)
        status, part_chosen, part_cuts = _select_part(ordered, tiers, rows_of[k], props, merges, metamodel.acyclic_types)
        cuts += part_cuts
        if status != "optimal":
            return status, set(), rows + cuts
        chosen |= part_chosen
    return "optimal", chosen, rows + cuts


def _canonical_order(props: list[Proposal], merges: list[MergeCandidate]) -> list[int]:
    """All variables in canonical order: by tier; within a tier relationships (source, type, target), then merges (first, second)."""
    keys: list[tuple[int, int, str, str, str, str]] = [(p.tier, 0, p.source, p.relationship_type, p.target, p.identifier) for p in props]
    keys += [(m.tier, 1, m.first, m.second, "", "") for m in merges]
    return sorted(range(len(keys)), key=lambda i: keys[i])


def _parts(props: list[Proposal], merges: list[MergeCandidate]) -> list[list[int]]:
    """Variables grouped by connected part of the element graph, in input order."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ends = [(p.source, p.target) for p in props] + [(m.first, m.second) for m in merges]
    for a, b in ends:
        parent[find(a)] = find(b)
    groups: dict[str, list[int]] = defaultdict(list)
    for i, (a, _) in enumerate(ends):
        groups[find(a)].append(i)
    return sorted(groups.values(), key=lambda variables: variables[0])


def _select_part(
    variables: list[int],
    tiers: list[int],
    rows: list[_Row],
    props: list[Proposal],
    merges: list[MergeCandidate],
    acyclic: frozenset[str],
) -> tuple[str, set[int], list[_Row]]:
    """Lexicographic optimum of one part (``variables`` in canonical order), with lazy cycle cuts; returns status, choice and cuts."""
    cuts: list[_Row] = []
    for round_ in range(MAX_CYCLE_ROUNDS + 1):
        if not rows and not cuts:
            # Nothing constrains the part: every variable is worth taking
            chosen: set[int] | None = set(variables)
        else:
            chosen = _lexicographic(variables, tiers, rows + cuts)
        if chosen is None:
            return "solver_failed", set(), cuts
        cycles = _find_cycles(props, merges, chosen, acyclic)
        if not cycles:
            return "optimal", chosen, cuts
        if round_ == MAX_CYCLE_ROUNDS:
            break
        # One cut per cycle in the selection, so independent cycles cost one round
        cuts += [_Row("H3", {i: 1.0 for i in c}, float(len(c) - 1)) for c in cycles]
    return "cycle_limit", set(), cuts


def _canonical_merges(candidates: list[MergeCandidate], types: dict[str, str]) -> list[MergeCandidate]:
    best: dict[tuple[str, str], MergeCandidate] = {}
    for m in candidates:
        a, b = sorted((m.first, m.second))
        if a == b or a not in types or b not in types or types[a] != types[b]:
            continue
        m = replace(m, first=a, second=b)
        current = best.get((a, b))
        if current is None or (m.tier, m.evidence) < (current.tier, current.evidence):
            best[(a, b)] = m
    return sorted(best.values(), key=lambda m: (m.tier, m.first, m.second))


def _collide_after_merge(p: Proposal, q: Proposal, u: str, v: str, single_parent: frozenset[str]) -> bool:
    def rep(x: str) -> str:
        return u if x == v else x

    if (p.source, p.target) == (q.source, q.target):
        return False
    if (rep(p.source), rep(p.target)) == (rep(q.source), rep(q.target)):
        return True
    return p.relationship_type == q.relationship_type and p.relationship_type in single_parent and p.target != q.target and rep(p.target) == rep(q.target)


def _build_rows(props: list[Proposal], merges: list[MergeCandidate], single_parent: frozenset[str]) -> list[_Row]:
    rows: list[_Row] = []
    n_p = len(props)
    by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    one_parent: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, p in enumerate(props):
        by_pair[(p.source, p.target)].append(i)
        if p.relationship_type in single_parent:
            one_parent[(p.target, p.relationship_type)].append(i)
    rows += [_Row("H1", {i: 1.0 for i in idx}, 1.0) for idx in by_pair.values() if len(idx) > 1]
    rows += [_Row("H2", {i: 1.0 for i in idx}, 1.0) for idx in one_parent.values() if len(idx) > 1]

    index = {(m.first, m.second): n_p + k for k, m in enumerate(merges)}
    for k, m in enumerate(merges):
        var = n_p + k
        pair = {m.first, m.second}
        touching = [i for i, p in enumerate(props) if p.source in pair or p.target in pair]
        for i in touching:
            if {props[i].source, props[i].target} == pair:
                rows.append(_Row("H4", {i: 1.0, var: 1.0}, 1.0))
        for a_idx, i in enumerate(touching):
            for j in touching[a_idx + 1 :]:
                if _collide_after_merge(props[i], props[j], m.first, m.second, single_parent):
                    rows.append(_Row("H5", {i: 1.0, j: 1.0, var: 1.0}, 2.0))
        # Two merges, one joining the sources and one the targets of two relationships, put both on one pair; neither
        # merge alone does (a chain of merges needs its direct merge, H6, so pairs of direct merges cover chains)
        for i in (i for i, p in enumerate(props) if p.source == m.first):
            for j in (j for j, q in enumerate(props) if q.source == m.second):
                other = index.get(tuple(sorted((props[i].target, props[j].target))))
                if other is not None and other != var and props[i].target != props[j].target:
                    rows.append(_Row("H5", {i: 1.0, j: 1.0, var: 1.0, other: 1.0}, 3.0))

    for k1, m1 in enumerate(merges):
        for k2 in range(k1 + 1, len(merges)):
            m2 = merges[k2]
            shared = {m1.first, m1.second} & {m2.first, m2.second}
            if len(shared) != 1:
                continue
            a = ({m1.first, m1.second} - shared).pop()
            c = ({m2.first, m2.second} - shared).pop()
            coef = {n_p + k1: 1.0, n_p + k2: 1.0}
            third = index.get((min(a, c), max(a, c)))
            if third is not None:
                coef[third] = -1.0
            rows.append(_Row("H6", coef, 1.0))
    return rows


def _lexicographic(variables: list[int], tiers: list[int], rows: list[_Row]) -> set[int] | None:
    """Maximise tier 1, then 2, then 3 over ``variables``, then fix them one by one in their (canonical) order, each to
    1 when still feasible: the lexicographic maximum. The chosen ones."""
    index = {v: j for j, v in enumerate(variables)}
    n = len(variables)
    matrix: list[list[float]] = []
    bounds: list[float] = []
    for row in rows:
        line = [0.0] * n
        for i, c in row.coef.items():
            line[index[i]] = c
        matrix.append(line)
        bounds.append(row.rhs)
    for j in range(n):
        line = [0.0] * n
        line[j] = 1.0
        matrix.append(line)
        bounds.append(1.0)

    def best(c: list[float], warm: list[int] | None) -> list[int] | None:
        result = solve_milp(c, matrix, bounds, integers=list(range(n)), minimize=False, warm_start=warm)
        if result.status != Status.OPTIMAL or result.solution is None:
            return None
        return [round(v) for v in result.solution]

    solution: list[int] | None = None
    for tier in (1, 2, 3):
        c = [1.0 if tiers[v] == tier else 0.0 for v in variables]
        if not any(c):
            continue
        solution = best(c, solution)
        if solution is None:
            return None
        achieved = sum(solution[j] for j in range(n) if c[j])
        matrix.append([-v for v in c])
        bounds.append(-achieved + 0.5)
    for j in range(n):
        # When the current solution already takes it, it is feasible: fixed to 1 without a solve
        if solution is None or solution[j] != 1:
            c = [0.0] * n
            c[j] = 1.0
            candidate = best(c, solution)
            if candidate is None:
                return None
            solution = candidate
        line = [0.0] * n
        if solution[j] == 1:
            line[j] = -1.0
            bounds.append(-1.0)
        else:
            line[j] = 1.0
            bounds.append(0.0)
        matrix.append(line)
    assert solution is not None
    return {variables[j] for j in range(n) if solution[j] == 1}


def _representatives(merges: list[MergeCandidate]) -> dict[str, str]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in merges:
        ra, rb = find(m.first), find(m.second)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {x: find(x) for x in parent}


def _find_cycles(
    props: list[Proposal],
    merges: list[MergeCandidate],
    chosen: set[int],
    acyclic: frozenset[str],
) -> list[list[int]]:
    """Cycles in the selection: each found cycle's relationships are set aside before the next search."""
    cycles: list[list[int]] = []
    remaining = set(chosen)
    while (cycle := _find_cycle(props, merges, remaining, acyclic)) is not None:
        cycles.append(cycle)
        remaining -= {i for i in cycle if i < len(props)}
    return cycles


def _find_cycle(
    props: list[Proposal],
    merges: list[MergeCandidate],
    chosen: set[int],
    acyclic: frozenset[str],
) -> list[int] | None:
    n_p = len(props)
    chosen_merges = [(k, merges[k - n_p]) for k in sorted(chosen) if k >= n_p]
    rep = _representatives([m for _, m in chosen_merges])
    for rel_type in sorted(acyclic):
        edges: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for i in sorted(chosen):
            if i < n_p and props[i].relationship_type == rel_type:
                p = props[i]
                edges[rep.get(p.source, p.source)].append((rep.get(p.target, p.target), i))
        found = _cycle_in(edges)
        if found:
            cycle_vars, cycle_nodes = found
            merge_vars = [k for k, m in chosen_merges if rep.get(m.first, m.first) in cycle_nodes]
            return cycle_vars + merge_vars
    return None


def _cycle_in(
    edges: dict[str, list[tuple[str, int]]],
) -> tuple[list[int], set[str]] | None:
    state: dict[str, int] = {}
    path_nodes: list[str] = []
    path_vars: list[int] = []

    def visit(node: str) -> tuple[list[int], set[str]] | None:
        state[node] = 1
        path_nodes.append(node)
        for nxt, var in sorted(edges.get(node, [])):
            if state.get(nxt) == 1:
                start = path_nodes.index(nxt)
                return path_vars[start:] + [var], set(path_nodes[start:])
            if nxt not in state:
                path_vars.append(var)
                found = visit(nxt)
                if found:
                    return found
                path_vars.pop()
        state[node] = 2
        path_nodes.pop()
        return None

    for node in sorted(edges):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def _reason(
    i: int,
    rows: list[_Row],
    chosen: set[int],
    props: list[Proposal],
    merges: list[MergeCandidate],
) -> str:
    n_p = len(props)
    for row in rows:
        if i not in row.coef:
            continue
        winners = [j for j in sorted(row.coef) if j != i and j in chosen]
        if winners:
            labels = [props[j].identifier if j < n_p else f"merge:{merges[j - n_p].first}+{merges[j - n_p].second}" for j in winners]
            return f"{row.name}:{','.join(labels)}"
    return "unselected"


def _decision(
    elements: list[JointElement],
    props: list[Proposal],
    merges: list[MergeCandidate],
    rows: list[_Row],
    chosen: set[int],
    dropped: dict[str, str],
) -> JointDecision:
    n_p = len(props)
    by_id = {e.identifier: e for e in elements}
    rep = _representatives([merges[k - n_p] for k in sorted(chosen) if k >= n_p])
    groups: dict[str, list[str]] = defaultdict(list)
    for member, root in rep.items():
        groups[root].append(member)
    survivor_of: dict[str, str] = {}
    for members in groups.values():
        survivor = min(members, key=lambda m: (-by_id[m].pagerank, -by_id[m].doc_length, m))
        for member in members:
            if member != survivor:
                survivor_of[member] = survivor

    kept: list[str] = []
    redirects: dict[str, tuple[str, str]] = {}
    for i, p in enumerate(props):
        if i in chosen:
            kept.append(p.identifier)
            new_pair = (
                survivor_of.get(p.source, p.source),
                survivor_of.get(p.target, p.target),
            )
            if new_pair != (p.source, p.target):
                redirects[p.identifier] = new_pair
        else:
            dropped[p.identifier] = _reason(i, rows, chosen, props, merges)
    return JointDecision(
        status="optimal",
        kept=kept,
        dropped=dropped,
        merges=survivor_of,
        redirects=redirects,
    )
