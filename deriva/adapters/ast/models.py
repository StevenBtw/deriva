"""AST-based extraction models.

TODO: Implement AST-based extraction models for Python code analysis.

This module will provide data models for:
- TypeDefinition: Classes, interfaces, type aliases
- Method: Functions, methods with signatures
- ExternalDependency: Import statements and package dependencies

These will complement LLM-based extraction with precise, deterministic
extraction of code structure.
"""

from __future__ import annotations

__all__: list[str] = []

# TODO: Implement AST extraction models
# Example structure:
#
# from dataclasses import dataclass
# from typing import Any
#
# @dataclass
# class ASTTypeDefinition:
#     """Represents a type extracted via AST parsing."""
#     name: str
#     kind: str  # class, interface, type_alias, enum
#     module_path: str
#     line_number: int
#     docstring: str | None = None
#     bases: list[str] | None = None
#     decorators: list[str] | None = None
