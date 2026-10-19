"""Consolidated tests for all language extractors (Java, JavaScript, C#, Python).

This file replaces the individual test_java.py, test_javascript.py, test_csharp.py,
and test_python.py files with parameterized tests that reduce duplication.
"""

from __future__ import annotations

from typing import Any

import pytest

from deriva.adapters.treesitter import TreeSitterManager

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def manager():
    """Provide a TreeSitterManager instance for all tests."""
    return TreeSitterManager()


# =============================================================================
# LANGUAGE-SPECIFIC CODE SAMPLES
# =============================================================================

SAMPLES: dict[str, dict[str, Any]] = {
    "java": {
        "class": ("public class UserService { private String name; }", "UserService", "class"),
        "class_inheritance": ("public class Admin extends User { private int level; }", "Admin"),
        "interface": ("public interface Repository<T> { T findById(Long id); }", "Repository", "interface"),
        "enum": ("public enum Status { PENDING, ACTIVE, COMPLETED }", "Status"),
        "abstract_class": ("public abstract class BaseEntity { public abstract void validate(); }", "BaseEntity"),
        "inner_class": ("public class Outer { public class Inner { private int value; } }", "Outer"),
        "method_public": ("public class Calc { public int add(int a, int b) { return a + b; } }", "add"),
        "method_private": ("public class Svc { private void helper() { } }", "helper"),
        "method_static": ("public class Utils { public static String format(String s) { return s; } }", "format"),
        "constructor": ("public class Person { public Person(String name) { } }", "Person", "Person"),
        "overloaded": ("public class P { public void print(String s) {} public void print(int i) {} }", "print", 2),
        "import_single": ("import java.util.List;", 1),
        "import_wildcard": ("import java.util.*;", 1),
        "import_multiple": ("import java.util.List;\nimport java.util.Map;\nimport java.io.IOException;", 3),
        "annotated_class": ('@Entity\n@Table(name = "users")\npublic class User { }', "User"),
        "record": ("public record User(String name, int age) { }", "User"),
    },
    "javascript": {
        "class": ("class UserService { constructor() { this.users = []; } }", "UserService", "class"),
        "class_inheritance": ("class Admin extends User { constructor() { super(); } }", "Admin"),
        "function": ("function processData(data) { return data; }", "processData", "function"),
        "async_function": ("async function fetchUser(id) { return await fetch(id); }", "fetchUser", True),
        "arrow_function": ("const multiply = (x, y) => { return x * y; };", "multiply", "function"),
        "async_arrow": ("const fetchData = async (url) => { return await fetch(url); };", "fetchData", True),
        "exported_class": ("export class Service { run() { return true; } }", "Service"),
        "method_class": ("class Calc { add(a, b) { return a + b; } subtract(a, b) { return a - b; } }", ["add", "subtract"]),
        "constructor": ("class Service { constructor(config) { this.config = config; } }", "constructor"),
        "async_method": ("class Api { async get(url) { return await fetch(url); } }", "get", True),
        "static_method": ("class MathUtils { static square(x) { return x * x; } }", "square"),
        "import_default": ("import React from 'react';", "react"),
        "import_named": ("import { useState, useEffect } from 'react';", 1),
        "import_namespace": ("import * as utils from './utils';", 1),
        "import_require": ("const express = require('express');", "express"),
        "jsx_function": ("function Component() { return <div>Hello</div>; }", "Component", "function"),
        "private_fields": ("class Counter { #count = 0; increment() { this.#count++; } }", "increment", "Counter"),
    },
    "csharp": {
        "class": ("public class UserService { private string _name; }", "UserService", "class"),
        "class_inheritance": ("public class Admin : User { public int Level { get; set; } }", "Admin"),
        "interface": ("public interface IRepository<T> { T GetById(int id); }", "IRepository", "interface"),
        "struct": ("public struct Point { public int X; public int Y; }", "Point"),
        "enum": ("public enum Status { Pending, Active, Completed }", "Status"),
        "abstract_class": ("public abstract class BaseEntity { public abstract void Validate(); }", "BaseEntity"),
        "record": ("public record User(string Name, int Age);", "User"),
        "method_public": ("public class Calc { public int Add(int a, int b) { return a + b; } }", "Add"),
        "method_private": ("public class Svc { private void Helper() { } }", "Helper"),
        "method_static": ("public class Utils { public static string Format(string s) { return s; } }", "Format"),
        "method_async": ("public class Api { public async Task<User> GetUserAsync(int id) { return null; } }", "GetUserAsync"),
        "constructor": ("public class Person { public Person(string name) { } public string Name { get; } }", "Person", "Person"),
        "import_using": ("using System;", 1),
        "import_multiple": ("using System;\nusing System.Collections.Generic;\nusing System.Linq;", 3),
        "import_alias": ("using Console = System.Console;", 1),
        "namespace_class": ("namespace MyApp.Services { public class UserService { } }", "UserService"),
        "file_scoped_ns": ("namespace MyApp.Services;\npublic class UserService { }", "UserService"),
        "attributes": ('[Serializable]\n[Table("users")]\npublic class User { }', "User"),
        "partial_class": ("public partial class User { public string Name { get; set; } }", "User"),
    },
    "python": {
        "class": ("class User: pass", "User", "class"),
        "class_inheritance": ("class Admin(User, PermissionMixin): pass", "Admin", {"User", "PermissionMixin"}),
        "class_docstring": ('class Service:\n    """A service class."""\n    pass', "Service", "service"),
        "decorated_class": ("@dataclass\nclass Config:\n    name: str", "Config"),
        "function": ("def process_data(items): return items", "process_data", "function"),
        "async_function": ("async def fetch_user(user_id): pass", "fetch_user", True),
        "type_alias": ("type UserId = int\ntype Callback = Callable[[int], str]", 2),
        "multiple_classes": ("class First: pass\nclass Second: pass\nclass Third: pass", {"First", "Second", "Third"}),
        "method_class": ("class Calc:\n    def add(self, a, b): return a + b\n    def sub(self, a, b): return a - b", ["add", "sub"], "Calc"),
        "standalone_fn": ("def helper_function(x): return x * 2", "helper_function", None),
        "async_method": ("class Svc:\n    async def fetch(self, url): return url", "fetch", True),
        "staticmethod": ("class Utils:\n    @staticmethod\n    def format_date(date): return date", "format_date", "static"),
        "classmethod": ("class Factory:\n    @classmethod\n    def create(cls): return cls()", "create", "classmethod"),
        "property": ("class Person:\n    @property\n    def full_name(self): return self.name", "full_name", "property"),
        "import_simple": ("import os", "os", False),
        "import_alias": ("import numpy as np", "numpy", "np"),
        "import_from": ("from pathlib import Path", "pathlib", ["Path"]),
        "import_multiple": ("import os\nimport sys\nimport json\nfrom pathlib import Path\nfrom typing import Any", 5),
        "nested_class": ("class Outer:\n    class Inner:\n        def method(self): pass", "Outer"),
        "unicode": ("class Données:\n    def traiter(self): pass", "Données"),
    },
}


# =============================================================================
# TYPE EXTRACTION TESTS
# =============================================================================


class TestTypeExtraction:
    """Tests for type extraction across all languages."""

    @pytest.mark.parametrize("language", ["java", "javascript", "csharp", "python"])
    def test_extracts_class(self, manager, language):
        """Should extract basic class definition."""
        source, name, kind = SAMPLES[language]["class"]
        types = manager.extract_types(source, language=language)

        assert len(types) >= 1
        target = next((t for t in types if t.name == name), None)
        assert target is not None, f"Expected to find {name} in {[t.name for t in types]}"
        assert target.kind == kind

    @pytest.mark.parametrize("language", ["java", "javascript", "csharp", "python"])
    def test_extracts_class_with_inheritance(self, manager, language):
        """Should extract class with inheritance/extends."""
        sample = SAMPLES[language].get("class_inheritance")
        if not sample:
            pytest.skip(f"No inheritance sample for {language}")
        assert sample is not None  # For type checker after pytest.skip

        source, name = sample[0], sample[1]
        types = manager.extract_types(source, language=language)

        target = next((t for t in types if t.name == name), None)
        assert target is not None, f"Expected to find {name}"
        # Python has bases attribute to check
        if language == "python" and len(sample) > 2:
            assert set(target.bases) == sample[2]

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("java", "interface"),
            ("csharp", "interface"),
        ],
    )
    def test_extracts_interface(self, manager, language, sample_key):
        """Should extract interface definition."""
        source, name, kind = SAMPLES[language][sample_key]
        types = manager.extract_types(source, language=language)

        target = next((t for t in types if t.name == name), None)
        assert target is not None
        assert target.kind == kind

    @pytest.mark.parametrize("language", ["java", "csharp"])
    def test_extracts_enum(self, manager, language):
        """Should extract enum definition."""
        source, name = SAMPLES[language]["enum"][:2]
        types = manager.extract_types(source, language=language)

        assert [(t.name, t.kind, t.visibility) for t in types] == [(name, "enum", "public")]

    @pytest.mark.parametrize("language", ["java", "csharp"])
    def test_extracts_abstract_class(self, manager, language):
        """Should extract abstract class."""
        source, name = SAMPLES[language]["abstract_class"][:2]
        types = manager.extract_types(source, language=language)

        assert [(t.name, t.kind) for t in types] == [(name, "class")]

    @pytest.mark.parametrize("language", ["java", "csharp"])
    def test_extracts_record(self, manager, language):
        """Should extract record type."""
        source, name = SAMPLES[language]["record"][:2]
        types = manager.extract_types(source, language=language)

        assert [(t.name, t.kind) for t in types] == [(name, "record")]

    def test_csharp_extracts_struct(self, manager):
        """Should extract C# struct."""
        source, name = SAMPLES["csharp"]["struct"][:2]
        types = manager.extract_types(source, language="csharp")

        assert [(t.name, t.kind) for t in types] == [(name, "struct")]

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("javascript", "function"),
            ("javascript", "async_function"),
            ("javascript", "arrow_function"),
            ("python", "function"),
            ("python", "async_function"),
        ],
    )
    def test_extracts_function_as_type(self, manager, language, sample_key):
        """Should extract top-level functions as types."""
        sample = SAMPLES[language][sample_key]
        source, name = sample[0], sample[1]
        types = manager.extract_types(source, language=language)

        target = next((t for t in types if t.name == name), None)
        assert target is not None
        # Check async flag if provided
        if len(sample) > 2 and sample[2] is True:
            assert target.is_async is True

    def test_python_extracts_type_alias(self, manager):
        """Should extract Python type aliases."""
        source, count = SAMPLES["python"]["type_alias"][:2]
        types = manager.extract_types(source, language="python")
        aliases = [t for t in types if t.kind == "type_alias"]

        assert len(aliases) == count

    def test_python_extracts_multiple_classes(self, manager):
        """Should extract multiple class definitions."""
        source, expected_names = SAMPLES["python"]["multiple_classes"][:2]
        types = manager.extract_types(source, language="python")

        assert {t.name for t in types} == expected_names


# =============================================================================
# METHOD EXTRACTION TESTS
# =============================================================================


class TestMethodExtraction:
    """Tests for method extraction across all languages."""

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("java", "method_public"),
            ("javascript", "method_class"),
            ("csharp", "method_public"),
            ("python", "method_class"),
        ],
    )
    def test_extracts_class_methods(self, manager, language, sample_key):
        """Should extract methods from a class."""
        sample = SAMPLES[language][sample_key]
        source = sample[0]
        expected = sample[1]  # Either a name or list of names
        methods = manager.extract_methods(source, language=language)

        if isinstance(expected, list):
            names = {m.name for m in methods}
            assert all(e in names for e in expected), f"Expected {expected} in {names}"
        else:
            target = next((m for m in methods if m.name == expected), None)
            assert target is not None

    @pytest.mark.parametrize("language", ["java", "csharp"])
    def test_extracts_private_method(self, manager, language):
        """Should extract private methods."""
        source, name = SAMPLES[language]["method_private"][:2]
        methods = manager.extract_methods(source, language=language)

        assert [(m.name, m.class_name, m.visibility) for m in methods] == [(name, "Svc", "private")]

    @pytest.mark.parametrize("language", ["java", "javascript", "csharp"])
    def test_extracts_static_method(self, manager, language):
        """Should extract static methods."""
        sample_key = "method_static" if language != "javascript" else "static_method"
        source, name = SAMPLES[language][sample_key][:2]
        methods = manager.extract_methods(source, language=language)

        assert [(m.name, m.is_static, m.is_classmethod) for m in methods] == [(name, True, False)]

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("java", "constructor"),
            ("javascript", "constructor"),
            ("csharp", "constructor"),
        ],
    )
    def test_extracts_constructor(self, manager, language, sample_key):
        """Should extract constructor."""
        sample = SAMPLES[language][sample_key]
        source, name = sample[0], sample[1]
        methods = manager.extract_methods(source, language=language)

        target = next((m for m in methods if m.name == name), None)
        assert target is not None
        # Check class_name if provided
        if len(sample) > 2:
            assert target.class_name == sample[2]

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("javascript", "async_method"),
            ("csharp", "method_async"),
            ("python", "async_method"),
        ],
    )
    def test_extracts_async_method(self, manager, language, sample_key):
        """Should detect async methods."""
        sample = SAMPLES[language][sample_key]
        source, name = sample[0], sample[1]
        methods = manager.extract_methods(source, language=language)

        target = next((m for m in methods if m.name == name), None)
        assert target is not None
        if language == "python" or language == "javascript":
            assert target.is_async is True

    def test_java_extracts_overloaded_methods(self, manager):
        """Should extract overloaded methods in Java."""
        source, name, count = SAMPLES["java"]["overloaded"]
        methods = manager.extract_methods(source, language="java")

        matching = [m for m in methods if m.name == name]
        assert len(matching) == count

    def test_python_extracts_standalone_function(self, manager):
        """Should extract standalone function with no class."""
        source, name, class_name = SAMPLES["python"]["standalone_fn"]
        methods = manager.extract_methods(source, language="python")

        target = next((m for m in methods if m.name == name), None)
        assert target is not None
        assert target.class_name is class_name

    @pytest.mark.parametrize(
        "sample_key,expected_attr",
        [
            ("staticmethod", "is_static"),
            ("classmethod", "is_classmethod"),
            ("property", "is_property"),
        ],
    )
    def test_python_extracts_decorated_methods(self, manager, sample_key, expected_attr):
        """Should detect Python method decorators."""
        source, name = SAMPLES["python"][sample_key][:2]
        methods = manager.extract_methods(source, language="python")

        target = next((m for m in methods if m.name == name), None)
        assert target is not None
        assert getattr(target, expected_attr) is True


# =============================================================================
# IMPORT EXTRACTION TESTS
# =============================================================================


class TestImportExtraction:
    """Tests for import extraction across all languages."""

    @pytest.mark.parametrize(
        "language,sample_key,expected_count",
        [
            ("java", "import_single", 1),
            ("java", "import_wildcard", 1),
            ("java", "import_multiple", 3),
            ("javascript", "import_named", 1),
            ("javascript", "import_namespace", 1),
            ("csharp", "import_using", 1),
            ("csharp", "import_multiple", 3),
            ("csharp", "import_alias", 1),
            ("python", "import_multiple", 5),
        ],
    )
    def test_extracts_imports_count(self, manager, language, sample_key, expected_count):
        """Should extract correct number of imports."""
        source = SAMPLES[language][sample_key][0]
        imports = manager.extract_imports(source, language=language)

        assert len(imports) >= expected_count

    def test_python_extracts_simple_import(self, manager):
        """Should extract simple Python import."""
        source, module, is_from = SAMPLES["python"]["import_simple"]
        imports = manager.extract_imports(source, language="python")

        assert len(imports) == 1
        assert imports[0].module == module
        assert imports[0].is_from_import is is_from

    def test_python_extracts_import_with_alias(self, manager):
        """Should extract Python import with alias."""
        source, module, alias = SAMPLES["python"]["import_alias"]
        imports = manager.extract_imports(source, language="python")

        assert imports[0].module == module
        assert imports[0].alias == alias

    def test_python_extracts_from_import(self, manager):
        """Should extract Python from-import."""
        source, module, names = SAMPLES["python"]["import_from"]
        imports = manager.extract_imports(source, language="python")

        assert imports[0].module == module
        assert all(n in imports[0].names for n in names)
        assert imports[0].is_from_import is True

    def test_javascript_extracts_default_import(self, manager):
        """Should extract JavaScript default import."""
        source, module = SAMPLES["javascript"]["import_default"][:2]
        imports = manager.extract_imports(source, language="javascript")

        assert len(imports) >= 1
        assert any(module in i.module for i in imports)

    def test_javascript_extracts_require(self, manager):
        """Should extract CommonJS require statements."""
        source, module = SAMPLES["javascript"]["import_require"][:2]
        imports = manager.extract_imports(source, language="javascript")

        modules = [i.module for i in imports]
        assert any(module in m for m in modules)

    def test_python_extracts_imports_inside_functions_and_blocks(self, manager):
        """Imports in functions, methods and if/try blocks are dependencies too (lazy and optional imports)."""
        source = """import os

if TYPE_CHECKING:
    from pkg.types import Thing

try:
    import fast_json as json
except ImportError:
    import json


def run():
    from pkg.services import worker
    import pkg.tools


class Runner:
    def go(self):
        from .local import helper
"""
        imports = manager.extract_imports(source, language="python")

        assert sorted(i.module for i in imports) == [".local", "fast_json", "json", "os", "pkg.services", "pkg.tools", "pkg.types"]
        worker = next(i for i in imports if i.module == "pkg.services")
        assert worker.names == ["worker"] and worker.is_from_import and worker.line == 13

    def test_javascript_extracts_require_and_dynamic_import_inside_functions_and_blocks(self, manager):
        """A require() anywhere, bare or assigned, and a dynamic import() are dependencies too."""
        source = """const a = require('./a');

function load() {
  const b = require('./b');
  require('./c');
  return import('./d');
}

if (ready) {
  const { e } = require('./e');
}
"""
        imports = manager.extract_imports(source, language="javascript")

        assert sorted(i.module for i in imports) == ["./a", "./b", "./c", "./d", "./e"]
        assert next(i for i in imports if i.module == "./e").names == ["e"]
        assert next(i for i in imports if i.module == "./c").line == 5

    def test_javascript_an_awaited_dynamic_import_keeps_its_binding_name(self, manager):
        source = """async function load() {
  const mod = await import('./mod');
}
"""
        (imp,) = manager.extract_imports(source, language="javascript")

        assert imp.module == "./mod" and imp.names == ["mod"]


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases across all languages."""

    @pytest.mark.parametrize("language", ["java", "javascript", "csharp", "python"])
    def test_handles_empty_file(self, manager, language):
        """Should handle empty file without error."""
        types = manager.extract_types("", language=language)
        assert types == []

        methods = manager.extract_methods("", language=language)
        assert methods == []

        imports = manager.extract_imports("", language=language)
        assert imports == []

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("java", "annotated_class"),
            ("csharp", "attributes"),
            ("python", "decorated_class"),
        ],
    )
    def test_handles_decorated_annotated_classes(self, manager, language, sample_key):
        """Should handle classes with decorators/annotations/attributes."""
        source, name = SAMPLES[language][sample_key][:2]
        types = manager.extract_types(source, language=language)

        assert [(t.name, t.kind) for t in types] == [(name, "class")]
        # The decorators, annotations or attributes are kept
        assert types[0].decorators

    @pytest.mark.parametrize(
        "language,sample_key",
        [
            ("csharp", "namespace_class"),
            ("csharp", "file_scoped_ns"),
        ],
    )
    def test_handles_namespaces(self, manager, language, sample_key):
        """Should handle namespace declarations."""
        source, name = SAMPLES[language][sample_key][:2]
        types = manager.extract_types(source, language=language)

        assert [(t.name, t.kind) for t in types] == [(name, "class")]

    def test_java_handles_inner_class(self, manager):
        """Should handle Java inner classes."""
        source, name = SAMPLES["java"]["inner_class"][:2]
        types = manager.extract_types(source, language="java")

        # The outer class and the one inside it
        assert [(t.name, t.kind) for t in types] == [(name, "class"), ("Inner", "class")]

    def test_javascript_handles_jsx(self, manager):
        """Should handle JSX syntax."""
        source, name, kind = SAMPLES["javascript"]["jsx_function"]
        types = manager.extract_types(source, language="javascript")

        target = next((t for t in types if t.name == name), None)
        assert target is not None
        assert target.kind == kind

    def test_javascript_handles_private_fields(self, manager):
        """Should handle private class fields."""
        source, name, class_name = SAMPLES["javascript"]["private_fields"]
        methods = manager.extract_methods(source, language="javascript")

        target = next((m for m in methods if m.name == name), None)
        assert target is not None
        assert target.class_name == class_name

    def test_csharp_handles_partial_class(self, manager):
        """Should handle partial classes."""
        source, name = SAMPLES["csharp"]["partial_class"][:2]
        types = manager.extract_types(source, language="csharp")

        assert [(t.name, t.kind) for t in types] == [(name, "class")]

    def test_python_handles_nested_class(self, manager):
        """Should handle nested class definitions."""
        source, name = SAMPLES["python"]["nested_class"][:2]
        types = manager.extract_types(source, language="python")

        assert name in {t.name for t in types}

    def test_python_handles_unicode_identifiers(self, manager):
        """Should handle unicode in identifiers."""
        source, name = SAMPLES["python"]["unicode"][:2]
        types = manager.extract_types(source, language="python")

        assert [(t.name, t.kind) for t in types] == [(name, "class")]

    def test_python_handles_syntax_errors(self, manager):
        """Should handle syntax errors gracefully."""
        source = "class Incomplete {\n    def broken"
        types = manager.extract_types(source, language="python")
        # The class header does not parse: nothing is extracted, and nothing is raised
        assert types == []

    def test_python_handles_comments_only(self, manager):
        """Should handle file with only comments."""
        types = manager.extract_types("# Comment\n# Another", language="python")
        assert types == []


# =============================================================================
# CALL EXTRACTION TESTS
# =============================================================================


class TestCallExtraction:
    """Tests for function call extraction."""

    def test_python_extracts_simple_function_call(self, manager):
        """Should extract simple function calls."""
        source = "def caller():\n    target()"
        calls = manager.extract_calls(source, language="python")

        assert len(calls) >= 1
        call = next((c for c in calls if c.callee_name == "target"), None)
        assert call is not None
        assert call.caller_name == "caller"

    def test_python_extracts_method_call(self, manager):
        """Should extract method calls on objects."""
        source = "def caller():\n    obj.method()"
        calls = manager.extract_calls(source, language="python")

        call = next((c for c in calls if c.callee_name == "method"), None)
        assert call is not None
        assert call.callee_qualifier == "obj"
        assert call.is_method_call is True

    def test_python_extracts_chained_calls(self, manager):
        """Should extract calls from method chains."""
        source = "def caller():\n    a.first().second()"
        calls = manager.extract_calls(source, language="python")

        # Both calls of the chain, the outer one qualified by the inner
        assert [(c.callee_name, c.callee_qualifier, c.is_method_call) for c in calls] == [("second", "a.first()", True), ("first", "a", True)]

    def test_python_extracts_calls_from_class_methods(self, manager):
        """Should extract calls from class methods."""
        source = """class MyClass:
    def my_method(self):
        helper()
        self.other_method()
"""
        calls = manager.extract_calls(source, language="python")

        # Should have both helper() and other_method() calls
        helper_call = next((c for c in calls if c.callee_name == "helper"), None)
        method_call = next((c for c in calls if c.callee_name == "other_method"), None)

        assert helper_call is not None
        assert helper_call.caller_class == "MyClass"
        assert method_call is not None

    def test_python_extracts_calls_from_decorated_methods(self, manager):
        """Should extract calls from decorated methods."""
        source = """class MyClass:
    @staticmethod
    def static_method():
        helper()
"""
        calls = manager.extract_calls(source, language="python")

        assert [(c.caller_name, c.caller_class, c.callee_name) for c in calls] == [("static_method", "MyClass", "helper")]

    def test_python_extracts_calls_from_top_level_decorated_functions(self, manager):
        """Should extract calls from decorated top-level functions."""
        source = """@decorator
def my_func():
    target()
"""
        calls = manager.extract_calls(source, language="python")

        target_call = next((c for c in calls if c.callee_name == "target"), None)
        assert target_call is not None
        assert target_call.caller_class is None

    def test_python_skips_complex_call_expressions(self, manager):
        """Should handle complex call expressions gracefully."""
        source = "def caller():\n    funcs[0]()"  # Subscript call
        calls = manager.extract_calls(source, language="python")

        # A call through a subscript has no name to resolve: it is left out, without an error
        assert calls == []

    def test_javascript_extracts_calls(self, manager):
        """Should extract calls from JavaScript."""
        source = """function caller() {
    target();
    obj.method();
}"""
        calls = manager.extract_calls(source, language="javascript")

        assert [(c.caller_name, c.callee_name, c.callee_qualifier, c.is_method_call) for c in calls] == [("caller", "target", None, False), ("caller", "method", "obj", True)]


# =============================================================================
# PYTHON-SPECIFIC EXTRACTION TESTS
# =============================================================================


class TestPythonSpecificExtraction:
    """Additional tests for Python-specific extraction features."""

    def test_extracts_type_alias_simple(self, manager):
        """Should extract simple type aliases."""
        # Use simpler type alias that tree-sitter can parse
        source = "type UserId = int"
        types = manager.extract_types(source, language="python")

        assert [(t.name, t.kind) for t in types] == [("UserId", "type_alias")]

    def test_extracts_decorated_function_as_type(self, manager):
        """Should extract decorated top-level functions as types."""
        source = """@app.route("/api")
def api_endpoint():
    return {}
"""
        types = manager.extract_types(source, language="python")

        func = next((t for t in types if t.name == "api_endpoint"), None)
        assert func is not None
        assert "app.route" in func.decorators or "route" in str(func.decorators)

    def test_extracts_async_decorated_function(self, manager):
        """Should extract async decorated functions."""
        source = """@asynccontextmanager
async def async_resource():
    yield "resource"
"""
        types = manager.extract_types(source, language="python")

        func = next((t for t in types if t.name == "async_resource"), None)
        assert func is not None
        assert func.is_async is True

    def test_extracts_method_with_complex_decorators(self, manager):
        """Should extract methods with complex decorator expressions."""
        source = """class MyClass:
    @decorator_factory(arg1="value")
    def decorated_method(self):
        pass
"""
        methods = manager.extract_methods(source, language="python")

        assert [(m.name, m.class_name, m.decorators) for m in methods] == [("decorated_method", "MyClass", ['decorator_factory(arg1="value")'])]

    def test_extracts_dunder_methods(self, manager):
        """Should extract dunder methods."""
        source = """class MyClass:
    def __init__(self):
        pass

    def __str__(self):
        return ""
"""
        methods = manager.extract_methods(source, language="python")

        assert [(m.name, m.class_name) for m in methods] == [("__init__", "MyClass"), ("__str__", "MyClass")]

    def test_extracts_multiple_inheritance(self, manager):
        """Should extract class with multiple bases."""
        source = "class Child(Parent1, Parent2, Mixin): pass"
        types = manager.extract_types(source, language="python")

        child = next((t for t in types if t.name == "Child"), None)
        assert child is not None
        assert set(child.bases) == {"Parent1", "Parent2", "Mixin"}

    def test_extracts_from_import_with_multiple_names(self, manager):
        """Should extract from import with multiple names."""
        source = "from typing import List, Dict, Optional, Union"
        imports = manager.extract_imports(source, language="python")

        assert len(imports) == 1
        imp = imports[0]
        assert imp.module == "typing"
        assert "List" in imp.names
        assert "Dict" in imp.names
        assert "Optional" in imp.names
        assert "Union" in imp.names

    def test_extracts_wildcard_import(self, manager):
        """Should extract wildcard import."""
        source = "from module import *"
        imports = manager.extract_imports(source, language="python")

        assert len(imports) == 1
        imp = imports[0]
        assert imp.module == "module"
        assert "*" in imp.names

    def test_extracts_relative_import(self, manager):
        """Should extract relative imports."""
        source = "from . import sibling\nfrom ..parent import something\nfrom .pkg import mod"
        imports = manager.extract_imports(source, language="python")

        assert [(i.module, i.names) for i in imports] == [(".", ["sibling"]), ("..parent", ["something"]), (".pkg", ["mod"])]

    def test_an_aliased_from_import_keeps_the_imported_name(self, manager):
        """``from x import y as z`` imports y (a module or a member of x)."""
        imports = manager.extract_imports("from app import services as svc\nfrom . import routes as r, views", language="python")

        assert [(i.module, i.names) for i in imports] == [("app", ["services"]), (".", ["routes", "views"])]

    def test_handles_empty_class_body(self, manager):
        """Should handle class with pass statement only."""
        source = "class Empty: pass"
        types = manager.extract_types(source, language="python")

        assert [(t.name, t.kind) for t in types] == [("Empty", "class")]

    def test_handles_ellipsis_body(self, manager):
        """Should handle class/function with ellipsis body."""
        source = """class Protocol:
    def method(self): ...
"""
        methods = manager.extract_methods(source, language="python")

        assert [(m.name, m.class_name) for m in methods] == [("method", "Protocol")]


# =============================================================================
# JAVASCRIPT-SPECIFIC EXTRACTION TESTS
# =============================================================================


class TestJavaScriptSpecificExtraction:
    """Additional tests for JavaScript-specific extraction features."""

    def test_extracts_arrow_function_expression(self, manager):
        """Should extract arrow functions assigned to variables."""
        source = "const add = (a, b) => a + b;"
        types = manager.extract_types(source, language="javascript")

        assert [(t.name, t.kind, t.is_async) for t in types] == [("add", "function", False)]

    def test_extracts_async_arrow_function(self, manager):
        """Should extract async arrow functions."""
        source = "const fetchData = async (url) => await fetch(url);"
        types = manager.extract_types(source, language="javascript")

        func = next((t for t in types if t.name == "fetchData"), None)
        assert func is not None
        assert func.is_async is True

    def test_extracts_getter_setter_methods(self, manager):
        """Should extract getter and setter methods."""
        source = """class Person {
    get name() { return this._name; }
    set name(value) { this._name = value; }
}"""
        methods = manager.extract_methods(source, language="javascript")

        # Both accessors, as properties of the class; the setter takes the value
        assert [(m.name, m.class_name, m.is_property, [p["name"] for p in m.parameters]) for m in methods] == [
            ("name", "Person", True, []),
            ("name", "Person", True, ["value"]),
        ]

    def test_extracts_export_default_class(self, manager):
        """Should extract export default class."""
        source = "export default class Service { run() {} }"
        types = manager.extract_types(source, language="javascript")

        assert [(t.name, t.kind) for t in types] == [("Service", "class")]

    def test_extracts_commonjs_module(self, manager):
        """Should extract CommonJS module.exports class."""
        source = """class Helper {}
module.exports = Helper;"""
        types = manager.extract_types(source, language="javascript")

        assert [(t.name, t.kind) for t in types] == [("Helper", "class")]


# =============================================================================
# JAVA-SPECIFIC EXTRACTION TESTS
# =============================================================================


class TestJavaSpecificExtraction:
    """Additional tests for Java-specific extraction features."""

    def test_extracts_generic_class(self, manager):
        """Should extract generic class."""
        source = "public class Container<T> { private T value; }"
        types = manager.extract_types(source, language="java")

        # The name without its type parameters
        assert [(t.name, t.kind) for t in types] == [("Container", "class")]

    def test_extracts_generic_interface(self, manager):
        """Should extract generic interface."""
        source = "public interface Mapper<S, T> { T map(S source); }"
        types = manager.extract_types(source, language="java")

        mapper = next((t for t in types if t.name == "Mapper"), None)
        assert mapper is not None
        assert mapper.kind == "interface"

    def test_extracts_annotated_method(self, manager):
        """Should extract annotated methods."""
        source = """public class Api {
    @GetMapping("/users")
    public List<User> getUsers() { return null; }
}"""
        methods = manager.extract_methods(source, language="java")

        assert [(m.name, m.class_name, m.return_annotation, m.decorators) for m in methods] == [("getUsers", "Api", "List<User>", ['GetMapping("/users")'])]

    def test_extracts_static_import(self, manager):
        """Should extract static imports."""
        source = "import static java.lang.Math.PI;"
        imports = manager.extract_imports(source, language="java")

        assert [(i.module, i.names, i.is_from_import) for i in imports] == [("java.lang.Math", ["PI"], True)]


# =============================================================================
# CSHARP-SPECIFIC EXTRACTION TESTS
# =============================================================================


class TestCSharpSpecificExtraction:
    """Additional tests for C#-specific extraction features."""

    def test_extracts_generic_class(self, manager):
        """Should extract generic class."""
        source = "public class Repository<T> where T : class { }"
        types = manager.extract_types(source, language="csharp")

        assert [(t.name, t.kind) for t in types] == [("Repository", "class")]

    def test_extracts_extension_method(self, manager):
        """Should extract extension methods."""
        source = """public static class StringExtensions {
    public static string Reverse(this string s) { return null; }
}"""
        methods = manager.extract_methods(source, language="csharp")

        assert [(m.name, m.class_name, m.is_static, [p["name"] for p in m.parameters]) for m in methods] == [("Reverse", "StringExtensions", True, ["s"])]

    def test_extracts_async_method_with_task(self, manager):
        """Should extract async methods returning Task."""
        source = """public class Service {
    public async Task<User> GetUserAsync(int id) { return null; }
}"""
        methods = manager.extract_methods(source, language="csharp")

        assert [(m.name, m.is_async, [(p["name"], p["annotation"]) for p in m.parameters]) for m in methods] == [("GetUserAsync", True, [("id", "int")])]

    def test_extracts_global_using(self, manager):
        """Should extract global using directives."""
        source = "global using System;\nglobal using System.Linq;"
        imports = manager.extract_imports(source, language="csharp")

        assert [(i.module, i.names) for i in imports] == [("System", []), ("System.Linq", [])]


# =============================================================================
# PARSER FIXES: results the parsers once got wrong
# =============================================================================


class TestParserFixes:
    """Decorators of a Python class, a type alias name, one type per exported JavaScript class, and C# return types."""

    def test_a_decorated_python_class_keeps_its_decorator(self, manager):
        source, name = SAMPLES["python"]["decorated_class"][:2]

        assert [(t.name, t.decorators) for t in manager.extract_types(source, language="python")] == [(name, ["dataclass"])]

    def test_a_python_type_alias_is_named(self, manager):
        types = manager.extract_types("type UserId = int\ntype Callback = Callable[[int], str]", language="python")

        assert [(t.name, t.kind) for t in types] == [("UserId", "type_alias"), ("Callback", "type_alias")]

    def test_an_exported_default_class_is_one_type(self, manager):
        types = manager.extract_types("export default class Service { run() {} }", language="javascript")

        assert [(t.name, t.kind) for t in types] == [("Service", "class")]

    def test_a_commonjs_export_adds_no_type(self, manager):
        types = manager.extract_types("class Helper {}\nmodule.exports = Helper;", language="javascript")

        assert [(t.name, t.kind) for t in types] == [("Helper", "class")]

    def test_a_csharp_method_keeps_its_return_type(self, manager):
        methods = manager.extract_methods("public class Service {\n    public async Task<User> GetUserAsync(int id) { return null; }\n}", language="csharp")

        assert [(m.name, m.return_annotation) for m in methods] == [("GetUserAsync", "Task<User>")]


class TestSqlDdl:
    """CREATE TABLE statements are table types, parsed without an LLM."""

    def test_tables_with_schema_quotes_and_if_not_exists(self, manager):
        source = """-- schema
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER
);

create table "Shop"."Customer" (id int);
CREATE TABLE SHOP.TRANSACTION_TYPE
  (TR_TYPE CHAR(2) NOT NULL);
CREATE INDEX idx_x ON order_items (order_id);
"""
        types = manager.extract_types(source, language="sql")

        assert [(t.name, t.kind, t.line_start) for t in types] == [("order_items", "table", 2), ("Customer", "table", 7), ("TRANSACTION_TYPE", "table", 8)]
        assert types[2].decorators == ["schema:SHOP"]

    def test_ddl_files_are_sql(self, manager):
        assert manager.extract_types("CREATE TABLE T1 (a int);", file_path="db/T1.ddl")[0].name == "T1"

    def test_a_quoted_name_is_one_identifier_even_with_spaces_and_dots(self, manager):
        types = manager.extract_types('CREATE TABLE [dbo].[my table] (a int);\nCREATE TABLE "app"."order.lines" (a int);', language="sql")

        assert [(t.name, t.decorators) for t in types] == [("my table", ["schema:dbo"]), ("order.lines", ["schema:app"])]

    def test_create_table_in_comments_and_literals_is_no_table(self, manager):
        source = """-- CREATE TABLE old_orders (id int);
/* CREATE TABLE draft (id int); */
INSERT INTO notes VALUES ('CREATE TABLE fake (x int)');
CREATE TABLE real_one (id int);
"""
        assert [t.name for t in manager.extract_types(source, language="sql")] == ["real_one"]

    def test_a_table_ends_at_its_own_terminator(self, manager):
        source = """CREATE TABLE settings (
    sep CHAR(1) DEFAULT ';',
    name TEXT
);
CREATE TABLE plain (
    id INT
)
"""
        settings, plain = manager.extract_types(source, language="sql")

        assert (settings.line_start, settings.line_end) == (1, 4)
        assert (plain.line_start, plain.line_end) == (5, 7)
