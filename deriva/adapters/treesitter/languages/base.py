"""Abstract base class for language-specific tree-sitter extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tree_sitter

from ..models import (
    ExtractedCall,
    ExtractedImport,
    ExtractedMethod,
    ExtractedType,
    FilterConstants,
)


class LanguageExtractor(ABC):
    """Abstract base class for language-specific extractors.

    Each language extractor knows how to navigate tree-sitter parse trees
    for its specific language and extract types, methods, and imports.
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Return the language name (e.g., 'python', 'javascript')."""

    @abstractmethod
    def get_language(self) -> Any:
        """Return the tree-sitter Language object.

        Returns:
            tree_sitter.Language object for this language
        """

    @abstractmethod
    def extract_types(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedType]:
        """Extract type definitions from parsed tree.

        Args:
            tree: Parsed tree-sitter tree
            source: Original source code as bytes

        Returns:
            List of ExtractedType objects
        """

    @abstractmethod
    def extract_methods(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedMethod]:
        """Extract methods/functions from parsed tree.

        Args:
            tree: Parsed tree-sitter tree
            source: Original source code as bytes

        Returns:
            List of ExtractedMethod objects
        """

    @abstractmethod
    def extract_imports(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedImport]:
        """Extract import statements from parsed tree.

        Args:
            tree: Parsed tree-sitter tree
            source: Original source code as bytes

        Returns:
            List of ExtractedImport objects
        """

    def extract_calls(self, tree: tree_sitter.Tree, source: bytes) -> list[ExtractedCall]:
        """Extract function/method calls from parsed tree.

        This is optional - languages can override to provide call extraction.

        Args:
            tree: Parsed tree-sitter tree
            source: Original source code as bytes

        Returns:
            List of ExtractedCall objects
        """
        return []

    def get_filter_constants(self) -> FilterConstants:
        """Return language-specific filter constants for edge extraction.

        Override in language-specific extractors to provide constants for
        filtering standard library, builtins, and framework code during
        edge extraction.

        Returns:
            FilterConstants with language-specific sets
        """
        return FilterConstants()

    # =========================================================================
    # Helper methods available to all extractors
    # =========================================================================

    def get_node_text(self, node: tree_sitter.Node, source: bytes) -> str:
        """Extract text content from a tree-sitter node.

        Args:
            node: Tree-sitter node
            source: Original source as bytes

        Returns:
            Text content of the node
        """
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def get_line_start(self, node: tree_sitter.Node) -> int:
        """Get 1-indexed line number where node starts."""
        return node.start_point[0] + 1

    def get_line_end(self, node: tree_sitter.Node) -> int:
        """Get 1-indexed line number where node ends."""
        return node.end_point[0] + 1

    def find_child_by_type(self, node: tree_sitter.Node, type_name: str) -> tree_sitter.Node | None:
        """Find first child node with given type.

        Args:
            node: Parent node
            type_name: Node type to find

        Returns:
            First matching child or None
        """
        for child in node.children:
            if child.type == type_name:
                return child
        return None

    def find_children_by_type(self, node: tree_sitter.Node, type_name: str) -> list[tree_sitter.Node]:
        """Find all child nodes with given type.

        Args:
            node: Parent node
            type_name: Node type to find

        Returns:
            List of matching children
        """
        return [child for child in node.children if child.type == type_name]

    def find_child_by_field(self, node: tree_sitter.Node, field_name: str) -> tree_sitter.Node | None:
        """Find child node by field name.

        Args:
            node: Parent node
            field_name: Field name to find

        Returns:
            Child node or None
        """
        return node.child_by_field_name(field_name)

    def walk_tree(self, node: tree_sitter.Node, type_names: set[str]) -> list[tree_sitter.Node]:
        """Walk tree and collect nodes matching type names.

        Args:
            node: Root node to start from
            type_names: Set of node types to collect

        Returns:
            List of matching nodes in document order
        """
        results: list[tree_sitter.Node] = []

        def _walk(n: tree_sitter.Node) -> None:
            if n.type in type_names:
                results.append(n)
            for child in n.children:
                _walk(child)

        _walk(node)
        return results

    def extract_docstring(self, node: tree_sitter.Node, source: bytes) -> str | None:
        """Extract docstring from a node if present.

        Override in language-specific extractors for custom docstring formats.

        Args:
            node: Node to extract docstring from
            source: Original source as bytes

        Returns:
            Docstring text or None
        """
        return None


__all__ = ["LanguageExtractor"]
