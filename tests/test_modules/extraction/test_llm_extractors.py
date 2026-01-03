"""Tests for LLM-based extraction modules."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from deriva.modules.extraction import (
    business_concept,
    external_dependency,
    method,
    technology,
    type_definition,
)
from deriva.modules.extraction import (
    test as test_module,
)


class TestBusinessConceptModule:
    """Tests for business_concept extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = business_concept.BUSINESS_CONCEPT_SCHEMA

        assert "name" in schema
        assert schema["name"] == "business_concepts_extraction"
        assert "schema" in schema
        assert schema["schema"]["type"] == "object"
        assert "concepts" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = business_concept.build_extraction_prompt(
            file_content="# Business Overview\n\nThis is a user service.",
            file_path="docs/overview.md",
            instruction="Extract business concepts from documentation",
            example='{"concepts": [{"conceptName": "User", "conceptType": "entity"}]}',
        )

        assert "docs/overview.md" in prompt
        assert "Business Overview" in prompt
        assert "Extract business concepts" in prompt
        assert '"conceptName"' in prompt

    def test_build_business_concept_node_success(self):
        """Should build valid node from concept data."""
        concept_data = {
            "conceptName": "User Authentication",
            "conceptType": "service",
            "description": "Handles user login and session management",
            "confidence": 0.9,
        }

        result = business_concept.build_business_concept_node(
            concept_data, "auth.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "BusinessConcept"
        assert result["data"]["properties"]["conceptName"] == "User Authentication"
        assert result["data"]["properties"]["conceptType"] == "service"

    def test_build_business_concept_node_missing_field(self):
        """Should fail when required field is missing."""
        concept_data = {
            "conceptType": "service",
            "description": "Some description",
        }

        result = business_concept.build_business_concept_node(
            concept_data, "auth.py", "myrepo"
        )

        assert result["success"] is False
        assert any("conceptName" in e for e in result["errors"])

    def test_build_business_concept_node_invalid_type(self):
        """Should default to 'other' for invalid concept type."""
        concept_data = {
            "conceptName": "Something",
            "conceptType": "invalid_type",
            "description": "Some description",
        }

        result = business_concept.build_business_concept_node(
            concept_data, "file.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["properties"]["conceptType"] == "other"

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "concepts": [
                {"conceptName": "User", "conceptType": "entity", "description": "A user"}
            ]
        })

        result = business_concept.parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1

    def test_parse_llm_response_invalid_json(self):
        """Should handle invalid JSON gracefully."""
        response = "not valid json {"

        result = business_concept.parse_llm_response(response)

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_parse_llm_response_missing_concepts(self):
        """Should fail when concepts array is missing."""
        response = json.dumps({"data": []})

        result = business_concept.parse_llm_response(response)

        assert result["success"] is False


class TestTypeDefinitionModule:
    """Tests for type_definition extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = type_definition.TYPE_DEFINITION_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "types" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = type_definition.build_extraction_prompt(
            file_content="class UserModel:\n    pass",
            file_path="models/user.py",
            instruction="Extract type definitions",
            example='{"types": []}',
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

        result = type_definition.build_type_definition_node(
            type_data, "models/user.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "TypeDefinition"
        assert result["data"]["properties"]["typeName"] == "UserModel"

    def test_build_type_definition_node_missing_field(self):
        """Should fail when required field is missing."""
        type_data = {
            "typeCategory": "class",
        }

        result = type_definition.build_type_definition_node(
            type_data, "file.py", "myrepo"
        )

        assert result["success"] is False

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "types": [
                {"typeName": "User", "typeCategory": "class", "description": "User model"}
            ]
        })

        result = type_definition.parse_llm_response(response)

        assert result["success"] is True


class TestMethodModule:
    """Tests for method extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = method.METHOD_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "methods" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = method.build_extraction_prompt(
            code_snippet="def get_user(id: int) -> User:\n    pass",
            type_name="UserService",
            type_category="class",
            file_path="api/users.py",
            instruction="Extract methods",
            example='{"methods": []}',
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

        result = method.build_method_node(
            method_data, "api/users.py", "UserService", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "Method"
        assert result["data"]["properties"]["methodName"] == "get_user"

    def test_build_method_node_missing_field(self):
        """Should fail when required field is missing."""
        method_data = {
            "returnType": "User",
        }

        result = method.build_method_node(
            method_data, "file.py", "SomeClass", "myrepo"
        )

        assert result["success"] is False

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "methods": [
                {"methodName": "process", "returnType": "void", "visibility": "public"}
            ]
        })

        result = method.parse_llm_response(response)

        assert result["success"] is True


class TestTechnologyModule:
    """Tests for technology extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = technology.TECHNOLOGY_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "technologies" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = technology.build_extraction_prompt(
            file_content="import redis\nimport fastapi",
            file_path="app/main.py",
            instruction="Extract technology references",
            example='{"technologies": []}',
        )

        assert "app/main.py" in prompt
        assert "import redis" in prompt

    def test_build_technology_node_success(self):
        """Should build valid node from technology data."""
        tech_data = {
            "techName": "Redis",
            "techCategory": "system_software",
            "description": "In-memory data store",
            "version": "7.0",
            "confidence": 0.95,
        }

        result = technology.build_technology_node(
            tech_data, "app/main.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "Technology"
        assert result["data"]["properties"]["techName"] == "Redis"

    def test_build_technology_node_missing_field(self):
        """Should fail when required field is missing."""
        tech_data = {
            "techCategory": "service",
        }

        result = technology.build_technology_node(
            tech_data, "file.py", "myrepo"
        )

        assert result["success"] is False

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "technologies": [
                {"techName": "FastAPI", "techCategory": "service", "description": "Web framework"}
            ]
        })

        result = technology.parse_llm_response(response)

        assert result["success"] is True


class TestExternalDependencyModule:
    """Tests for external_dependency extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = external_dependency.EXTERNAL_DEPENDENCY_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "dependencies" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = external_dependency.build_extraction_prompt(
            file_content='fastapi = "^0.100.0"\nredis = "^4.0.0"',
            file_path="pyproject.toml",
            instruction="Extract dependencies",
            example='{"dependencies": []}',
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

        result = external_dependency.build_external_dependency_node(
            dep_data, "pyproject.toml", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "ExternalDependency"
        assert result["data"]["properties"]["dependencyName"] == "FastAPI"
        assert result["data"]["properties"]["dependencyCategory"] == "library"

    def test_build_external_dependency_node_missing_field(self):
        """Should fail when required field is missing."""
        dep_data = {
            "dependencyCategory": "library",
        }

        result = external_dependency.build_external_dependency_node(
            dep_data, "file.py", "myrepo"
        )

        assert result["success"] is False
        assert any("dependencyName" in e for e in result["errors"])

    def test_build_external_dependency_node_invalid_category(self):
        """Should default to 'library' for invalid category."""
        dep_data = {
            "dependencyName": "Something",
            "dependencyCategory": "invalid_category",
            "description": "Some lib",
        }

        result = external_dependency.build_external_dependency_node(
            dep_data, "file.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["properties"]["dependencyCategory"] == "library"

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "dependencies": [
                {"dependencyName": "Redis", "dependencyCategory": "library", "description": "Cache"}
            ]
        })

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
        """Should fail when dependencies array is missing."""
        response = json.dumps({"data": []})

        result = external_dependency.parse_llm_response(response)

        assert result["success"] is False


class TestTestExtractionModule:
    """Tests for test extraction module."""

    def test_schema_has_required_structure(self):
        """Should have properly structured JSON schema."""
        schema = test_module.TEST_SCHEMA

        assert "name" in schema
        assert "schema" in schema
        assert "tests" in schema["schema"]["properties"]

    def test_build_extraction_prompt(self):
        """Should build prompt with all components."""
        prompt = test_module.build_extraction_prompt(
            file_content="def test_user_creation():\n    assert True",
            file_path="tests/test_user.py",
            instruction="Extract test definitions",
            example='{"tests": []}',
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

        result = test_module.build_test_node(
            test_data, "tests/test_user.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["label"] == "Test"
        assert result["data"]["properties"]["testName"] == "test_user_creation"
        assert result["data"]["properties"]["testType"] == "unit"

    def test_build_test_node_missing_field(self):
        """Should fail when required field is missing."""
        test_data = {
            "testType": "unit",
        }

        result = test_module.build_test_node(
            test_data, "tests/file.py", "myrepo"
        )

        assert result["success"] is False
        assert any("testName" in e for e in result["errors"])

    def test_build_test_node_invalid_type(self):
        """Should default to 'other' for invalid test type."""
        test_data = {
            "testName": "test_something",
            "testType": "invalid_type",
            "description": "Some test",
        }

        result = test_module.build_test_node(
            test_data, "tests/file.py", "myrepo"
        )

        assert result["success"] is True
        assert result["data"]["properties"]["testType"] == "other"

    def test_parse_llm_response_valid(self):
        """Should parse valid LLM response."""
        response = json.dumps({
            "tests": [
                {"testName": "test_foo", "testType": "unit", "description": "Tests foo"}
            ]
        })

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


class TestExtractBusinessConcepts:
    """Tests for extract_business_concepts function."""

    def test_extract_handles_llm_error_response(self):
        """Should handle LLM error responses (response with .error attribute)."""

        class ErrorResponse:
            error = "Rate limit exceeded"
            content = ""

        mock_llm = MagicMock(return_value=ErrorResponse())

        result = business_concept.extract_business_concepts(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is False
        assert any("LLM error" in e for e in result["errors"])
        assert result["stats"]["llm_error"] is True

    def test_extract_handles_parse_error(self):
        """Should handle parse errors from LLM response."""
        mock_response = MockLLMResponse({"invalid": "structure"})  # No 'concepts' key

        mock_llm = MagicMock(return_value=mock_response)

        result = business_concept.extract_business_concepts(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is False
        assert result["stats"]["parse_error"] is True

    def test_extract_handles_node_build_failure(self):
        """Should continue when some nodes fail to build."""
        # Missing required conceptName in second item
        mock_response = MockLLMResponse({
            "concepts": [
                {"conceptName": "Valid", "conceptType": "service", "description": "OK"},
                {"conceptType": "broken", "description": "Missing name"},
            ]
        })

        mock_llm = MagicMock(return_value=mock_response)

        result = business_concept.extract_business_concepts(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        # Should succeed with partial results
        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1
        assert len(result["errors"]) > 0  # Errors from failed node

    def test_extract_success(self):
        """Should extract concepts successfully with mocked LLM."""
        mock_response = MockLLMResponse(
            {
                "concepts": [
                    {
                        "conceptName": "UserService",
                        "conceptType": "service",
                        "description": "Handles user operations",
                        "confidence": 0.9,
                    }
                ]
            },
            usage={"prompt_tokens": 100, "completion_tokens": 50},
        )

        mock_llm = MagicMock(return_value=mock_response)

        result = business_concept.extract_business_concepts(
            file_path="services/user.py",
            file_content="class UserService:\n    pass",
            repo_name="myrepo",
            llm_query_fn=mock_llm,
            config={"instruction": "Extract concepts", "example": "{}"},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1
        assert result["data"]["nodes"][0]["label"] == "BusinessConcept"
        mock_llm.assert_called_once()

    def test_extract_handles_llm_error(self):
        """Should handle LLM errors gracefully."""
        mock_llm = MagicMock(side_effect=Exception("LLM failed"))

        result = business_concept.extract_business_concepts(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_extract_creates_edges(self):
        """Should create REFERENCES edges from File to concepts."""
        mock_response = MockLLMResponse({
            "concepts": [
                {"conceptName": "Auth", "conceptType": "service", "description": "Auth"}
            ]
        })

        mock_llm = MagicMock(return_value=mock_response)

        result = business_concept.extract_business_concepts(
            file_path="auth.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert len(result["data"]["edges"]) > 0
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "REFERENCES"


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
            config={"instruction": "Extract types"},
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
            config={},
        )

        assert result["success"] is False


class TestExtractMethods:
    """Tests for extract_methods function."""

    def test_extract_success(self):
        """Should extract methods successfully."""
        mock_response = MockLLMResponse({
            "methods": [
                {
                    "methodName": "get_user",
                    "returnType": "User",
                    "visibility": "public",
                    "parameters": [],
                    "description": "Gets a user",
                }
            ]
        })

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
            config={},
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
            config={},
        )

        assert result["success"] is False


class TestExtractTechnologies:
    """Tests for extract_technologies function."""

    def test_extract_success(self):
        """Should extract technologies successfully."""
        mock_response = MockLLMResponse(
            {
                "technologies": [
                    {
                        "techName": "Redis",
                        "techCategory": "system_software",
                        "description": "Cache",
                        "version": "7.0",
                    }
                ]
            },
            usage={"prompt_tokens": 20},
        )

        mock_llm = MagicMock(return_value=mock_response)

        result = technology.extract_technologies(
            file_path="main.py",
            file_content="import redis",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_handles_error(self):
        """Should handle extraction errors."""
        mock_llm = MagicMock(side_effect=Exception("API error"))

        result = technology.extract_technologies(
            file_path="file.py",
            file_content="code",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is False


class TestExtractExternalDependencies:
    """Tests for extract_external_dependencies function."""

    def test_extract_success(self):
        """Should extract dependencies successfully."""
        mock_response = MockLLMResponse({
            "dependencies": [
                {
                    "dependencyName": "FastAPI",
                    "dependencyCategory": "library",
                    "version": "0.100.0",
                    "ecosystem": "pypi",
                    "description": "Web framework",
                }
            ]
        })

        mock_llm = MagicMock(return_value=mock_response)

        result = external_dependency.extract_external_dependencies(
            file_path="pyproject.toml",
            file_content='fastapi = "^0.100.0"',
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1

    def test_extract_handles_error(self):
        """Should handle extraction errors."""
        mock_llm = MagicMock(side_effect=Exception("Timeout"))

        result = external_dependency.extract_external_dependencies(
            file_path="file.toml",
            file_content="content",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
        )

        assert result["success"] is False


class TestExtractTests:
    """Tests for extract_tests function."""

    def test_extract_success(self):
        """Should extract tests successfully."""
        mock_response = MockLLMResponse({
            "tests": [
                {
                    "testName": "test_login",
                    "testType": "unit",
                    "description": "Tests login",
                    "testedElement": "AuthService",
                    "framework": "pytest",
                }
            ]
        })

        mock_llm = MagicMock(return_value=mock_response)

        result = test_module.extract_tests(
            file_path="tests/test_auth.py",
            file_content="def test_login(): assert True",
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={},
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
            config={},
        )

        assert result["success"] is False
