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

# CREATE [OR REPLACE] [TEMP|TEMPORARY] TABLE [IF NOT EXISTS] [schema.]name (
_CREATE_TABLE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:GLOBAL|LOCAL)\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>(?:[`\"\[]?[\w$#@]+[`\"\]]?\.)*[`\"\[]?[\w$#@]+[`\"\]]?)",
    re.IGNORECASE,
)


def _unquote(part: str) -> str:
    return part.strip('`"[]')


class SqlExtractor(StructuralExtractor):
    """SQL extractor for the tables of a DDL file."""

    @property
    def language_name(self) -> str:
        return "sql"

    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        parsed = ParsedSource()
        for match in _CREATE_TABLE.finditer(source):
            parts = [_unquote(p) for p in match.group("name").split(".")]
            start = source.count("\n", 0, match.start()) + 1
            end_index = source.find(";", match.end())
            end = source.count("\n", 0, end_index) + 1 if end_index >= 0 else start
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
