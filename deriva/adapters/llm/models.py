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
from deriva.common.exceptions import CircuitOpenError as CircuitOpenError
from deriva.common.exceptions import ConfigurationError as ConfigurationError
from deriva.common.exceptions import LLMError as LLMError
from deriva.common.exceptions import RateLimitError as RateLimitError
from deriva.common.exceptions import TransientError as TransientError
from deriva.common.exceptions import ValidationError as ValidationError
from pydantic import BaseModel

from .model_registry import VALID_PROVIDERS

__all__ = [
    # Exceptions (re-exported)
    "APIError",
    "CacheError",
    "CircuitOpenError",
    "ConfigurationError",
    "LLMError",
    "RateLimitError",
    "TransientError",
    "ValidationError",
    # Models
    "BenchmarkModelConfig",
    "ResponseType",
    "BaseResponse",
    "LiveResponse",
    "CachedResponse",
    "FailedResponse",
    "LLMResponse",
]


# =============================================================================
# Benchmark Model Configuration
# =============================================================================


@dataclass
class BenchmarkModelConfig:
    """
    Configuration for a specific LLM model used in benchmarking.

    Attributes:
        name: Friendly name for the model config (e.g., "azure-gpt4")
        provider: Provider type: azure, openai, anthropic, ollama, mistral, lmstudio
        model: Model identifier (e.g., "gpt-4", "claude-sonnet-4-20250514")
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
            raise ValueError(f"Invalid provider: {self.provider}. Must be one of {VALID_PROVIDERS}")

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

        defaults = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "anthropic": "https://api.anthropic.com/v1/messages",
            "ollama": "http://localhost:11434/api/chat",
            "lmstudio": "http://localhost:1234/v1/chat/completions",
            "mistral": "https://api.mistral.ai/v1/chat/completions",
        }
        return defaults.get(self.provider, "")


class ResponseType(str, Enum):  # noqa: UP042 - StrEnum would change str() of members, which callers compare
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
    usage: dict[str, Any] | None = None
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
