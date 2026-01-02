"""File chunking utilities for Deriva.

Provides chunking functionality to handle large files that exceed LLM token limits.
Chunking strategy is configurable per file extension via the file_type_registry.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Chunk",
    "estimate_tokens",
    "should_chunk",
    "chunk_by_lines",
    "chunk_by_delimiter",
    "chunk_content",
    "get_model_token_limit",
    "MODEL_TOKEN_LIMITS",
]


# =============================================================================
# Model Token Limits
# =============================================================================

MODEL_TOKEN_LIMITS: dict[str, int] = {
    # OpenAI models
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # Anthropic models
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5-sonnet": 200_000,
    # Azure OpenAI (same as OpenAI)
    "gpt-4o-mini-azure": 128_000,
    # Ollama / local models (conservative estimates)
    "llama3": 8_192,
    "llama3.2": 8_192,
    "devstral": 32_000,
    "devstral-small-2": 32_000,
    "deepseek-coder-v2": 128_000,
    "codellama": 16_000,
    "mistral": 32_000,
    "mixtral": 32_000,
    # Default fallback
    "default": 4_000,
}

# Safety margin - use 80% of limit to leave room for system prompt + response
TOKEN_SAFETY_MARGIN = 0.8


def get_model_token_limit(model: str | None = None) -> int:
    """Get the token limit for a model.

    Args:
        model: Model name or identifier. If None, returns default limit.

    Returns:
        Token limit for the model (with safety margin applied).
    """
    if model is None:
        limit = MODEL_TOKEN_LIMITS["default"]
    else:
        # Try exact match first
        model_lower = model.lower()
        if model_lower in MODEL_TOKEN_LIMITS:
            limit = MODEL_TOKEN_LIMITS[model_lower]
        else:
            # Try partial match
            for key, value in MODEL_TOKEN_LIMITS.items():
                if key in model_lower or model_lower in key:
                    limit = value
                    break
            else:
                limit = MODEL_TOKEN_LIMITS["default"]

    return int(limit * TOKEN_SAFETY_MARGIN)


# =============================================================================
# Chunk Dataclass
# =============================================================================


@dataclass
class Chunk:
    """Represents a chunk of file content with metadata."""

    content: str
    index: int
    total: int
    start_line: int
    end_line: int

    @property
    def is_first(self) -> bool:
        """Check if this is the first chunk."""
        return self.index == 0

    @property
    def is_last(self) -> bool:
        """Check if this is the last chunk."""
        return self.index == self.total - 1

    def __str__(self) -> str:
        return f"Chunk {self.index + 1}/{self.total} (lines {self.start_line}-{self.end_line})"


# =============================================================================
# Token Estimation
# =============================================================================


def estimate_tokens(content: str) -> int:
    """Estimate the number of tokens in content.

    Uses a simple character-to-token ratio of 4:1.
    This is a rough estimate - actual tokenization varies by model.

    Args:
        content: Text content to estimate tokens for.

    Returns:
        Estimated token count.
    """
    if not content:
        return 0
    return len(content) // 4


def should_chunk(content: str, max_tokens: int | None = None, model: str | None = None) -> bool:
    """Check if content should be chunked.

    Args:
        content: Text content to check.
        max_tokens: Maximum tokens allowed. If None, uses model limit.
        model: Model name for looking up token limit.

    Returns:
        True if content exceeds token limit and should be chunked.
    """
    if max_tokens is None:
        max_tokens = get_model_token_limit(model)

    return estimate_tokens(content) > max_tokens


# =============================================================================
# Chunking Functions
# =============================================================================


def chunk_by_lines(
    content: str,
    max_tokens: int | None = None,
    model: str | None = None,
    overlap: int = 0,
) -> list[Chunk]:
    """Chunk content by lines, respecting token limits.

    Splits content at line boundaries, keeping each chunk under the token limit.

    Args:
        content: Text content to chunk.
        max_tokens: Maximum tokens per chunk. If None, uses model limit.
        model: Model name for looking up token limit.
        overlap: Number of lines to overlap between chunks (default: 0).

    Returns:
        List of Chunk objects.
    """
    if max_tokens is None:
        max_tokens = get_model_token_limit(model)

    if not should_chunk(content, max_tokens):
        lines = content.splitlines()
        return [Chunk(content=content, index=0, total=1, start_line=1, end_line=len(lines))]

    lines = content.splitlines(keepends=True)
    chunks: list[Chunk] = []
    current_chunk_lines: list[str] = []
    current_tokens = 0
    chunk_start_line = 1

    for i, line in enumerate(lines, start=1):
        line_tokens = estimate_tokens(line)

        # Check if adding this line would exceed limit
        if current_tokens + line_tokens > max_tokens and current_chunk_lines:
            # Save current chunk
            chunk_content = "".join(current_chunk_lines)
            chunks.append(
                Chunk(
                    content=chunk_content,
                    index=len(chunks),
                    total=0,  # Will update after
                    start_line=chunk_start_line,
                    end_line=i - 1,
                )
            )

            # Start new chunk with overlap
            if overlap > 0 and len(current_chunk_lines) >= overlap:
                overlap_lines = current_chunk_lines[-overlap:]
                current_chunk_lines = overlap_lines.copy()
                current_tokens = estimate_tokens("".join(overlap_lines))
                chunk_start_line = i - overlap
            else:
                current_chunk_lines = []
                current_tokens = 0
                chunk_start_line = i

        current_chunk_lines.append(line)
        current_tokens += line_tokens

    # Don't forget the last chunk
    if current_chunk_lines:
        chunk_content = "".join(current_chunk_lines)
        chunks.append(
            Chunk(
                content=chunk_content,
                index=len(chunks),
                total=0,
                start_line=chunk_start_line,
                end_line=len(lines),
            )
        )

    # Update total count in all chunks
    total = len(chunks)
    for chunk in chunks:
        chunk.total = total

    return chunks


def chunk_by_delimiter(
    content: str,
    delimiter: str,
    max_tokens: int | None = None,
    model: str | None = None,
    overlap: int = 0,
) -> list[Chunk]:
    """Chunk content by a custom delimiter, respecting token limits.

    Splits content at delimiter boundaries (e.g., '\\n\\nclass ', '\\ndef ').
    If a single section exceeds max_tokens, falls back to line-based chunking for that section.

    Args:
        content: Text content to chunk.
        delimiter: Delimiter string to split on (kept at start of each section).
        max_tokens: Maximum tokens per chunk. If None, uses model limit.
        model: Model name for looking up token limit.
        overlap: Number of sections to overlap between chunks (default: 0).

    Returns:
        List of Chunk objects.
    """
    if max_tokens is None:
        max_tokens = get_model_token_limit(model)

    if not should_chunk(content, max_tokens):
        lines = content.splitlines()
        return [Chunk(content=content, index=0, total=1, start_line=1, end_line=len(lines))]

    # Split by delimiter, keeping delimiter at start of each section
    sections = content.split(delimiter)

    # Reconstruct sections with delimiter (except first)
    if sections:
        sections = [sections[0]] + [delimiter + s for s in sections[1:] if s]

    chunks: list[Chunk] = []
    current_sections: list[str] = []
    current_tokens = 0
    current_line = 1

    for section in sections:
        section_tokens = estimate_tokens(section)

        # If single section exceeds limit, use line-based chunking for it
        if section_tokens > max_tokens:
            # First, save any accumulated sections
            if current_sections:
                chunk_content = "".join(current_sections)
                end_line = current_line + chunk_content.count("\n")
                chunks.append(
                    Chunk(
                        content=chunk_content,
                        index=len(chunks),
                        total=0,
                        start_line=current_line,
                        end_line=end_line,
                    )
                )
                current_line = end_line + 1
                current_sections = []
                current_tokens = 0

            # Chunk the large section by lines
            sub_chunks = chunk_by_lines(section, max_tokens, model, overlap)
            for sub_chunk in sub_chunks:
                chunks.append(
                    Chunk(
                        content=sub_chunk.content,
                        index=len(chunks),
                        total=0,
                        start_line=current_line + sub_chunk.start_line - 1,
                        end_line=current_line + sub_chunk.end_line - 1,
                    )
                )
            current_line += section.count("\n") + 1
            continue

        # Check if adding this section would exceed limit
        if current_tokens + section_tokens > max_tokens and current_sections:
            chunk_content = "".join(current_sections)
            end_line = current_line + chunk_content.count("\n")
            chunks.append(
                Chunk(
                    content=chunk_content,
                    index=len(chunks),
                    total=0,
                    start_line=current_line,
                    end_line=end_line,
                )
            )
            current_line = end_line + 1

            # Handle overlap
            if overlap > 0 and len(current_sections) >= overlap:
                overlap_sections = current_sections[-overlap:]
                current_sections = overlap_sections.copy()
                current_tokens = estimate_tokens("".join(overlap_sections))
            else:
                current_sections = []
                current_tokens = 0

        current_sections.append(section)
        current_tokens += section_tokens

    # Don't forget the last chunk
    if current_sections:
        chunk_content = "".join(current_sections)
        end_line = current_line + chunk_content.count("\n")
        chunks.append(
            Chunk(
                content=chunk_content,
                index=len(chunks),
                total=0,
                start_line=current_line,
                end_line=end_line,
            )
        )

    # Update total count
    total = len(chunks)
    for chunk in chunks:
        chunk.total = total

    return chunks


def chunk_content(
    content: str,
    delimiter: str | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    overlap: int = 0,
) -> list[Chunk]:
    """Chunk content using the appropriate strategy.

    Main entry point for chunking. Uses delimiter-based chunking if a delimiter
    is provided, otherwise falls back to line-based chunking.

    Args:
        content: Text content to chunk.
        delimiter: Optional delimiter for splitting. If None, uses line-based chunking.
        max_tokens: Maximum tokens per chunk. If None, uses model limit.
        model: Model name for looking up token limit.
        overlap: Overlap between chunks (lines for line-based, sections for delimiter-based).

    Returns:
        List of Chunk objects. Returns single chunk if content doesn't need chunking.
    """
    if delimiter:
        return chunk_by_delimiter(content, delimiter, max_tokens, model, overlap)
    else:
        return chunk_by_lines(content, max_tokens, model, overlap)
