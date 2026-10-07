"""Tree-sitter based extraction manager for multi-language code analysis.

Provides deterministic, precise extraction that complements LLM-based semantic extraction.
Extracts types, methods, and imports from source files using tree-sitter parsers.

Supported Languages:
    - Python (.py, .pyw, .pyi) - Full support
    - JavaScript (.js, .mjs, .cjs, .jsx) - Full support
    - TypeScript (.ts, .tsx, .mts, .cts) - Limited support (see note below)
    - Java (.java) - Full support
    - C# (.cs) - Full support

TypeScript Support Note:
    TypeScript files are currently parsed using the JavaScript grammar.
    This provides approximately 90% accuracy for common patterns but may miss:

    - Interface definitions (parsed as generic objects)
    - Generic type parameters (e.g., Array<T>, Promise<Result>)
    - Complex type annotations
    - Type-only imports/exports
    - Enums (partially supported)

    For most practical extraction purposes (classes, functions, imports),
    the JavaScript grammar handles TypeScript adequately. A dedicated
    TypeScript extractor using tree-sitter-typescript is planned for
    full TypeScript support.

Usage:
    from deriva.adapters.treesitter import TreeSitterManager

    ts = TreeSitterManager()

    # Extract types from source code
    types = ts.extract_types(source_code, file_path="app.py")
    for t in types:
        print(f"{t.name}: {t.kind}")  # e.g., "User: class"

    # Extract methods
    methods = ts.extract_methods(source_code, file_path="app.py")
    for m in methods:
        print(f"{m.name}({m.parameters})")

    # Extract imports
    imports = ts.extract_imports(source_code, file_path="app.py")
"""

from __future__ import annotations

import os
from typing import Any

import tree_sitter

from .languages import get_extractor, supported_languages
from .models import (
    ExtractedCall,
    ExtractedImport,
    ExtractedMethod,
    ExtractedType,
    FilterConstants,
)


class TreeSitterManager:
    """Unified manager for tree-sitter-based code extraction across all languages.

    Provides deterministic extraction of:
    - Type definitions (classes, interfaces, enums, structs)
    - Methods and functions (with parameters, return types)
    - Import statements (modules, symbols)

    Uses tree-sitter parsers for fast, accurate AST-based extraction.
    Automatically detects language from file extension.
    """

    # Supported languages
    SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "java", "csharp"}

    # Extension to language mapping
    EXTENSION_MAP: dict[str, str] = {
        ".py": "python",
        ".pyw": "python",
        ".pyi": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".mts": "typescript",
        ".cts": "typescript",
        ".java": "java",
        ".cs": "csharp",
    }

    def __init__(self) -> None:
        """Initialize the manager."""
        self._parsers: dict[str, tree_sitter.Parser] = {}

    def extract_types(self, source: str, file_path: str | None = None, language: str | None = None) -> list[ExtractedType]:
        """Extract type definitions from source code.

        Args:
            source: Source code as string
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            List of ExtractedType objects
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return []

        extractor = get_extractor(lang)
        if not extractor:
            return []

        tree = self._parse(source, lang, extractor)
        if not tree:
            return []

        return extractor.extract_types(tree, source.encode("utf-8"))

    def extract_methods(self, source: str, file_path: str | None = None, language: str | None = None) -> list[ExtractedMethod]:
        """Extract method and function definitions from source code.

        Args:
            source: Source code as string
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            List of ExtractedMethod objects
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return []

        extractor = get_extractor(lang)
        if not extractor:
            return []

        tree = self._parse(source, lang, extractor)
        if not tree:
            return []

        return extractor.extract_methods(tree, source.encode("utf-8"))

    def extract_imports(self, source: str, file_path: str | None = None, language: str | None = None) -> list[ExtractedImport]:
        """Extract import statements from source code.

        Args:
            source: Source code as string
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            List of ExtractedImport objects
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return []

        extractor = get_extractor(lang)
        if not extractor:
            return []

        tree = self._parse(source, lang, extractor)
        if not tree:
            return []

        return extractor.extract_imports(tree, source.encode("utf-8"))

    def extract_calls(self, source: str, file_path: str | None = None, language: str | None = None) -> list[ExtractedCall]:
        """Extract function/method calls from source code.

        Args:
            source: Source code as string
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            List of ExtractedCall objects
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return []

        extractor = get_extractor(lang)
        if not extractor:
            return []

        tree = self._parse(source, lang, extractor)
        if not tree:
            return []

        return extractor.extract_calls(tree, source.encode("utf-8"))

    def extract_all(self, source: str, file_path: str | None = None, language: str | None = None) -> dict[str, Any]:
        """Extract all elements from source code.

        Args:
            source: Source code as string
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            Dictionary with 'types', 'methods', 'imports', 'calls' keys
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return {"types": [], "methods": [], "imports": [], "calls": []}

        extractor = get_extractor(lang)
        if not extractor:
            return {"types": [], "methods": [], "imports": [], "calls": []}

        tree = self._parse(source, lang, extractor)
        if not tree:
            return {"types": [], "methods": [], "imports": [], "calls": []}

        source_bytes = source.encode("utf-8")
        return {
            "types": extractor.extract_types(tree, source_bytes),
            "methods": extractor.extract_methods(tree, source_bytes),
            "imports": extractor.extract_imports(tree, source_bytes),
            "calls": extractor.extract_calls(tree, source_bytes),
        }

    @classmethod
    def detect_language(cls, file_path: str) -> str | None:
        """Detect language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            Language name or None if not detected
        """
        ext = os.path.splitext(file_path)[1].lower()
        return cls.EXTENSION_MAP.get(ext)

    @classmethod
    def supports_language(cls, language: str) -> bool:
        """Check if a language is supported.

        Args:
            language: Language name

        Returns:
            True if the language is supported
        """
        return language.lower() in cls.SUPPORTED_LANGUAGES

    @classmethod
    def get_supported_languages(cls) -> list[str]:
        """Get list of supported languages.

        Returns:
            List of supported language names
        """
        return supported_languages()

    def get_filter_constants(self, file_path: str | None = None, language: str | None = None) -> FilterConstants:
        """Get language-specific filter constants for edge extraction.

        Args:
            file_path: Optional file path (used for language detection)
            language: Optional language override

        Returns:
            FilterConstants for the detected/specified language,
            or empty FilterConstants if language not supported
        """
        lang = self._resolve_language(file_path, language)
        if not lang:
            return FilterConstants()

        extractor = get_extractor(lang)
        if not extractor:
            return FilterConstants()

        return extractor.get_filter_constants()

    # =========================================================================
    # Private helper methods
    # =========================================================================

    def _resolve_language(self, file_path: str | None, language: str | None) -> str | None:
        """Resolve the language to use for extraction.

        TypeScript files are mapped to JavaScript for extraction.
        See module docstring for details on TypeScript support limitations.

        Args:
            file_path: Optional file path to detect language from extension
            language: Optional explicit language override

        Returns:
            Language name or None if unsupported
        """
        if language:
            lang = language.lower()
            # TypeScript -> JavaScript mapping
            # The JavaScript grammar handles ~90% of TS patterns correctly.
            # Missing: interfaces, generics, type-only imports, complex annotations
            # TODO: Add dedicated TypeScript extractor for full support
            if lang == "typescript":
                lang = "javascript"
            return lang if lang in self.SUPPORTED_LANGUAGES else None

        if file_path:
            detected = self.detect_language(file_path)
            if detected == "typescript":
                detected = "javascript"
            return detected

        return None

    def _get_parser(self, language: str, extractor: Any) -> tree_sitter.Parser:
        """Get or create a parser for the given language.

        Args:
            language: Language name
            extractor: Language extractor (to get the grammar)

        Returns:
            Configured tree-sitter parser
        """
        if language not in self._parsers:
            raw_language = extractor.get_language()
            # Wrap in Language object (tree-sitter 0.24+ API)
            ts_language = tree_sitter.Language(raw_language)
            parser = tree_sitter.Parser(ts_language)
            self._parsers[language] = parser

        return self._parsers[language]

    def _parse(self, source: str, language: str, extractor: Any) -> tree_sitter.Tree | None:
        """Parse source code into a tree-sitter tree.

        Args:
            source: Source code as string
            language: Language name
            extractor: Language extractor

        Returns:
            Parsed tree or None on failure
        """
        try:
            parser = self._get_parser(language, extractor)
            return parser.parse(source.encode("utf-8"))
        except Exception:
            return None


__all__ = ["TreeSitterManager"]
