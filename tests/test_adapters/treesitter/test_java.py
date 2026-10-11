"""Tests for Java tree-sitter extractor."""

from __future__ import annotations

import pytest
import tree_sitter

from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.java import (
    JAVA_BUILTIN_TYPES,
    JAVA_BUILTINS,
    JAVA_DECORATOR_BUILTINS,
    JAVA_GENERIC_CONTAINERS,
    JAVA_STDLIB,
    JavaExtractor,
)


@pytest.fixture
def extractor():
    """Provide a Java extractor instance."""
    return JavaExtractor()


@pytest.fixture
def parser(extractor):
    """Provide a tree-sitter parser for Java."""
    raw_lang = extractor.get_language()
    language = tree_sitter.Language(raw_lang)
    return tree_sitter.Parser(language)


def parse(parser, source: str) -> tree_sitter.Tree:
    """Helper to parse Java source code."""
    return parser.parse(source.encode("utf-8"))


class TestJavaExtractorProperties:
    """Tests for JavaExtractor properties."""

    def test_language_name_is_java(self, extractor):
        """Should return 'java' as the language name."""
        assert extractor.language_name == "java"

    def test_get_extractor_returns_java_extractor(self):
        """get_extractor should return JavaExtractor for 'java'."""
        ext = get_extractor("java")
        assert ext is not None
        assert isinstance(ext, JavaExtractor)

    def test_get_language_returns_valid_language(self, extractor):
        """Should return a valid tree-sitter language."""
        lang = extractor.get_language()
        assert lang is not None


class TestJavaFilterConstants:
    """Tests for Java filter constants."""

    def test_get_filter_constants_returns_correct_type(self, extractor):
        """Should return FilterConstants with correct attributes."""
        constants = extractor.get_filter_constants()
        assert hasattr(constants, "stdlib_modules")
        assert hasattr(constants, "builtin_functions")
        assert hasattr(constants, "builtin_decorators")
        assert hasattr(constants, "builtin_types")
        assert hasattr(constants, "generic_containers")

    def test_filter_constants_contain_java_packages(self, extractor):
        """stdlib_modules should contain java.* packages."""
        constants = extractor.get_filter_constants()
        assert {"java.lang", "java.util", "java.io"}.issubset(constants.stdlib_modules)

    def test_filter_constants_contain_builtin_methods(self, extractor):
        """builtin_functions should contain common methods."""
        constants = extractor.get_filter_constants()
        assert "toString" in constants.builtin_functions
        assert "hashCode" in constants.builtin_functions
        assert "equals" in constants.builtin_functions

    def test_java_stdlib_contains_javax_packages(self):
        """JAVA_STDLIB should contain javax.* packages."""
        assert "javax.swing" in JAVA_STDLIB
        assert "javax.servlet" in JAVA_STDLIB

    def test_java_stdlib_contains_jakarta_packages(self):
        """JAVA_STDLIB should contain jakarta.* packages."""
        assert "jakarta.servlet" in JAVA_STDLIB
        assert "jakarta.persistence" in JAVA_STDLIB

    def test_java_builtins_contains_stream_methods(self):
        """JAVA_BUILTINS should contain stream methods."""
        stream_methods = {"stream", "filter", "map", "collect", "forEach"}
        assert stream_methods.issubset(JAVA_BUILTINS)

    def test_java_decorator_builtins_contains_annotations(self):
        """JAVA_DECORATOR_BUILTINS should contain common annotations."""
        assert "Override" in JAVA_DECORATOR_BUILTINS
        assert "Deprecated" in JAVA_DECORATOR_BUILTINS
        assert "Test" in JAVA_DECORATOR_BUILTINS

    def test_java_decorator_builtins_contains_spring_annotations(self):
        """JAVA_DECORATOR_BUILTINS should contain Spring annotations."""
        spring_annotations = {"Component", "Service", "Repository", "Controller", "Autowired"}
        assert spring_annotations.issubset(JAVA_DECORATOR_BUILTINS)

    def test_java_builtin_types_contains_primitives(self):
        """JAVA_BUILTIN_TYPES should contain primitive types."""
        primitives = {"int", "long", "double", "boolean", "char", "void"}
        assert primitives.issubset(JAVA_BUILTIN_TYPES)

    def test_java_builtin_types_contains_wrapper_classes(self):
        """JAVA_BUILTIN_TYPES should contain wrapper classes."""
        wrappers = {"Integer", "Long", "Double", "Boolean", "String"}
        assert wrappers.issubset(JAVA_BUILTIN_TYPES)

    def test_java_builtin_types_contains_collections(self):
        """JAVA_BUILTIN_TYPES should contain collection types."""
        collections = {"List", "Set", "Map", "ArrayList", "HashMap"}
        assert collections.issubset(JAVA_BUILTIN_TYPES)

    def test_java_generic_containers_defined(self):
        """JAVA_GENERIC_CONTAINERS should contain generic collection types."""
        assert "List" in JAVA_GENERIC_CONTAINERS
        assert "Map" in JAVA_GENERIC_CONTAINERS
        assert "Optional" in JAVA_GENERIC_CONTAINERS


class TestJavaExtractTypes:
    """Tests for extract_types method."""

    def test_extracts_class(self, extractor, parser):
        """Should extract a class declaration."""
        source = "public class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "MyClass"
        assert types[0].kind == "class"
        assert types[0].visibility == "public"

    def test_extracts_interface(self, extractor, parser):
        """Should extract an interface declaration."""
        source = "public interface MyInterface { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "MyInterface"
        assert types[0].kind == "interface"

    def test_extracts_enum(self, extractor, parser):
        """Should extract an enum declaration."""
        source = "public enum Status { ACTIVE, INACTIVE }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "Status"
        assert types[0].kind == "enum"

    def test_extracts_record(self, extractor, parser):
        """Should extract a record declaration."""
        source = "public record Person(String name, int age) { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "Person"
        assert types[0].kind == "record"

    def test_extracts_class_with_extends(self, extractor, parser):
        """Should extract a class with extends clause."""
        source = "public class Child extends Parent { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "Child"
        assert len(types[0].bases) > 0

    def test_extracts_class_with_implements(self, extractor, parser):
        """Should extract a class implementing interfaces."""
        source = "public class MyClass implements Runnable { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(types[0].bases) > 0

    def test_extracts_class_with_annotations(self, extractor, parser):
        """Should extract a class with annotations."""
        source = "@Entity\npublic class User { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(types[0].decorators) > 0

    def test_extracts_private_class(self, extractor, parser):
        """Should extract private class (inner class context)."""
        source = "private class Inner { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].visibility == "private"

    def test_extracts_protected_class(self, extractor, parser):
        """Should extract protected visibility."""
        source = "protected class Inner { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].visibility == "protected"

    def test_extracts_nested_classes(self, extractor, parser):
        """Should extract nested class declarations."""
        source = """
public class Outer {
    public class Inner { }
}
"""
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 2
        names = [t.name for t in types]
        assert "Outer" in names
        assert "Inner" in names

    def test_extracts_line_numbers(self, extractor, parser):
        """Should extract correct line numbers."""
        source = """
public class MyClass {
    int field;
}
"""
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].line_start == 2
        assert types[0].line_end == 4


class TestJavaExtractMethods:
    """Tests for extract_methods method."""

    def test_extracts_method(self, extractor, parser):
        """Should extract a method declaration."""
        source = """
public class MyClass {
    public void doSomething() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "doSomething"
        assert methods[0].class_name == "MyClass"

    def test_extracts_method_with_return_type(self, extractor, parser):
        """Should extract method return type."""
        source = """
public class MyClass {
    public int getValue() { return 42; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "getValue"

    def test_extracts_method_parameters(self, extractor, parser):
        """Should extract method parameters."""
        source = """
public class MyClass {
    public void process(String name, int count) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2
        assert methods[0].parameters[0]["name"] == "name"
        assert methods[0].parameters[1]["name"] == "count"

    def test_extracts_constructor(self, extractor, parser):
        """Should extract a constructor."""
        source = """
public class MyClass {
    public MyClass(String name) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "MyClass"
        assert methods[0].class_name == "MyClass"

    def test_extracts_static_method(self, extractor, parser):
        """Should extract static methods."""
        source = """
public class MyClass {
    public static void main(String[] args) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_static is True

    def test_extracts_method_with_annotations(self, extractor, parser):
        """Should extract method annotations."""
        source = """
public class MyClass {
    @Override
    public String toString() { return ""; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].decorators) > 0

    def test_extracts_private_method(self, extractor, parser):
        """Should extract private method visibility."""
        source = """
public class MyClass {
    private void helper() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].visibility == "private"

    def test_extracts_protected_method(self, extractor, parser):
        """Should extract protected method visibility."""
        source = """
public class MyClass {
    protected void onEvent() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].visibility == "protected"

    def test_extracts_method_with_varargs(self, extractor, parser):
        """Should extract method with varargs parameter."""
        source = """
public class MyClass {
    public void process(String... items) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "process"

    def test_extracts_method_with_array_parameter(self, extractor, parser):
        """Should extract method with array parameter."""
        source = """
public class MyClass {
    public void process(int[] numbers) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 1

    def test_extracts_generic_method(self, extractor, parser):
        """Should extract generic method."""
        source = """
public class MyClass {
    public <T> T process(T input) { return input; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "process"


class TestJavaExtractImports:
    """Tests for extract_imports method."""

    def test_extracts_simple_import(self, extractor, parser):
        """Should extract a simple import."""
        source = "import java.util.List;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert "java.util" in imports[0].module

    def test_extracts_wildcard_import(self, extractor, parser):
        """Should extract wildcard import."""
        source = "import java.util.*;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert "*" in imports[0].names or imports[0].module.endswith("util")

    def test_extracts_static_import(self, extractor, parser):
        """Should extract static import."""
        source = "import static java.lang.Math.PI;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].is_from_import is True

    def test_extracts_multiple_imports(self, extractor, parser):
        """Should extract multiple imports."""
        source = """
import java.util.List;
import java.util.Map;
import java.io.IOException;
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 3

    def test_extracts_import_line_number(self, extractor, parser):
        """Should extract correct line number for import."""
        source = """
import java.util.List;
import java.util.Map;
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 2
        assert imports[0].line == 2
        assert imports[1].line == 3


class TestJavaExtractCalls:
    """Tests for extract_calls method."""

    def test_extracts_simple_method_call(self, extractor, parser):
        """Should extract a simple method call."""
        source = """
public class MyClass {
    public void caller() {
        doSomething();
    }
    public void doSomething() { }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        call = next((c for c in calls if c.callee_name == "doSomething"), None)
        assert call is not None
        assert call.caller_name == "caller"

    def test_extracts_method_call_on_object(self, extractor, parser):
        """Should extract method call on an object."""
        source = """
public class MyClass {
    public void process() {
        String s = "hello";
        int len = s.length();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        length_call = next((c for c in calls if c.callee_name == "length"), None)
        assert length_call is not None
        assert length_call.callee_qualifier == "s"
        assert length_call.is_method_call is True

    def test_extracts_constructor_call(self, extractor, parser):
        """Should extract constructor call (new)."""
        source = """
public class MyClass {
    public void create() {
        ArrayList<String> list = new ArrayList<>();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        ctor_call = next((c for c in calls if c.callee_name == "ArrayList"), None)
        assert ctor_call is not None

    def test_extracts_static_method_call(self, extractor, parser):
        """Should extract static method call."""
        source = """
public class MyClass {
    public void process() {
        int max = Math.max(1, 2);
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        max_call = next((c for c in calls if c.callee_name == "max"), None)
        assert max_call is not None
        assert max_call.callee_qualifier == "Math"

    def test_extracts_calls_from_constructor(self, extractor, parser):
        """Should extract calls from constructor."""
        source = """
public class MyClass {
    public MyClass() {
        initialize();
    }
    private void initialize() { }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        init_call = next((c for c in calls if c.callee_name == "initialize"), None)
        assert init_call is not None

    def test_extracts_chained_method_call(self, extractor, parser):
        """Should extract chained method calls."""
        source = """
public class MyClass {
    public void process() {
        String result = "hello".toUpperCase().trim();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        call_names = [c.callee_name for c in calls]
        assert "toUpperCase" in call_names or "trim" in call_names

    def test_extracts_call_line_number(self, extractor, parser):
        """Should extract correct line number for call."""
        source = """
public class MyClass {
    public void process() {
        doSomething();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        assert calls[0].line == 4


class TestJavaHelperMethods:
    """Tests for private helper methods."""

    def test_get_type_kind_for_class(self, extractor, parser):
        """Should return 'class' for class declaration."""
        source = "class MyClass { }"
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]

        kind = extractor._get_type_kind(class_node)
        assert kind == "class"

    def test_get_type_kind_for_interface(self, extractor, parser):
        """Should return 'interface' for interface declaration."""
        source = "interface MyInterface { }"
        tree = parse(parser, source)
        interface_node = tree.root_node.children[0]

        kind = extractor._get_type_kind(interface_node)
        assert kind == "interface"

    def test_get_type_kind_for_enum(self, extractor, parser):
        """Should return 'enum' for enum declaration."""
        source = "enum Status { A, B }"
        tree = parse(parser, source)
        enum_node = tree.root_node.children[0]

        kind = extractor._get_type_kind(enum_node)
        assert kind == "enum"

    def test_get_visibility_returns_none_when_no_modifier(self, extractor, parser):
        """Should return None when no visibility modifier."""
        source = "class MyClass { }"
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]

        visibility = extractor._get_visibility(class_node, source.encode("utf-8"))
        assert visibility is None

    def test_has_modifier_returns_true(self, extractor, parser):
        """Should return True when modifier exists."""
        source = """
public class MyClass {
    public static void method() { }
}
"""
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]
        body = extractor.find_child_by_field(class_node, "body")
        method_node = None
        if body:
            for child in body.children:
                if child.type == "method_declaration":
                    method_node = child
                    break

        if method_node:
            has_static = extractor._has_modifier(method_node, source.encode("utf-8"), "static")
            assert has_static is True

    def test_has_modifier_returns_false(self, extractor, parser):
        """Should return False when modifier does not exist."""
        source = """
public class MyClass {
    public void method() { }
}
"""
        tree = parse(parser, source)
        class_node = tree.root_node.children[0]
        body = extractor.find_child_by_field(class_node, "body")
        method_node = None
        if body:
            for child in body.children:
                if child.type == "method_declaration":
                    method_node = child
                    break

        if method_node:
            has_static = extractor._has_modifier(method_node, source.encode("utf-8"), "static")
            assert has_static is False


class TestJavaEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_handles_empty_class(self, extractor, parser):
        """Should handle empty class."""
        source = "public class Empty { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(methods) == 0

    def test_handles_generic_class(self, extractor, parser):
        """Should handle generic class."""
        source = "public class Container<T> { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_multiple_interfaces(self, extractor, parser):
        """Should handle class implementing multiple interfaces."""
        source = "public class MyClass implements Runnable, Comparable<MyClass> { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_abstract_class(self, extractor, parser):
        """Should handle abstract class."""
        source = """
public abstract class BaseClass {
    public abstract void doSomething();
}
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(methods) >= 1

    def test_handles_final_class(self, extractor, parser):
        """Should handle final class."""
        source = "public final class FinalClass { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_package_declaration(self, extractor, parser):
        """Should handle class with package declaration."""
        source = """
package com.example;

public class MyClass { }
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1
        assert types[0].name == "MyClass"

    def test_handles_interface_with_default_method(self, extractor, parser):
        """Should handle interface with default method."""
        source = """
public interface MyInterface {
    default void doSomething() { }
}
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].kind == "interface"

    def test_handles_enum_with_methods(self, extractor, parser):
        """Should handle enum with methods."""
        source = """
public enum Status {
    ACTIVE, INACTIVE;

    public boolean isActive() {
        return this == ACTIVE;
    }
}
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].kind == "enum"

    def test_handles_method_throws_clause(self, extractor, parser):
        """Should handle method with throws clause."""
        source = """
public class MyClass {
    public void process() throws IOException { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "process"

    def test_handles_synchronized_method(self, extractor, parser):
        """Should handle synchronized method."""
        source = """
public class MyClass {
    public synchronized void process() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "process"

    def test_handles_native_method(self, extractor, parser):
        """Should handle native method."""
        source = """
public class MyClass {
    public native void nativeMethod();
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "nativeMethod"

    def test_handles_method_with_no_parameters(self, extractor, parser):
        """Should handle method with no parameters."""
        source = """
public class MyClass {
    public void noParams() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 0
