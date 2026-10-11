"""Base class for extractors that read line-oriented source without a tree-sitter grammar.

Some languages have a shallow, line-oriented structure and no grammar in the
tree-sitter packages (COBOL, JCL, BMS). Their extractors parse the text once into
a ParsedSource; the manager hands that object to the extract methods in place of
a tree-sitter tree, so callers use them exactly like the grammar-based extractors.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from ..models import ExtractedCall, ExtractedImport, ExtractedMethod, ExtractedType
from .base import LanguageExtractor


@dataclass
class ParsedSource:
    """Everything one structural parse of a source file found."""

    types: list[ExtractedType] = field(default_factory=list)
    methods: list[ExtractedMethod] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    calls: list[ExtractedCall] = field(default_factory=list)


class StructuralExtractor(LanguageExtractor):
    """Language extractor that parses source text itself (no grammar)."""

    def get_language(self) -> Any:
        """No tree-sitter grammar: the manager calls parse_source instead."""
        return None

    @abstractmethod
    def parse_source(self, source: str, file_path: str | None = None) -> ParsedSource:
        """Parse the source text once.

        Args:
            source: Source code as string
            file_path: Optional file path (names what the source itself leaves unnamed)

        Returns:
            ParsedSource with the types, methods, imports and calls found
        """

    def extract_types(self, tree: Any, source: bytes) -> list[ExtractedType]:
        """Return the types of a ParsedSource."""
        return list(tree.types)

    def extract_methods(self, tree: Any, source: bytes) -> list[ExtractedMethod]:
        """Return the methods of a ParsedSource."""
        return list(tree.methods)

    def extract_imports(self, tree: Any, source: bytes) -> list[ExtractedImport]:
        """Return the imports of a ParsedSource."""
        return list(tree.imports)

    def extract_calls(self, tree: Any, source: bytes) -> list[ExtractedCall]:
        """Return the calls of a ParsedSource."""
        return list(tree.calls)


def member_name(file_path: str | None) -> str | None:
    """The member name a file path stands for: its stem in upper case."""
    if not file_path:
        return None
    stem = PurePath(file_path.replace("\\", "/")).stem
    return stem.upper() or None


__all__ = ["ParsedSource", "StructuralExtractor", "member_name"]
