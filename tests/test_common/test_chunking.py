"""Tests for common.chunking module."""

from __future__ import annotations

import pytest

from deriva.common.chunking import (
    MODEL_TOKEN_LIMITS,
    TOKEN_SAFETY_MARGIN,
    Chunk,
    chunk_by_delimiter,
    chunk_by_lines,
    chunk_content,
    estimate_tokens,
    get_model_token_limit,
    should_chunk,
)


class TestChunk:
    """Tests for Chunk dataclass."""

    def test_chunk_properties(self):
        """Should create chunk with correct properties."""
        chunk = Chunk(
            content="some content", index=0, total=3, start_line=1, end_line=10
        )

        assert chunk.content == "some content"
        assert chunk.index == 0
        assert chunk.total == 3
        assert chunk.start_line == 1
        assert chunk.end_line == 10

    def test_is_first(self):
        """Should correctly identify first chunk."""
        first_chunk = Chunk(content="", index=0, total=3, start_line=1, end_line=10)
        second_chunk = Chunk(content="", index=1, total=3, start_line=11, end_line=20)

        assert first_chunk.is_first is True
        assert second_chunk.is_first is False

    def test_is_last(self):
        """Should correctly identify last chunk."""
        first_chunk = Chunk(content="", index=0, total=3, start_line=1, end_line=10)
        last_chunk = Chunk(content="", index=2, total=3, start_line=21, end_line=30)

        assert first_chunk.is_last is False
        assert last_chunk.is_last is True

    def test_single_chunk_is_both_first_and_last(self):
        """Single chunk should be both first and last."""
        chunk = Chunk(content="", index=0, total=1, start_line=1, end_line=10)

        assert chunk.is_first is True
        assert chunk.is_last is True

    def test_str_representation(self):
        """Should have informative string representation."""
        chunk = Chunk(content="", index=1, total=5, start_line=11, end_line=20)

        str_repr = str(chunk)
        assert "2/5" in str_repr  # index+1 / total
        assert "11" in str_repr
        assert "20" in str_repr


class TestGetModelTokenLimit:
    """Tests for get_model_token_limit function."""

    def test_returns_default_for_none(self):
        """Should return default limit when model is None."""
        limit = get_model_token_limit(None)

        expected = int(MODEL_TOKEN_LIMITS["default"] * TOKEN_SAFETY_MARGIN)
        assert limit == expected

    def test_exact_match(self):
        """Should return exact match for known models."""
        limit = get_model_token_limit("gpt-4o")

        expected = int(MODEL_TOKEN_LIMITS["gpt-4o"] * TOKEN_SAFETY_MARGIN)
        assert limit == expected

    def test_case_insensitive(self):
        """Should match models case-insensitively."""
        limit_lower = get_model_token_limit("gpt-4o")
        limit_upper = get_model_token_limit("GPT-4O")

        assert limit_lower == limit_upper

    def test_partial_match(self):
        """Should find partial matches for model names."""
        # Should match "llama3" even if exact match doesn't exist
        limit = get_model_token_limit("llama3:latest")

        expected = int(MODEL_TOKEN_LIMITS["llama3"] * TOKEN_SAFETY_MARGIN)
        assert limit == expected

    def test_unknown_model_returns_default(self):
        """Should return default for unknown models."""
        limit = get_model_token_limit("unknown-model-xyz")

        expected = int(MODEL_TOKEN_LIMITS["default"] * TOKEN_SAFETY_MARGIN)
        assert limit == expected

    def test_applies_safety_margin(self):
        """Should apply safety margin to limit."""
        limit = get_model_token_limit("gpt-4o")
        raw_limit = MODEL_TOKEN_LIMITS["gpt-4o"]

        assert limit < raw_limit
        assert limit == int(raw_limit * TOKEN_SAFETY_MARGIN)


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Should return 0 for empty string."""
        assert estimate_tokens("") == 0

    def test_short_content(self):
        """Should estimate tokens using 4:1 character ratio."""
        content = "1234567890123456"  # 16 chars
        assert estimate_tokens(content) == 4  # 16 // 4

    def test_longer_content(self):
        """Should scale estimation with content length."""
        content = "a" * 1000
        assert estimate_tokens(content) == 250  # 1000 // 4


class TestShouldChunk:
    """Tests for should_chunk function."""

    def test_small_content_no_chunk(self):
        """Should return False for small content."""
        content = "small content"
        assert should_chunk(content, max_tokens=1000) is False

    def test_large_content_needs_chunk(self):
        """Should return True when content exceeds limit."""
        content = "a" * 10000  # ~2500 tokens
        assert should_chunk(content, max_tokens=1000) is True

    def test_uses_model_limit_when_not_specified(self):
        """Should use model limit when max_tokens not provided."""
        content = "a" * 100
        # Should not need chunking for small content
        assert should_chunk(content, model="gpt-4o") is False

    def test_edge_case_exactly_at_limit(self):
        """Should return False when exactly at limit."""
        content = "a" * 4000  # Exactly 1000 tokens
        assert should_chunk(content, max_tokens=1000) is False


class TestChunkByLines:
    """Tests for chunk_by_lines function."""

    def test_small_content_single_chunk(self):
        """Should return single chunk for small content."""
        content = "line 1\nline 2\nline 3"

        chunks = chunk_by_lines(content, max_tokens=1000)

        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].is_first is True
        assert chunks[0].is_last is True
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 3

    def test_splits_at_line_boundaries(self):
        """Should split content at line boundaries."""
        # Create content that will exceed token limit
        lines = ["line " + str(i) * 50 for i in range(100)]
        content = "\n".join(lines)

        chunks = chunk_by_lines(content, max_tokens=100)

        assert len(chunks) > 1
        for chunk in chunks:
            # Each chunk should end at a line boundary
            assert chunk.content.endswith("\n") or chunk.is_last

    def test_chunk_indices_are_sequential(self):
        """Should have sequential chunk indices."""
        content = "a" * 10000 + "\n" + "b" * 10000

        chunks = chunk_by_lines(content, max_tokens=100)

        for i, chunk in enumerate(chunks):
            assert chunk.index == i
            assert chunk.total == len(chunks)

    def test_overlap_preserves_context(self):
        """Should include overlap lines from previous chunk."""
        lines = [f"line {i}" for i in range(20)]
        content = "\n".join(lines)

        chunks = chunk_by_lines(content, max_tokens=50, overlap=2)

        # With overlap, later chunks should start with lines from previous chunk
        if len(chunks) > 1:
            # Check that start_line accounts for overlap
            assert chunks[1].start_line < chunks[0].end_line + 1

    def test_preserves_line_endings(self):
        """Should preserve line endings in chunks."""
        content = "line 1\nline 2\nline 3\n"

        chunks = chunk_by_lines(content, max_tokens=1000)

        assert chunks[0].content == content


class TestChunkByDelimiter:
    """Tests for chunk_by_delimiter function."""

    def test_small_content_single_chunk(self):
        """Should return single chunk for small content."""
        content = "class Foo:\n    pass\n\nclass Bar:\n    pass"

        chunks = chunk_by_delimiter(content, "\n\nclass ", max_tokens=1000)

        assert len(chunks) == 1
        assert chunks[0].content == content

    def test_splits_at_delimiter(self):
        """Should split content at delimiter boundaries."""
        sections = [f"class Section{i}:\n    # lots of code\n    " + "x" * 200 for i in range(10)]
        content = "\n\n".join(sections)

        chunks = chunk_by_delimiter(content, "\n\nclass ", max_tokens=100)

        assert len(chunks) > 1

    def test_preserves_delimiter_at_section_start(self):
        """Should keep delimiter at start of each section (except first)."""
        content = "first\n\nclass Second:\n    pass\n\nclass Third:\n    pass"

        chunks = chunk_by_delimiter(content, "\n\nclass ", max_tokens=1000)

        # When not chunked, content is preserved as-is
        assert chunks[0].content == content

    def test_fallback_to_line_chunking_for_large_section(self):
        """Should use line chunking for sections exceeding token limit."""
        # Create a section larger than max_tokens
        large_section = "x" * 5000  # ~1250 tokens
        content = f"header\n\n{large_section}\n\nfooter"

        chunks = chunk_by_delimiter(content, "\n\n", max_tokens=100)

        # Should have multiple chunks despite only 3 delimiter-separated sections
        assert len(chunks) > 3


class TestChunkContent:
    """Tests for chunk_content function."""

    def test_uses_line_chunking_without_delimiter(self):
        """Should use line-based chunking when no delimiter provided."""
        content = "line 1\nline 2\nline 3"

        chunks = chunk_content(content, max_tokens=1000)

        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].total == 1
        assert "line 1" in chunks[0].content

    def test_uses_delimiter_chunking_with_delimiter(self):
        """Should use delimiter-based chunking when delimiter provided."""
        content = "section 1\n---\nsection 2\n---\nsection 3"

        chunks = chunk_content(content, delimiter="\n---\n", max_tokens=1000)

        assert len(chunks) == 1
        assert chunks[0].content == content

    def test_accepts_model_parameter(self):
        """Should accept model parameter for token limits."""
        content = "some content"

        chunks = chunk_content(content, model="gpt-4o")

        assert len(chunks) == 1

    def test_accepts_overlap_parameter(self):
        """Should accept overlap parameter."""
        # Create content with multiple lines that will exceed token limit
        lines = [f"line {i} " + "x" * 50 for i in range(50)]
        content = "\n".join(lines)

        chunks = chunk_content(content, max_tokens=100, overlap=2)

        assert len(chunks) > 1

    def test_returns_single_chunk_for_small_content(self):
        """Should return single chunk when content is small."""
        content = "Hello, World!"

        chunks = chunk_content(content, max_tokens=1000)

        assert len(chunks) == 1
        assert chunks[0].is_first is True
        assert chunks[0].is_last is True


class TestModelTokenLimits:
    """Tests for MODEL_TOKEN_LIMITS constants."""

    def test_has_default_limit(self):
        """Should have a default limit defined."""
        assert "default" in MODEL_TOKEN_LIMITS
        assert MODEL_TOKEN_LIMITS["default"] > 0

    def test_has_common_models(self):
        """Should have common models defined."""
        assert "gpt-4o" in MODEL_TOKEN_LIMITS
        assert "claude-3-opus" in MODEL_TOKEN_LIMITS

    def test_all_limits_positive(self):
        """All token limits should be positive."""
        for model, limit in MODEL_TOKEN_LIMITS.items():
            assert limit > 0, f"{model} has non-positive limit"
