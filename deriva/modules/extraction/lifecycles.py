"""Business processes from structure (no LLM): the lifecycle of a business domain's status.

A lifecycle is the ordered vocabulary of a status attribute of an entity in a business domain:

- an enum type (a domain member named with a status word) with its constants in declaration order;
- or an ORM status attribute: its default (the initial state), the values of an allowed-values literal next to a
  generic setter (``x.status = new``), and the code values assigned to it (``x.status = "APPROVED"``, a keyword in
  the entity's constructor, ``UPDATE <table> SET status = 'APPROVED'``), in that order.

Each state is reached in the units whose code sets it specifically, else in the unit a documented flow step names
together with the state, else where the generic setter is. An event is a state where the lifecycle passes to
another unit, and the first state after an ORM default (the lifecycle's start). A documented flow (a numbered
list under a heading with a flow word whose items name the states) adds its heading as a name candidate.

With transitions the states follow them (an ORM default stays first); the events are read in that order.
Transitions are only those the code or an anchored documented flow shows: an assignment of a state guarded by
another (``if x.status == "A": x.status = "B"``; a ``!=`` guard that raises or returns requires its state), an
``UPDATE ... SET status = 'B' WHERE ... status = 'A'``, a transition table (a ``switch`` over the status whose
cases name the next states; a literal mapping states to lists of states) and consecutive steps of the documented
flow. An event triggers the next event that a transition path reaches through states that are no events; an
event that no other event reaches this way hangs off the lifecycle.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class LifecycleRules:
    """The signals of the BusinessLayer step's lifecycles (extraction config ``params``)."""

    status_words: tuple[str, ...] = ("status", "state", "stage", "phase")  # The last word of a status attribute or enum
    min_states: int = 3
    value_pattern: str = r"[A-Z][A-Z0-9_]+"  # A code value (a state)
    flow_words: tuple[str, ...] = ("flow", "lifecycle", "workflow", "process")  # A heading word of a documented flow
    heading_noise: tuple[str, ...] = ("flow", "workflow", "overview", "steps")  # Heading words a process name drops
    unit_noise: tuple[str, ...] = ("service", "server", "backend", "frontend", "app", "api")  # Unit name words a stem drops
    name_templates: tuple[str, ...] = ("{object} Lifecycle",)


@dataclass
class Lifecycle:
    key: str
    domain: str
    entity: str  # The entity (class or enum) display name
    attribute: str
    states: list[str] = field(default_factory=list)
    units_of_state: dict[str, list[str]] = field(default_factory=dict)
    sites: dict[str, list[str]] = field(default_factory=dict)  # state -> files that set it
    events: list[str] = field(default_factory=list)
    name_candidates: list[str] = field(default_factory=list)
    flow: str | None = None
    from_enum: bool = False
    transitions: list[tuple[str, str]] = field(default_factory=list)  # (from state, to state), sorted
    triggers: list[tuple[str | None, str]] = field(default_factory=list)  # (event or None: the lifecycle, event)


def _words(name: str) -> list[str]:
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name)


def display(name: str) -> str:
    """A type name in words: ``OrderRequest`` -> ``Order Request``; ``UNDER_REVIEW`` -> ``Under Review``."""
    if re.fullmatch(r"[A-Z0-9_]+", name):
        return " ".join(w.capitalize() for w in name.split("_") if w)
    return " ".join(w if w.isupper() and len(w) > 1 else w.capitalize() for w in _words(name))


def _is_status(name: str, rules: LifecycleRules) -> bool:
    words = [w.casefold() for w in re.split(r"[_\W]+|(?<=[a-z])(?=[A-Z])", name) if w]
    return bool(words) and words[-1] in {w.casefold() for w in rules.status_words}


class _Holders:
    def __init__(self, units: list[dict[str, Any]]):
        self.units = sorted(units, key=lambda u: -len(str(u["path"])))

    def of(self, path: str) -> str | None:
        return next((str(u["id"]) for u in self.units if path.startswith(str(u["path"]) + "/")), None)


def _stem(name: str, noise: tuple[str, ...]) -> str:
    return " ".join(w for w in re.split(r"[^a-z0-9]+", PurePosixPath(name).name.casefold()) if w and w not in {n.casefold() for n in noise})


_BLOCKS = r"(?m)^(?=\s*def |\s*function |\s*(?:public|private|protected) )"


def _ordered(states: list[str], transitions: list[tuple[str, str]], pinned: int) -> list[str]:
    """The states in an order the transitions allow (no state before one that leads to it), ties and cycles in the
    given order; the first ``pinned`` states (an ORM default: the initial state) stay first. No transitions: as given."""
    if not transitions:
        return list(states)
    head, rest = states[:pinned], states[pinned:]
    position = {s: i for i, s in enumerate(rest)}
    before: dict[str, set[str]] = {s: set() for s in rest}
    for a, b in transitions:
        if a in position and b in position and a != b:
            before[b].add(a)
    ordered: list[str] = []
    while len(ordered) < len(rest):
        left = [s for s in rest if s not in ordered]
        ready = [s for s in left if before[s] <= set(ordered)]
        ordered.append(min(ready or left, key=position.__getitem__))
    return head + ordered


def _braced(text: str, start: int) -> str:
    """The text from ``start`` (just after an opening brace) to its closing brace."""
    depth = 1
    for i in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i]
    return text[start:]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _guarded(block: str, quoted: str, entity_of: Any, path: str) -> set[tuple[str, str, str]]:
    """(lifecycle key, from state, to state) of the assignments in a block that a state guards.

    An ``==`` guard covers the deeper lines below it (its body); a ``!=`` guard whose body raises or returns covers
    the later lines at its own depth (the state is required). An ``else`` ends the guards at its depth."""
    guard = re.compile(rf"\b(\w+)\.(\w+)\s*(==|!=)\s*{quoted}")
    assign = re.compile(rf"\b(\w+)\.(\w+)\s*=\s*{quoted}")
    lines = block.splitlines()
    active: list[tuple[str, str, int, str]] = []  # (key, state, depth, kind)
    found: set[tuple[str, str, str]] = set()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        depth = _indent(line)
        # An == guard ends below its body; a != guard (a requirement) holds until its scope ends
        active = [g for g in active if depth > g[2] or (g[3] == "!=" and depth == g[2])]
        if re.match(r"\s*(?:\}\s*)?else\b(?!\s*if)", line):
            active = [g for g in active if g[2] < depth]
            continue
        guards = list(guard.finditer(line))
        for a in assign.finditer(line):
            key = entity_of(a.group(1), a.group(2), path)
            # An assignment on the guard's own line comes after it (``if x.s == "A": x.s = "B"``)
            here = [(entity_of(g.group(1), g.group(2), path), g.group(4)) for g in guards if g.group(3) == "==" and g.start() < a.start()]
            covering = [(g[0], g[1]) for g in active if g[3] == "==" or depth == g[2]]
            for k, state in covering + here:
                if k is not None and k == key and state != a.group(3):
                    found.add((key, state, a.group(3)))
        for g in guards:
            key = entity_of(g.group(1), g.group(2), path)
            if key is None:
                continue
            body = next((n for n in lines[i + 1 :] if n.strip()), "")
            if g.group(3) == "==":
                active.append((key, g.group(4), depth, "=="))
            elif _indent(body) > depth and re.match(r"\s*(?:raise|return|throw|abort)\b", body):
                active.append((key, g.group(4), depth, "!="))
    return found


def detect_lifecycles(files: dict[str, str], members: list[dict[str, Any]], units: list[dict[str, Any]], rules: LifecycleRules, docs: dict[str, str]) -> list[Lifecycle]:
    """The lifecycles of the business domains.

    Args:
        files: Path -> text of the code files (and DDL)
        members: {"domain", "object", "name", "path"}: the member types of business domains (``object``: its BusinessObject)
        units: {"id", "path", "name"} of the deployable units
        rules: The signals
        docs: Path -> text of the documentation files
    """
    value = re.compile(rf"^{rules.value_pattern}$")
    quoted = rf"[\"']({rules.value_pattern})[\"']"
    holders = _Holders(units)
    by_name = {m["name"]: m for m in members}
    found: dict[str, Lifecycle] = {}
    specific: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    generic: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    # Enums: a status-named domain member declared as an enum; its constants in order, its uses as sites
    for m in members:
        text = files.get(m["path"], "")
        declared = re.search(rf"\benum\s+{re.escape(m['name'])}\b[^{{]*\{{(.*?)(?:;|\}})", text, re.DOTALL)
        if not _is_status(m["name"], rules) or not declared:
            continue
        body = re.sub(r"//[^\n]*|/\*.*?\*/|@\w+(\([^)]*\))?", " ", declared.group(1), flags=re.DOTALL)
        states = [part.split("(")[0].strip() for part in body.split(",")]
        states = [s for s in states if value.match(s)]
        key = f"{m['domain']}::{m['name']}"
        life = found.setdefault(key, Lifecycle(key=key, domain=m["domain"], entity=m["object"], attribute=m["name"], from_enum=True))
        life.states += [s for s in states if s not in life.states]
        for path, text in files.items():
            for s in re.findall(rf"\b{re.escape(m['name'])}\.({rules.value_pattern})\b", text):
                specific[key][s].add(path)

    # ORM status attributes: classes of domain members with a status column
    tables: dict[str, str] = {}  # table name -> class
    with_default: set[str] = set()  # lifecycles whose first state is the column default
    attributes: dict[str, list[tuple[str, str]]] = defaultdict(list)  # attribute -> (class, lifecycle key)
    for path, text in sorted(files.items()):
        classes = list(re.finditer(r"(?m)^class\s+(\w+)\s*\(", text))
        for i, c in enumerate(classes):
            if c.group(1) not in by_name:
                continue
            body = text[c.end() : classes[i + 1].start() if i + 1 < len(classes) else len(text)]
            if table := re.search(r"__tablename__\s*=\s*[\"']([\w.]+)[\"']", body):
                tables[table.group(1).split(".")[-1]] = c.group(1)
            for column in re.finditer(r"(?m)^\s+(\w+)\s*=\s*(?:Column|mapped_column)\((.*)$", body):
                attr = column.group(1)
                if not _is_status(attr, rules):
                    continue
                m = by_name[c.group(1)]
                key = f"{m['domain']}::{c.group(1)}::{attr}"
                life = found.setdefault(key, Lifecycle(key=key, domain=m["domain"], entity=display(c.group(1)), attribute=attr))
                attributes[attr].append((c.group(1), key))
                if (default := re.search(rf"default\s*=\s*{quoted}", column.group(2))) and default.group(1) not in life.states:
                    life.states.insert(0, default.group(1))
                    with_default.add(key)
                    generic[key][default.group(1)].add(path)

    def entity_of(var: str, attr: str, path: str) -> str | None:
        """The lifecycle a ``var.attr`` assignment belongs to: the one entity with that attribute whose name has a word
        the variable starts (``req`` -> OrderRequest, ``case`` -> SupportCase); a variable naming no entity
        sets no lifecycle."""
        options = attributes.get(attr, [])
        named = [(cls, k) for cls, k in options if len(var) >= 3 and any(w.casefold().startswith(var.casefold()) for w in _words(cls))]
        if len({k for _, k in named}) > 1:
            # Several entities carry the word: the one whose class lies in the assignment's own unit
            unit = holders.of(path)
            named = [(cls, k) for cls, k in named if holders.of(by_name[cls]["path"]) == unit]
        keys = {k for _, k in named}
        return keys.pop() if len(keys) == 1 else None

    literal = re.compile(rf"[\[{{(]\s*((?:{quoted}\s*,\s*){{2,}}{quoted})\s*,?\s*[\]}})]")
    moves: dict[str, set[tuple[str, str]]] = defaultdict(set)  # lifecycle key -> transitions found in code
    for path, text in sorted(files.items()):
        for block in re.split(_BLOCKS, text):
            for key, a, b in _guarded(block, quoted, entity_of, path):
                moves[key].add((a, b))
        for table, attr, state, rest in re.findall(rf"(?i:UPDATE)\s+(?:\w+\.)?(\w+)\s+(?i:SET)\s+[^;]*?\b(\w+)\s*=\s*'({rules.value_pattern})'([^;\"]*)", text):
            key = next((k for c, k in attributes.get(attr, []) if c == tables.get(table)), None)
            if key and (before := re.search(rf"(?i:WHERE)\b.*?\b{re.escape(attr)}\s*=\s*'({rules.value_pattern})'", rest)):
                moves[key].add((before.group(1), state))
        for var, attr, state in re.findall(rf"\b(\w+)\.(\w+)\s*=\s*{quoted}", text):
            if (key := entity_of(var, attr, path)) is not None:
                specific[key][state].add(path)
        for cls, args in re.findall(r"\b(?:\w+\.)?(\w+)\(([^()]*)\)", text):
            if cls in by_name:
                for attr, state in re.findall(rf"\b(\w+)\s*=\s*{quoted}", args):
                    key = next((k for c, k in attributes.get(attr, []) if c == cls), None)
                    if key:
                        specific[key][state].add(path)
        for table, attr, state in re.findall(rf"(?i:UPDATE)\s+(?:\w+\.)?(\w+)\s+(?i:SET)\s+[^;]*?\b(\w+)\s*=\s*'({rules.value_pattern})'", text):
            key = next((k for c, k in attributes.get(attr, []) if c == tables.get(table)), None)
            if key:
                specific[key][state].add(path)
        # An allowed-values literal next to a generic setter (x.status = new) lists the states it may set
        for block in re.split(r"(?m)^(?=\s*def |\s*function |\s*(?:public|private|protected) )", text):
            setters = re.findall(r"\b(\w+)\.(\w+)\s*=\s*([a-z_]\w*)\b", block)
            for match in literal.finditer(block):
                values = re.findall(quoted, match.group(1))
                for var, attr, _ in setters:
                    if (key := entity_of(var, attr, path)) is not None:
                        life = found[key]
                        life.states += [v for v in values if v not in life.states]
                        for v in values:
                            generic[key][v].add(path)

    # Documented flows: numbered items under a heading with a flow word; an item names a state and a unit
    unit_stems = {str(u["id"]): _stem(str(u.get("name") or u["path"]), rules.unit_noise) for u in units}
    flows: list[tuple[str, str, list[str]]] = []  # (doc path, heading, items)
    for path, text in sorted(docs.items()):
        heading, items = "", []
        for line in text.splitlines() + ["# end"]:
            if re.match(r"^#+\s", line):
                if heading and len(items) >= rules.min_states:
                    flows.append((path, heading, items))
                heading = re.sub(r"^#+\s*", "", line).strip() if any(w in line.casefold().split() for w in rules.flow_words) else ""
                items = []
            elif heading and (item := re.match(r"^\s*\d+\.\s+(.*)", line)):
                items.append(item.group(1))
            elif heading and items and line.startswith("   "):
                items[-1] += " " + line.strip()

    def tables_of(life: Lifecycle) -> set[tuple[str, str]]:
        """Transition tables in code: a switch over the status (``this`` or a status-named value) whose case labels
        are states and whose cases name the next states; a literal mapping states to lists of states."""
        states = set(life.states)
        found: set[tuple[str, str]] = set()
        for text in files.values():
            for switch in re.finditer(r"\bswitch\s*\(\s*([\w.]+(?:\(\))?)\s*\)\s*\{", text):
                subject = switch.group(1).removesuffix("()").split(".")[-1]
                if subject != "this" and not _is_status(re.sub(r"^get", "", subject), rules):
                    continue
                parts = re.split(r"\bcase\s+(?:\w+\.)?(\w+)\s*(?::|->)", _braced(text, switch.end()))
                pending: list[str] = []
                for label, segment in zip(parts[1::2], parts[2::2], strict=False):
                    if label not in states:
                        pending = []
                        continue
                    pending.append(label)
                    if segment.strip():
                        body = re.sub(r"\bdefault\b.*", "", segment, flags=re.DOTALL)
                        targets = [t for t in re.findall(rf"\b({rules.value_pattern})\b", body) if t in states]
                        found |= {(a, b) for a in pending for b in targets if a != b}
                        pending = []
            for mapping in re.finditer(r"\{([^{}]*)\}", text):
                entries = re.findall(rf"{quoted}\s*:\s*[\[(]([^\])]*)[\])]", mapping.group(1))
                pairs = {(a, b) for a, values in entries for b in re.findall(quoted, values)}
                if len(entries) >= 2 and pairs and {x for p in pairs for x in p} <= states:
                    found |= pairs
        return found

    def triggers_of(life: Lifecycle) -> list[tuple[str | None, str]]:
        """Event -> the events a transition path reaches through states that are no events; the rest hang off the lifecycle."""
        after: dict[str, set[str]] = defaultdict(set)
        for a, b in life.transitions:
            after[a].add(b)
        events = set(life.events)
        pairs: set[tuple[str, str]] = set()
        for a in life.events:
            seen: set[str] = set()
            stack = sorted(after[a])
            while stack:
                s = stack.pop()
                if s in seen:
                    continue
                seen.add(s)
                if s in events:
                    if s != a:
                        pairs.add((a, s))
                else:
                    stack.extend(sorted(after[s]))
        result: list[tuple[str | None, str]] = []
        for e in life.events:
            sources = [a for a in life.events if (a, e) in pairs]
            result += [(a, e) for a in sources] if sources else [(None, e)]
        return result

    lifecycles: list[Lifecycle] = []
    per_domain = defaultdict(int)
    for life in found.values():
        per_domain[life.domain] += 1
    for key, life in sorted(found.items()):
        # Values assigned to the attribute join its states, in the order of their first assignment (by file)
        first_seen = sorted((min(paths), state) for state, paths in specific[key].items() if state not in life.states)
        life.states += [state for _, state in first_seen if value.match(state)]
        if len(life.states) < rules.min_states:
            continue
        flow_units: dict[str, list[str]] = {}
        for path, heading, items in flows:
            named = [i for i in items if any(re.search(rf"\b{re.escape(s)}\b", i) for s in life.states)]
            if len(named) * 2 < len(items) and len(named) < rules.min_states:
                continue
            life.flow = f"{path}#{heading}"
            steps = [[s for s in life.states if re.search(rf"\b{re.escape(s)}\b", i)] for i in named]
            moves[key] |= {(a, b) for before, after in zip(steps, steps[1:], strict=False) for a in before for b in after if a != b}
            name = " ".join(w for w in heading.split() if w.casefold() not in {n.casefold() for n in rules.heading_noise})
            if name:
                life.name_candidates.append(" ".join(w[:1].upper() + w[1:] for w in name.split()))
            for item in named:
                lowered = item.casefold()
                unit = max((u for u, stem in unit_stems.items() if stem and re.search(rf"\b{re.escape(stem)}\b", lowered)), key=lambda u: len(unit_stems[u]), default=None)
                if unit:
                    for s in life.states:
                        if re.search(rf"\b{re.escape(s)}\b", item):
                            flow_units.setdefault(s, [unit])
            break
        life.transitions = sorted(moves[key] | tables_of(life))
        life.states = _ordered(life.states, life.transitions, pinned=1 if key in with_default else 0)
        for s in life.states:
            spec = sorted({u for p in specific[key].get(s, ()) if (u := holders.of(p))})
            gen = sorted({u for p in generic[key].get(s, ()) if (u := holders.of(p))})
            life.units_of_state[s] = spec or flow_units.get(s) or gen
            life.sites[s] = sorted(specific[key].get(s, set()) | generic[key].get(s, set()))
        start = 0 if life.from_enum else 1
        previous = life.units_of_state[life.states[0]]
        for i, s in enumerate(life.states[1:], 1):
            current = life.units_of_state[s]
            if (i == start) or (current and previous and not set(current) & set(previous)):
                life.events.append(s)
            previous = current or previous
        life.triggers = triggers_of(life)
        objects = {m["domain"]: m["object"] for m in members}
        names = [t.format(object=objects.get(life.domain, life.entity)) for t in rules.name_templates]
        if per_domain[life.domain] > 1 or life.entity.casefold() != objects.get(life.domain, life.entity).casefold():
            names += [t.format(object=life.entity) for t in rules.name_templates]
        life.name_candidates = list(dict.fromkeys(names + life.name_candidates))
        lifecycles.append(life)
    return lifecycles
