"""Tests for treesitter base extractor helper methods."""

from __future__ import annotations

import pytest
import tree_sitter
import tree_sitter_python

from deriva.adapters.treesitter.languages import get_extractor


# Shared fixture for all tests that need parsing
@pytest.fixture
def python_parser():
    """Provide a Python parser and extractor for tests."""
    extractor = get_extractor("python")
    raw_lang = tree_sitter_python.language()
    language = tree_sitter.Language(raw_lang)
    parser = tree_sitter.Parser(language)
    return extractor, parser


def parse(parser, source: str) -> tree_sitter.Tree:
    """Helper to parse source code."""
    return parser.parse(source.encode("utf-8"))


class TestLanguageExtractorProperties:
    """Tests for language extractor properties."""

    @pytest.mark.parametrize("lang", ["python", "javascript", "java", "csharp"])
    def test_extractor_returns_correct_language_name(self, lang):
        """Each extractor should return its correct language name."""
        extractor = get_extractor(lang)
        assert extractor is not None
        assert extractor.language_name == lang

    def test_unknown_language_returns_none(self):
        """Unknown language should return None."""
        assert get_extractor("unknown") is None


class TestGetNodeText:
    """Tests for get_node_text helper."""

    def test_extracts_simple_text(self, python_parser):
        """Should extract text from node."""
        extractor, parser = python_parser
        source = "x = 42"
        tree = parse(parser, source)

        text = extractor.get_node_text(tree.root_node, source.encode("utf-8"))
        assert text == "x = 42"

    def test_extracts_function_name(self, python_parser):
        """Should extract text from child nodes."""
        extractor, parser = python_parser
        source = "def hello(): pass"
        tree = parse(parser, source)
        func_node = tree.root_node.children[0]
        name_node = extractor.find_child_by_field(func_node, "name")

        assert name_node is not None
        assert extractor.get_node_text(name_node, source.encode("utf-8")) == "hello"

    def test_handles_unicode(self, python_parser):
        """Should handle unicode characters."""
        extractor, parser = python_parser
        source = "name = '日本語'"
        tree = parse(parser, source)

        text = extractor.get_node_text(tree.root_node, source.encode("utf-8"))
        assert "日本語" in text


class TestLineNumbers:
    """Tests for line number helpers."""

    def test_line_numbers_are_one_indexed(self, python_parser):
        """Should return 1-indexed line numbers."""
        extractor, parser = python_parser
        tree = parse(parser, "x = 1")

        assert extractor.get_line_start(tree.root_node) == 1

    def test_multiline_function_line_range(self, python_parser):
        """Should get correct start and end lines for multiline code."""
        extractor, parser = python_parser
        source = "def func():\n    pass\n    return True"
        tree = parse(parser, source)
        func_node = tree.root_node.children[0]

        assert extractor.get_line_start(func_node) == 1
        assert extractor.get_line_end(func_node) == 3


class TestFindChildByType:
    """Tests for find_child_by_type helper."""

    def test_finds_existing_child(self, python_parser):
        """Should find child by type."""
        extractor, parser = python_parser
        tree = parse(parser, "def hello(): pass")

        func_node = extractor.find_child_by_type(tree.root_node, "function_definition")
        assert func_node is not None
        assert func_node.type == "function_definition"

    def test_returns_none_for_missing_child(self, python_parser):
        """Should return None when child type not found."""
        extractor, parser = python_parser
        tree = parse(parser, "x = 1")

        assert extractor.find_child_by_type(tree.root_node, "function_definition") is None


class TestFindChildrenByType:
    """Tests for find_children_by_type helper."""

    def test_finds_multiple_children(self, python_parser):
        """Should find all children of given type."""
        extractor, parser = python_parser
        source = "def a(): pass\ndef b(): pass\ndef c(): pass"
        tree = parse(parser, source)

        funcs = extractor.find_children_by_type(tree.root_node, "function_definition")
        assert len(funcs) == 3

    def test_returns_empty_list_when_none_found(self, python_parser):
        """Should return empty list when no children match."""
        extractor, parser = python_parser
        tree = parse(parser, "x = 1")

        assert extractor.find_children_by_type(tree.root_node, "function_definition") == []


class TestFindChildByField:
    """Tests for find_child_by_field helper."""

    def test_finds_field(self, python_parser):
        """Should find child by field name."""
        extractor, parser = python_parser
        source = "def hello(): pass"
        tree = parse(parser, source)
        func_node = tree.root_node.children[0]

        name_node = extractor.find_child_by_field(func_node, "name")
        assert name_node is not None
        assert extractor.get_node_text(name_node, source.encode("utf-8")) == "hello"

    def test_returns_none_for_missing_field(self, python_parser):
        """Should return None when field not found."""
        extractor, parser = python_parser
        tree = parse(parser, "def hello(): pass")
        func_node = tree.root_node.children[0]

        assert extractor.find_child_by_field(func_node, "nonexistent") is None


class TestWalkTree:
    """Tests for walk_tree helper."""

    def test_finds_nested_nodes(self, python_parser):
        """Should find nodes at any depth."""
        extractor, parser = python_parser
        source = "class Outer:\n    class Inner:\n        def method(self): pass"
        tree = parse(parser, source)

        classes = extractor.walk_tree(tree.root_node, {"class_definition"})
        assert len(classes) == 2

    def test_finds_multiple_types(self, python_parser):
        """Should find nodes matching any of the given types."""
        extractor, parser = python_parser
        source = "class MyClass: pass\ndef my_func(): pass"
        tree = parse(parser, source)

        results = extractor.walk_tree(tree.root_node, {"class_definition", "function_definition"})
        assert len(results) == 2

    def test_returns_in_document_order(self, python_parser):
        """Should return nodes in document order."""
        extractor, parser = python_parser
        source = "def first(): pass\ndef second(): pass\ndef third(): pass"
        tree = parse(parser, source)

        funcs = extractor.walk_tree(tree.root_node, {"function_definition"})
        names = [extractor.get_node_text(extractor.find_child_by_field(f, "name"), source.encode("utf-8")) for f in funcs]

        assert names == ["first", "second", "third"]


class TestExtractDocstring:
    """Tests for extract_docstring base method."""

    def test_base_returns_none(self, python_parser):
        """Base implementation should return None (override in subclasses)."""
        extractor, parser = python_parser
        tree = parse(parser, "def func(): pass")
        func_node = tree.root_node.children[0]

        # Base extract_docstring returns None - actual extraction is in language-specific methods
        assert extractor.extract_docstring(func_node, b"def func(): pass") is None


class TestExtractCalls:
    """Tests for extract_calls default method."""

    def test_default_returns_empty_list(self, python_parser):
        """Default extract_calls should return empty list for base class."""
        # Python extractor overrides this, but we can test the base behavior
        # by checking that it returns a list
        extractor, parser = python_parser
        source = "func()"
        tree = parse(parser, source)

        # A call outside any function has no caller, so it is no call edge
        calls = extractor.extract_calls(tree, source.encode("utf-8"))
        assert calls == []


class TestGetFilterConstants:
    """Tests for get_filter_constants method."""

    def test_returns_filter_constants(self, python_parser):
        """Should return FilterConstants object."""
        extractor, _ = python_parser

        constants = extractor.get_filter_constants()

        # Should return a FilterConstants object with sets
        assert hasattr(constants, "stdlib_modules")
        assert hasattr(constants, "builtin_functions")
        assert isinstance(constants.stdlib_modules, set)
        assert isinstance(constants.builtin_functions, set)

    @pytest.mark.parametrize("lang", ["python", "javascript", "java", "csharp"])
    def test_each_language_has_filter_constants(self, lang):
        """Each language extractor should provide filter constants."""
        extractor = get_extractor(lang)
        assert extractor is not None
        constants = extractor.get_filter_constants()

        # A standard library module of each language is known as one
        stdlib = {"python": "typing", "javascript": "fs", "java": "java.util.stream", "csharp": "System.Globalization"}[lang]
        assert stdlib in constants.stdlib_modules
