"""Relationships derived from chains of direct relationships (pure; no LLM).

The derivation rules are data (``Rule``), each tagged with its rule number, so one engine serves the reference
scoring (a reference relationship counts as found when a chain of the model's direct relationships derives it) and
the enterprise abstraction (an EA relationship exists only as the derivation of a direct chain below it). The
metamodel decides whether a derived triple exists at all (``is_valid``, injected: modules use no adapter).

A rule joins two relationships that share an element:

- ``chain``: p(a, b) and q(b, c) give r(a, c);
- ``into``: p(a, b) and q(c, b) give r(a, c);
- ``from``: p(b, a) and q(b, c) give r(a, c);
- ``back``: p(a, b) and q(c, b) give r(c, a) (a relationship into an element transfers to what is related to it).

The derived type is the weakest of the two (``weakest``, by the given strength order), the first's or the second's
type, or a fixed relationship type.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

JOINS = ("chain", "into", "from", "back")


@dataclass(frozen=True)
class Rule:
    """One derivation rule: the relationship types it joins, how, and the type it derives."""

    number: str  # The rule's number in its source (cited in every derivation it makes)
    first: frozenset[str]
    second: frozenset[str]
    join: str  # One of JOINS
    result: str  # "weakest", "first", "second" or a relationship type


@dataclass(frozen=True)
class Derived:
    """A derived relationship: the direct relationships it follows from, in chain order, and the rules applied."""

    source: str
    relationship_type: str
    target: str
    chain: tuple[str, ...]
    rules: tuple[str, ...]


def rules_from(data: Iterable[tuple[str, Iterable[str], Iterable[str], str, str]]) -> list[Rule]:
    """Rules from plain data (number, first types, second types, join, result), as a metamodel adapter supplies them."""
    return [Rule(number=n, first=frozenset(a), second=frozenset(b), join=j, result=r) for n, a, b, j, r in data]


def _result(rule: Rule, first: str, second: str, strength: tuple[str, ...]) -> str | None:
    if rule.result == "weakest":
        if first not in strength or second not in strength:
            return None
        return min(first, second, key=strength.index)
    if rule.result == "first":
        return first
    if rule.result == "second":
        return second
    return rule.result


def derive(
    relationships: Iterable[tuple[str, str, str, str]],
    element_types: dict[str, str],
    rules: list[Rule],
    strength: tuple[str, ...],
    is_valid: Callable[[str, str, str], bool],
    max_length: int = 4,
) -> dict[tuple[str, str, str], Derived]:
    """Every relationship the rules derive from the direct ``relationships`` ((id, source, type, target)) over chains of
    at most ``max_length`` direct relationships, keyed by (source, type, target).

    A triple that is itself direct, a self-loop, or one the metamodel does not allow for the two element types
    (``is_valid(source type, relationship type, target type)``; an element without a type is not checked) is not
    derived. Of several chains the shortest wins, then the first by its relationship ids, so the result does not
    depend on the input order.
    """
    for rule in rules:
        if rule.join not in JOINS:
            raise ValueError(f"Rule {rule.number}: join must be one of {JOINS}, not {rule.join!r}")
    direct = {(s, k, t): Derived(s, k, t, (i,), ()) for i, s, k, t in sorted(relationships, key=lambda r: r[0])}
    known: dict[tuple[str, str, str], Derived] = dict(direct)

    def allowed(source: str, kind: str, target: str) -> bool:
        s, t = element_types.get(source), element_types.get(target)
        return s is None or t is None or is_valid(s, kind, t)

    def better(new: Derived, old: Derived | None) -> bool:
        return old is None or (len(new.chain), new.chain) < (len(old.chain), old.chain)

    for _ in range(max(max_length - 1, 0)):
        by_source: dict[str, list[Derived]] = defaultdict(list)
        by_target: dict[str, list[Derived]] = defaultdict(list)
        for d in known.values():
            by_source[d.source].append(d)
            by_target[d.target].append(d)
        found: dict[tuple[str, str, str], Derived] = {}
        for p in sorted(known.values(), key=lambda d: (len(d.chain), d.chain)):
            for rule in rules:
                if p.relationship_type not in rule.first:
                    continue
                if rule.join == "chain":
                    pairs = [(p.source, q, q.target) for q in by_source[p.target]]
                elif rule.join == "into":
                    pairs = [(p.source, q, q.source) for q in by_target[p.target]]
                elif rule.join == "back":
                    pairs = [(q.source, q, p.source) for q in by_target[p.target]]
                else:
                    pairs = [(p.target, q, q.target) for q in by_source[p.source]]
                for a, q, c in pairs:
                    if q is p or q.relationship_type not in rule.second or a == c or len(p.chain) + len(q.chain) > max_length:
                        continue
                    kind = _result(rule, p.relationship_type, q.relationship_type, strength)
                    if kind is None or (a, kind, c) in direct or not allowed(a, kind, c):
                        continue
                    candidate = Derived(a, kind, c, p.chain + q.chain, p.rules + q.rules + (rule.number,))
                    if better(candidate, found.get((a, kind, c))) and better(candidate, known.get((a, kind, c))):
                        found[(a, kind, c)] = candidate
        if not found:
            break
        known.update(found)
    return {key: d for key, d in known.items() if key not in direct}
