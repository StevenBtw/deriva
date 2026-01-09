# LLM Adapter

Multi-provider LLM abstraction with caching and structured output support.

**Version:** 1.0.0

## Purpose

The LLM adapter provides a unified interface for querying multiple LLM providers (Azure OpenAI, OpenAI, Anthropic, Ollama, LM Studio) with automatic caching and Pydantic-based structured output parsing.

## Key Exports

```python
from deriva.adapters.llm import (
    LLMManager,             # Main service class
    # Providers
    create_provider,        # Factory function
    AzureOpenAIProvider,
    OpenAIProvider,
    AnthropicProvider,
    OllamaProvider,
    LMStudioProvider,
    ProviderConfig,
    CompletionResult,
    # Response types
    LLMResponse,
    BaseResponse,
    LiveResponse,
    CachedResponse,
    FailedResponse,
    ResponseType,
    StructuredOutputMixin,
    # Caching
    CacheManager,
    cached_llm_call,
    # Exceptions
    LLMError,
    ConfigurationError,
    APIError,
    CacheError,
    ValidationError,
)
```

## Basic Usage

```python
from deriva.adapters.llm import LLMManager

# Uses provider from .env (LLM_PROVIDER, LLM_MODEL, etc.)
llm = LLMManager()

# Simple query
response = llm.query("What is Python?")
if response.response_type == "live":
    print(response.content)
```

## Structured Output with Pydantic

```python
from pydantic import BaseModel, Field
from deriva.adapters.llm import LLMManager

class BusinessConcept(BaseModel):
    name: str = Field(description="Concept name")
    concept_type: str = Field(description="actor, service, entity, etc.")
    description: str

llm = LLMManager()
result = llm.query(
    prompt="Extract the main business concept from this code...",
    response_model=BusinessConcept
)
# result is a validated BusinessConcept instance
print(result.name)
```

## File Structure

```text
deriva/adapters/llm/
├── __init__.py           # Package exports
├── manager.py            # LLMManager class
├── providers.py          # Provider implementations
├── models.py             # Response types and exceptions
└── cache.py              # CacheManager and caching utilities
```

## Configuration

Set provider via environment variables in `.env`:

```bash
# Primary provider
LLM_PROVIDER=azure          # azure, openai, anthropic, ollama, lmstudio
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=your-key
LLM_API_URL=https://...     # Optional custom endpoint

# Multiple models for benchmarking
LLM_OLLAMA_LLAMA_PROVIDER=ollama
LLM_OLLAMA_LLAMA_MODEL=llama3.2
LLM_OLLAMA_LLAMA_URL=http://localhost:11434/api/chat

# LM Studio (local, OpenAI-compatible)
LLM_LMSTUDIO_LOCAL_PROVIDER=lmstudio
LLM_LMSTUDIO_LOCAL_MODEL=local-model
LLM_LMSTUDIO_LOCAL_URL=http://localhost:1234/v1/chat/completions
```

## Providers

| Provider | Class | Description |
|----------|-------|-------------|
| Azure OpenAI | `AzureOpenAIProvider` | Azure-hosted OpenAI models |
| OpenAI | `OpenAIProvider` | OpenAI API direct |
| Anthropic | `AnthropicProvider` | Claude models |
| Ollama | `OllamaProvider` | Local Ollama models |
| LM Studio | `LMStudioProvider` | Local LM Studio (OpenAI-compatible) |

## Response Types

| Type | When | Key Fields |
|------|------|------------|
| `LiveResponse` | Fresh API call | `content`, `usage`, `finish_reason` |
| `CachedResponse` | From cache | `content`, `cache_key`, `cached_at` |
| `FailedResponse` | Error occurred | `error`, `error_type` |

## LLMManager Methods

| Method | Description |
|--------|-------------|
| `query(prompt, response_model, temperature, max_tokens)` | Send LLM query |
| `load_benchmark_models()` | Load multiple model configs from env |

## Caching

- Responses cached to `workspace/cache/` by default
- Cache key = SHA256(prompt + model + schema)
- Disable with `LLM_NOCACHE=true` in `.env`
- Use `cached_llm_call` decorator for custom caching

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and LLM usage guidelines
