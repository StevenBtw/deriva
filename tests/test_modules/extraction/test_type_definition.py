"""Tests for modules.extraction.type_definition module."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from deriva.modules.extraction.type_definition import (
    TYPE_DEFINITION_SCHEMA,
    base_type_name,
    build_extraction_prompt,
    build_type_definition_node,
    extract_type_definitions,
    extract_type_definitions_batch,
    extract_types_from_source,
    parse_llm_response,
    resolve_base_type,
)

PROMPT_TEXTS = {"persona": "Analyze the source.", "task": "Extract the items."}


class TestBaseTypeResolution:
    """An inheritance reference resolves to the repository's own type of that name, decided by structure."""

    def test_the_name_drops_type_arguments(self):
        assert base_type_name("Renderer<Circle.Options>") == "Renderer"
        assert base_type_name("Generic[T]") == "Generic"
        assert base_type_name(" Shape ") == "Shape"

    def test_a_qualified_name_has_no_key(self):
        # A module or package prefix names one specific type: its last part alone must not match
        assert base_type_name("widgets.Shape") is None

    def test_resolves_to_the_only_definition(self):
        definitions = {"Shape": ["typedef::r::shapes_Shape.java::Shape"]}

        assert resolve_base_type("Shape", definitions, source_id="typedef::r::shapes_Circle.java::Circle") == "typedef::r::shapes_Shape.java::Shape"

    def test_type_arguments_do_not_block_resolution(self):
        definitions = {"Renderer": ["typedef::r::Renderer.java::Renderer"]}

        assert resolve_base_type("Renderer<Circle>", definitions, source_id="typedef::r::Circle.java::Circle") == "typedef::r::Renderer.java::Renderer"

    def test_no_definition_or_several_leave_it_unresolved(self):
        definitions = {"Shape": ["typedef::r::a_Shape.java::Shape", "typedef::r::b_Shape.java::Shape"]}

        assert resolve_base_type("Shape", definitions, source_id="typedef::r::Circle.java::Circle") is None
        assert resolve_base_type("Serializable", definitions, source_id="typedef::r::Circle.java::Circle") is None

    def test_never_resolves_to_the_extending_type_itself(self):
        definitions = {"Shape": ["typedef::r::Shape.java::Shape"]}

        assert resolve_base_type("Shape", definitions, source_id="typedef::r::Shape.java::Shape") is None


class TestTypeDefinitionSchema:
    """Tests for TYPE_DEFINITION_SCHEMA."""

    def test_schema_has_required_structure(self):
        """Should have correct schema structure."""
        assert "name" in TYPE_DEFINITION_SCHEMA
        assert "strict" in TYPE_DEFINITION_SCHEMA
        assert "schema" in TYPE_DEFINITION_SCHEMA
        assert TYPE_DEFINITION_SCHEMA["strict"] is True

    def test_schema_has_types_array(self):
        """Should require types array."""
        schema = cast(dict[str, Any], TYPE_DEFINITION_SCHEMA["schema"])
        assert schema["type"] == "object"
        properties = cast(dict[str, Any], schema["properties"])
        assert "types" in properties
        types_schema = cast(dict[str, Any], properties["types"])
        assert types_schema["type"] == "array"

    def test_type_item_schema_has_required_fields(self):
        """Should require all necessary fields in type items."""
        schema = cast(dict[str, Any], TYPE_DEFINITION_SCHEMA["schema"])
        properties = cast(dict[str, Any], schema["properties"])
        types_schema = cast(dict[str, Any], properties["types"])
        item_schema = cast(dict[str, Any], types_schema["items"])
        required = cast(list[str], item_schema["required"])
        assert "typeName" in required
        assert "category" in required
        assert "description" in required
        assert "interfaceType" in required
        assert "startLine" in required
        assert "endLine" in required
        assert "confidence" in required


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_file_path(self):
        """Should include file path in prompt."""
        prompt = build_extraction_prompt(
            file_content="class User: pass",
            file_path="src/models/user.py",
            instruction="Extract types",
            example="{}",
            texts=PROMPT_TEXTS,
        )
        assert "src/models/user.py" in prompt

    def test_includes_instruction(self):
        """Should include instruction in prompt."""
        instruction = "Extract all class and function definitions"
        prompt = build_extraction_prompt(
            file_content="class User: pass",
            file_path="test.py",
            instruction=instruction,
            example="{}",
            texts=PROMPT_TEXTS,
        )
        assert instruction in prompt

    def test_includes_example(self):
        """Should include example in prompt."""
        example = '{"types": [{"typeName": "User"}]}'
        prompt = build_extraction_prompt(
            file_content="class User: pass",
            file_path="test.py",
            instruction="Extract types",
            example=example,
            texts=PROMPT_TEXTS,
        )
        assert example in prompt

    def test_includes_numbered_content(self):
        """Should include line-numbered file content."""
        prompt = build_extraction_prompt(
            file_content="class User:\n    pass",
            file_path="test.py",
            instruction="Extract types",
            example="{}",
            texts=PROMPT_TEXTS,
        )
        # Should have line numbers
        assert "1 |" in prompt or "   1" in prompt


class TestBuildTypeDefinitionNode:
    """Tests for build_type_definition_node function."""

    def test_builds_node_with_valid_data(self):
        """Should build node with valid type data."""
        type_data = {
            "typeName": "UserService",
            "category": "class",
            "description": "Handles user operations",
            "interfaceType": "REST API",
            "startLine": 10,
            "endLine": 50,
            "confidence": 0.95,
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="src/services/user.py",
            repo_name="myapp",
            file_content="",
        )

        assert result["success"] is True
        assert result["data"]["label"] == "TypeDefinition"
        assert result["data"]["properties"]["typeName"] == "UserService"
        assert result["data"]["properties"]["category"] == "class"
        assert result["data"]["properties"]["interfaceType"] == "REST API"

    def test_returns_error_for_missing_type_name(self):
        """Should return error when typeName is missing."""
        type_data = {
            "category": "class",
            "description": "Some class",
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is False
        assert any("typeName" in e for e in result["errors"])

    def test_returns_error_for_missing_category(self):
        """Should return error when category is missing."""
        type_data = {
            "typeName": "User",
            "description": "A user class",
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is False
        assert any("category" in e for e in result["errors"])

    def test_returns_error_for_missing_description(self):
        """Should return error when description is missing."""
        type_data = {
            "typeName": "User",
            "category": "class",
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is False
        assert any("description" in e for e in result["errors"])

    def test_normalizes_invalid_category(self):
        """Should normalize invalid category to 'other'."""
        type_data = {
            "typeName": "User",
            "category": "INVALID_CATEGORY",
            "description": "A class",
            "interfaceType": "none",
            "startLine": 1,
            "endLine": 10,
            "confidence": 0.9,
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is True
        assert result["data"]["properties"]["category"] == "other"

    def test_normalizes_invalid_interface_type(self):
        """Should normalize invalid interface type to 'none'."""
        type_data = {
            "typeName": "User",
            "category": "class",
            "description": "A class",
            "interfaceType": "INVALID_TYPE",
            "startLine": 1,
            "endLine": 10,
            "confidence": 0.9,
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is True
        # interfaceType should be None when normalized to 'none'
        assert result["data"]["properties"]["interfaceType"] is None

    def test_extracts_code_snippet(self):
        """Should extract code snippet from file content."""
        file_content = "line1\nline2\nclass User:\n    pass\nline5"
        type_data = {
            "typeName": "User",
            "category": "class",
            "description": "A class",
            "startLine": 3,
            "endLine": 4,
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
            file_content=file_content,
        )

        assert result["success"] is True
        assert "class User:" in result["data"]["properties"]["codeSnippet"]
        assert "pass" in result["data"]["properties"]["codeSnippet"]

    def test_handles_missing_line_numbers(self):
        """Should handle missing line numbers gracefully."""
        type_data = {
            "typeName": "User",
            "category": "class",
            "description": "A class",
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="test.py",
            repo_name="repo",
            file_content="class User: pass",
        )

        assert result["success"] is True
        assert result["data"]["properties"]["startLine"] == 0
        assert result["data"]["properties"]["endLine"] == 0

    def test_generates_unique_node_id(self):
        """Should generate unique node ID."""
        type_data = {
            "typeName": "UserService",
            "category": "class",
            "description": "Service class",
        }
        result = build_type_definition_node(
            type_data=type_data,
            file_path="src/services/user.py",
            repo_name="myapp",
        )

        assert result["success"] is True
        node_id = result["data"]["node_id"]
        assert "typedef::" in node_id
        assert "myapp" in node_id
        assert "UserService" in node_id


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_parses_valid_response(self):
        """Should parse valid JSON response."""
        response = '{"types": [{"typeName": "User", "category": "class"}]}'
        result = parse_llm_response(response)

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["typeName"] == "User"

    def test_handles_empty_types_array(self):
        """Should handle empty types array."""
        response = '{"types": []}'
        result = parse_llm_response(response)

        assert result["success"] is True
        assert result["data"] == []

    def test_returns_error_for_invalid_json(self):
        """Should return error for invalid JSON."""
        response = "not valid json"
        result = parse_llm_response(response)

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_returns_error_for_missing_types_key(self):
        """Should return error when types key is missing."""
        response = '{"data": []}'
        result = parse_llm_response(response)

        assert result["success"] is False


class TestExtractTypeDefinitions:
    """Tests for extract_type_definitions function."""

    def test_extracts_types_successfully(self):
        """Should extract types from file content."""

        class MockResponse:
            content = (
                '{"types": [{"typeName": "User", "category": "class", "description": "User model", "interfaceType": "none", "startLine": 1, "endLine": 3, "confidence": 0.9}]}'
            )
            usage = {"prompt_tokens": 100, "completion_tokens": 50}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="models/user.py",
            file_content="class User:\n    pass",
            repo_name="myapp",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 1
        assert len(result["data"]["edges"]) == 1
        assert result["data"]["nodes"][0]["properties"]["typeName"] == "User"

    def test_handles_llm_error(self):
        """Should handle LLM error response."""

        class MockErrorResponse:
            content = ""
            error = "Rate limit exceeded"

        mock_llm_fn = MagicMock(return_value=MockErrorResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="test.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert result["success"] is False
        assert any("LLM error" in e for e in result["errors"])

    def test_handles_parse_error(self):
        """Should handle parse error gracefully."""

        class MockResponse:
            content = "invalid json"
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="test.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert result["success"] is False
        assert "parse_error" in result["stats"]

    def test_handles_node_build_error(self):
        """Should handle node build errors."""

        class MockResponse:
            content = '{"types": [{"typeName": "", "category": "class", "description": ""}]}'
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="test.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        # Should have errors from node building
        assert len(result["errors"]) > 0

    def test_records_llm_details(self):
        """Should record LLM call details."""

        class MockResponse:
            content = '{"types": []}'
            usage = {"prompt_tokens": 100, "completion_tokens": 50}
            response_type = "ResponseType.CACHED"

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="test.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert "llm_details" in result
        assert result["llm_details"]["tokens_in"] == 100
        assert result["llm_details"]["tokens_out"] == 50

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        mock_llm_fn = MagicMock(side_effect=RuntimeError("Connection failed"))
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="test.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert result["success"] is False
        assert any("Fatal error" in e for e in result["errors"])

    def test_creates_edges_with_file_path(self):
        """Should create CONTAINS edges with proper file node ID."""

        class MockResponse:
            content = (
                '{"types": [{"typeName": "User", "category": "class", "description": "User class", "interfaceType": "none", "startLine": 1, "endLine": 2, "confidence": 0.9}]}'
            )
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions(
            file_path="models/user.py",
            file_content="class User: pass",
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        # Should create edges
        assert result["success"] is True
        if result["data"]["edges"]:
            edge = result["data"]["edges"][0]
            assert "file::" in edge["from_node_id"]
            assert "typedef::" in edge["to_node_id"]
            assert edge["relationship_type"] == "CONTAINS"


class TestExtractTypeDefinitionsBatch:
    """Tests for extract_type_definitions_batch function."""

    def test_processes_multiple_files(self):
        """Should process multiple files."""

        class MockResponse:
            content = '{"types": [{"typeName": "User", "category": "class", "description": "User", "interfaceType": "none", "startLine": 1, "endLine": 1, "confidence": 0.9}]}'
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}
        files = [
            {"path": "user.py", "content": "class User: pass"},
            {"path": "order.py", "content": "class Order: pass"},
        ]

        result = extract_type_definitions_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert result["success"] is True
        assert result["stats"]["files_processed"] == 2
        assert len(result["data"]["nodes"]) == 2

    def test_calls_progress_callback(self):
        """Should call progress callback for each file."""

        class MockResponse:
            content = '{"types": []}'
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        progress_calls: list[tuple[int, int, str]] = []

        def progress_callback(current: int, total: int, path: str) -> None:
            progress_calls.append((current, total, path))

        files = [
            {"path": "a.py", "content": ""},
            {"path": "b.py", "content": ""},
        ]
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        extract_type_definitions_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
            progress_callback=progress_callback,
        )

        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "a.py")
        assert progress_calls[1] == (2, 2, "b.py")

    def test_aggregates_errors_per_file(self):
        """Should aggregate errors with file path context."""

        class MockResponse:
            content = "invalid"
            usage = {}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        files = [
            {"path": "broken.py", "content": ""},
        ]
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        # Errors should include file path
        assert any("broken.py" in e for e in result["errors"])

    def test_returns_file_results_with_llm_details(self):
        """Should return per-file results with LLM details."""

        class MockResponse:
            content = '{"types": []}'
            usage = {"prompt_tokens": 50, "completion_tokens": 10}

        mock_llm_fn = MagicMock(return_value=MockResponse())
        files = [
            {"path": "test.py", "content": ""},
        ]
        config = {"instruction": "Extract types", "example": "{}", "params": {"prompt": PROMPT_TEXTS}}

        result = extract_type_definitions_batch(
            files=files,
            repo_name="repo",
            llm_query_fn=mock_llm_fn,
            config=config,
        )

        assert "file_results" in result
        assert len(result["file_results"]) == 1
        assert result["file_results"][0]["file_path"] == "test.py"
        assert "llm_details" in result["file_results"][0]


class TestExtractTypesFromSource:
    """Tests for extract_types_from_source function."""

    def test_extracts_python_class(self):
        """Should extract Python class using tree-sitter."""
        file_content = '''class UserService:
    """Handles user operations."""

    def get_user(self, user_id: int):
        pass
'''
        result = extract_types_from_source(
            file_path="services/user.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) >= 1
        assert result["stats"]["extraction_method"] == "treesitter"

        # Find the UserService class
        user_service = next(
            (n for n in result["data"]["nodes"] if n["properties"]["typeName"] == "UserService"),
            None,
        )
        assert user_service is not None
        assert user_service["properties"]["category"] == "class"

    def test_extracts_python_function(self):
        """Should extract top-level Python function as type."""
        file_content = '''def process_data(items: list) -> list:
    """Process a list of items."""
    return [item * 2 for item in items]
'''
        result = extract_types_from_source(
            file_path="utils.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        # Should extract the function
        func_node = next(
            (n for n in result["data"]["nodes"] if n["properties"]["typeName"] == "process_data"),
            None,
        )
        assert func_node is not None
        assert func_node["properties"]["category"] == "function"

    def test_creates_contains_edges(self):
        """Should create CONTAINS edges from file to types."""
        file_content = "class User: pass"
        result = extract_types_from_source(
            file_path="models/user.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        assert len(result["data"]["edges"]) >= 1

        # Check edge structure
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "CONTAINS"
        assert "file::" in edge["from_node_id"]
        assert "typedef::" in edge["to_node_id"]

    def test_creates_inherits_edges_for_base_classes(self):
        """Should create INHERITS edges for base classes."""
        file_content = '''class Admin(User):
    """Admin user class."""
    pass
'''
        result = extract_types_from_source(
            file_path="models/admin.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True

        # Find INHERITS edge
        inherits_edges = [e for e in result["data"]["edges"] if e["relationship_type"] == "INHERITS"]
        assert len(inherits_edges) == 1
        assert inherits_edges[0]["properties"]["base_name"] == "User"

    def test_skips_builtin_base_classes(self):
        """Should skip built-in base classes like object and Exception."""
        file_content = '''class CustomError(Exception):
    """Custom exception."""
    pass
'''
        result = extract_types_from_source(
            file_path="errors.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True

        # Should not have INHERITS edge for Exception
        inherits_edges = [e for e in result["data"]["edges"] if e["relationship_type"] == "INHERITS"]
        assert len(inherits_edges) == 0

    def test_handles_empty_file(self):
        """Should handle empty file."""
        result = extract_types_from_source(
            file_path="empty.py",
            file_content="",
            repo_name="myapp",
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) == 0

    def test_handles_syntax_errors(self):
        """Should handle files with syntax errors."""
        file_content = "class Broken {"  # Invalid Python
        result = extract_types_from_source(
            file_path="broken.py",
            file_content=file_content,
            repo_name="myapp",
        )

        # Tree-sitter is error tolerant so it may still extract something
        # Just verify it doesn't crash
        assert isinstance(result, dict)
        assert "success" in result

    def test_includes_decorators(self):
        """Should include decorator information."""
        file_content = """@dataclass
class Config:
    name: str
"""
        result = extract_types_from_source(
            file_path="config.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        config_node = next(
            (n for n in result["data"]["nodes"] if n["properties"]["typeName"] == "Config"),
            None,
        )
        assert config_node is not None
        assert "decorators" in config_node["properties"]

    def test_includes_docstring(self):
        """Should include docstring as description."""
        file_content = '''class UserService:
    """Handles user-related operations."""
    pass
'''
        result = extract_types_from_source(
            file_path="services.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        service_node = next(
            (n for n in result["data"]["nodes"] if n["properties"]["typeName"] == "UserService"),
            None,
        )
        assert service_node is not None
        assert "user-related" in service_node["properties"]["description"].lower()

    def test_javascript_extraction(self):
        """Should extract JavaScript classes."""
        file_content = """class UserService {
    constructor() {
        this.users = [];
    }

    getUser(id) {
        return this.users.find(u => u.id === id);
    }
}
"""
        result = extract_types_from_source(
            file_path="services/user.js",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) >= 1

    def test_sets_confidence_to_one(self):
        """Should set confidence to 1.0 for tree-sitter extraction."""
        file_content = "class User: pass"
        result = extract_types_from_source(
            file_path="user.py",
            file_content=file_content,
            repo_name="myapp",
        )

        assert result["success"] is True
        for node in result["data"]["nodes"]:
            assert node["properties"]["confidence"] == 1.0
