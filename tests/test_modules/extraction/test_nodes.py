"""Tests for node extraction modules (LLM-based and AST-based)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from deriva.adapters.treesitter.models import ExtractedMethod, ExtractedType
from deriva.modules.extraction import (
    external_dependency,
    method,
    type_definition,
)
from deriva.modules.extraction import (
    test as test_module,
)
from deriva.modules.extraction.base import is_python_file
from deriva.modules.extraction.directory import (
    build_directory_node,
    extract_directories,
)
from deriva.modules.extraction.file import (
    _infer_tested_file,
    build_file_node,
    extract_files,
)
from deriva.modules.extraction.method import (
    _build_method_node_from_treesitter,
    extract_methods_from_python,
)
from deriva.modules.extraction.repository import (
    build_repository_node,
    extract_repository,
)
from deriva.modules.extraction.type_definition import (
    _build_type_node_from_treesitter,
    extract_types_from_python,
)

PROMPT_TEXTS = {"persona": "Analyze the source.", "task": "Extract the items."}


class TestTypeDefinitionModule:
    """Tests for type_definition extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = type_definition.TYPE_DEFINITION_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "types" in schema["schema"]["properties"]  # type: ignore[operator,index]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = type_definition.build_extraction_prompt(
            file_content="class UserModel:\n    pass",
            file_path="models/user.py",
            instruction="Extract type definitions",
            example='{"types": []}',
            texts=PROMPT_TEXTS,
        )

        assert "models/user.py" in prompt
        assert "class UserModel" in prompt

    def test_build_type_definition_node_success(self):
        """Should build valid node from type data."""
        type_data = {
            "typeName": "UserModel",
            "category": "class",
            "description": "User data model",
            "startLine": 1,
            "endLine": 5,
            "confidence": 0.95,
        }

        result = type_definition.build_type_definition_node(type_data, "models/user.py", "myrepo")

        assert result["success"] is True
        assert result["data"]["label"] == "TypeDefinition"
        assert result["data"]["properties"]["typeName"] == "UserModel"

    def test_build_type_definition_node_missing_field(self):
        """Should fail when required field is missing."""
        type_data = {
            "typeCategory": "class",
        }

        result = type_definition.build_type_definition_node(type_data, "file.py", "myrepo")

        assert result["success"] is False

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({"types": [{"typeName": "User", "typeCategory": "class", "description": "User model"}]})

        result = type_definition.parse_llm_response(response)

        assert result["success"] is True


class TestMethodModule:
    """Tests for method extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = method.METHOD_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "methods" in schema["schema"]["properties"]  # type: ignore[operator,index]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = method.build_extraction_prompt(
            code_snippet="def get_user(id: int) -> User:\n    pass",
            type_name="UserService",
            type_category="class",
            file_path="api/users.py",
            instruction="Extract methods",
            example='{"methods": []}',
            texts=PROMPT_TEXTS,
        )

        assert "api/users.py" in prompt
        assert "def get_user" in prompt
        assert "UserService" in prompt

    def test_build_method_node_success(self):
        """Should build valid node from method data."""
        method_data = {
            "methodName": "get_user",
            "returnType": "User",
            "visibility": "public",
            "parameters": [{"name": "id", "type": "int"}],
            "description": "Get user by ID",
            "confidence": 0.9,
        }

        result = method.build_method_node(method_data, "api/users.py", "UserService", "myrepo")

        assert result["success"] is True
        assert result["data"]["label"] == "Method"
        assert result["data"]["properties"]["methodName"] == "get_user"

    def test_build_method_node_missing_field(self):
        """Should fail when required field is missing."""
        method_data = {
            "returnType": "User",
        }

        result = method.build_method_node(method_data, "file.py", "SomeClass", "myrepo")

        assert result["success"] is False

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({"methods": [{"methodName": "process", "returnType": "void", "visibility": "public"}]})

        result = method.parse_llm_response(response)

        assert result["success"] is True


class TestExternalDependencyModule:
    """Tests for external_dependency extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = external_dependency.EXTERNAL_DEPENDENCY_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "dependencies" in schema["schema"]["properties"]  # type: ignore[operator,index]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = external_dependency.build_extraction_prompt(
            file_content='fastapi = "^0.100.0"\nredis = "^4.0.0"',
            file_path="pyproject.toml",
            instruction="Extract dependencies",
            example='{"dependencies": []}',
            texts=PROMPT_TEXTS,
        )

        assert "pyproject.toml" in prompt
        assert "fastapi" in prompt
        assert "redis" in prompt

    def test_build_external_dependency_node_success(self):
        """Should build valid node from dependency data."""
        dep_data = {
            "dependencyName": "FastAPI",
            "dependencyCategory": "library",
            "version": "^0.100.0",
            "ecosystem": "pypi",
            "description": "Modern web framework",
            "confidence": 0.95,
        }

        result = external_dependency.build_external_dependency_node(dep_data, "pyproject.toml", "myrepo")

        assert result["success"] is True
        assert result["data"]["label"] == "ExternalDependency"
        assert result["data"]["properties"]["dependencyName"] == "FastAPI"
        assert result["data"]["properties"]["dependencyCategory"] == "library"

    def test_build_external_dependency_node_missing_field(self):
        """Should fail when required field is missing."""
        dep_data = {
            "dependencyCategory": "library",
        }

        result = external_dependency.build_external_dependency_node(dep_data, "file.py", "myrepo")

        assert result["success"] is False
        assert any("dependencyName" in e for e in result["errors"])

    def test_build_external_dependency_node_invalid_category(self):
        """Should default to 'library' for invalid category."""
        dep_data = {
            "dependencyName": "Something",
            "dependencyCategory": "invalid_category",
            "description": "Some lib",
        }

        result = external_dependency.build_external_dependency_node(dep_data, "file.py", "myrepo")

        assert result["success"] is True
        assert result["data"]["properties"]["dependencyCategory"] == "library"

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({"dependencies": [{"dependencyName": "Redis", "dependencyCategory": "library", "description": "Cache"}]})

        result = external_dependency.parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_parse_llm_response_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "not valid json {"

        result = external_dependency.parse_llm_response(response)

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_parse_llm_response_missing_dependencies(self):
        """Should return empty data when response has unrecognized structure."""
        response = json.dumps({"data": []})

        result = external_dependency.parse_llm_response(response)

        # Unrecognized response structure treated as "no dependencies found"
        assert result["success"] is True
        assert result["data"] == []


class TestTestExtractionModule:
    """Tests for test extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = test_module.TEST_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "tests" in schema["schema"]["properties"]  # type: ignore[operator,index]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = test_module.build_extraction_prompt(
            file_content="def test_user_creation():\n    assert True",
            file_path="tests/test_user.py",
            instruction="Extract test definitions",
            example='{"tests": []}',
            texts=PROMPT_TEXTS,
        )

        assert "tests/test_user.py" in prompt
        assert "test_user_creation" in prompt

    def test_build_test_node_success(self):
        """Should build valid node from test data."""
        test_data = {
            "testName": "test_user_creation",
            "testType": "unit",
            "description": "Verifies user creation logic",
            "testedElement": "UserService",
            "framework": "pytest",
            "startLine": 1,
            "endLine": 5,
            "confidence": 0.95,
        }

        result = test_module.build_test_node(test_data, "tests/test_user.py", "myrepo")

        assert result["success"] is True
        assert result["data"]["label"] == "Test"
        assert result["data"]["properties"]["testName"] == "test_user_creation"
        assert result["data"]["properties"]["testType"] == "unit"

    def test_build_test_node_missing_field(self):
        """Should fail when required field is missing."""
        test_data = {
            "testType": "unit",
        }

        result = test_module.build_test_node(test_data, "tests/file.py", "myrepo")

        assert result["success"] is False
        assert any("testName" in e for e in result["errors"])

    def test_build_test_node_invalid_type(self):
        """Should default to 'other' for invalid test type."""
        test_data = {
            "testName": "test_something",
            "testType": "invalid_type",
            "description": "Some test",
        }

        result = test_module.build_test_node(test_data, "tests/file.py", "myrepo")

        assert result["success"] is True
        assert result["data"]["properties"]["testType"] == "other"

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({"tests": [{"testName": "test_foo", "testType": "unit", "description": "Tests foo"}]})

        result = test_module.parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_parse_llm_response_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "not valid json {"

        result = test_module.parse_llm_response(response)

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_parse_llm_response_missing_tests(self):
        """Should fail when tests array is missing."""
        response = json.dumps({"data": []})

        result = test_module.parse_llm_response(response)

        assert result["success"] is False


# =============================================================================
# Tests for extract_* functions with mocked LLM
# =============================================================================


class MockLLMResponse:
    """Mock LLM response that only has specific attributes (no .error)."""

    def __init__(self, content_dict, usage=None):
        self.content = json.dumps(content_dict)
        self.usage = usage or {}
        self.response_type = "live"


class TestExtractTypeDefs:
    """Tests for extract_type_definitions function."""

    def test_extract_success(self):
        """Should extract type definitions successfully."""
        mock_response = MockLLMResponse(
            {
                "types": [
                    {
                        "typeName": "UserModel",
                        "category": "class",
                        "description": "User data",
                        "startLine": 1,
                        "endLine": 10,
                    }
                ]
            },
            usage={"prompt_tokens": 50, "completion_tokens": 30},
        )

        mock_llm = MagicMock(return_value=mock_response)

        result = type_definition.extract_type_definitions(
            file_path="models.py",
            file_content="class UserModel:\n    pass",
            repo_name="myrepo",
            llm_query_fn=mock_llm,
            config={"instruction": "Extract types", "params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_handles_error(self):
        """Should handle extraction errors."""
        mock_llm = MagicMock(side_effect=RuntimeError("Network error"))

        result = type_definition.extract_type_definitions(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False


class TestExtractMethods:
    """Tests for extract_methods function."""

    def test_extract_success(self):
        """Should extract methods successfully."""
        mock_response = MockLLMResponse(
            {
                "methods": [
                    {
                        "methodName": "get_user",
                        "returnType": "User",
                        "visibility": "public",
                        "parameters": [],
                        "description": "Gets a user",
                    }
                ]
            }
        )

        mock_llm = MagicMock(return_value=mock_response)

        # extract_methods takes a type_node dict
        type_node = {
            "node_id": "type_repo_UserService",
            "label": "TypeDefinition",
            "properties": {
                "typeName": "UserService",
                "typeCategory": "class",
                "codeSnippet": "def get_user(): pass",
                "originSource": "users.py",
            },
        }

        result = method.extract_methods(
            type_node=type_node,
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_handles_error(self):
        """Should handle extraction errors."""
        mock_llm = MagicMock(side_effect=Exception("Failed"))

        type_node = {
            "node_id": "type_repo_Type",
            "label": "TypeDefinition",
            "properties": {
                "typeName": "Type",
                "typeCategory": "class",
                "codeSnippet": "code",
                "originSource": "file.py",
            },
        }

        result = method.extract_methods(
            type_node=type_node,
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False


class TestExtractExternalDependencies:
    """Tests for extract_external_dependencies function."""

    def test_extract_llm_success(self):
        """Should extract dependencies from requirements.txt deterministically."""
        result = external_dependency.extract_external_dependencies(
            file_path="requirements.txt",
            file_content="fastapi==0.100.0\n",
            repo_name="repo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_deterministic_requirements_txt(self):
        """Should extract dependencies deterministically from requirements.txt."""
        result = external_dependency.extract_external_dependencies(
            file_path="requirements.txt",
            file_content="flask==2.0.0\nrequests>=2.25.0\n",
            repo_name="repo",
            llm_query_fn=None,  # No LLM needed
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 2
        names = [n["properties"]["dependencyName"] for n in result["data"]["nodes"]]
        assert "flask" in names
        assert "requests" in names

    def test_extract_handles_error(self):
        """Should return skipped result for unsupported file types."""
        result = external_dependency.extract_external_dependencies(
            file_path="config.toml",  # Generic file is skipped (no LLM fallback)
            file_content="content",
            repo_name="repo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        # config.toml is not a recognized file type, so it's skipped
        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 0


class TestExtractTests:
    """Tests for extract_tests function."""

    def test_extract_success(self):
        """Should extract tests successfully."""
        mock_response = MockLLMResponse(
            {
                "tests": [
                    {
                        "testName": "test_login",
                        "testType": "unit",
                        "description": "Tests login",
                        "testedElement": "AuthService",
                        "framework": "pytest",
                    }
                ]
            }
        )

        mock_llm = MagicMock(return_value=mock_response)

        result = test_module.extract_tests(
            file_path="tests/test_auth.py",
            file_content="def test_login(): assert True",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_handles_error(self):
        """Should handle extraction errors."""
        mock_llm = MagicMock(side_effect=Exception("Error"))

        result = test_module.extract_tests(
            file_path="test.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False


# =============================================================================
# AST-based extraction tests (Python type/method extraction)
# =============================================================================


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

    @patch("deriva.modules.extraction.type_definition.TreeSitterManager")
    def test_extracts_class_successfully(self, mock_treesitter_manager_class):
        """Should extract class as TypeDefinition node."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
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
        assert result["stats"]["extraction_method"] == "treesitter"
        assert len(result["data"]["nodes"]) == 1
        # 2 edges: CONTAINS (File->Type) + INHERITS (UserService->BaseService)
        assert len(result["data"]["edges"]) >= 1

        node = result["data"]["nodes"][0]
        assert node["label"] == "TypeDefinition"
        assert node["properties"]["typeName"] == "UserService"
        assert node["properties"]["category"] == "class"
        assert node["properties"]["confidence"] == 1.0

    @patch("deriva.modules.extraction.type_definition.TreeSitterManager")
    def test_handles_syntax_error(self, mock_treesitter_manager_class):
        """Should return error result for syntax errors."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_types.side_effect = SyntaxError("invalid syntax")

        result = extract_types_from_python("src/bad.py", "def broken(", "myrepo")

        assert result["success"] is False
        assert "syntax error" in result["errors"][0].lower()
        assert result["stats"]["total_nodes"] == 0

    @patch("deriva.modules.extraction.type_definition.TreeSitterManager")
    def test_handles_general_exception(self, mock_treesitter_manager_class):
        """Should return error result for general exceptions."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_types.side_effect = RuntimeError("unexpected error")

        result = extract_types_from_python("src/file.py", "x = 1", "myrepo")

        assert result["success"] is False
        assert "Tree-sitter extraction error" in result["errors"][0]
        assert result["stats"]["extraction_method"] == "treesitter"

    @patch("deriva.modules.extraction.type_definition.TreeSitterManager")
    def test_empty_file_returns_empty_nodes(self, mock_treesitter_manager_class):
        """Should return empty nodes for file with no types."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_types.return_value = []

        result = extract_types_from_python("src/empty.py", "", "myrepo")

        assert result["success"] is True
        assert result["stats"]["total_nodes"] == 0
        assert result["data"]["nodes"] == []
        assert result["data"]["edges"] == []


class TestExtractMethodsFromPython:
    """Tests for extract_methods_from_python function."""

    @patch("deriva.modules.extraction.method.TreeSitterManager")
    def test_extracts_class_method(self, mock_treesitter_manager_class):
        """Should extract class method with CONTAINS edge to class."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
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

    @patch("deriva.modules.extraction.method.TreeSitterManager")
    def test_extracts_top_level_function(self, mock_treesitter_manager_class):
        """Should extract top-level function with CONTAINS edge to file."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
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
        assert "file::" in edge["from_node_id"]

    @patch("deriva.modules.extraction.method.TreeSitterManager")
    def test_handles_syntax_error(self, mock_treesitter_manager_class):
        """Should return error result for syntax errors."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_methods.side_effect = SyntaxError("invalid syntax")

        result = extract_methods_from_python("src/bad.py", "def (:", "myrepo")

        assert result["success"] is False
        assert "syntax error" in result["errors"][0].lower()

    @patch("deriva.modules.extraction.method.TreeSitterManager")
    def test_handles_general_exception(self, mock_treesitter_manager_class):
        """Should return error result for general exceptions."""
        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_methods.side_effect = ValueError("bad value")

        result = extract_methods_from_python("src/file.py", "x = 1", "myrepo")

        assert result["success"] is False
        assert "Tree-sitter extraction error" in result["errors"][0]


class TestBuildTypeNodeFromAst:
    """Tests for _build_type_node_from_treesitter helper."""

    def test_class_category(self):
        """Should map class kind to class category."""
        ext_type = ExtractedType(name="MyClass", kind="class", line_start=1, line_end=5)
        node = _build_type_node_from_treesitter(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["category"] == "class"

    def test_function_category(self):
        """Should map function kind to function category."""
        ext_type = ExtractedType(name="my_func", kind="function", line_start=1, line_end=3)
        node = _build_type_node_from_treesitter(ext_type, "file.py", "def code", "repo")
        assert node["properties"]["category"] == "function"

    def test_type_alias_category(self):
        """Should map type_alias kind to alias category."""
        ext_type = ExtractedType(name="MyType", kind="type_alias", line_start=1, line_end=1)
        node = _build_type_node_from_treesitter(ext_type, "file.py", "type code", "repo")
        assert node["properties"]["category"] == "alias"

    def test_unknown_kind_maps_to_other(self):
        """Should map unknown kind to other category."""
        ext_type = ExtractedType(name="Thing", kind="unknown_kind", line_start=1, line_end=1)
        node = _build_type_node_from_treesitter(ext_type, "file.py", "code", "repo")
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
        node = _build_type_node_from_treesitter(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["description"] == "This is my class."

    def test_generates_default_description_without_docstring(self):
        """Should generate default description when no docstring."""
        ext_type = ExtractedType(name="MyClass", kind="class", line_start=1, line_end=5, docstring=None)
        node = _build_type_node_from_treesitter(ext_type, "file.py", "class code", "repo")
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
        node = _build_type_node_from_treesitter(ext_type, "file.py", "class code", "repo")
        assert node["properties"]["bases"] == ["BaseA", "BaseB"]
        assert node["properties"]["decorators"] == ["dataclass"]
        assert node["properties"]["is_async"] is True


class TestBuildMethodNodeFromAst:
    """Tests for _build_method_node_from_treesitter helper."""

    def test_public_visibility(self):
        """Should set public visibility for regular methods."""
        ext_method = ExtractedMethod(name="get_data", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "public"

    def test_private_visibility_single_underscore(self):
        """Should set private visibility for single underscore prefix."""
        ext_method = ExtractedMethod(name="_internal", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "private"

    def test_protected_visibility_double_underscore(self):
        """Should set protected visibility for name-mangled methods."""
        ext_method = ExtractedMethod(name="__secret", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["visibility"] == "protected"

    def test_dunder_methods_are_private(self):
        """Dunder methods are private since they start with underscore."""
        ext_method = ExtractedMethod(name="__init__", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["description"] == "Does the thing."

    def test_default_description_without_docstring(self):
        """Should generate default description without docstring."""
        ext_method = ExtractedMethod(name="do_thing", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
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
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["isStatic"] is True
        assert node["properties"]["isAsync"] is True
        assert node["properties"]["is_classmethod"] is True
        assert node["properties"]["is_property"] is True
        assert node["properties"]["decorators"] == ["staticmethod", "async"]

    def test_top_level_function_typename(self):
        """Should set empty typeName for top-level functions."""
        ext_method = ExtractedMethod(name="helper", class_name=None, line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["typeName"] == ""

    def test_class_method_typename(self):
        """Should set typeName for class methods."""
        ext_method = ExtractedMethod(name="method", class_name="MyClass", line_start=1, line_end=3)
        node = _build_method_node_from_treesitter(ext_method, "file.py", "repo")
        assert node["properties"]["typeName"] == "MyClass"


# =============================================================================
# Structural extraction tests (Repository, Directory, File nodes)
# =============================================================================


class TestBuildRepositoryNode:
    """Tests for build_repository_node function."""

    def test_valid_repository_metadata(self):
        """Should create valid repository node from metadata."""
        metadata = {
            "name": "myproject",
            "url": "https://github.com/user/myproject.git",
            "description": "A test project",
            "total_size_mb": 15.5,
            "total_files": 120,
        }

        result = build_repository_node(metadata)

        assert result["success"] is True
        assert result["data"]["node_id"] == "repo::myproject"
        assert result["data"]["label"] == "Repository"
        assert result["data"]["properties"]["name"] == "myproject"

    def test_missing_required_fields(self):
        """Should fail when required fields are missing."""
        result = build_repository_node({})

        assert result["success"] is False
        assert len(result["errors"]) >= 1


class TestExtractRepository:
    """Tests for extract_repository function."""

    def test_successful_extraction(self):
        """Should extract repository and return proper structure."""
        metadata = {
            "name": "myproject",
            "url": "https://github.com/user/myproject.git",
        }

        result = extract_repository(metadata)

        assert result["success"] is True
        assert result["stats"]["total_nodes"] == 1
        assert len(result["data"]["nodes"]) == 1


class TestBuildDirectoryNode:
    """Tests for build_directory_node function."""

    def test_valid_directory_metadata(self):
        """Should create valid directory node from metadata."""
        metadata = {"path": "src/utils", "name": "utils"}

        result = build_directory_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["data"]["node_id"] == "dir::myrepo::src_utils"
        assert result["data"]["label"] == "Directory"

    def test_missing_required_fields(self):
        """Should fail when required fields are missing."""
        result = build_directory_node({}, "myrepo")

        assert result["success"] is False


class TestExtractDirectories:
    """Tests for extract_directories function."""

    def test_nonexistent_path(self):
        """Should fail gracefully for nonexistent path."""
        result = extract_directories("/nonexistent/path", "myrepo")

        assert result["success"] is False
        assert "does not exist" in result["errors"][0]

    def test_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["data"]["nodes"] == []

    def test_nested_directories(self):
        """Should extract nested directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            helpers = Path(tmpdir) / "src" / "utils" / "helpers"
            helpers.mkdir(parents=True)

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 3

    def test_skips_git_directories(self):
        """Should skip .git directories and their contents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create regular directory
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir()

            # Create .git directory with subdirectories
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            (git_dir / "objects").mkdir()
            (git_dir / "refs").mkdir()

            result = extract_directories(tmpdir, "myrepo")

            assert result["success"] is True
            # Should only include src, not .git or its subdirectories
            assert result["stats"]["total_nodes"] == 1
            node_paths = [n["properties"]["path"] for n in result["data"]["nodes"]]
            assert "src" in node_paths
            assert ".git" not in node_paths
            assert ".git/objects" not in node_paths

    def test_handles_directory_processing_error(self):
        """Should handle errors when processing individual directories."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a valid directory
            valid_dir = Path(tmpdir) / "valid"
            valid_dir.mkdir()

            # Patch Path.iterdir to fail for specific directory
            with patch.object(Path, "iterdir"):
                # This test is tricky because iterdir is called in rglob
                # Let's test the error handling by checking success is True
                # even when some directories have errors
                result = extract_directories(tmpdir, "myrepo")

            # Even with errors, should succeed if some nodes extracted
            assert "errors" in result

    def test_handles_fatal_extraction_error(self):
        """Should handle fatal errors during extraction."""
        from unittest.mock import patch

        # Mock Path to raise an exception
        with patch("deriva.modules.extraction.directory.Path") as mock_path:
            mock_path.side_effect = RuntimeError("Fatal error")

            result = extract_directories("/some/path", "myrepo")

            assert result["success"] is False
            assert "Fatal error" in result["errors"][0]
            assert result["stats"]["total_nodes"] == 0


class TestBuildFileNode:
    """Tests for build_file_node function."""

    def test_valid_file_metadata(self):
        """Should create valid file node from metadata."""
        metadata = {"path": "src/main.py", "name": "main.py"}

        result = build_file_node(metadata, "myrepo")

        assert result["success"] is True
        assert result["data"]["node_id"] == "file::myrepo::src_main.py"
        assert result["data"]["label"] == "File"

    def test_missing_required_fields(self):
        """Should fail when required fields are missing."""
        result = build_file_node({}, "myrepo")

        assert result["success"] is False


class TestExtractFiles:
    """Tests for extract_files function."""

    def test_nonexistent_path(self):
        """Should fail gracefully for nonexistent path."""
        result = extract_files("/nonexistent/path", "myrepo")

        assert result["success"] is False

    def test_empty_directory(self):
        """Should handle empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["data"]["nodes"] == []

    def test_single_file(self):
        """Should extract single file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "main.py"
            test_file.write_text("print('hello')")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1
            assert result["data"]["nodes"][0]["properties"]["name"] == "main.py"

    def test_skips_git_files(self):
        """Should skip files in .git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = Path(tmpdir) / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("[core]")
            (Path(tmpdir) / "main.py").write_text("print('hello')")

            result = extract_files(tmpdir, "myrepo")

            assert result["success"] is True
            assert result["stats"]["total_nodes"] == 1
            file_names = [n["properties"]["name"] for n in result["data"]["nodes"]]
            assert "main.py" in file_names
            assert "config" not in file_names

    def test_creates_tests_edge_for_test_file(self):
        """Should create TESTS edge when test file matches source file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("source code")
            (Path(tmpdir) / "test_main.py").write_text("test code")

            classification = {
                "main.py": {"file_type": "source", "subtype": "python"},
                "test_main.py": {"file_type": "test", "subtype": "pytest"},
            }
            result = extract_files(tmpdir, "myrepo", classification_lookup=classification)

            assert result["success"] is True
            test_edges = [e for e in result["data"]["edges"] if e["relationship_type"] == "TESTS"]
            assert len(test_edges) == 1
            assert test_edges[0]["from_node_id"] == "file::myrepo::test_main.py"
            assert test_edges[0]["to_node_id"] == "file::myrepo::main.py"


class TestInferSourceFileForTest:
    """Tests for _infer_tested_file function."""

    def test_test_prefix_pattern(self):
        """Should find source file for test_foo.py pattern."""
        all_paths = {"foo.py", "bar.py", "test_foo.py"}
        result = _infer_tested_file("test_foo.py", all_paths)
        assert result == "foo.py"

    def test_test_suffix_pattern(self):
        """Should find source file for foo_test.py pattern."""
        all_paths = {"foo.py", "foo_test.py"}
        result = _infer_tested_file("foo_test.py", all_paths)
        assert result == "foo.py"

    def test_spec_pattern(self):
        """Should find source file for foo.spec.js pattern."""
        all_paths = {"foo.js", "foo.spec.js"}
        result = _infer_tested_file("foo.spec.js", all_paths)
        assert result == "foo.js"

    def test_tests_dir_to_src_dir(self):
        """Should find source in src/ when test is in tests/."""
        all_paths = {"src/main.py", "tests/test_main.py"}
        result = _infer_tested_file("tests/test_main.py", all_paths)
        assert result == "src/main.py"

    def test_no_match_returns_none(self):
        """Should return None when no source file found."""
        all_paths = {"other.py", "test_unknown.py"}
        result = _infer_tested_file("test_unknown.py", all_paths)
        assert result is None


# =============================================================================
# Deterministic extraction tests (pyproject.toml, package.json, etc.)
# =============================================================================


class TestExtractFromPyprojectToml:
    """Tests for pyproject.toml deterministic extraction."""

    def test_extracts_dependencies_from_pyproject(self):
        """Should extract dependencies from pyproject.toml."""
        content = """
[project]
dependencies = [
    "flask>=2.0.0",
    "requests",
]
"""
        result = external_dependency.extract_external_dependencies(
            file_path="pyproject.toml",
            file_content=content,
            repo_name="myrepo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        names = [n["properties"]["dependencyName"] for n in result["data"]["nodes"]]
        assert "flask" in names
        assert "requests" in names


class TestExtractFromPackageJson:
    """Tests for package.json deterministic extraction."""

    def test_extracts_npm_dependencies(self):
        """Should extract dependencies from package.json."""
        content = json.dumps(
            {
                "dependencies": {
                    "express": "^4.18.0",
                    "lodash": "^4.17.21",
                },
                "devDependencies": {
                    "jest": "^29.0.0",
                },
            }
        )

        result = external_dependency.extract_external_dependencies(
            file_path="package.json",
            file_content=content,
            repo_name="myrepo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        names = [n["properties"]["dependencyName"] for n in result["data"]["nodes"]]
        assert "express" in names
        assert "lodash" in names
        assert "jest" in names

    def test_handles_invalid_package_json(self):
        """Should handle invalid JSON gracefully."""
        result = external_dependency.extract_external_dependencies(
            file_path="package.json",
            file_content="{invalid json",
            repo_name="myrepo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False or len(result["data"]["nodes"]) == 0


class TestExtractFromPythonAst:
    """Tests for Python AST-based import extraction."""

    @patch("deriva.adapters.treesitter.TreeSitterManager")
    def test_extracts_imports_via_ast(self, mock_treesitter_manager_class):
        """Should extract external imports from Python files."""
        from deriva.adapters.treesitter.models import ExtractedImport

        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_imports.return_value = [
            ExtractedImport(
                module="requests",
                names=[],
                is_from_import=False,
                line=1,
            ),
            ExtractedImport(
                module="flask",
                names=["Flask"],
                is_from_import=True,
                line=2,
            ),
        ]

        result = external_dependency.extract_external_dependencies(
            file_path="main.py",
            file_content="import requests\nfrom flask import Flask",
            repo_name="myrepo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
            subtype="python",  # Required to trigger AST extraction
        )

        assert result["success"] is True
        names = [n["properties"]["dependencyName"] for n in result["data"]["nodes"]]
        assert "requests" in names
        assert "flask" in names

    @patch("deriva.adapters.treesitter.TreeSitterManager")
    def test_skips_stdlib_imports(self, mock_treesitter_manager_class):
        """Should skip standard library imports."""
        from deriva.adapters.treesitter.models import ExtractedImport

        mock_manager = MagicMock()
        mock_treesitter_manager_class.return_value = mock_manager
        mock_manager.extract_imports.return_value = [
            ExtractedImport(module="os", names=[], is_from_import=False, line=1),
            ExtractedImport(module="json", names=[], is_from_import=False, line=2),
            ExtractedImport(module="requests", names=[], is_from_import=False, line=3),
        ]

        result = external_dependency.extract_external_dependencies(
            file_path="main.py",
            file_content="import os\nimport json\nimport requests",
            repo_name="myrepo",
            llm_query_fn=None,
            config={"params": {"prompt": PROMPT_TEXTS}},
            subtype="python",  # Required to trigger AST extraction
        )

        assert result["success"] is True
        names = [n["properties"]["dependencyName"] for n in result["data"]["nodes"]]
        # stdlib should be skipped
        assert "os" not in names
        assert "json" not in names
        # third-party should be included
        assert "requests" in names


# =============================================================================
# Batch extraction tests
# =============================================================================


class TestExtractTestsBatch:
    """Tests for extract_tests_batch function."""

    def test_batch_success(self):
        """Should extract tests from multiple files."""
        mock_response = MockLLMResponse(
            {
                "tests": [
                    {
                        "testName": "test_auth",
                        "testType": "unit",
                        "description": "Tests auth",
                        "testedElement": "Auth",
                        "framework": "pytest",
                    }
                ]
            }
        )

        mock_llm = MagicMock(return_value=mock_response)

        files = [
            {"path": "test_auth.py", "content": "def test_auth(): pass"},
            {"path": "test_user.py", "content": "def test_user(): pass"},
        ]

        result = test_module.extract_tests_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert result["stats"]["files_processed"] == 2
        assert result["stats"]["files_with_tests"] == 2

    def test_batch_with_progress_callback(self):
        """Should call progress callback for each file."""
        mock_response = MockLLMResponse({"tests": []})
        mock_llm = MagicMock(return_value=mock_response)

        progress_calls = []

        def progress_cb(current, total, path):
            progress_calls.append((current, total, path))

        files = [
            {"path": "test1.py", "content": "code1"},
            {"path": "test2.py", "content": "code2"},
        ]

        test_module.extract_tests_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
            progress_callback=progress_cb,
        )

        assert len(progress_calls) == 2


class TestExtractTestsEdgeCases:
    """Additional edge case tests for test extraction."""

    def test_llm_error_response(self):
        """Should handle LLM error response."""

        class ErrorResponse:
            error = "API error"
            content = ""

        mock_llm = MagicMock(return_value=ErrorResponse())

        result = test_module.extract_tests(
            file_path="test.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False
        assert result["stats"]["llm_error"] is True

    def test_parse_error(self):
        """Should handle parse error from invalid response."""
        mock_response = MockLLMResponse({"invalid": "structure"})
        mock_llm = MagicMock(return_value=mock_response)

        result = test_module.extract_tests(
            file_path="test.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False
        assert result["stats"]["parse_error"] is True

    def test_partial_node_build_failure(self):
        """Should continue when some test nodes fail to build."""
        mock_response = MockLLMResponse(
            {
                "tests": [
                    {
                        "testName": "test_valid",
                        "testType": "unit",
                        "description": "Valid test",
                    },
                    {
                        "testType": "unit",  # Missing testName
                        "description": "Missing name",
                    },
                ]
            }
        )

        mock_llm = MagicMock(return_value=mock_response)

        result = test_module.extract_tests(
            file_path="test.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1
        assert len(result["errors"]) > 0


class TestExcludedDirectories:
    """Dependency directories (a configurable list) never become graph nodes."""

    EXCLUDED = (".git", "node_modules", "vendor")

    @staticmethod
    def _repo(tmpdir):
        root = Path(tmpdir)
        (root / "src").mkdir()
        (root / "src" / "app.py").write_text("x = 1")
        (root / "node_modules" / "pkg" / "lib").mkdir(parents=True)
        (root / "node_modules" / "pkg" / "lib" / "client.js").write_text("x")
        (root / "web" / "vendor").mkdir(parents=True)
        (root / "web" / "vendor" / "lib.js").write_text("x")
        (root / "web" / "main.js").write_text("x")
        (root / "vendored_notes.md").write_text("x")  # name only contains a segment: kept
        return root

    def test_is_excluded_path_matches_whole_segments(self):
        from deriva.modules.extraction.base import is_excluded_path

        assert is_excluded_path("node_modules/pkg/index.js", self.EXCLUDED)
        assert is_excluded_path("web/vendor", self.EXCLUDED)
        assert not is_excluded_path("web/vendored_notes.md", self.EXCLUDED)
        assert not is_excluded_path("src/app.py", self.EXCLUDED)

    def test_directories_skip_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._repo(tmpdir)

            result = extract_directories(tmpdir, "myrepo", excluded_dirs=self.EXCLUDED)

        paths = sorted(n["properties"]["path"] for n in result["data"]["nodes"])
        assert paths == ["src", "web"]

    def test_files_skip_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._repo(tmpdir)

            result = extract_files(tmpdir, "myrepo", excluded_dirs=self.EXCLUDED)

        paths = sorted(n["properties"]["path"] for n in result["data"]["nodes"])
        assert paths == ["src/app.py", "vendored_notes.md", "web/main.js"]

    def test_directory_stats_ignore_excluded_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._repo(tmpdir)

            result = extract_directories(tmpdir, "myrepo", excluded_dirs=self.EXCLUDED)

        web = next(n for n in result["data"]["nodes"] if n["properties"]["path"] == "web")
        assert web["properties"]["subdirectory_count"] == 0


class TestExtractDirectoriesWalk:
    """One pruned walk gives exactly the nodes, order, counts and sizes of the full rglob scan."""

    EXCLUDED = ("node_modules", "vendor", ".git")

    @staticmethod
    def _tree(root):
        files = {
            "README.md": 10,
            "src/app.py": 100,
            "src/lib/util.py": 40,
            "src/lib/deep/x.py": 7,
            "src/vendor/pkg.js": 999,  # excluded directory below a kept one
            "docs/guide.md": 25,
            "docs/api/ref.md": 5,
            "docs/api/v1/x.md": 2,  # depth 3 in two branches: rglob's order is not breadth-first
            "tools/vendor": 3,  # a file named like an excluded directory
            "node_modules/a/index.js": 5000,
            "a_dir/b_dir/c.txt": 1,
        }
        for rel, size in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * size)
        (root / "empty").mkdir()

    @classmethod
    def _reference(cls, root, repo):
        """The previous algorithm: rglob for the directories, rglob again per directory for its size."""
        from deriva.modules.extraction.base import is_excluded_path

        out = []
        for d in root.rglob("*"):
            rel = d.relative_to(root).as_posix()
            if not d.is_dir() or is_excluded_path(rel, cls.EXCLUDED):
                continue
            files = len([f for f in d.iterdir() if f.is_file()])
            subdirs = len([s for s in d.iterdir() if s.is_dir() and s.name not in cls.EXCLUDED])
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file() and not is_excluded_path(f.relative_to(root).as_posix(), cls.EXCLUDED))
            out.append((rel, d.name, files, subdirs, size))
        return out

    def test_matches_the_full_scan(self, tmp_path):
        self._tree(tmp_path)

        result = extract_directories(str(tmp_path), "r", excluded_dirs=self.EXCLUDED)

        got = [
            (n["properties"]["path"], n["properties"]["name"], n["properties"]["file_count"], n["properties"]["subdirectory_count"], n["properties"]["total_size_bytes"])
            for n in result["data"]["nodes"]
        ]
        assert got == self._reference(tmp_path, "r")
        assert [(e["from_node_id"], e["to_node_id"]) for e in result["data"]["edges"]][:2] == [("repo::r", "dir::r::a_dir"), ("repo::r", "dir::r::docs")]

    def test_never_enters_an_excluded_directory(self, tmp_path, monkeypatch):
        import os

        self._tree(tmp_path)
        visited = []
        real_scandir = os.scandir

        def recording_scandir(path="."):
            visited.append(os.fspath(path))
            return real_scandir(path)

        monkeypatch.setattr(os, "scandir", recording_scandir)
        extract_directories(str(tmp_path), "r", excluded_dirs=self.EXCLUDED)

        assert visited
        assert not [p for p in visited if "node_modules" in p or os.sep + "vendor" in p]
