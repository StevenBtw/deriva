"""Tests for modules.extraction.method module."""

from __future__ import annotations

from unittest.mock import MagicMock

from deriva.modules.extraction.method import (
    METHOD_SCHEMA,
    build_extraction_prompt,
    build_method_node,
    extract_methods,
    extract_methods_batch,
    extract_methods_from_source,
    parse_llm_response,
)

PROMPT_TEXTS = {"persona": "Analyze the source.", "task": "Extract the items."}


class TestMethodSchema:
    """Tests for METHOD_SCHEMA constant."""

    def test_schema_has_name(self):
        """Should have a name field."""
        assert "name" in METHOD_SCHEMA
        assert METHOD_SCHEMA["name"] == "methods_extraction"

    def test_schema_is_strict(self):
        """Should be strict mode."""
        assert METHOD_SCHEMA["strict"] is True

    def test_schema_has_methods_array(self):
        """Should define methods array in schema."""
        assert "properties" in METHOD_SCHEMA["schema"]  # type: ignore[operator]
        assert "methods" in METHOD_SCHEMA["schema"]["properties"]  # type: ignore[operator]

    def test_methods_item_has_required_fields(self):
        """Method items should have required fields."""
        method_schema = METHOD_SCHEMA["schema"]["properties"]["methods"]["items"]  # type: ignore[index]
        required = method_schema["required"]  # type: ignore[index]

        assert "methodName" in required  # type: ignore[operator]
        assert "returnType" in required  # type: ignore[operator]
        assert "visibility" in required  # type: ignore[operator]
        assert "parameters" in required  # type: ignore[operator]


class TestBuildExtractionPrompt:
    """Tests for build_extraction_prompt function."""

    def test_includes_type_info(self):
        """Should include type information in prompt."""
        prompt = build_extraction_prompt(
            code_snippet="class MyClass:\n    pass",
            type_name="MyClass",
            type_category="class",
            file_path="src/my_file.py",
            instruction="Extract all methods",
            example='{"methods": []}',
            texts=PROMPT_TEXTS,
        )

        assert "MyClass" in prompt
        assert "class" in prompt
        assert "src/my_file.py" in prompt

    def test_includes_line_numbers(self):
        """Should add line numbers to code snippet."""
        prompt = build_extraction_prompt(
            code_snippet="line1\nline2\nline3",
            type_name="Test",
            type_category="class",
            file_path="test.py",
            instruction="",
            example="",
            texts=PROMPT_TEXTS,
        )

        assert "1 |" in prompt
        assert "2 |" in prompt
        assert "3 |" in prompt

    def test_includes_instruction_and_example(self):
        """Should include instruction and example."""
        prompt = build_extraction_prompt(
            code_snippet="code",
            type_name="Test",
            type_category="class",
            file_path="test.py",
            instruction="Custom instruction here",
            example='{"methods": [{"name": "test"}]}',
            texts=PROMPT_TEXTS,
        )

        assert "Custom instruction here" in prompt
        assert '{"methods":' in prompt


class TestBuildMethodNode:
    """Tests for build_method_node function."""

    def test_builds_valid_node(self):
        """Should build a valid method node."""
        result = build_method_node(
            method_data={
                "methodName": "get_user",
                "returnType": "User",
                "visibility": "public",
                "parameters": "self, user_id: int",
                "description": "Gets a user",
                "isStatic": False,
                "isAsync": False,
                "startLine": 10,
                "endLine": 15,
                "confidence": 0.9,
            },
            type_name="UserService",
            file_path="src/user_service.py",
            repo_name="my_repo",
            type_start_line=5,
        )

        assert result["success"] is True
        assert result["data"]["label"] == "Method"
        assert result["data"]["properties"]["methodName"] == "get_user"
        assert result["data"]["properties"]["returnType"] == "User"
        assert result["data"]["properties"]["visibility"] == "public"

    def test_generates_unique_node_id(self):
        """Should generate unique node ID."""
        result = build_method_node(
            method_data={
                "methodName": "my_method",
                "returnType": "str",
                "visibility": "private",
            },
            type_name="MyClass",
            file_path="src/module.py",
            repo_name="test_repo",
        )

        node_id = result["data"]["node_id"]
        assert "method::test_repo" in node_id
        assert "MyClass" in node_id
        assert "my_method" in node_id

    def test_returns_error_for_missing_fields(self):
        """Should return error when required fields missing."""
        result = build_method_node(
            method_data={"methodName": "test"},  # Missing returnType, visibility
            type_name="Test",
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert "returnType" in result["errors"][0] or "visibility" in result["errors"][0]

    def test_normalizes_invalid_visibility(self):
        """Should normalize invalid visibility to public."""
        result = build_method_node(
            method_data={
                "methodName": "test",
                "returnType": "void",
                "visibility": "invalid",
            },
            type_name="Test",
            file_path="test.py",
            repo_name="repo",
        )

        assert result["success"] is True
        assert result["data"]["properties"]["visibility"] == "public"

    def test_handles_default_values(self):
        """Should use default values for optional fields."""
        result = build_method_node(
            method_data={
                "methodName": "test",
                "returnType": "void",
                "visibility": "public",
            },
            type_name="Test",
            file_path="test.py",
            repo_name="repo",
        )

        props = result["data"]["properties"]
        assert props["parameters"] == ""
        assert props["description"] == ""
        assert props["isStatic"] is False
        assert props["isAsync"] is False
        assert props["confidence"] == 0.8


class TestParseLlmResponse:
    """Tests for parse_llm_response function."""

    def test_parses_valid_json(self):
        """Should parse valid JSON response."""
        result = parse_llm_response('{"methods": [{"methodName": "test", "returnType": "void"}]}')

        assert result["success"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["methodName"] == "test"

    def test_returns_error_for_invalid_json(self):
        """Should return error for invalid JSON."""
        result = parse_llm_response("not valid json")

        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_returns_empty_for_empty_methods(self):
        """Should return empty list for empty methods array."""
        result = parse_llm_response('{"methods": []}')

        assert result["success"] is True
        assert result["data"] == []


class TestExtractMethods:
    """Tests for extract_methods function."""

    def test_skips_empty_code_snippet(self):
        """Should skip nodes with empty code snippet."""
        result = extract_methods(
            type_node={"properties": {"codeSnippet": ""}},
            repo_name="test",
            llm_query_fn=MagicMock(),
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is True
        assert result["stats"]["skipped"] == "no_code_snippet"

    def test_calls_llm_with_prompt(self):
        """Should call LLM with built prompt."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"methods": []}'
        mock_response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        mock_response.response_type = "ResponseType.NEW"
        mock_llm.return_value = mock_response

        extract_methods(
            type_node={
                "node_id": "type_1",
                "properties": {
                    "typeName": "MyClass",
                    "category": "class",
                    "filePath": "test.py",
                    "codeSnippet": "class MyClass:\n    pass",
                },
            },
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"instruction": "Extract methods", "example": "{}", "params": {"prompt": PROMPT_TEXTS}},
        )

        mock_llm.assert_called_once()
        prompt = mock_llm.call_args[0][0]
        assert "MyClass" in prompt

    def test_handles_llm_error(self):
        """Should handle LLM error response."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.error = "API rate limit exceeded"
        mock_llm.return_value = mock_response

        result = extract_methods(
            type_node={
                "node_id": "type_1",
                "properties": {
                    "codeSnippet": "class Test: pass",
                },
            },
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False
        assert "LLM error" in result["errors"][0]

    def test_handles_exception(self):
        """Should handle exception during extraction."""
        mock_llm = MagicMock(side_effect=Exception("Connection error"))

        result = extract_methods(
            type_node={
                "node_id": "type_1",
                "properties": {"codeSnippet": "class Test: pass"},
            },
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["success"] is False
        assert "Fatal error" in result["errors"][0]

    def test_creates_contains_edges(self):
        """Should create CONTAINS edges from type to methods."""
        mock_llm = MagicMock()
        mock_response = MagicMock(spec=["content", "usage", "response_type"])
        mock_response.content = """{"methods": [
            {"methodName": "test", "returnType": "void", "visibility": "public",
             "parameters": "", "description": "", "isStatic": false, "isAsync": false,
             "startLine": 1, "endLine": 2, "confidence": 0.9}
        ]}"""
        mock_response.usage = None
        mock_response.response_type = "ResponseType.NEW"
        mock_llm.return_value = mock_response

        result = extract_methods(
            type_node={
                "node_id": "type_test",
                "properties": {
                    "typeName": "Test",
                    "codeSnippet": "def test(): pass",
                },
            },
            repo_name="repo",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert len(result["data"]["edges"]) == 1
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "CONTAINS"
        assert edge["from_node_id"] == "type_test"


class TestExtractMethodsBatch:
    """Tests for extract_methods_batch function."""

    def test_processes_multiple_types(self):
        """Should process multiple type nodes."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"methods": []}'
        mock_response.usage = None
        mock_llm.return_value = mock_response

        result = extract_methods_batch(
            type_nodes=[
                {"node_id": "t1", "properties": {"typeName": "A", "codeSnippet": "code"}},
                {"node_id": "t2", "properties": {"typeName": "B", "codeSnippet": "code"}},
            ],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert result["stats"]["types_processed"] == 2
        assert mock_llm.call_count == 2

    def test_calls_progress_callback(self):
        """Should call progress callback during processing."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"methods": []}'
        mock_response.usage = None
        mock_llm.return_value = mock_response

        progress_calls = []

        def progress_cb(current, total, name):
            progress_calls.append((current, total, name))

        extract_methods_batch(
            type_nodes=[
                {"node_id": "t1", "properties": {"typeName": "TypeA", "codeSnippet": "c"}},
            ],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
            progress_callback=progress_cb,
        )

        assert len(progress_calls) == 1
        assert progress_calls[0] == (1, 1, "TypeA")

    def test_aggregates_results(self):
        """Should aggregate results from all types."""
        mock_llm = MagicMock()
        mock_response = MagicMock(spec=["content", "usage", "response_type"])
        mock_response.content = """{"methods": [
            {"methodName": "m1", "returnType": "void", "visibility": "public",
             "parameters": "", "description": "", "isStatic": false, "isAsync": false,
             "startLine": 1, "endLine": 2, "confidence": 0.9}
        ]}"""
        mock_response.usage = None
        mock_response.response_type = "ResponseType.NEW"
        mock_llm.return_value = mock_response

        result = extract_methods_batch(
            type_nodes=[
                {"node_id": "t1", "properties": {"typeName": "A", "codeSnippet": "code"}},
                {"node_id": "t2", "properties": {"typeName": "B", "codeSnippet": "code"}},
            ],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        # Each type produces 1 method
        assert result["stats"]["total_nodes"] == 2
        assert result["stats"]["types_with_methods"] == 2

    def test_includes_type_results(self):
        """Should include per-type results for logging."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"methods": []}'
        mock_response.usage = None
        mock_llm.return_value = mock_response

        result = extract_methods_batch(
            type_nodes=[
                {"node_id": "t1", "properties": {"typeName": "A", "codeSnippet": "c"}},
            ],
            repo_name="test",
            llm_query_fn=mock_llm,
            config={"params": {"prompt": PROMPT_TEXTS}},
        )

        assert "type_results" in result
        assert len(result["type_results"]) == 1
        assert result["type_results"][0]["type_name"] == "A"


class TestExtractMethodsFromSource:
    """Tests for extract_methods_from_source function."""

    def test_extracts_python_methods(self):
        """Should extract methods from Python source."""
        source = '''
class UserService:
    def get_user(self, user_id: int) -> User:
        """Get a user by ID."""
        pass

    def _private_method(self):
        pass
'''
        result = extract_methods_from_source(
            file_path="src/user_service.py",
            file_content=source,
            repo_name="test_repo",
        )

        assert result["success"] is True
        assert result["stats"]["total_nodes"] >= 2
        method_names = [n["properties"]["methodName"] for n in result["data"]["nodes"]]
        assert "get_user" in method_names
        assert "_private_method" in method_names

    def test_handles_top_level_functions(self):
        """Should extract top-level functions."""
        source = """
def standalone_function():
    pass
"""
        result = extract_methods_from_source(
            file_path="utils.py",
            file_content=source,
            repo_name="test",
        )

        assert result["success"] is True
        assert len(result["data"]["nodes"]) >= 1

    def test_determines_visibility(self):
        """Should determine visibility from naming conventions."""
        source = """
class Test:
    def public_method(self): pass
    def _private_method(self): pass
    def __protected_method(self): pass
"""
        result = extract_methods_from_source(
            file_path="test.py",
            file_content=source,
            repo_name="test",
        )

        nodes = result["data"]["nodes"]
        visibilities = {n["properties"]["methodName"]: n["properties"]["visibility"] for n in nodes}

        assert visibilities.get("public_method") == "public"
        assert visibilities.get("_private_method") == "private"
        assert visibilities.get("__protected_method") == "protected"

    def test_handles_syntax_error(self):
        """Should handle syntax errors gracefully."""
        result = extract_methods_from_source(
            file_path="bad.py",
            file_content="def broken(",
            repo_name="test",
        )

        # May or may not succeed depending on tree-sitter tolerance
        # Just ensure it doesn't crash
        assert "success" in result

    def test_creates_contains_edges(self):
        """Should create CONTAINS edges."""
        source = """
class MyClass:
    def my_method(self):
        pass
"""
        result = extract_methods_from_source(
            file_path="test.py",
            file_content=source,
            repo_name="repo",
        )

        assert len(result["data"]["edges"]) >= 1
        edge = result["data"]["edges"][0]
        assert edge["relationship_type"] == "CONTAINS"

    def test_extraction_method_is_treesitter(self):
        """Should set extraction_method to treesitter."""
        result = extract_methods_from_source(
            file_path="test.py",
            file_content="def f(): pass",
            repo_name="test",
        )

        assert result["stats"]["extraction_method"] == "treesitter"
