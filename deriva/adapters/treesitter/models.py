"""Data models for tree-sitter extraction results.

These models are language-agnostic and used across all supported languages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedType:
    """Represents an extracted type definition (class, interface, function, etc.)."""

    name: str
    kind: str  # 'class', 'interface', 'enum', 'struct', 'function', 'type_alias', 'type' (a Go defined type), 'package'
    line_start: int
    line_end: int
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    visibility: str | None = None  # 'public', 'private', 'protected', etc.


@dataclass
class ExtractedMethod:
    """Represents an extracted method/function."""

    name: str
    class_name: str | None  # None for top-level functions
    line_start: int
    line_end: int
    docstring: str | None = None
    parameters: list[dict[str, Any]] = field(default_factory=list)
    return_annotation: str | None = None
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_property: bool = False
    visibility: str | None = None  # 'public', 'private', 'protected', etc.


@dataclass
class ExtractedImport:
    """Represents an extracted import statement."""

    module: str
    names: list[str]  # What is imported (empty for 'import module')
    alias: str | None = None
    line: int = 0
    is_from_import: bool = False


@dataclass
class ExtractedCall:
    """Represents an extracted function/method call."""

    caller_name: str  # Function/method making the call
    caller_class: str | None  # Class containing the caller (None for top-level)
    callee_name: str  # Function/method being called
    callee_qualifier: str | None  # Object/module qualifier (e.g., 'self', 'os.path')
    line: int
    is_method_call: bool = False  # True if called on an object (x.method())


@dataclass
class FilterConstants:
    """Language-specific constants for filtering edges during extraction.

    These constants help filter out language primitives, standard library
    modules, and builtin functions to focus on user-defined code relationships.
    """

    stdlib_modules: set[str] = field(default_factory=set)
    """Standard library modules to treat as external (not internal imports)."""

    builtin_functions: set[str] = field(default_factory=set)
    """Built-in functions to skip in call resolution."""

    builtin_decorators: set[str] = field(default_factory=set)
    """Built-in decorators to skip in decorator edge resolution."""

    builtin_types: set[str] = field(default_factory=set)
    """Built-in types to skip in reference resolution."""

    generic_containers: set[str] = field(default_factory=set)
    """Generic container types (we want inner types, not the container)."""


__all__ = [
    "ExtractedType",
    "ExtractedMethod",
    "ExtractedImport",
    "ExtractedCall",
    "FilterConstants",
]
