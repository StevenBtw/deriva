"""Tests for common.json_utils module."""

from __future__ import annotations

from deriva.common.json_utils import (
    ParseResult,
    extract_json_from_response,
    parse_json_array,
)


class TestExtractJsonFromResponse:
    """Tests for extract_json_from_response function."""

    def test_extracts_from_markdown_code_block(self):
        """Should extract JSON from ```json ... ``` blocks."""
        content = '```json\n{"key": "value"}\n```'
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_extracts_from_bare_code_block(self):
        """Should extract JSON from ``` ... ``` blocks without language."""
        content = "```\n[1, 2, 3]\n```"
        result = extract_json_from_response(content)
        assert result == "[1, 2, 3]"

    def test_passes_through_raw_json_object(self):
        """Should pass through raw JSON objects."""
        content = '{"key": "value"}'
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_passes_through_raw_json_array(self):
        """Should pass through raw JSON arrays."""
        content = "[1, 2, 3]"
        result = extract_json_from_response(content)
        assert result == "[1, 2, 3]"

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        content = '  \n  {"key": "value"}  \n  '
        result = extract_json_from_response(content)
        assert result == '{"key": "value"}'

    def test_extracts_json_from_text(self):
        """Should extract JSON object embedded in text."""
        content = 'Here is the result: {"items": [1, 2]} end'
        result = extract_json_from_response(content)
        assert result == '{"items": [1, 2]}'


class TestParseResult:
    """Tests for ParseResult class."""

    def test_stores_success_data_errors(self):
        """Should store success, data, and errors."""
        result = ParseResult(True, [1, 2, 3], [])
        assert result.success is True
        assert result.data == [1, 2, 3]
        assert result.errors == []

    def test_to_dict_returns_dictionary(self):
        """Should convert to dictionary."""
        result = ParseResult(False, [], ["Error message"])
        d = result.to_dict()
        assert d == {"success": False, "data": [], "errors": ["Error message"]}


class TestParseJsonArray:
    """Tests for parse_json_array function."""

    def test_extracts_array_by_key(self):
        """Should extract array by specified key."""
        content = '{"items": [1, 2, 3]}'
        result = parse_json_array(content, "items")
        assert result.success is True
        assert result.data == [1, 2, 3]
        assert result.errors == []

    def test_handles_markdown_wrapped_json(self):
        """Should handle JSON wrapped in markdown."""
        content = '```json\n{"elements": ["a", "b"]}\n```'
        result = parse_json_array(content, "elements")
        assert result.success is True
        assert result.data == ["a", "b"]

    def test_returns_error_for_missing_key(self):
        """Should return error when key is missing."""
        content = '{"other": []}'
        result = parse_json_array(content, "items")
        assert result.success is False
        assert result.data == []
        assert 'missing "items" array' in result.errors[0]

    def test_returns_error_for_non_array_value(self):
        """Should return error when value is not array."""
        content = '{"items": "not an array"}'
        result = parse_json_array(content, "items")
        assert result.success is False
        assert '"items" must be an array' in result.errors[0]

    def test_returns_error_for_invalid_json(self):
        """Should return error for invalid JSON."""
        content = "not valid json"
        result = parse_json_array(content, "items")
        assert result.success is False
        assert "JSON parsing error" in result.errors[0]

    def test_handles_schema_wrapper_format(self):
        """Should handle GPT schema wrapper format."""
        content = '{"schema": {"concepts": [1, 2, 3]}}'
        result = parse_json_array(content, "concepts")
        assert result.success is True
        assert result.data == [1, 2, 3]

    def test_returns_empty_array_on_failure(self):
        """Should return empty data array on any failure."""
        result = parse_json_array("invalid", "key")
        assert result.data == []
