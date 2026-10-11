"""BMS structural extractor (screen maps).

A BMS source is a list of assembler macros: ``DFHMSD`` opens a mapset, ``DFHMDI``
a map (one screen) and ``DFHMDF`` a field of the map. A statement continues on
the next line when column 72 is not blank. The mapping:

- each map is a type of kind ``screen``, with its mapset in the decorators
  (``mapset:``)
- the docstring lists the named fields, the fields that accept input and the
  constant texts shown on the screen

Maps have no methods, imports or calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import ExtractedType
from . import register_extractor
from .structural import ParsedSource, StructuralExtractor

_CONTINUATION_COLUMN = 71  # column 72, zero-based
_STATEMENT = re.compile(r"(\S*)\s+(DFHMSD|DFHMDI|DFHMDF)(?:\s+(.*))?$", re.IGNORECASE)


@dataclass
class _Map:
    name: str
    mapset: str
    line_start: int
    line_end: int
    size: str = ""
    fields: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def _operands(text: str) -> dict[str, str]:
    """The KEY=VALUE operands of a macro, split at top-level commas."""
    operands: dict[str, str] = {}
    depth = 0
    quoted = False
    current = ""
    for char in text + ",":
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and not quoted and depth <= 0:
            key, equals, value = current.strip().partition("=")
            if equals:
                operands[key.strip().upper()] = value.strip()
            current = ""
        else:
            current += char
    return operands


def _statements(source: str) -> list[tuple[int, int, str]]:
    """The macro statements as (first line, last line, text), continuations joined."""
    statements: list[tuple[int, int, str]] = []
    pending: tuple[int, str] | None = None
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.expandtabs(8)
        if pending is None and line.startswith("*"):
            continue
        continued = len(line) > _CONTINUATION_COLUMN and line[_CONTINUATION_COLUMN] != " "
        text = line[:_CONTINUATION_COLUMN].rstrip()
        if pending is None:
            start, joined = number, text
        else:
            start, joined = pending[0], pending[1] + text.strip()
        if continued:
            pending = (start, joined)
        else:
            pending = None
            statements.append((start, number, joined))
    if pending:
        statements.append((pending[0], pending[0], pending[1]))
    return statements


def _parse(source: str) -> list[_Map]:
    maps: list[_Map] = []
    mapset = ""
    current: _Map | None = None
    for start, end, text in _statements(source):
        match = _STATEMENT.match(text)
        if not match:
            continue
        label, macro, operand_text = match.group(1).upper(), match.group(2).upper(), match.group(3) or ""
        operands = _operands(operand_text)
        if macro == "DFHMSD":
            if label:
                mapset = label
            current = None
        elif macro == "DFHMDI":
            if not label:
                current = None
                continue
            current = _Map(name=label, mapset=mapset, line_start=start, line_end=end, size=operands.get("SIZE", "").strip("()").replace(",", "x"))
            maps.append(current)
        elif current:
            current.line_end = end
            if label:
                current.fields.append(label)
                if "UNPROT" in operands.get("ATTRB", "").upper():
                    current.inputs.append(label)
            else:
                initial = operands.get("INITIAL", "")
                if len(initial) > 1 and initial.startswith("'"):
                    body = initial[1:-1] if initial.endswith("'") else initial[1:]
                    label_text = body.replace("''", "'").replace("&&", "&").strip()
                    if any(char.isalnum() for char in label_text):
                        current.labels.append(label_text)
    return maps


class BmsExtractor(StructuralExtractor):
    """BMS extractor for the maps of a mapset."""

    @property
    def language_name(self) -> str:
        return "bms"

    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        parsed = ParsedSource()
        for screen in _parse(source):
            of_mapset = f" of mapset {screen.mapset}" if screen.mapset else ""
            size = f" ({screen.size})" if screen.size else ""
            sentences = [f"Screen map {screen.name}{of_mapset}{size}."]
            if screen.fields:
                sentences.append(f"Fields: {', '.join(screen.fields)}.")
            if screen.inputs:
                sentences.append(f"Input fields: {', '.join(screen.inputs)}.")
            if screen.labels:
                labels = ", ".join(f"'{label}'" for label in screen.labels)
                sentences.append(f"Labels: {labels}.")
            parsed.types.append(
                ExtractedType(
                    name=screen.name,
                    kind="screen",
                    line_start=screen.line_start,
                    line_end=screen.line_end,
                    docstring=" ".join(sentences),
                    decorators=[f"mapset:{screen.mapset}"] if screen.mapset else [],
                )
            )
        return parsed


register_extractor("bms", BmsExtractor)

__all__ = ["BmsExtractor"]
