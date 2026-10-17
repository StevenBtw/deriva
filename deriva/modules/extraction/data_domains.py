"""Information domains (no LLM): the data an architect names ("Customer Data"), each a group of entities.

The entities of the DataEntity step and the data types it left out (parts of an aggregate, value objects,
technical words) are grouped in this order:

1. aggregate: a root takes the types it references (parts, value objects), transitively, not other roots;
2. naming root: an entity whose name is another entity's full name plus words joins that entity's domain;
3. ownership: an entity whose one owner (an owning collection, a mandatory foreign key) has it, and that has
   no member of its own, joins the owner; a lookup with no member that one other domain uses joins it;
4. bounded context: the unrelated entities of one unit form one domain.

A technical-word type joins a domain like any other; it forms a domain of its own only as an aggregate root
or as the only data of its unit (an exception domain), else it stays out. A domain gets a BusinessObject
unless it is an exception domain, an identity domain (its anchor names an identity word and it owns or is
owned by no business entity) or a domain of DDL tables alone (stored data with no code entity behind it). Name candidates are closed sets: "<anchor> Data", the unit stem for a unit's
whole data, documentation terms "<anchor or stem> <data noun>", and the bare anchor for a domain without a
BusinessObject.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from deriva.common.naming import name_key


@dataclass(frozen=True)
class DomainRules:
    """The signals of the DataDomain step (extraction config ``params``)."""

    identity_words: tuple[str, ...] = ()  # An anchor naming one of these is an identity domain (no BusinessObject)
    unit_noise: tuple[str, ...] = ()  # Words dropped from a unit's name for its stem ("service")
    data_nouns: tuple[str, ...] = ("data", "trail", "record", "records", "history", "catalog", "log")
    name_template: str = "{name} Data"


@dataclass
class Domain:
    key: str
    anchor: str  # The anchor's name
    kind: str  # aggregate, naming, ownership, context, single
    members: list[str] = field(default_factory=list)  # Type ids
    nodes: list[str] = field(default_factory=list)  # Entity keys and candidate type ids
    units: list[str] = field(default_factory=list)
    exception: bool = False
    business_object: str | None = None
    name_candidates: list[str] = field(default_factory=list)


@dataclass
class Left:
    name: str
    reason: str


@dataclass
class DomainResult:
    domains: list[Domain] = field(default_factory=list)
    excluded: list[Left] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------- ORM relations

_JAVA_FIELD = re.compile(
    r"@(OneToMany|ManyToMany|ManyToOne|OneToOne)\s*(\([^)]*\))?\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:private|protected|public)?\s*(?:final\s+)?([\w.]+(?:<[\w.,\s]+>)?)\s+\w+\s*;"
)
_JAVA_CLASS = re.compile(r"\b(?:class|record)\s+(\w+)")


def _generic(type_text: str) -> str:
    inner = re.search(r"<\s*([\w.]+)\s*>", type_text)
    return (inner.group(1) if inner else type_text).split(".")[-1]


def orm_relations(path: str, text: str) -> list[tuple[str, str, str]]:
    """(class, relation, class) of a source file: "owns" for an owning collection or one-to-one (cascade all, orphan
    removal, delete-orphan), "parent" for the parent of a mandatory foreign key or many-to-one, "refers" for every
    foreign key or many-to-one."""
    relations: set[tuple[str, str, str]] = set()
    lower = path.lower()
    if lower.endswith((".java", ".kt")):
        declared = _JAVA_CLASS.search(text)
        if not declared:
            return []
        this = declared.group(1)
        for m in _JAVA_FIELD.finditer(text):
            kind, args, other = m.group(1), m.group(2) or "", _generic(m.group(3))
            if kind in ("OneToMany", "ManyToMany"):
                if re.search(r"CascadeType\.ALL|orphanRemoval\s*=\s*true", args):
                    relations.add((this, "owns", other))
            elif kind == "ManyToOne":
                relations.add((this, "refers", other))
                if re.search(r"optional\s*=\s*false", args):
                    relations.add((other, "parent", this))
            elif re.search(r"CascadeType\.ALL|orphanRemoval\s*=\s*true", args):  # a one-to-one it holds
                relations.add((this, "owns", other))
    elif lower.endswith(".py"):
        classes = list(re.finditer(r"(?m)^class\s+(\w+)\s*\(", text))
        tables = {}
        for i, c in enumerate(classes):
            body = text[c.end() : classes[i + 1].start() if i + 1 < len(classes) else len(text)]
            if table := re.search(r"__tablename__\s*=\s*[\"']([\w.]+)[\"']", body):
                tables[table.group(1)] = c.group(1)
        for i, c in enumerate(classes):
            this = c.group(1)
            body = text[c.end() : classes[i + 1].start() if i + 1 < len(classes) else len(text)]
            for line in body.splitlines():
                if fk := re.search(r"ForeignKey\(\s*[\"']([\w.]+)\.\w+[\"']", line):
                    parent = tables.get(fk.group(1).split(".")[-1])
                    if parent and parent != this:
                        relations.add((this, "refers", parent))
                        if re.search(r"nullable\s*=\s*False|primary_key\s*=\s*True", line):
                            relations.add((parent, "parent", this))
                if rel := re.search(r"relationship\(\s*[\"'](\w+)[\"'][^)]*delete-orphan", line):
                    relations.add((this, "owns", rel.group(1)))
    elif lower.endswith((".sql", ".ddl")):
        for table in re.finditer(r"(?is)CREATE\s+TABLE\s+(?:[\w$#@\"]+\.)?\"?(\w+)\"?\s*\((.*?)\)\s*;", text):
            for column in table.group(2).split(","):
                if ref := re.search(r"(?i)REFERENCES\s+(?:[\w$#@\"]+\.)?\"?(\w+)", column):
                    relations.add((table.group(1), "refers", ref.group(1)))
                    if re.search(r"(?i)NOT\s+NULL", column):
                        relations.add((ref.group(1), "parent", table.group(1)))
    return sorted(relations)


# ---------------------------------------------------------------------------------------------- domains


def _words(name: str) -> list[str]:
    return [w.casefold() for w in re.findall(r"[A-Za-z0-9]+", name)]


def _slug(name: str) -> str:
    return "-".join(_words(name))


def _title(phrase: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in phrase.split())


def detect_domains(
    entities: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    references: list[tuple[str, str]],
    relations: list[tuple[str, str, str]],
    rules: DomainRules,
    roots: set[str] | None = None,
    unit_names: dict[str, str] | None = None,
    docs: dict[str, str] | None = None,
) -> DomainResult:
    """The information domains.

    Args:
        entities: {"key", "name", "signal", "type_ids", "units"} of the data entities
        candidates: {"type_id", "name", "reason", "units"} of the data types left out (display names)
        references: (type id, type id) type -> type references (signatures, fields)
        relations: (node, "owns" | "parent" | "refers", node) between entity keys or candidate type ids
        rules: The signals
        roots: Type ids of aggregate roots among the candidates (a technical-word root)
        unit_names: unit id -> its name (for the unit stem)
        docs: path -> documentation text (for documentation terms)
    """
    roots = set(roots or ())
    unit_names = unit_names or {}
    # Nodes: entities by key, candidates by type id
    name: dict[str, str] = {}
    types: dict[str, list[str]] = {}
    units: dict[str, list[str]] = {}
    reason: dict[str, str] = {}
    tables_only: set[str] = set()  # entities made of a DDL table alone (no code entity)
    for e in entities:
        if e.get("signal") == "table":
            tables_only.add(e["key"])
        name[e["key"]], types[e["key"]], units[e["key"]] = e["name"], list(e["type_ids"]), list(e.get("units") or [])
        if e.get("signal") == "aggregate root":
            roots |= set(e["type_ids"])
    for c in candidates:
        # Only what may belong to a domain: parts of an aggregate, value objects, technical-word types
        if c["reason"] not in ("part of an aggregate", "value object") and not c["reason"].startswith("technical word"):
            continue
        name[c["type_id"]], types[c["type_id"]], units[c["type_id"]], reason[c["type_id"]] = c["name"], [c["type_id"]], list(c.get("units") or []), c["reason"]
    node_of = {t: n for n, ts in types.items() for t in ts}
    technical = {n for n, r in reason.items() if r.startswith("technical word")}
    value_objects = {n for n, r in reason.items() if r == "value object"}
    is_root = {n for n, ts in types.items() if set(ts) & roots}

    parent: dict[str, str] = {n: n for n in name}  # node -> the anchor of its domain
    kind: dict[str, str] = {}

    def anchor(n: str) -> str:
        while parent[n] != n:
            n = parent[n]
        return n

    def join(n: str, into: str, how: str) -> None:
        a, b = anchor(n), anchor(into)
        if a != b:
            parent[a] = b
            kind.setdefault(b, how)

    def size(a: str) -> int:
        return sum(1 for n in name if anchor(n) == a)

    # 1. Aggregates: a root takes what it references, transitively, never another root
    refs: dict[str, set[str]] = defaultdict(set)
    for a, b in references:
        if a in node_of and b in node_of and node_of[a] != node_of[b]:
            refs[node_of[a]].add(node_of[b])
    claims: dict[str, list[str]] = defaultdict(list)
    for root in sorted(is_root):
        seen, todo = {root}, [root]
        while todo:
            for nxt in sorted(refs[todo.pop()]):
                if nxt not in seen and nxt not in is_root and nxt in reason:
                    seen.add(nxt)
                    claims[nxt].append(root)
                    todo.append(nxt)
    for part, by in sorted(claims.items()):
        same_unit = [r for r in by if set(units[r]) & set(units[part])]
        join(part, sorted(same_unit or by)[0], "aggregate")
        kind[anchor(part)] = "aggregate"
    # A copy of a claimed part that no reference reaches (the same class in another unit) follows the claimed copy
    claimed_by_name = {name_key(name[p]): anchor(p) for p in sorted(claims)}
    for n in sorted(reason):
        if n not in claims and n not in is_root and anchor(n) == n and name_key(name[n]) in claimed_by_name:
            join(n, claimed_by_name[name_key(name[n])], "aggregate")
    # Value objects no root takes are no data of their own
    unused = {n for n in value_objects if anchor(n) == n and size(n) == 1}

    # 2. Naming roots: the longest other anchor whose words start this one's name (across units)
    anchors = [n for n in name if anchor(n) == n and n not in unused]
    for n in sorted(anchors, key=lambda n: (-len(_words(name[n])), n)):
        if n in is_root:  # a root anchors its aggregate, it never joins another domain by its name
            continue
        words = _words(name[n])
        prefixes = [m for m in anchors if m != n and anchor(m) == m and len(_words(name[m])) < len(words) and words[: len(_words(name[m]))] == _words(name[m])]
        if prefixes and anchor(n) == n:
            join(n, max(prefixes, key=lambda m: (len(_words(name[m])), m)), "naming")

    # 3. Ownership: one owner (owning collection or mandatory parent), no member of its own -> joins the owner
    owners: dict[str, set[str]] = defaultdict(set)
    users: dict[str, set[str]] = defaultdict(set)  # node -> nodes that refer to it
    holds: set[str] = set()  # nodes with an owning collection: never a lookup
    for owner, how, child in relations:
        if owner in name and child in name and owner != child:
            if how in ("owns", "parent"):
                owners[child].add(owner)
                if how == "owns":
                    holds.add(owner)
            else:
                users[child].add(owner)
    moved = True
    while moved:
        moved = False
        for n in sorted(name):
            if n in unused or anchor(n) != n or size(n) > 1:
                continue
            by = {anchor(o) for o in owners[n]} - {n}
            if len(by) == 1:
                join(n, next(iter(by)), "ownership")
                kind[anchor(n)] = kind.get(anchor(n)) or "ownership"
                moved = True
                continue
            # A lookup: no owner, no owning collection, and exactly one other domain refers to it
            used_by = {anchor(u) for u in users[n]} - {n}
            if not owners[n] and n not in holds and len(used_by) == 1:
                join(n, next(iter(used_by)), "ownership")
                moved = True

    # 4. Bounded context: the unrelated entities of one unit
    related = {n for pair in references for n in (node_of.get(pair[0]), node_of.get(pair[1])) if n} | {n for o, _, c in relations for n in (o, c)}
    loose = [n for n in name if anchor(n) == n and size(n) == 1 and n not in reason and n not in related and len(units[n]) == 1]
    by_unit: dict[str, list[str]] = defaultdict(list)
    for n in loose:
        by_unit[units[n][0]].append(n)
    incoming = Counter(node_of[b] for _, b in references if b in node_of)
    for group in by_unit.values():
        if len(group) > 1:
            head = sorted(group, key=lambda n: (-incoming[n], name[n]))[0]
            for n in group:
                join(n, head, "context")
            kind[head] = "context"

    # Domains; technical-word anchors need evidence (a root, or the only data of their unit)
    data_in_unit = Counter(u for n in name if n not in unused and n not in value_objects for u in units[n])
    result = DomainResult()
    groups: dict[str, list[str]] = defaultdict(list)
    for n in name:
        if n not in unused:
            groups[anchor(n)].append(n)
    domains: list[Domain] = []
    for head, nodes in sorted(groups.items()):
        if head in value_objects:
            continue
        exception = head in technical
        if exception and not (head in is_root or (len(units[head]) == 1 and data_in_unit[units[head][0]] == len(nodes))):
            result.excluded += [Left(name[n], "technical word, no domain of its own") for n in sorted(nodes)]
            continue
        members = sorted(t for n in nodes for t in types[n])
        domain_units = sorted({u for n in nodes for u in units[n]})
        domains.append(
            Domain(
                key=head if head not in reason else _slug(name[head]),
                anchor=name[head],
                kind=kind.get(head, "aggregate" if head in is_root else "single"),
                members=members,
                nodes=sorted(nodes),
                units=domain_units,
                exception=exception,
            )
        )

    # BusinessObjects: not for exception domains, nor for identity domains (an identity anchor whose members and
    # owned or owning domains are all identity data), nor for domains of DDL tables alone
    identity_words = {w.casefold() for w in rules.identity_words}
    is_identity = lambda text: bool(set(_words(text)) & identity_words)  # noqa: E731 - a one-line helper
    domain_of = {n: d for d in domains for n in d.nodes}
    for d in domains:
        linked = {domain_of[o].key for n in d.nodes for o in owners[n] if o in domain_of} | {
            domain_of[c].key for c, os in owners.items() if c in domain_of and set(os) & set(d.nodes)
        }
        business = any(not is_identity(name[n]) for n in d.nodes) or any(not is_identity(x.anchor) for x in domains if x.key in linked - {d.key})
        # A domain of DDL tables alone (no code entity behind it) is stored data, not a business object
        if not d.exception and business and not set(d.nodes) <= tables_only:
            d.business_object = d.anchor

    # Name candidates (closed set): anchor (without a BusinessObject), "<anchor> Data", the unit stem, documentation terms
    whole_unit = {u for u, n in data_in_unit.items()}
    texts = list((docs or {}).values())
    for d in domains:
        found: list[str] = []
        if d.business_object is None:
            found.append(d.anchor)
        found.append(rules.name_template.format(name=d.anchor))
        stem = ""
        if len(d.units) == 1 and d.units[0] in unit_names and d.units[0] in whole_unit and data_in_unit[d.units[0]] == len(d.nodes):
            stem = " ".join(w for w in _words(PurePosixPath(unit_names[d.units[0]]).name) if w not in {x.casefold() for x in rules.unit_noise})
            if stem:
                found.append(rules.name_template.format(name=_title(stem)))
        heads = [" ".join(_words(d.anchor))] + ([stem] if stem else [])
        nouns = "|".join(re.escape(n) for n in rules.data_nouns)
        for text in texts:
            for head in heads:
                for m in re.finditer(rf"(?i)\b{re.escape(head)}\s+({nouns})\b", text):
                    found.append(_title(f"{head} {m.group(1).lower()}"))
        seen: set[str] = set()
        d.name_candidates = [n for n in found if not (name_key(n) in seen or seen.add(name_key(n)))]
    # A name another domain's anchor or "<anchor> Data" holds is dropped, unless it is the only one left
    taken = Counter(name_key(n) for d in domains for n in {d.anchor, rules.name_template.format(name=d.anchor)})
    for d in domains:
        own = {name_key(d.anchor), name_key(rules.name_template.format(name=d.anchor))}
        kept = [n for n in d.name_candidates if name_key(n) in own or taken[name_key(n)] == 0]
        d.name_candidates = kept or d.name_candidates
    result.domains = domains
    return result
