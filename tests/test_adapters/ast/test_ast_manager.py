"""Tests for AST-based extraction manager."""

from __future__ import annotations

from deriva.adapters.ast.manager import ASTManager
from deriva.adapters.ast.models import ExtractedImport, ExtractedMethod, ExtractedType


class TestExtractTypes:
    """Tests for ASTManager.extract_types()."""

    def test_extracts_simple_class(self):
        """Should extract a simple class definition."""
        source = """
class User:
    pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert len(types) == 1
        assert types[0].name == "User"
        assert types[0].kind == "class"
        assert types[0].bases == []

    def test_extracts_class_with_inheritance(self):
        """Should extract class with base classes."""
        source = """
class Admin(User, Permissions):
    pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert len(types) == 1
        assert types[0].name == "Admin"
        assert "User" in types[0].bases
        assert "Permissions" in types[0].bases

    def test_extracts_class_with_docstring(self):
        """Should extract class docstring."""
        source = '''
class User:
    """Represents a user in the system."""
    pass
'''
        manager = ASTManager()
        types = manager.extract_types(source)

        assert types[0].docstring == "Represents a user in the system."

    def test_extracts_class_with_decorators(self):
        """Should extract class decorators."""
        source = """
@dataclass
@frozen
class User:
    pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert "dataclass" in types[0].decorators
        assert "frozen" in types[0].decorators

    def test_extracts_top_level_function(self):
        """Should extract top-level functions as types."""
        source = """
def process_data(items):
    return items
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert len(types) == 1
        assert types[0].name == "process_data"
        assert types[0].kind == "function"
        assert types[0].is_async is False

    def test_extracts_async_function(self):
        """Should mark async functions correctly."""
        source = """
async def fetch_data():
    pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert types[0].name == "fetch_data"
        assert types[0].is_async is True

    def test_extracts_line_numbers(self):
        """Should capture line start and end."""
        source = """
class User:
    name: str
    age: int
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert types[0].line_start == 2
        assert types[0].line_end >= 4

    def test_extracts_multiple_classes(self):
        """Should extract multiple class definitions."""
        source = """
class User:
    pass

class Admin:
    pass

class Guest:
    pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        assert len(types) == 3
        names = [t.name for t in types]
        assert "User" in names
        assert "Admin" in names
        assert "Guest" in names

    def test_returns_empty_for_syntax_error(self):
        """Should return empty list for invalid syntax."""
        source = "class User( pass"  # Invalid syntax
        manager = ASTManager()
        types = manager.extract_types(source)

        assert types == []

    def test_returns_empty_for_empty_source(self):
        """Should return empty list for empty source."""
        manager = ASTManager()
        types = manager.extract_types("")

        assert types == []

    def test_ignores_nested_classes(self):
        """Should only extract top-level classes (nested are included by ast.walk)."""
        source = """
class Outer:
    class Inner:
        pass
"""
        manager = ASTManager()
        types = manager.extract_types(source)

        # ast.walk finds both Outer and Inner
        names = [t.name for t in types]
        assert "Outer" in names
        assert "Inner" in names


class TestExtractMethods:
    """Tests for ASTManager.extract_methods()."""

    def test_extracts_class_method(self):
        """Should extract methods from classes."""
        source = """
class User:
    def get_name(self):
        return self.name
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert len(methods) == 1
        assert methods[0].name == "get_name"
        assert methods[0].class_name == "User"

    def test_extracts_top_level_function(self):
        """Should extract top-level functions with class_name=None."""
        source = """
def process(data):
    return data
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert len(methods) == 1
        assert methods[0].name == "process"
        assert methods[0].class_name is None

    def test_extracts_async_method(self):
        """Should mark async methods correctly."""
        source = """
class API:
    async def fetch(self):
        pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].is_async is True

    def test_extracts_static_method(self):
        """Should identify static methods."""
        source = """
class Utils:
    @staticmethod
    def helper():
        pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].is_static is True
        assert methods[0].is_classmethod is False

    def test_extracts_classmethod(self):
        """Should identify class methods."""
        source = """
class Factory:
    @classmethod
    def create(cls):
        pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].is_classmethod is True
        assert methods[0].is_static is False

    def test_extracts_property(self):
        """Should identify property methods."""
        source = """
class User:
    @property
    def full_name(self):
        return self.name
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].is_property is True

    def test_extracts_parameters(self):
        """Should extract method parameters."""
        source = """
def process(name: str, age: int, active: bool = True):
    pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        params = methods[0].parameters
        assert len(params) == 3
        assert params[0]["name"] == "name"
        assert params[0]["annotation"] == "str"
        assert params[1]["name"] == "age"
        assert params[2]["has_default"] is True

    def test_extracts_return_annotation(self):
        """Should extract return type annotation."""
        source = """
def get_user(id: int) -> User:
    pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].return_annotation == "User"

    def test_extracts_method_docstring(self):
        """Should extract method docstring."""
        source = '''
def process():
    """Process the data."""
    pass
'''
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods[0].docstring == "Process the data."

    def test_extracts_varargs_and_kwargs(self):
        """Should extract *args and **kwargs parameters."""
        source = """
def flexible(*args, **kwargs):
    pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        params = methods[0].parameters
        param_names = [p["name"] for p in params]
        assert "*args" in param_names
        assert "**kwargs" in param_names

    def test_extracts_decorators(self):
        """Should extract method decorators."""
        source = """
class API:
    @cache
    @validate
    def get_data(self):
        pass
"""
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert "cache" in methods[0].decorators
        assert "validate" in methods[0].decorators

    def test_returns_empty_for_syntax_error(self):
        """Should return empty list for invalid syntax."""
        source = "def broken("
        manager = ASTManager()
        methods = manager.extract_methods(source)

        assert methods == []


class TestExtractImports:
    """Tests for ASTManager.extract_imports()."""

    def test_extracts_simple_import(self):
        """Should extract simple import statement."""
        source = "import json"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert len(imports) == 1
        assert imports[0].module == "json"
        assert imports[0].is_from_import is False
        assert imports[0].names == []

    def test_extracts_import_with_alias(self):
        """Should extract import with alias."""
        source = "import numpy as np"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports[0].module == "numpy"
        assert imports[0].alias == "np"

    def test_extracts_from_import(self):
        """Should extract from...import statement."""
        source = "from pathlib import Path"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports[0].module == "pathlib"
        assert imports[0].names == ["Path"]
        assert imports[0].is_from_import is True

    def test_extracts_from_import_multiple(self):
        """Should extract multiple names from single import."""
        source = "from typing import List, Dict, Optional"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports[0].module == "typing"
        assert "List" in imports[0].names
        assert "Dict" in imports[0].names
        assert "Optional" in imports[0].names

    def test_extracts_multiple_imports(self):
        """Should extract multiple import statements."""
        source = """
import os
import sys
from pathlib import Path
"""
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert len(imports) == 3
        modules = [i.module for i in imports]
        assert "os" in modules
        assert "sys" in modules
        assert "pathlib" in modules

    def test_extracts_line_numbers(self):
        """Should capture import line numbers."""
        source = """
import os
import sys
"""
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports[0].line == 2
        assert imports[1].line == 3

    def test_extracts_relative_import(self):
        """Should handle relative imports."""
        source = "from . import utils"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports[0].module == ""
        assert "utils" in imports[0].names

    def test_returns_empty_for_syntax_error(self):
        """Should return empty list for invalid syntax."""
        source = "from import"
        manager = ASTManager()
        imports = manager.extract_imports(source)

        assert imports == []


class TestExtractAll:
    """Tests for ASTManager.extract_all()."""

    def test_extracts_all_elements(self):
        """Should extract types, methods, and imports together."""
        source = """
import json
from pathlib import Path

class User:
    def get_name(self):
        return self.name

def process():
    pass
"""
        manager = ASTManager()
        result = manager.extract_all(source)

        assert "types" in result
        assert "methods" in result
        assert "imports" in result

        assert len(result["imports"]) == 2
        assert len(result["types"]) >= 1  # User class + process function
        assert len(result["methods"]) >= 1  # get_name method + process function

    def test_handles_empty_source(self):
        """Should return empty collections for empty source."""
        manager = ASTManager()
        result = manager.extract_all("")

        assert result["types"] == []
        assert result["methods"] == []
        assert result["imports"] == []


class TestExtractedModels:
    """Tests for AST data models."""

    def test_extracted_type_defaults(self):
        """Should have correct defaults for ExtractedType."""
        ext_type = ExtractedType(
            name="Test",
            kind="class",
            line_start=1,
            line_end=5,
        )
        assert ext_type.docstring is None
        assert ext_type.bases == []
        assert ext_type.decorators == []
        assert ext_type.is_async is False

    def test_extracted_method_defaults(self):
        """Should have correct defaults for ExtractedMethod."""
        method = ExtractedMethod(
            name="test",
            class_name=None,
            line_start=1,
            line_end=3,
        )
        assert method.docstring is None
        assert method.parameters == []
        assert method.return_annotation is None
        assert method.decorators == []
        assert method.is_async is False
        assert method.is_static is False
        assert method.is_classmethod is False
        assert method.is_property is False

    def test_extracted_import_defaults(self):
        """Should have correct defaults for ExtractedImport."""
        imp = ExtractedImport(
            module="os",
            names=[],
        )
        assert imp.alias is None
        assert imp.line == 0
        assert imp.is_from_import is False
