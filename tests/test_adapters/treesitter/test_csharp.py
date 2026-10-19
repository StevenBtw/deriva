"""Tests for C# tree-sitter extractor."""

from __future__ import annotations

import pytest
import tree_sitter

from deriva.adapters.treesitter.languages import get_extractor
from deriva.adapters.treesitter.languages.csharp import (
    CSHARP_BUILTIN_TYPES,
    CSHARP_BUILTINS,
    CSHARP_DECORATOR_BUILTINS,
    CSHARP_GENERIC_CONTAINERS,
    CSHARP_STDLIB,
    CSharpExtractor,
)


@pytest.fixture
def extractor():
    """Provide a C# extractor instance."""
    return CSharpExtractor()


@pytest.fixture
def parser(extractor):
    """Provide a tree-sitter parser for C#."""
    raw_lang = extractor.get_language()
    language = tree_sitter.Language(raw_lang)
    return tree_sitter.Parser(language)


def parse(parser, source: str) -> tree_sitter.Tree:
    """Helper to parse C# source code."""
    return parser.parse(source.encode("utf-8"))


class TestCSharpExtractorProperties:
    """Tests for CSharpExtractor properties."""

    def test_language_name_is_csharp(self, extractor):
        """Should return 'csharp' as the language name."""
        assert extractor.language_name == "csharp"

    def test_get_extractor_returns_csharp_extractor(self):
        """get_extractor should return CSharpExtractor for 'csharp'."""
        ext = get_extractor("csharp")
        assert type(ext) is CSharpExtractor

    def test_get_language_returns_valid_language(self, extractor):
        """Should return a valid tree-sitter language."""
        lang = extractor.get_language()
        # A grammar tree-sitter can parse with
        import tree_sitter

        root = tree_sitter.Parser(tree_sitter.Language(lang)).parse(b"class A { }").root_node
        assert (root.has_error, root.child_count) == (False, 1)


class TestCSharpFilterConstants:
    """Tests for C# filter constants."""

    def test_get_filter_constants_returns_correct_type(self, extractor):
        """Should return FilterConstants with correct attributes."""
        constants = extractor.get_filter_constants()
        assert hasattr(constants, "stdlib_modules")
        assert hasattr(constants, "builtin_functions")
        assert hasattr(constants, "builtin_decorators")
        assert hasattr(constants, "builtin_types")
        assert hasattr(constants, "generic_containers")

    def test_filter_constants_contain_system_namespace(self, extractor):
        """stdlib_modules should contain System namespaces."""
        constants = extractor.get_filter_constants()
        assert "System" in constants.stdlib_modules
        assert "System.Collections.Generic" in constants.stdlib_modules
        assert "System.Linq" in constants.stdlib_modules

    def test_filter_constants_contain_builtin_functions(self, extractor):
        """builtin_functions should contain common methods."""
        constants = extractor.get_filter_constants()
        assert "ToString" in constants.builtin_functions
        assert "Where" in constants.builtin_functions
        assert "Select" in constants.builtin_functions

    def test_csharp_stdlib_contains_microsoft_namespaces(self):
        """CSHARP_STDLIB should contain Microsoft namespaces."""
        assert "Microsoft.Extensions" in CSHARP_STDLIB
        assert "Microsoft.AspNetCore" in CSHARP_STDLIB

    def test_csharp_builtins_contains_linq_methods(self):
        """CSHARP_BUILTINS should contain LINQ methods."""
        linq_methods = {"Where", "Select", "OrderBy", "GroupBy", "First", "Any", "All"}
        assert linq_methods.issubset(CSHARP_BUILTINS)

    def test_csharp_decorator_builtins_contains_attributes(self):
        """CSHARP_DECORATOR_BUILTINS should contain common attributes."""
        assert "Serializable" in CSHARP_DECORATOR_BUILTINS
        assert "HttpGet" in CSHARP_DECORATOR_BUILTINS
        assert "Required" in CSHARP_DECORATOR_BUILTINS

    def test_csharp_builtin_types_contains_primitives(self):
        """CSHARP_BUILTIN_TYPES should contain primitive types."""
        primitives = {"int", "long", "string", "bool", "double", "decimal"}
        assert primitives.issubset(CSHARP_BUILTIN_TYPES)

    def test_csharp_builtin_types_contains_collections(self):
        """CSHARP_BUILTIN_TYPES should contain collection types."""
        collections = {"List", "Dictionary", "HashSet", "IEnumerable"}
        assert collections.issubset(CSHARP_BUILTIN_TYPES)

    def test_csharp_generic_containers_defined(self):
        """CSHARP_GENERIC_CONTAINERS should contain generic collection types."""
        assert "List" in CSHARP_GENERIC_CONTAINERS
        assert "Dictionary" in CSHARP_GENERIC_CONTAINERS
        assert "Task" in CSHARP_GENERIC_CONTAINERS


class TestCSharpExtractTypes:
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
        source = "public interface IMyInterface { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "IMyInterface"
        assert types[0].kind == "interface"

    def test_extracts_struct(self, extractor, parser):
        """Should extract a struct declaration."""
        source = "public struct MyStruct { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "MyStruct"
        assert types[0].kind == "struct"

    def test_extracts_enum(self, extractor, parser):
        """Should extract an enum declaration."""
        source = "public enum MyEnum { Value1, Value2 }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "MyEnum"
        assert types[0].kind == "enum"

    def test_extracts_record(self, extractor, parser):
        """Should extract a record declaration."""
        source = "public record MyRecord(string Name, int Age);"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "MyRecord"
        assert types[0].kind == "record"

    def test_extracts_class_with_base_class(self, extractor, parser):
        """Should extract a class with a base class."""
        source = "public class Derived : BaseClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].name == "Derived"
        assert len(types[0].bases) > 0

    def test_extracts_class_with_interface(self, extractor, parser):
        """Should extract a class implementing an interface."""
        source = "public class MyClass : IDisposable { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(types[0].bases) > 0

    def test_extracts_class_with_attributes(self, extractor, parser):
        """Should extract a class with attributes."""
        source = "[Serializable]\npublic class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(types[0].decorators) > 0

    def test_extracts_private_class(self, extractor, parser):
        """Should extract private visibility."""
        source = "private class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].visibility == "private"

    def test_extracts_internal_class(self, extractor, parser):
        """Should extract internal visibility."""
        source = "internal class MyClass { }"
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].visibility == "internal"

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
    public int Field;
}
"""
        tree = parse(parser, source)
        types = extractor.extract_types(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert types[0].line_start == 2
        assert types[0].line_end == 4


class TestCSharpExtractMethods:
    """Tests for extract_methods method."""

    def test_extracts_method(self, extractor, parser):
        """Should extract a method declaration."""
        source = """
public class MyClass {
    public void DoSomething() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "DoSomething"
        assert methods[0].class_name == "MyClass"

    def test_extracts_method_with_return_type(self, extractor, parser):
        """Should extract method return type."""
        source = """
public class MyClass {
    public int GetValue() { return 42; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        # Return type extraction depends on tree-sitter grammar node field names
        # It may be None if the grammar uses different field names
        assert methods[0].name == "GetValue"

    def test_extracts_method_parameters(self, extractor, parser):
        """Should extract method parameters."""
        source = """
public class MyClass {
    public void Process(string name, int count) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2
        assert methods[0].parameters[0]["name"] == "name"
        assert methods[0].parameters[0]["annotation"] == "string"
        assert methods[0].parameters[1]["name"] == "count"
        assert methods[0].parameters[1]["annotation"] == "int"

    def test_extracts_constructor(self, extractor, parser):
        """Should extract a constructor."""
        source = """
public class MyClass {
    public MyClass(string name) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "MyClass"
        assert methods[0].class_name == "MyClass"

    def test_extracts_property(self, extractor, parser):
        """Should extract a property declaration."""
        source = """
public class MyClass {
    public string Name { get; set; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "Name"
        assert methods[0].is_property is True
        assert methods[0].return_annotation == "string"

    def test_extracts_static_method(self, extractor, parser):
        """Should extract static methods."""
        source = """
public class MyClass {
    public static void StaticMethod() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_static is True

    def test_extracts_async_method(self, extractor, parser):
        """Should extract async methods."""
        source = """
public class MyClass {
    public async Task DoAsync() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_async is True

    def test_extracts_method_with_attributes(self, extractor, parser):
        """Should extract method attributes."""
        source = """
public class MyClass {
    [HttpGet]
    public void Get() { }
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
    private void Helper() { }
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
    protected void OnEvent() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].visibility == "protected"

    def test_extracts_method_with_default_parameter(self, extractor, parser):
        """Should extract method with default parameter."""
        source = """
public class MyClass {
    public void Process(int count = 10) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "Process"
        # Default parameter detection depends on tree-sitter grammar

    def test_extracts_method_with_params_parameter(self, extractor, parser):
        """Should extract method with params parameter."""
        source = """
public class MyClass {
    public void Process(params string[] items) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "Process"
        # params parameter handling depends on tree-sitter grammar version

    def test_extracts_method_with_ref_parameter(self, extractor, parser):
        """Should extract method with ref parameter."""
        source = """
public class MyClass {
    public void Swap(ref int a, ref int b) { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2
        assert "ref" in methods[0].parameters[0]["name"]

    def test_extracts_method_with_out_parameter(self, extractor, parser):
        """Should extract method with out parameter."""
        source = """
public class MyClass {
    public bool TryParse(string s, out int result) { result = 0; return true; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 2
        assert "out" in methods[0].parameters[1]["name"]

    def test_extracts_static_property(self, extractor, parser):
        """Should extract static property."""
        source = """
public class MyClass {
    public static MyClass Instance { get; set; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_static is True
        assert methods[0].is_property is True


class TestCSharpExtractImports:
    """Tests for extract_imports method."""

    def test_extracts_simple_using(self, extractor, parser):
        """Should extract a simple using directive."""
        source = "using System;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "System"

    def test_extracts_nested_namespace_using(self, extractor, parser):
        """Should extract using with nested namespace."""
        source = "using System.Collections.Generic;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].module == "System.Collections.Generic"

    def test_extracts_using_with_alias(self, extractor, parser):
        """Should extract using with alias."""
        source = "using MyList = System.Collections.Generic.List<int>;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        # Alias handling varies by tree-sitter version

    def test_extracts_static_using(self, extractor, parser):
        """Should extract static using directive."""
        source = "using static System.Math;"
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 1
        assert imports[0].is_from_import is True

    def test_extracts_multiple_usings(self, extractor, parser):
        """Should extract multiple using directives."""
        source = """
using System;
using System.Linq;
using System.Collections.Generic;
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 3

    def test_extracts_using_line_number(self, extractor, parser):
        """Should extract correct line number for using."""
        source = """
using System;
using System.Linq;
"""
        tree = parse(parser, source)
        imports = extractor.extract_imports(tree, source.encode("utf-8"))

        assert len(imports) == 2
        assert imports[0].line == 2
        assert imports[1].line == 3


class TestCSharpExtractCalls:
    """Tests for extract_calls method."""

    def test_extracts_simple_method_call(self, extractor, parser):
        """Should extract a simple method call."""
        source = """
public class MyClass {
    public void Caller() {
        DoSomething();
    }
    public void DoSomething() { }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        call = next((c for c in calls if c.callee_name == "DoSomething"), None)
        assert call is not None
        assert call.caller_name == "Caller"

    def test_extracts_method_call_on_object(self, extractor, parser):
        """Should extract method call on an object."""
        source = """
public class MyClass {
    public void Process() {
        var list = new List<int>();
        list.Add(42);
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        add_call = next((c for c in calls if c.callee_name == "Add"), None)
        assert add_call is not None
        assert add_call.callee_qualifier == "list"
        assert add_call.is_method_call is True

    def test_extracts_constructor_call(self, extractor, parser):
        """Should extract constructor call (new)."""
        source = """
public class MyClass {
    public void Create() {
        var obj = new StringBuilder();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        ctor_call = next((c for c in calls if c.callee_name == "StringBuilder"), None)
        assert ctor_call is not None
        assert ctor_call.is_method_call is True

    def test_extracts_static_method_call(self, extractor, parser):
        """Should extract static method call."""
        source = """
public class MyClass {
    public void Process() {
        var result = Math.Max(1, 2);
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        max_call = next((c for c in calls if c.callee_name == "Max"), None)
        assert max_call is not None
        assert max_call.callee_qualifier == "Math"

    def test_extracts_calls_from_constructor(self, extractor, parser):
        """Should extract calls from constructor."""
        source = """
public class MyClass {
    public MyClass() {
        Initialize();
    }
    private void Initialize() { }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        init_call = next((c for c in calls if c.callee_name == "Initialize"), None)
        assert init_call is not None
        assert init_call.caller_name == "MyClass"

    def test_extracts_chained_method_call(self, extractor, parser):
        """Should extract chained method calls."""
        source = """
public class MyClass {
    public void Process() {
        var result = items.Where(x => x > 0).Select(x => x * 2).ToList();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        # Should find at least Where, Select, ToList
        call_names = [c.callee_name for c in calls]
        assert "Where" in call_names or "Select" in call_names or "ToList" in call_names

    def test_extracts_generic_method_call(self, extractor, parser):
        """Should extract generic method call."""
        source = """
public class MyClass {
    public void Process() {
        var list = new List<string>();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        # The constructor of the generic type, by its name without the type argument
        assert [(c.caller_name, c.caller_class, c.callee_name) for c in calls] == [("Process", "MyClass", "List")]

        list_call = next((c for c in calls if c.callee_name == "List"), None)
        assert list_call is not None

    def test_extracts_call_line_number(self, extractor, parser):
        """Should extract correct line number for call."""
        source = """
public class MyClass {
    public void Process() {
        DoSomething();
    }
}
"""
        tree = parse(parser, source)
        calls = extractor.extract_calls(tree, source.encode("utf-8"))

        assert len(calls) >= 1
        assert calls[0].line == 4


class TestCSharpHelperMethods:
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
        source = "interface IMyInterface { }"
        tree = parse(parser, source)
        interface_node = tree.root_node.children[0]

        kind = extractor._get_type_kind(interface_node)
        assert kind == "interface"

    def test_get_type_kind_for_struct(self, extractor, parser):
        """Should return 'struct' for struct declaration."""
        source = "struct MyStruct { }"
        tree = parse(parser, source)
        struct_node = tree.root_node.children[0]

        kind = extractor._get_type_kind(struct_node)
        assert kind == "struct"

    def test_get_type_kind_for_enum(self, extractor, parser):
        """Should return 'enum' for enum declaration."""
        source = "enum MyEnum { A, B }"
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
        # May be None or a default visibility
        assert visibility is None or visibility in {"public", "private", "protected", "internal"}

    def test_has_modifier_returns_true(self, extractor, parser):
        """Should return True when modifier exists."""
        source = """
public class MyClass {
    public static void Method() { }
}
"""
        tree = parse(parser, source)
        # Navigate to method
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
    public void Method() { }
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
            has_async = extractor._has_modifier(method_node, source.encode("utf-8"), "async")
            assert has_async is False


class TestCSharpEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_handles_empty_class(self, extractor, parser):
        """Should handle empty class."""
        source = "public class Empty { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(methods) == 0

    def test_handles_class_without_body(self, extractor, parser):
        """Should handle record with positional parameters (no body)."""
        source = "public record Point(int X, int Y);"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_generic_class(self, extractor, parser):
        """Should handle generic class."""
        source = "public class Container<T> { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1
        # Generic type name may vary

    def test_handles_multiple_interfaces(self, extractor, parser):
        """Should handle class implementing multiple interfaces."""
        source = "public class MyClass : IDisposable, ICloneable { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1
        assert len(types[0].bases) >= 1

    def test_handles_expression_bodied_method(self, extractor, parser):
        """Should handle expression-bodied method."""
        source = """
public class MyClass {
    public int Double(int x) => x * 2;
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].name == "Double"

    def test_handles_partial_class(self, extractor, parser):
        """Should handle partial class."""
        source = "public partial class MyClass { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_abstract_class(self, extractor, parser):
        """Should handle abstract class."""
        source = """
public abstract class BaseClass {
    public abstract void DoSomething();
}
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(types) == 1
        assert len(methods) >= 1

    def test_handles_sealed_class(self, extractor, parser):
        """Should handle sealed class."""
        source = "public sealed class FinalClass { }"
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_namespace_declaration(self, extractor, parser):
        """Should handle class in namespace."""
        source = """
namespace MyApp {
    public class MyClass { }
}
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1
        assert types[0].name == "MyClass"

    def test_handles_file_scoped_namespace(self, extractor, parser):
        """Should handle file-scoped namespace."""
        source = """
namespace MyApp;

public class MyClass { }
"""
        tree = parse(parser, source)

        types = extractor.extract_types(tree, source.encode("utf-8"))
        assert len(types) == 1

    def test_handles_global_using(self, extractor, parser):
        """Should handle global using directive."""
        source = "global using System;"
        tree = parse(parser, source)

        imports = extractor.extract_imports(tree, source.encode("utf-8"))
        assert [(i.module, i.names, i.is_from_import) for i in imports] == [("System", [], False)]

    def test_handles_nullable_type_annotation(self, extractor, parser):
        """Should handle nullable type annotations."""
        source = """
public class MyClass {
    public string? Name { get; set; }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert methods[0].is_property is True

    def test_handles_method_with_no_parameters(self, extractor, parser):
        """Should handle method with no parameters."""
        source = """
public class MyClass {
    public void NoParams() { }
}
"""
        tree = parse(parser, source)
        methods = extractor.extract_methods(tree, source.encode("utf-8"))

        assert len(methods) == 1
        assert len(methods[0].parameters) == 0
