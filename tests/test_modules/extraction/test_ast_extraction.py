"""Tests for modules.extraction.ast_extraction module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.adapters.ast.models import ExtractedMethod, ExtractedType
from deriva.modules.extraction.ast_extraction import (
    _build_method_node_from_ast,
    _build_type_node_from_ast,
    extract_methods_from_python,
    extract_types_from_python,
    is_python_file,
)


class TestIsPythonFile:
    """Tests for is_python_file function."""

    def test_python_subtype_returns_true(self):
        """Should return True for python subtype."""
        assert is_python_file("python") is True

    def test_python_uppercase_returns_true(self):
        """Should return True for Python (case insensitive)."""
        assert is_python_file("Python") is True

    def test_other_subtype_returns_false(self):
        """Should return False for non-python subtype."""
        assert is_python_file("javascript") is False

    def test_none_subtype_returns_false(self):
        """Should return False for None subtype."""
        assert is_python_file(None) is False


class TestExtractTypesFromPython:
    """Tests for extract_types_from_python function."""

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_extracts_class_successfully(self, mock_ast_manager_class):
        """Should extract class as TypeDefinition node."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_types.return_value = [
            ExtractedType(
                name="UserService",
                kind="class",
                line_start=1,
                line_end=5,
                docstring="User management service.",
                bases=["BaseService"],
                decorators=["dataclass"],
            )
        ]

        file_content = "class UserService(BaseService):\n    pass\n"
        result = extract_types_from_python("src/service.py", file_content, "myrepo")

        assert result["success"] is True
        assert result["stats"]["total_nodes"] == 1
        assert result["stats"]["node_types"]["TypeDefinition"] == 1
        assert result["stats"]["extraction_method"] == "ast"
        assert len(result["data"]["nodes"]) == 1
        assert len(result["data"]["edges"]) == 1

        node = result["data"]["nodes"][0]
        assert node["label"] == "TypeDefinition"
        assert node["properties"]["typeName"] == "UserService"
        assert node["properties"]["category"] == "class"
        assert node["properties"]["confidence"] == 1.0

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_handles_syntax_error(self, mock_ast_manager_class):
        """Should return error result for syntax errors."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_types.side_effect = SyntaxError("invalid syntax")

        result = extract_types_from_python("src/bad.py", "def broken(", "myrepo")

        assert result["success"] is False
        assert "syntax error" in result["errors"][0].lower()
        assert result["stats"]["total_nodes"] == 0

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_handles_general_exception(self, mock_ast_manager_class):
        """Should return error result for general exceptions."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_types.side_effect = RuntimeError("unexpected error")

        result = extract_types_from_python("src/file.py", "x = 1", "myrepo")

        assert result["success"] is False
        assert "AST extraction error" in result["errors"][0]
        assert result["stats"]["extraction_method"] == "ast"

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_empty_file_returns_empty_nodes(self, mock_ast_manager_class):
        """Should return empty nodes for file with no types."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_types.return_value = []

        result = extract_types_from_python("src/empty.py", "", "myrepo")

        assert result["success"] is True
        assert result["stats"]["total_nodes"] == 0
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []


class TestExtractMethodsFromPython:
    """Tests for extract_methods_from_python function."""

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_extracts_class_method(self, mock_ast_manager_class):
        """Should extract class method with CONTAINS edge to class."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_methods.return_value = [
            ExtractedMethod(
                name="get_user",
                class_name="UserService",
                line_start=5,
                line_end=10,
                docstring="Get user by ID.",
                parameters=[{"name": "user_id", "annotation": "int"}],
                return_annotation="User",
            )
        ]

        result = extract_methods_from_python("src/service.py", "class code", "myrepo")

        assert result["success"] is True
        assert result["stats"]["total_nodes"] == 1
        assert result["stats"]["node_types"]["Method"] == 1

        node = result["data"]["nodes"][0]
        assert node["label"] == "Method"
        assert node["properties"]["methodName"] == "get_user"
        assert node["properties"]["typeName"] == "UserService"

        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "CONTAINS"
        assert "UserService" in edge["from_node_id"]

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_extracts_top_level_function(self, mock_ast_manager_class):
        """Should extract top-level function with CONTAINS edge to file."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_methods.return_value = [
            ExtractedMethod(
                name="helper_function",
                class_name=None,
                line_start=1,
                line_end=5,
            )
        ]

        result = extract_methods_from_python("src/utils.py", "def helper():", "myrepo")

        assert result["success"] is True
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "CONTAINS"
        assert "file_" in edge["from_node_id"]

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_handles_syntax_error(self, mock_ast_manager_class):
        """Should return error result for syntax errors."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_methods.side_effect = SyntaxError("invalid syntax")

        result = extract_methods_from_python("src/bad.py", "def (:", "myrepo")

        assert result["success"] is False
        assert "syntax error" in result["errors"][0].lower()

    @patch("deriva.modules.extraction.ast_extraction.ASTManager")
    def test_handles_general_exception(self, mock_ast_manager_class):
        """Should return error result for general exceptions."""
        mock_manager = MagicMock()
        mock_ast_manager_class.return_value = mock_manager
        mock_manager.extract_methods.side_effect = ValueError("bad value")

        result = extract_methods_from_python("src/file.py", "x = 1", "myrepo")

        assert result["success"] is False
        assert "AST extraction error" in result["errors"][0]


class TestBuildTypeNodeFromAst:
    """Tests for _build_type_node_from_ast helper."""

    def test_class_category(self):
        """Should map class kind to class category."""
        ext_type = ExtractedType(name="MyClass", kind="class", line_start=1, line_end=5)
        node = _build_type_node_from_ast(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["category"] == "class"

    def test_function_category(self):
        """Should map function kind to function category."""
        ext_type = ExtractedType(
            name="my_func", kind="function", line_start=1, line_end=3
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "def code", "repo")
        assert node["properties"]["category"] == "function"

    def test_type_alias_category(self):
        """Should map type_alias kind to alias category."""
        ext_type = ExtractedType(
            name="MyType", kind="type_alias", line_start=1, line_end=1
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "type code", "repo")
        assert node["properties"]["category"] == "alias"

    def test_unknown_kind_maps_to_other(self):
        """Should map unknown kind to other category."""
        ext_type = ExtractedType(
            name="Thing", kind="unknown_kind", line_start=1, line_end=1
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "code", "repo")
        assert node["properties"]["category"] == "other"

    def test_uses_docstring_for_description(self):
        """Should use docstring as description when present."""
        ext_type = ExtractedType(
            name="MyClass",
            kind="class",
            line_start=1,
            line_end=5,
            docstring="This is my class.",
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["description"] == "This is my class."

    def test_generates_default_description_without_docstring(self):
        """Should generate default description when no docstring."""
        ext_type = ExtractedType(
            name="MyClass", kind="class", line_start=1, line_end=5, docstring=None
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "class code", "repo")
        assert "Class MyClass" in node["properties"]["description"]

    def test_includes_ast_specific_properties(self):
        """Should include AST-specific properties."""
        ext_type = ExtractedType(
            name="MyClass",
            kind="class",
            line_start=1,
            line_end=10,
            bases=["BaseA", "BaseB"],
            decorators=["dataclass"],
            is_async=True,
        )
        node = _build_type_node_from_ast(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["bases"] == ["BaseA", "BaseB"]
        assert node["properties"]["decorators"] == ["dataclass"]
        assert node["properties"]["is_async"] is True


class TestBuildMethodNodeFromAst:
    """Tests for _build_method_node_from_ast helper."""

    def test_public_visibility(self):
        """Should set public visibility for regular methods."""
        ext_method = ExtractedMethod(
            name="get_data", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "public"

    def test_private_visibility_single_underscore(self):
        """Should set private visibility for single underscore prefix."""
        ext_method = ExtractedMethod(
            name="_internal", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "private"

    def test_protected_visibility_double_underscore(self):
        """Should set protected visibility for name-mangled methods."""
        ext_method = ExtractedMethod(
            name="__secret", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "protected"

    def test_dunder_methods_are_private(self):
        """Dunder methods are private since they start with underscore."""
        ext_method = ExtractedMethod(
            name="__init__", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        # Code treats anything starting with _ as private
        assert node["properties"]["visibility"] == "private"

    def test_formats_parameters_with_annotations(self):
        """Should format parameters with type annotations."""
        ext_method = ExtractedMethod(
            name="process",
            class_name="MyClass",
            line_start=1,
            line_end=3,
            parameters=[
                {"name": "data", "annotation": "str"},
                {"name": "count", "annotation": "int"},
            ],
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["parameters"] == "data: str, count: int"

    def test_formats_parameters_without_annotations(self):
        """Should format parameters without annotations."""
        ext_method = ExtractedMethod(
            name="process",
            class_name="MyClass",
            line_start=1,
            line_end=3,
            parameters=[{"name": "data"}, {"name": "count"}],
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["parameters"] == "data, count"

    def test_uses_docstring_for_description(self):
        """Should use docstring as description when present."""
        ext_method = ExtractedMethod(
            name="do_thing",
            class_name="MyClass",
            line_start=1,
            line_end=5,
            docstring="Does the thing.",
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["description"] == "Does the thing."

    def test_default_description_without_docstring(self):
        """Should generate default description without docstring."""
        ext_method = ExtractedMethod(
            name="do_thing", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert "Method do_thing" in node["properties"]["description"]

    def test_return_type_default(self):
        """Should default return type to None when not specified."""
        ext_method = ExtractedMethod(
            name="do_thing",
            class_name="MyClass",
            line_start=1,
            line_end=3,
            return_annotation=None,
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["returnType"] == "None"

    def test_return_type_specified(self):
        """Should use specified return annotation."""
        ext_method = ExtractedMethod(
            name="get_user",
            class_name="MyClass",
            line_start=1,
            line_end=3,
            return_annotation="User",
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["returnType"] == "User"

    def test_includes_method_flags(self):
        """Should include is_static, is_async and other flags."""
        ext_method = ExtractedMethod(
            name="factory",
            class_name="MyClass",
            line_start=1,
            line_end=5,
            is_static=True,
            is_async=True,
            is_classmethod=True,
            is_property=True,
            decorators=["staticmethod", "async"],
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["isStatic"] is True
        assert node["properties"]["isAsync"] is True
        assert node["properties"]["is_classmethod"] is True
        assert node["properties"]["is_property"] is True
        assert node["properties"]["decorators"] == ["staticmethod", "async"]

    def test_top_level_function_typename(self):
        """Should set empty typeName for top-level functions."""
        ext_method = ExtractedMethod(
            name="helper", class_name=None, line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["typeName"] == ""

    def test_class_method_typename(self):
        """Should set typeName for class methods."""
        ext_method = ExtractedMethod(
            name="method", class_name="MyClass", line_start=1, line_end=3
        )
        node = _build_method_node_from_ast(ext_method, "file.py", "repo")
        assert node["properties"]["typeName"] == "MyClass"
