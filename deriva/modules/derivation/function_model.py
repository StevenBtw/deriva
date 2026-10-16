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
    """A service to classify, described by structure only (rule 6d): its unit, members, data and lifecycles."""

    key: str  # The service element's identifier
    component: str
    members: list[str] = field(default_factory=list)
    data: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)


def _stable(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_function_prompt(items: list[ServiceItem], options: list[Function], instruction: str, model_name: str, level: int) -> str:
    """The prompt of one classification batch: the instruction, the options of one level, the services."""
    listed = "\n".join(f"- {f.id}: {f.name}" + (f". {f.description}" if f.description else "") for f in options)
    services = "\n".join(
        f"- s{n}: {item.component} | members: {', '.join(item.members[:20]) or '-'} | data: {', '.join(item.data) or '-'} | processes: {', '.join(item.processes) or '-'}"
        for n, item in enumerate(items, 1)
    )
    keys = ", ".join(f'"s{n}": "<id or {NONE}>"' for n in range(1, len(items) + 1))
    return f"""{instruction}

## Function model {model_name}, level {level}
{listed}
- {NONE}

## Application services
{services}

Return {{"choices": {{{keys}}}}}: for each service one option id as written, or "{NONE}"."""


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
