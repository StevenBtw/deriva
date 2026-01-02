"""AST-based extraction manager for Python code analysis.

Provides deterministic, precise extraction that complements LLM-based semantic extraction.
Extracts types, methods, and imports from Python source files using the ast module.
"""

from __future__ import annotations

import ast
from typing import Any

from .models import ExtractedImport, ExtractedMethod, ExtractedType


class ASTManager:
    """Manager for AST-based code extraction from Python files."""

    def extract_types(
        self, source: str, file_path: str | None = None
    ) -> list[ExtractedType]:
        """Extract type definitions (classes, functions, type aliases) from Python source.

        Args:
            source: Python source code as string
            file_path: Optional file path for error messages

        Returns:
            List of ExtractedType objects
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        types: list[ExtractedType] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                types.append(self._extract_class(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Only top-level functions (not methods)
                if self._is_top_level(tree, node):
                    types.append(self._extract_function_as_type(node))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                # Type alias: MyType = TypeVar(...) or MyType: TypeAlias = ...
                if self._is_type_alias(node):
                    types.append(self._extract_type_alias(node))

        return types

    def extract_methods(
        self, source: str, file_path: str | None = None
    ) -> list[ExtractedMethod]:
        """Extract method and function definitions from Python source.

        Args:
            source: Python source code as string
            file_path: Optional file path for error messages

        Returns:
            List of ExtractedMethod objects
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        methods: list[ExtractedMethod] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Extract methods from class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(self._extract_method(item, class_name=node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level functions
                if self._is_top_level(tree, node):
                    methods.append(self._extract_method(node, class_name=None))

        return methods

    def extract_imports(
        self, source: str, file_path: str | None = None
    ) -> list[ExtractedImport]:
        """Extract import statements from Python source.

        Args:
            source: Python source code as string
            file_path: Optional file path for error messages

        Returns:
            List of ExtractedImport objects
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        imports: list[ExtractedImport] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ExtractedImport(
                            module=alias.name,
                            names=[],
                            alias=alias.asname,
                            line=node.lineno,
                            is_from_import=False,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [alias.name for alias in node.names]
                imports.append(
                    ExtractedImport(
                        module=module,
                        names=names,
                        alias=None,
                        line=node.lineno,
                        is_from_import=True,
                    )
                )

        return imports

    def extract_all(self, source: str, file_path: str | None = None) -> dict[str, Any]:
        """Extract all elements from Python source.

        Args:
            source: Python source code as string
            file_path: Optional file path for error messages

        Returns:
            Dictionary with 'types', 'methods', 'imports' keys
        """
        return {
            "types": self.extract_types(source, file_path),
            "methods": self.extract_methods(source, file_path),
            "imports": self.extract_imports(source, file_path),
        }

    # =========================================================================
    # Private helper methods
    # =========================================================================

    def _is_top_level(self, tree: ast.Module, node: ast.AST) -> bool:
        """Check if a node is at the top level of the module."""
        return node in tree.body

    def _is_type_alias(self, node: ast.AnnAssign) -> bool:
        """Check if an annotated assignment is a type alias."""
        if node.annotation:
            ann = ast.unparse(node.annotation)
            return "TypeAlias" in ann or "TypeVar" in ann
        return False

    def _get_docstring(self, node: ast.AST) -> str | None:
        """Extract docstring from a class or function node."""
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef | ast.ClassDef | ast.Module):
            return ast.get_docstring(node)
        return None

    def _get_decorators(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[str]:
        """Extract decorator names from a node."""
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(ast.unparse(dec))
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(ast.unparse(dec.func))
        return decorators

    def _get_bases(self, node: ast.ClassDef) -> list[str]:
        """Extract base class names from a class definition."""
        bases = []
        for base in node.bases:
            bases.append(ast.unparse(base))
        return bases

    def _extract_class(self, node: ast.ClassDef) -> ExtractedType:
        """Extract a class definition."""
        return ExtractedType(
            name=node.name,
            kind="class",
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=self._get_docstring(node),
            bases=self._get_bases(node),
            decorators=self._get_decorators(node),
            is_async=False,
        )

    def _extract_function_as_type(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> ExtractedType:
        """Extract a top-level function as a type definition."""
        return ExtractedType(
            name=node.name,
            kind="function",
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=self._get_docstring(node),
            bases=[],
            decorators=self._get_decorators(node),
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )

    def _extract_type_alias(self, node: ast.AnnAssign) -> ExtractedType:
        """Extract a type alias definition."""
        name = node.target.id if isinstance(node.target, ast.Name) else ""
        return ExtractedType(
            name=name,
            kind="type_alias",
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=None,
            bases=[],
            decorators=[],
            is_async=False,
        )

    def _extract_method(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str | None
    ) -> ExtractedMethod:
        """Extract a method or function definition."""
        decorators = self._get_decorators(node)

        # Determine method characteristics from decorators
        is_static = "staticmethod" in decorators
        is_classmethod = "classmethod" in decorators
        is_property = "property" in decorators

        # Extract parameters
        parameters = self._extract_parameters(node)

        # Extract return annotation
        return_annotation = None
        if node.returns:
            return_annotation = ast.unparse(node.returns)

        return ExtractedMethod(
            name=node.name,
            class_name=class_name,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            docstring=self._get_docstring(node),
            parameters=parameters,
            return_annotation=return_annotation,
            decorators=decorators,
            is_async=isinstance(node, ast.AsyncFunctionDef),
            is_static=is_static,
            is_classmethod=is_classmethod,
            is_property=is_property,
        )

    def _extract_parameters(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[dict[str, Any]]:
        """Extract function/method parameters with type annotations."""
        params = []
        args = node.args

        # Regular positional/keyword arguments
        defaults_offset = len(args.args) - len(args.defaults)

        for i, arg in enumerate(args.args):
            param: dict[str, Any] = {
                "name": arg.arg,
                "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
            }

            # Check for default value
            default_idx = i - defaults_offset
            if default_idx >= 0 and default_idx < len(args.defaults):
                param["has_default"] = True
            else:
                param["has_default"] = False

            params.append(param)

        # *args
        if args.vararg:
            params.append(
                {
                    "name": f"*{args.vararg.arg}",
                    "annotation": ast.unparse(args.vararg.annotation)
                    if args.vararg.annotation
                    else None,
                    "has_default": False,
                }
            )

        # **kwargs
        if args.kwarg:
            params.append(
                {
                    "name": f"**{args.kwarg.arg}",
                    "annotation": ast.unparse(args.kwarg.annotation)
                    if args.kwarg.annotation
                    else None,
                    "has_default": False,
                }
            )

        return params


__all__ = [
    "ASTManager",
]
