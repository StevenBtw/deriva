"""Tests for common.llm_utils module."""

from __future__ import annotations

from unittest.mock import MagicMock

from deriva.common.llm_utils import create_empty_llm_details, extract_llm_details


class TestCreateEmptyLlmDetails:
    """Tests for create_empty_llm_details function."""

    def test_returns_dict_with_all_keys(self):
        """Should return dictionary with all required keys."""
        details = create_empty_llm_details()
        assert "prompt" in details
        assert "response" in details
        assert "tokens_in" in details
        assert "tokens_out" in details
        assert "cache_used" in details

    def test_returns_default_values(self):
        """Should return correct default values."""
        details = create_empty_llm_details()
        assert details["prompt"] == ""
        assert details["response"] == ""
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0
        assert details["cache_used"] is False


class TestExtractLlmDetails:
    """Tests for extract_llm_details function."""

    def test_extracts_content(self):
        """Should extract content from response."""
        response = MagicMock()
        response.content = "Response text"
        response.usage = None
        del response.response_type

        details = extract_llm_details(response)
        assert details["response"] == "Response text"

    def test_extracts_usage_tokens(self):
        """Should extract token counts from usage."""
        response = MagicMock()
        response.content = ""
        response.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        del response.response_type

        details = extract_llm_details(response)
        assert details["tokens_in"] == 100
        assert details["tokens_out"] == 50

    def test_detects_cached_response(self):
        """Should detect cached response type."""
        response = MagicMock()
        response.content = ""
        response.usage = None
        response.response_type = "ResponseType.CACHED"

        details = extract_llm_details(response)
        assert details["cache_used"] is True

    def test_handles_missing_attributes(self):
        """Should handle response without optional attributes."""
        response = MagicMock(spec=[])  # No attributes

        details = extract_llm_details(response)
        assert details["response"] == ""
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0
        assert details["cache_used"] is False

    def test_handles_none_usage(self):
        """Should handle None usage."""
        response = MagicMock()
        response.content = "text"
        response.usage = None
        del response.response_type

        details = extract_llm_details(response)
        assert details["tokens_in"] == 0
        assert details["tokens_out"] == 0
