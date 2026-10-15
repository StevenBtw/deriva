"""
LLM Manager - A multi-provider LLM abstraction with caching and structured output.

Uses PydanticAI for model-agnostic LLM interactions.

Supports:
- Azure OpenAI
- OpenAI
- Anthropic
- Ollama
- Mistral
- LM Studio

Example:
    from deriva.adapters.llm import LLMManager
    from pydantic import BaseModel

    # Basic usage
    llm = LLMManager()
    response = llm.query("What is Python?")

    # Structured output
    class Concept(BaseModel):
        name: str
        description: str

    result = llm.query("Extract concept from...", response_model=Concept)
    print(result.name)  # Type-safe!
"""

from __future__ import annotations

from .cache import CacheManager, cached_llm_call
from .manager import LLMManager
from .model_registry import VALID_PROVIDERS, get_pydantic_ai_model
from .models import (
    APIError,
    BaseResponse,
    BenchmarkModelConfig,
    CachedResponse,
    CacheError,
    ConfigurationError,
    FailedResponse,
    LiveResponse,
    LLMError,
    LLMResponse,
    ResponseType,
    ValidationError,
)
from .rate_limiter import RateLimitConfig, RateLimiter, get_default_rate_limit

__all__ = [
    # Main service
    "LLMManager",
    # Response types
    "ResponseType",
    "BaseResponse",
    "LiveResponse",
    "CachedResponse",
    "FailedResponse",
    "LLMResponse",
    # Configuration
    "BenchmarkModelConfig",
    "VALID_PROVIDERS",
    "get_pydantic_ai_model",
    # Cache
    "CacheManager",
    "cached_llm_call",
    # Rate limiting
    "RateLimitConfig",
    "RateLimiter",
    "get_default_rate_limit",
    # Exceptions
    "LLMError",
    "ConfigurationError",
    "APIError",
    "CacheError",
    "ValidationError",
]

__version__ = "2.0.0"
