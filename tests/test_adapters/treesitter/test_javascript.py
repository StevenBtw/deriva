"""Tests for JavaScript tree-sitter extractor."""

from __future__ import annotations

import pytest
import tree_sitter

from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.javascript import (
    JS_BUILTIN_TYPES,
    JS_BUILTINS,
    JS_DECORATOR_BUILTINS,
    JS_GENERIC_CONTAINERS,
    JS_STDLIB,
    JavaScriptExtractor,
)


@pytest.fixture
def extractor():
    """Provide a JavaScript extractor instance."""
    return JavaScriptExtractor()


@pytest.fixture
def parser(extractor):
    """Provide a tree-sitter parser for JavaScript."""
    raw_lang = extractor.get_language()
    language = tree_sitter.Language(raw_lang)
    return tree_sitter.Parser(language)


def parse(parser, source: str) -> tree_sitter.Tree:
    """Helper to parse JavaScript source code."""
    return parser.parse(source.encode("utf-8"))


class TestJavaScriptExtractorProperties:
    """Tests for JavaScriptExtractor properties."""

    def test_language_name_is_javascript(self, extractor):
        """Should return 'javascript' as the language name."""
        assert extractor.language_name == "javascript"

    def test_get_extractor_returns_javascript_extractor(self):
        """get_extractor should return JavaScriptExtractor for 'javascript'."""
        ext = get_extractor("javascript")
        assert type(ext) is JavaScriptExtractor

    def test_get_language_returns_valid_language(self, extractor):
        """Should return a valid tree-sitter language."""
        lang = extractor.get_language()
        # A grammar tree-sitter can parse with
        import tree_sitter

        root = tree_sitter.Parser(tree_sitter.Language(lang)).parse(b"class A { }").root_node
        assert (root.has_error, root.child_count) == (False, 1)


class TestJavaScriptFilterConstants:
    """Tests for JavaScript filter constants."""

    def test_get_filter_constants_returns_correct_type(self, extractor):
        """Should return FilterConstants with correct attributes."""
        constants = extractor.get_filter_constants()
        assert hasattr(constants, "stdlib_modules")
        assert hasattr(constants, "builtin_functions")
        assert hasattr(constants, "builtin_decorators")
        assert hasattr(constants, "builtin_types")
        assert hasattr(constants, "generic_containers")

    def test_filter_constants_contain_node_modules(self, extractor):
        """stdlib_modules should contain Node.js core modules."""
        constants = extractor.get_filter_constants()
        assert "fs" in constants.stdlib_modules
        assert "path" in constants.stdlib_modules
        assert "http" in constants.stdlib_modules

    def test_filter_constants_contain_node_prefixed_modules(self, extractor):
        """stdlib_modules should contain node: prefixed modules."""
        constants = extractor.get_filter_constants()
        assert "node:fs" in constants.stdlib_modules
        assert "node:path" in constants.stdlib_modules

    def test_filter_constants_contain_builtin_functions(self, extractor):
        """builtin_functions should contain common functions."""
        constants = extractor.get_filter_constants()
        assert "parseInt" in constants.builtin_functions
        assert "setTimeout" in constants.builtin_functions
        assert "console" in constants.builtin_functions

    def test_js_stdlib_contains_core_modules(self):
        """JS_STDLIB should contain Node.js core modules."""
        core_modules = {"fs", "path", "http", "https", "crypto", "os", "util"}
        assert core_modules.issubset(JS_STDLIB)

    def test_js_builtins_contains_array_methods(self):
        """JS_BUILTINS should contain array methods."""
        array_methods = {"push", "pop", "map", "filter", "reduce", "forEach"}
        assert array_methods.issubset(JS_BUILTINS)

    def test_js_builtins_contains_promise_methods(self):
        """JS_BUILTINS should contain Promise methods."""
        assert "Promise" in JS_BUILTINS
        assert "resolve" in JS_BUILTINS
        assert "reject" in JS_BUILTINS

    def test_js_decorator_builtins_contains_framework_decorators(self):
        """JS_DECORATOR_BUILTINS should contain framework decorators."""
        assert "Component" in JS_DECORATOR_BUILTINS
        assert "Injectable" in JS_DECORATOR_BUILTINS
        assert "Controller" in JS_DECORATOR_BUILTINS

    def test_js_builtin_types_contains_primitives(self):
        """JS_BUILTIN_TYPES should contain TypeScript primitive types."""
        primitives = {"string", "number", "boolean", "void", "any", "unknown"}
        assert primitives.issubset(JS_BUILTIN_TYPES)

    def test_js_builtin_types_contains_utility_types(self):
        """JS_BUILTIN_TYPES should contain TypeScript utility types."""
        utility_types = {"Partial", "Required", "Readonly", "Record", "Pick", "Omit"}
        assert utility_types.issubset(JS_BUILTIN_TYPES)

    def test_js_generic_containers_defined(self):
        """JS_GENERIC_CONTAINERS should contain generic collection types."""
        assert "Array" in JS_GENERIC_CONTAINERS
        assert "Map" in JS_GENERIC_CONTAINERS
        assert "Promise" in JS_GENERIC_CONTAINERS


class TestJavaScriptExtractTypes:
    """Tests for extract_types method."""

    def test_extracts_class(self, extractor, parser):
        """Should extract a class declaration."""
        source = "class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert [(t.name, t.kind) for t in types] == [("MyClass", "class")]

    def test_extracts_class_with_extends(self, extractor, parser):
        """Should extract a class with extends clause."""
        source = "class Child extends Parent { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert [(t.name, t.kind, t.bases) for t in types] == [("Child", "class", ["Parent"])]

    def test_extracts_function_declaration(self, extractor, parser):
        """Should extract a function declaration as a type."""
        source = "function myFunction() { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "myFunction"
        assert types[0].kind == "function"

    def test_extracts_async_function(self, extractor, parser):
        """Should extract an async function."""
        source = "async function fetchData() { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "fetchData"
        assert types[0].is_async is True

    def test_extracts_arrow_function(self, extractor, parser):
        """Should extract an arrow function assigned to const."""
        source = "const myFunc = () => { };"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "myFunc"
        assert types[0].kind == "function"

    def test_extracts_async_arrow_function(self, extractor, parser):
        """Should extract an async arrow function."""
        source = "const fetchData = async () => { };"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].is_async is True

    def test_extracts_exported_class(self, extractor, parser):
        """Should extract an exported class."""
        source = "export class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert [(t.name, t.kind) for t in types] == [("MyClass", "class")]

    def test_extracts_exported_function(self, extractor, parser):
        """Should extract an exported function."""
        source = "export function myFunction() { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "myFunction"

    def test_extracts_line_numbers(self, extractor, parser):
        """Should extract correct line numbers."""
        source = """
class MyClass {
    constructor() { }
}
"""
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert [(t.name, t.line_start, t.line_end) for t in types] == [("MyClass", 2, 4)]


class TestJavaScriptExtractMethods:
    """Tests for extract_methods method."""

    def test_extracts_class_method(self, extractor, parser):
        """Should extract a class method."""
        source = """
class MyClass {
    doSomething() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "doSomething"
        assert methods[0].class_name == "MyClass"

    def test_extracts_constructor(self, extractor, parser):
        """Should extract a constructor."""
        source = """
class MyClass {
    constructor(name) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "constructor"

    def test_extracts_static_method(self, extractor, parser):
        """Should extract static methods."""
        source = """
class MyClass {
    static create() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_static is True

    def test_extracts_async_method(self, extractor, parser):
        """Should extract async methods."""
        source = """
class MyClass {
    async fetchData() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_async is True

    def test_extracts_getter(self, extractor, parser):
        """Should extract getter methods."""
        source = """
class MyClass {
    get name() { return this._name; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_property is True

    def test_extracts_setter(self, extractor, parser):
        """Should extract setter methods."""
        source = """
class MyClass {
    set name(value) { this._name = value; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_property is True

    def test_extracts_method_parameters(self, extractor, parser):
        """Should extract method parameters."""
        source = """
class MyClass {
    process(name, count) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2
        assert methods[0].parameters[0]["name"] == "name"
        assert methods[0].parameters[1]["name"] == "count"

    def test_extracts_method_with_default_parameter(self, extractor, parser):
        """Should extract method with default parameter."""
        source = """
class MyClass {
    process(count = 10) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 1
        assert methods[0].parameters[0]["has_default"] is True

    def test_extracts_method_with_rest_parameter(self, extractor, parser):
        """Should extract method with rest parameter."""
        source = """
class MyClass {
    process(...args) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 1
        assert "..." in methods[0].parameters[0]["name"]

    def test_extracts_standalone_function(self, extractor, parser):
        """Should extract standalone function."""
        source = "function helper() { }"
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "helper"
        assert methods[0].class_name is None

    def test_extracts_arrow_function(self, extractor, parser):
        """Should extract arrow function assigned to variable."""
        source = "const helper = () => { };"
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "helper"

    def test_extracts_arrow_function_with_parameters(self, extractor, parser):
        """Should extract arrow function with parameters."""
        source = "const add = (a, b) => a + b;"
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2


class TestJavaScriptExtractImports:
    """Tests for extract_imports method."""

    def test_extracts_default_import(self, extractor, parser):
        """Should extract default import."""
        source = "import MyModule from './myModule';"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "./myModule"
        assert "MyModule" in imports[0].names

    def test_extracts_named_import(self, extractor, parser):
        """Should extract named import."""
        source = "import { foo, bar } from './utils';"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "./utils"
        assert "foo" in imports[0].names
        assert "bar" in imports[0].names

    def test_extracts_namespace_import(self, extractor, parser):
        """Should extract namespace import."""
        source = "import * as Utils from './utils';"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert "*" in imports[0].names
        assert imports[0].alias == "Utils"

    def test_extracts_require(self, extractor, parser):
        """Should extract require() call."""
        source = "const fs = require('fs');"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "fs"
        assert "fs" in imports[0].names

    def test_extracts_require_with_destructuring(self, extractor, parser):
        """Should extract require() with destructuring."""
        source = "const { readFile, writeFile } = require('fs');"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "fs"

    def test_extracts_multiple_imports(self, extractor, parser):
        """Should extract multiple imports."""
        source = """
import fs from 'fs';
import path from 'path';
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 2

    def test_extracts_import_line_number(self, extractor, parser):
        """Should extract correct line number for import."""
        source = """
import fs from 'fs';
import path from 'path';
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 2
        assert imports[0].line == 2
        assert imports[1].line == 3


class TestJavaScriptExtractCalls:
    """Tests for extract_calls method."""

    def test_extracts_simple_function_call(self, extractor, parser):
        """Should extract a simple function call."""
        source = """
function caller() {
    doSomething();
}
function doSomething() { }
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        call = next((c for c in calls if c.callee_name == "doSomething"), None)
        assert call is not None
        assert call.caller_name == "caller"

    def test_extracts_method_call(self, extractor, parser):
        """Should extract method call on object."""
        source = """
function process() {
    console.log("hello");
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        log_call = next((c for c in calls if c.callee_name == "log"), None)
        assert log_call is not None
        assert log_call.callee_qualifier == "console"
        assert log_call.is_method_call is True

    def test_extracts_constructor_call(self, extractor, parser):
        """Should extract constructor call (new)."""
        source = """
function create() {
    const obj = new MyClass();
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert [(c.caller_name, c.callee_name, c.callee_qualifier, c.is_method_call) for c in calls] == [("create", "MyClass", "new", False)]

    def test_extracts_calls_from_class_method(self, extractor, parser):
        """Should extract calls from class method."""
        source = """
class MyClass {
    process() {
        this.helper();
    }
    helper() { }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        helper_call = next((c for c in calls if c.callee_name == "helper"), None)
        assert helper_call is not None
        assert helper_call.caller_name == "process"
        assert helper_call.caller_class == "MyClass"

    def test_extracts_chained_call(self, extractor, parser):
        """Should extract chained method calls."""
        source = """
function process() {
    arr.filter(x => x > 0).map(x => x * 2);
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        call_names = [c.callee_name for c in calls]
        assert "filter" in call_names or "map" in call_names

    def test_extracts_call_line_number(self, extractor, parser):
        """Should extract correct line number for call."""
        source = """
function process() {
    doSomething();
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        assert calls[0].line == 3


class TestJavaScriptHelperMethods:
    """Tests for private helper methods."""

    def test_get_class_name(self, extractor, parser):
        """Should get class name."""
        source = "class MyClass { }"
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]

        name = extractor._get_class_name(class_node, source.encode("utf-8"))
        assert name == "MyClass"

    def test_get_bases_with_extends(self, extractor, parser):
        """Should get base classes."""
        source = "class Child extends Parent { }"
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]

        bases = extractor._get_bases(class_node, source.encode("utf-8"))
        assert bases == ["Parent"]

    def test_extract_parameters_basic(self, extractor, parser):
        """Should extract basic parameters."""
        source = "function test(a, b, c) { }"
        tree = parse(parser, source)
        func_node = tree.root_node.children[0]

        params = extractor._extract_parameters(func_node, source.encode("utf-8"))
        assert len(params) == 3
        assert params[0]["name"] == "a"
        assert params[1]["name"] == "b"
        assert params[2]["name"] == "c"

    def test_extract_parameters_with_default(self, extractor, parser):
        """Should extract parameters with default values."""
        source = "function test(a = 1, b = 2) { }"
        tree = parse(parser, source)
        func_node = tree.root_node.children[0]

        params = extractor._extract_parameters(func_node, source.encode("utf-8"))
        assert len(params) == 2
        assert params[0]["has_default"] is True
        assert params[1]["has_default"] is True


class TestJavaScriptEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_handles_empty_class(self, extractor, parser):
        """Should handle empty class."""
        source = "class Empty { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert [(t.name, t.kind) for t in types] == [("Empty", "class")]
        assert methods == []

    def test_handles_class_expression(self, extractor, parser):
        """Should handle class expression."""
        source = "const MyClass = class { };"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        # Named after the variable it is assigned to
        assert [(t.name, t.kind) for t in types] == [("MyClass", "class")]

    def test_handles_iife(self, extractor, parser):
        """Should handle immediately invoked function expression."""
        source = "(function() { console.log('hello'); })();"
        tree = parse(parser, source)

        # An anonymous function invoked in place is no type
        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert types == []

    def test_handles_generator_function(self, extractor, parser):
        """Should handle generator function."""
        source = "function* generator() { yield 1; }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert [(t.name, t.kind) for t in types] == [("generator", "function")]

    def test_handles_destructuring_parameter(self, extractor, parser):
        """Should handle destructuring parameter."""
        source = "function test({ name, age }) { }"
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 1

    def test_handles_multiple_classes(self, extractor, parser):
        """Should handle multiple classes."""
        source = """
class First { }
class Second { }
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert [(t.name, t.line_start) for t in types] == [("First", 2), ("Second", 3)]

    def test_handles_class_with_computed_property(self, extractor, parser):
        """Should handle class with computed property names."""
        source = """
class MyClass {
    ['computed']() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1

    def test_handles_arrow_function_with_single_param(self, extractor, parser):
        """Should handle arrow function with single parameter (no parens)."""
        source = "const double = x => x * 2;"
        tree = parse(parser, source)

        methods = extractor.extract_methods(tree, source.encode("utf-8"))
        types = extractor.extract_types(tree, source.encode("utf-8"))

        # Should extract either as method or type
        assert len(methods) + len(types) >= 1

    def test_handles_export_default_class(self, extractor, parser):
        """Should handle export default class."""
        source = "export default class MyClass { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert [(t.name, t.kind) for t in types] == [("MyClass", "class")]

    def test_handles_private_class_field(self, extractor, parser):
        """Should handle private class field (if tree-sitter supports)."""
        source = """
class MyClass {
    #privateField = 42;
}
"""
        tree = parse(parser, source)
        # The field is no type of its own: the class, over its lines
        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert [(t.name, t.line_start, t.line_end) for t in types] == [("MyClass", 2, 4)]

    def test_handles_static_class_field(self, extractor, parser):
        """Should handle static class field."""
        source = """
class MyClass {
    static count = 0;
}
"""
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert [(t.name, t.line_start, t.line_end) for t in types] == [("MyClass", 2, 4)]

    def test_handles_method_with_no_parameters(self, extractor, parser):
        """Should handle method with no parameters."""
        source = """
class MyClass {
    noParams() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 0


class TestJavaScriptClassesAndGenerators:
    """One type per class (also exported, or assigned as an expression), its base, and generator functions."""

    def test_a_class_is_one_type(self, extractor, parser):
        source = "class First { }"
        types = extractor.extract_types(parse(parser, source), source.encode("utf-8"))

        assert [(t.name, t.kind) for t in types] == [("First", "class")]

    def test_an_exported_class_is_one_type(self, extractor, parser):
        source = "export class MyClass { }"
        types = extractor.extract_types(parse(parser, source), source.encode("utf-8"))

        assert [(t.name, t.kind) for t in types] == [("MyClass", "class")]

    def test_a_class_keeps_the_class_it_extends(self, extractor, parser):
        source = "class Child extends models.Parent { }"
        types = extractor.extract_types(parse(parser, source), source.encode("utf-8"))

        assert [(t.name, t.bases) for t in types] == [("Child", ["models.Parent"])]

    def test_a_class_expression_is_named_after_its_variable(self, extractor, parser):
        source = "const MyClass = class { run() { } };"
        tree = parse(parser, source)

        assert [(t.name, t.kind) for t in extractor.extract_types(tree, source.encode("utf-8"))] == [("MyClass", "class")]
        assert [(m.name, m.class_name) for m in extractor.extract_methods(tree, source.encode("utf-8"))] == [("run", "MyClass")]

    def test_a_generator_function_is_a_type_and_a_method(self, extractor, parser):
        source = "export function* generator() { yield 1; }"
        tree = parse(parser, source)

        assert [(t.name, t.kind) for t in extractor.extract_types(tree, source.encode("utf-8"))] == [("generator", "function")]
        assert [(m.name, m.class_name) for m in extractor.extract_methods(tree, source.encode("utf-8"))] == [("generator", None)]
