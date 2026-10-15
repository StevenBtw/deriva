"""SQL DDL extractor: the tables a schema file creates (no grammar, no LLM).

Each ``CREATE TABLE`` statement is one type of kind ``table``, named as written without its
schema or quotes; the schema is kept as a ``schema:<name>`` decorator. Other statements
(indexes, views, inserts) are no types.
"""

from __future__ import annotations

import re

from ..models import ExtractedType
from . import register_extractor
from .structural import ParsedSource, StructuralExtractor

# One name part: quoted as a whole (spaces and dots inside), or plain
_IDENTIFIER = r"(?:`[^`]+`|\"[^\"]+\"|\[[^\]]+\]|[\w$#@]+)"
# CREATE [OR REPLACE] [TEMP|TEMPORARY] TABLE [IF NOT EXISTS] [schema.]name (
_CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:GLOBAL|LOCAL)\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?P<name>{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})*)",
    re.IGNORECASE,
)
_PART = re.compile(_IDENTIFIER)


def _unquote(part: str) -> str:
    return part[1:-1] if part[:1] in '`"[' else part


def _code_only(source: str) -> str:
    """The source with comments and string literals blanked (same length, newlines kept), quoted names as written."""
    chars = list(source)
    i, n = 0, len(source)

    def blank(start: int, end: int) -> None:
        for k in range(start, end):
            if chars[k] != "\n":
                chars[k] = " "

    while i < n:
        if source.startswith("--", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end + 2
        elif source[i] == "'":
            end = i + 1
            while end < n and not (source[end] == "'" and source[end + 1 : end + 2] != "'"):
                end += 2 if source[end] == "'" else 1  # '' is a quote inside the literal
            end = min(end + 1, n)
        elif source[i] in '`"[':
            # A quoted name stays as written (what looks like a comment or literal inside it is part of the name)
            close = source.find("]" if source[i] == "[" else source[i], i + 1)
            i = n if close < 0 else close + 1
            continue
        else:
            i += 1
            continue
        blank(i, end)
        i = end
    return "".join(chars)


class SqlExtractor(StructuralExtractor):
    """SQL extractor for the tables of a DDL file."""

    @property
    def language_name(self) -> str:
        return "sql"

    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        parsed = ParsedSource()
        code = _code_only(source)
        matches = list(_CREATE_TABLE.finditer(code))
        for number, match in enumerate(matches):
            parts = [_unquote(p) for p in _PART.findall(match.group("name"))]
            start = code.count("\n", 0, match.start()) + 1
            # The statement ends at its terminator (outside comments and literals), else before the next table or at the end
            end_index = code.find(";", match.end())
            if end_index < 0:
                end_index = len(code[: matches[number + 1].start() if number + 1 < len(matches) else len(code)].rstrip()) - 1
            end = code.count("\n", 0, max(end_index, match.start())) + 1
            parsed.types.append(
                ExtractedType(
                    name=parts[-1],
                    kind="table",
                    line_start=start,
                    line_end=end,
                    docstring=f"Table {parts[-1]}" + (f" in schema {parts[-2]}." if len(parts) > 1 else "."),
                    decorators=[f"schema:{parts[-2]}"] if len(parts) > 1 else [],
                )
            )
        return parsed


register_extractor("sql", SqlExtractor)
