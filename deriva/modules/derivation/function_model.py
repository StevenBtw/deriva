"""Business functions from a supplied business function model (pure; no I/O).

A function model is the organization's own hierarchy of business functions (as in enterprise architecture
practice), read from a CSV file: ``id``, ``name``, ``parent``, ``level``, optional ``code`` and ``description``;
lines starting with ``#`` are notes (a licence notice, the source). Levels 1 and 2 are read, deeper rows ignored.

The application services that touch a business domain are classified into it level by level, each a closed
choice: first a level-1 function (or none), then one of that function's level-2 functions (or none). The chosen
functions become BusinessFunction elements named and identified by the model (``function::<model>::<id>``); a
level-2 function is composed in its level-1 function; a service serves the level-2 function it was classified
into (the level-1 function when level 2 was none).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from deriva.common.json_utils import extract_json_from_response
from deriva.modules.derivation.base import element_identifier, extract_response_content

logger = logging.getLogger(__name__)

ELEMENT_TYPE = "BusinessFunction"
NONE = "none"  # The answer for "no function of the options fits"


@dataclass(frozen=True)
class Function:
    id: str
    name: str
    level: int
    parent: str | None = None
    code: str = ""
    description: str = ""


@dataclass
class FunctionModel:
    name: str
    functions: dict[str, Function] = field(default_factory=dict)

    def get(self, function_id: str) -> Function | None:
        return self.functions.get(function_id)

    def level(self, level: int) -> list[Function]:
        return [f for f in self.functions.values() if f.level == level]

    def children(self, function_id: str) -> list[Function]:
        return [f for f in self.functions.values() if f.parent == function_id]


def parse_function_model(text: str, name: str, exclude: tuple[str, ...] = (), max_level: int = 2) -> FunctionModel:
    """The function model in a CSV text. ``exclude``: ids left out with everything below them.

    Raises:
        ValueError: a missing column, a repeated id, a level that is no whole number, a level-1 row with a parent or
            a deeper row whose parent is missing or not one level up.
    """
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    missing = {"id", "name", "level"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"function model {name}: missing column(s) {sorted(missing)} (id, name and level are required)")
    rows: dict[str, Function] = {}
    for row in reader:
        function_id = (row.get("id") or "").strip()
        if not function_id:
            continue
        if function_id in rows:
            raise ValueError(f"function model {name}: id {function_id!r} is not unique")
        try:
            level = int((row.get("level") or "").strip())
        except ValueError:
            raise ValueError(f"function model {name}: level of {function_id!r} is no whole number: {row.get('level')!r}") from None
        parent = (row.get("parent") or "").strip() or None
        rows[function_id] = Function(
            id=function_id,
            name=(row.get("name") or "").strip(),
            level=level,
            parent=parent,
            code=(row.get("code") or "").strip(),
            description=" ".join((row.get("description") or "").split()),
        )
    for f in rows.values():
        if f.level == 1 and f.parent:
            raise ValueError(f"function model {name}: level-1 function {f.id!r} has a parent")
        if f.level > 1 and (f.parent not in rows or rows[f.parent].level != f.level - 1):
            raise ValueError(f"function model {name}: the parent of {f.id!r} must be a level-{f.level - 1} function of the model, got {f.parent!r}")
    dropped = set(exclude)
    for f in sorted(rows.values(), key=lambda f: f.level):
        if f.parent in dropped:
            dropped.add(f.id)
    return FunctionModel(name=name, functions={i: f for i, f in rows.items() if i not in dropped and f.level <= max_level})


@dataclass(frozen=True)
class ServiceItem:
    """A service to classify, described by structure and the documentation that names its component (rule 6d):
    its unit, members, data and lifecycles, and the richer evidence (operations, lifecycle states it sets, interface
    roles, the unit's documentation lines, the named fields of its members' header comments)."""

    key: str  # The service element's identifier
    component: str
    members: list[str] = field(default_factory=list)
    data: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    documentation: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceRules:
    """How a service's evidence is read (function model step ``params.evidence``)."""

    # Decorator patterns (re.match) with named groups verb and/or path: an endpoint operation of a method or type
    operation_patterns: tuple[str, ...] = ()
    summary_patterns: tuple[str, ...] = ()  # Decorator patterns with a group text: the operation's summary
    header_fields: tuple[str, ...] = ()  # Field names whose "Name: value" lines in a file's leading comment block are notes
    technical_words: tuple[str, ...] = ()  # A service whose every operation (else member) names one of these is technical
    # Graph queries returning (a, b): node a describes member b (a program and the screen it sends); a's header notes count
    member_links: tuple[str, ...] = ()
    max_operations: int = 15
    max_members: int = 20
    max_doc_chars: int = 500
    max_notes: int = 5


def _words(text: str) -> list[str]:
    return [w.casefold() for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", text)]


def _matches(decorators: list[str], patterns: tuple[str, ...]) -> list[dict[str, str]]:
    found = []
    for decorator in decorators:
        for pattern in patterns:
            if m := re.match(pattern, decorator.strip()):
                found.append({k: v for k, v in m.groupdict().items() if v is not None})
                break
    return found


def operations_of(methods: list[dict[str, Any]], type_decorators: list[str], rules: EvidenceRules, type_name: str = "") -> list[str]:
    """The endpoint operations of a member: per method with a verb or path decorator "VERB /path name (summary)";
    the type's own path decorator is the prefix; a type with a path and no method operations (a servlet) is one
    operation of its own. ``methods``: {"name", "decorators"} in source order."""
    prefix = next((m["path"] for m in _matches(type_decorators, rules.operation_patterns) if m.get("path")), "")
    operations = []
    for method in methods:
        decorators = list(method.get("decorators") or [])
        found = _matches(decorators, rules.operation_patterns)
        if not found:
            continue
        verb = next((m["verb"] for m in found if m.get("verb")), "")
        verb = "ANY" if not verb or verb.casefold() == "request" else verb.upper()
        path = next((m["path"] for m in found if m.get("path") is not None), "")
        full = (prefix.rstrip("/") + ("/" + path.lstrip("/") if path else "")) or "/"
        summary = next((m["text"] for m in _matches(decorators, rules.summary_patterns) if m.get("text")), "")
        operations.append(f"{verb} {full} {method['name']}" + (f" ({summary})" if summary else ""))
    if not operations and prefix and type_name:
        operations.append(f"ANY {'/' + prefix.lstrip('/')} {type_name}")
    return operations


def header_notes(text: str, rules: EvidenceRules) -> list[str]:
    """The values of the named fields ("Function: ...") in the file's leading comment block."""
    if not rules.header_fields:
        return []
    fields = "|".join(re.escape(f) for f in rules.header_fields)
    notes = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if not re.match(r"^\s*(?:\*|#|//|/\*|--)", line):
            break  # The leading block ends at the first line of code
        content = re.sub(r"^[*#/\-\s]+", "", line.strip())
        if m := re.match(rf"(?i)^(?:{fields})\s*:\s*(.+?)[\s*]*$", content):
            notes.append(m.group(1))
    return notes


def is_technical(operations: list[str], members: list[str], rules: EvidenceRules) -> bool:
    """Whether a service only provides technical capability: every operation (without operations: every member
    name) names a technical word."""
    words = {w.casefold() for w in rules.technical_words}
    items = operations or members
    return bool(items and words) and all(words & set(_words(item)) for item in items)


def shown_operations(operations: list[str], rules: EvidenceRules) -> list[str]:
    """The operations a prompt shows: technical ones left out, a repeat (same verb, path and name) kept once, with its summary."""
    kept: dict[str, str] = {}
    for op in operations:
        if is_technical([op], [], rules):
            continue
        key = op.split(" (", 1)[0]
        if key not in kept or ("(" in op and "(" not in kept[key]):
            kept[key] = op
    return list(kept.values())


def _plain(line: str) -> str:
    """A Markdown line as plain text: images dropped, links as their text, emphasis and table pipes removed."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text).strip()
    if re.fullmatch(r"[\s|:\-]*", text):
        return ""  # A table separator or an empty cell row
    return " ".join(text.strip("|").replace(" |", " |").split())


def _joined(parts: list[str], max_chars: int) -> str:
    text = ""
    for part in parts:
        text = f"{text}{'' if not text else ' ' if text[-1] in '.!?:;' else '. '}{part}"
    return text[:max_chars].rstrip()


def component_documentation(unit_path: str, unit_name: str, documents: dict[str, str], max_chars: int) -> str:
    """A component's documentation: its own README's text under the title (up to the next heading), then the lines of
    the repository's root README that name it (a table row, a bold term, a link), as plain text, capped."""
    parts: list[str] = []
    own = sorted(p for p in documents if p.rsplit("/", 1)[0] == unit_path and p.rsplit("/", 1)[-1].lower().startswith("readme"))
    for path in own[:1]:
        fenced = False
        for line in documents[path].splitlines():
            if line.strip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            if re.match(r"^#{1,6}\s", line):
                if parts:
                    break  # The text under the title ends at the next heading
                continue
            if plain := _plain(line):
                parts.append(plain)
    repo = unit_path.split("/", 1)[0]
    roots = sorted(p for p in documents if p.rsplit("/", 1)[0] == repo and p.rsplit("/", 1)[-1].lower().startswith("readme") and repo != unit_path)
    names = {n for n in (unit_path.rsplit("/", 1)[-1], unit_name) if n}
    if roots and names:
        pattern = re.compile("|".join(rf"(?<![A-Za-z0-9-]){re.escape(n)}(?![A-Za-z0-9-])" for n in sorted(names)), re.IGNORECASE)
        # The first line that names it: a later one is usually a mention elsewhere (a finding, a log line)
        parts += [plain for line in documents[roots[0]].splitlines() if not re.match(r"^#{1,6}\s", line) and pattern.search(line) and (plain := _plain(line))][:1]
    return _joined(list(dict.fromkeys(parts)), max_chars)


def documentation_text(lines: list[str], max_chars: int) -> str:
    """Documentation lines as plain text (images dropped, links as their text, emphasis removed), capped."""
    text = ""
    for line in lines:
        plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", plain)
        plain = " ".join(re.sub(r"[*_`]+", "", plain).split())
        if not plain:
            continue
        text = f"{text}{'' if not text else ' ' if text[-1] in '.!?:;' else '. '}{plain}"
    return text[:max_chars].rstrip()


def _stable(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_function_prompt(items: list[ServiceItem], options: list[Function], instruction: str, model_name: str, level: int) -> str:
    """The prompt of one classification batch: the instruction, the options of one level, the services."""
    listed = "\n".join(f"- {f.id}: {f.name}" + (f". {f.description}" if f.description else "") for f in options)
    services = "\n".join(_service_lines(n, item) for n, item in enumerate(items, 1))
    keys = ", ".join(f'"s{n}": "<id or {NONE}>"' for n in range(1, len(items) + 1))
    return f"""{instruction}

## Function model {model_name}, level {level}
{listed}
- {NONE}

## Application services
{services}

Return {{"choices": {{{keys}}}}}: for each service one option id as written, or "{NONE}"."""


def _service_lines(n: int, item: ServiceItem) -> str:
    """One service in the prompt: the identifying first line, then the evidence it has."""
    head = f"- s{n}: {item.component} | members: {', '.join(item.members[:20]) or '-'} | data: {', '.join(item.data) or '-'} | processes: {', '.join(item.processes) or '-'}"
    lines = [head]
    for label, values in (("interfaces", item.interfaces), ("operations", item.operations), ("states", item.states), ("code notes", item.notes)):
        if values:
            lines.append(f"  {label}: {'; '.join(values)}")
    if item.documentation:
        lines.append(f"  documentation: {item.documentation}")
    return "\n".join(lines)


def function_schema(count: int, options: list[Function]) -> dict[str, Any]:
    """The output contract: per service key one of the option ids or none."""
    enum = [f.id for f in options] + [NONE]
    keys = [f"s{n}" for n in range(1, count + 1)]
    return {
        "name": "function_choice",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "choices": {
                    "type": "object",
                    "properties": {k: {"type": "string", "enum": enum} for k in keys},
                    "required": keys,
                    "additionalProperties": False,
                }
            },
            "required": ["choices"],
            "additionalProperties": False,
        },
    }


def _classify_batch(
    items: list[ServiceItem], options: list[Function], instruction: str, model_name: str, level: int, llm_query_fn: Callable[..., Any], llm_kwargs: dict[str, Any]
) -> dict[str, str | None]:
    """Item key -> the chosen option id (None: none, or an answer outside the options)."""
    allowed = {f.id for f in options}
    try:
        content, error = extract_response_content(
            llm_query_fn(build_function_prompt(items, options, instruction, model_name, level), function_schema(len(items), options), **llm_kwargs)
        )
        choices = {} if error else json.loads(extract_json_from_response(content)).get("choices") or {}
    except (ValueError, AttributeError) as exc:
        logger.warning("Unusable function choice (level %d, %d services): %s", level, len(items), exc)
        choices = {}
    return {item.key: (answer if (answer := choices.get(f"s{n}")) in allowed else None) for n, item in enumerate(items, 1)}


def classify_services(
    items: list[ServiceItem], model: FunctionModel, instruction: str, llm_query_fn: Callable[..., Any], batch_size: int, llm_kwargs: dict[str, Any] | None = None
) -> dict[str, tuple[str | None, str | None]]:
    """Service key -> (level-1 id, level-2 id): level 1 in batches over all services, then level 2 in batches per chosen
    level-1 function among its children. A level without options or a none stops the descent."""
    llm_kwargs = llm_kwargs or {}
    size = max(batch_size, 1)
    ordered = sorted(items, key=lambda i: _stable(i.key))  # Batches by a stable hash: the same services batch together in every run
    first: dict[str, str | None] = {}
    tops = model.level(1)
    for start in range(0, len(ordered), size):
        first.update(_classify_batch(ordered[start : start + size], tops, instruction, model.name, 1, llm_query_fn, llm_kwargs) if tops else {})
    second: dict[str, str | None] = {}
    by_top: dict[str, list[ServiceItem]] = defaultdict(list)
    for item in ordered:
        if first.get(item.key):
            by_top[str(first[item.key])].append(item)
    for top in sorted(by_top):
        options = model.children(top)
        group = by_top[top]
        for start in range(0, len(group), size):
            if options:
                second.update(_classify_batch(group[start : start + size], options, instruction, model.name, 2, llm_query_fn, llm_kwargs))
    return {item.key: (first.get(item.key), second.get(item.key)) for item in items}


def function_elements(decisions: dict[str, tuple[str | None, str | None]], model: FunctionModel, processes: dict[str, list[str]]) -> list[dict[str, Any]]:
    """The BusinessFunction elements of the chosen functions.

    Properties: ``services`` (the services it serves directly: its level-2 choice, or level 1 when level 2 was none),
    ``functions`` (a level-1 function's chosen level-2 functions), ``processes`` (the lifecycles its services serve).
    """
    served: dict[str, set[str]] = defaultdict(set)
    parts: dict[str, set[str]] = defaultdict(set)
    reached: dict[str, set[str]] = defaultdict(set)
    for service, (top, part) in sorted(decisions.items()):
        if not top:
            continue
        target = part or top
        served[target].add(service)
        reached[target] |= set(processes.get(service, []))
        served.setdefault(top, set())
        if part:
            parts[top].add(part)
    identifier = {f: element_identifier(ELEMENT_TYPE, f"function::{model.name}::{f}") for f in served}
    elements = []
    for function_id in sorted(served):
        f = model.get(function_id)
        if f is None:
            continue
        source = f"function::{model.name}::{f.id}"
        elements.append(
            {
                "identifier": identifier[function_id],
                "name": f.name,
                "element_type": ELEMENT_TYPE,
                "documentation": f.description,
                "properties": {
                    "source": source,
                    "function_model": model.name,
                    "function_id": f.id,
                    "code": f.code,
                    "level": f.level,
                    "parent": f"function::{model.name}::{f.parent}" if f.parent else "",
                    "services": sorted(served[function_id]),
                    "functions": sorted(identifier[p] for p in parts.get(function_id, ())),
                    "processes": sorted(reached.get(function_id, ())),
                    "confidence": 1.0,
                },
            }
        )
    return elements
