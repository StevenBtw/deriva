"""
LLM Manager - A multi-provider LLM abstraction with caching and structured output.

Supports:
- Azure OpenAI
- OpenAI
- Anthropic
- Ollama

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
from .models import (
    APIError,
    BaseResponse,
    CachedResponse,
    CacheError,
    ConfigurationError,
    FailedResponse,
    LiveResponse,
    LLMError,
    LLMResponse,
    ResponseType,
    StructuredOutputMixin,
    ValidationError,
)
from .providers import (
    AnthropicProvider,
    AzureOpenAIProvider,
    BaseProvider,
    CompletionResult,
    LLMProvider,
    LMStudioProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderConfig,
    ProviderError,
    create_provider,
)
from .rate_limiter import RateLimitConfig, RateLimiter, get_default_rate_limit
from .manager import LLMManager

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
    # Structured output
    "StructuredOutputMixin",
    # Providers
    "LLMProvider",
    "BaseProvider",
    "AzureOpenAIProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "LMStudioProvider",
    "ProviderConfig",
    "CompletionResult",
    "ProviderError",
    "create_provider",
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

__version__ = "1.0.0"
