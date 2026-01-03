"""
Pydantic models for LLM Manager responses and exceptions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

# Re-export exceptions for backwards compatibility
from deriva.common.exceptions import APIError as APIError
from deriva.common.exceptions import CacheError as CacheError
from deriva.common.exceptions import ConfigurationError as ConfigurationError
from deriva.common.exceptions import LLMError as LLMError
from deriva.common.exceptions import ValidationError as ValidationError
from pydantic import BaseModel

from deriva.adapters.llm.providers import VALID_PROVIDERS

__all__ = [
    # Exceptions (re-exported)
    "APIError",
    "CacheError",
    "ConfigurationError",
    "LLMError",
    "ValidationError",
    # Models
    "BenchmarkModelConfig",
    "ResponseType",
    "BaseResponse",
    "LiveResponse",
    "CachedResponse",
    "FailedResponse",
    "LLMResponse",
    "StructuredOutputMixin",
]


# =============================================================================
# Benchmark Model Configuration
# =============================================================================


@dataclass
class BenchmarkModelConfig:
    """
    Configuration for a specific LLM model used in benchmarking.

    This allows explicit configuration of models rather than relying on
    environment variables, enabling multi-model comparison in benchmarks.

    Attributes:
        name: Friendly name for the model config (e.g., "azure-gpt4")
        provider: Provider type: azure, openai, anthropic, ollama
        model: Model identifier (e.g., "gpt-4", "claude-3-5-sonnet-20241022")
        api_url: API endpoint URL (optional, uses provider default if not set)
        api_key: API key (optional, reads from api_key_env if not set)
        api_key_env: Environment variable name for API key
    """

    name: str
    provider: str
    model: str
    api_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None

    def __post_init__(self):
        """Validate provider."""
        if self.provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider: {self.provider}. Must be one of {VALID_PROVIDERS}"
            )

    def get_api_key(self) -> str | None:
        """Get API key from direct value or environment variable."""
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None

    def get_api_url(self) -> str:
        """Get API URL with provider defaults."""
        if self.api_url:
            return self.api_url

        # Provider defaults
        defaults = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "ollama": "http://localhost:11434/api/chat",
        }
        return defaults.get(self.provider, "")


class ResponseType(str, Enum):
    """Type of LLM response."""

    LIVE = "live"
    CACHED = "cached"
    FAILED = "failed"


class BaseResponse(BaseModel):
    """Base class for all response types."""

    response_type: ResponseType
    prompt: str
    model: str

    model_config = {"frozen": False, "extra": "ignore"}


class LiveResponse(BaseResponse):
    """Response from a live API call."""

    response_type: Literal[ResponseType.LIVE] = ResponseType.LIVE
    content: str
    usage: dict[str, Any] | None = (
        None  # Can contain nested dicts (e.g., completion_tokens_details)
    )
    finish_reason: str | None = None


class CachedResponse(BaseResponse):
    """Response retrieved from cache."""

    response_type: Literal[ResponseType.CACHED] = ResponseType.CACHED
    content: str
    cache_key: str
    cached_at: str


class FailedResponse(BaseResponse):
    """Response when API call fails."""

    response_type: Literal[ResponseType.FAILED] = ResponseType.FAILED
    error: str
    error_type: str


# Type alias for any response type
LLMResponse = LiveResponse | CachedResponse | FailedResponse


# =============================================================================
# Structured Output Support
# =============================================================================


class StructuredOutputMixin(BaseModel):
    """
    Mixin for models used as structured output schemas.

    Inherit from this to use your model with llm_manager.query(response_model=YourModel).

    Example:
        class BusinessConcept(StructuredOutputMixin):
            name: str = Field(description="The concept name")
            type: str = Field(description="The concept type")
            description: str = Field(description="Brief description")

        result = llm_manager.query(
            prompt="Extract business concepts from...",
            response_model=BusinessConcept
        )
    """

    model_config = {"extra": "forbid"}

    @classmethod
    def to_prompt_schema(cls) -> str:
        """
        Generate a prompt-friendly schema description.

        Returns:
            String description of the expected JSON structure
        """
        schema = cls.model_json_schema()
        return _format_schema_for_prompt(schema)


def _format_schema_for_prompt(schema: dict[str, Any], indent: int = 0) -> str:
    """
    Format a JSON schema into a readable prompt description.

    Args:
        schema: JSON schema dict
        indent: Current indentation level

    Returns:
        Formatted string description
    """
    lines = []
    prefix = "  " * indent

    if "properties" in schema:
        lines.append(f"{prefix}{{")
        props = schema["properties"]
        required = set(schema.get("required", []))

        for name, prop in props.items():
            prop_type = prop.get("type", "any")
            description = prop.get("description", "")
            req_marker = " (required)" if name in required else " (optional)"

            # Handle nested objects
            if prop_type == "object" and "properties" in prop:
                lines.append(f'{prefix}  "{name}": {req_marker}')
                lines.append(_format_schema_for_prompt(prop, indent + 2))
            # Handle arrays
            elif prop_type == "array":
                items = prop.get("items", {})
                items_type = items.get("type", "any")
                lines.append(
                    f'{prefix}  "{name}": [{items_type}...]{req_marker} - {description}'
                )
            # Handle enums
            elif "enum" in prop:
                enum_vals = ", ".join(f'"{v}"' for v in prop["enum"])
                lines.append(
                    f'{prefix}  "{name}": one of [{enum_vals}]{req_marker} - {description}'
                )
            else:
                lines.append(
                    f'{prefix}  "{name}": {prop_type}{req_marker} - {description}'
                )

        lines.append(f"{prefix}}}")

    return "\n".join(lines)
