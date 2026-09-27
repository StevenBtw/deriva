# LLM Adapter

Multi-provider LLM abstraction using pydantic-ai with caching and structured output support.

**Version:** 2.1.0

## Purpose

The LLM adapter provides a unified interface for querying multiple LLM providers (Azure OpenAI, OpenAI, Anthropic, Mistral, Ollama, LM Studio) using **pydantic-ai** for agent-based interactions with automatic retries and Pydantic-based structured output parsing.

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

## Structured Output with pydantic-ai

Uses pydantic-ai agents for type-safe, validated responses:

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
# result is a validated BusinessConcept instance (via pydantic-ai agent)
print(result.name)
```

## File Structure

```text
deriva/adapters/llm/
├── __init__.py           # Package exports
├── manager.py            # LLMManager class
├── providers.py          # Provider implementations
├── models.py             # Response types and exceptions
├── cache.py              # CacheManager and caching utilities
├── rate_limiter.py       # Token bucket rate limiting, adaptive throttling, circuit breaker
└── retry.py              # Exponential backoff with error classification
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

All providers are implemented via pydantic-ai's model abstraction:

| Provider     | pydantic-ai Model  | Description                         |
|--------------|--------------------| ------------------------------------|
| Azure OpenAI | `AzureOpenAIModel` | Azure-hosted OpenAI models          |
| OpenAI       | `OpenAIModel`      | OpenAI API direct                   |
| Anthropic    | `AnthropicModel`   | Claude models                       |
| Mistral      | `MistralModel`     | Mistral AI models                   |
| Ollama       | `OllamaModel`      | Local Ollama models                 |
| LM Studio    | `OpenAIModel`      | Local LM Studio (OpenAI-compatible) |

## Response Types

| Type | When | Key Fields |
|------|------|------------|
| `LiveResponse` | Fresh API call | `content`, `usage`, `finish_reason` |
| `CachedResponse` | From cache | `content`, `cache_key`, `cached_at` |
| `FailedResponse` | Error occurred | `error`, `error_type` |

## LLMManager Methods

| Method | Description |
|--------|-------------|
| `query(prompt, response_model, temperature, max_tokens, system_prompt)` | Send LLM query |
| `load_benchmark_models()` | Load multiple model configs from env |

### System Prompt Parameter

The `system_prompt` parameter allows passing instructions separately from the user prompt, which is more token-efficient for repeated queries with the same system context:

```python
llm = LLMManager()

# Without system_prompt (instruction embedded in prompt)
result = llm.query("You are a code analyzer. Extract concepts from: ...")

# With system_prompt (more efficient for batched operations)
result = llm.query(
    prompt="Extract concepts from this code: ...",
    system_prompt="You are a code analyzer. Return structured JSON.",
    response_model=BusinessConcept
)
```

## Caching

- Responses cached to `workspace/cache/` by default
- Cache key = SHA256(prompt + model + schema + system prompt + effective temperature + max_tokens), so changing any of them never returns an answer cached for other settings
- Disable with `LLM_NOCACHE=true` in `.env`
- Use `cached_llm_call` decorator for custom caching

## Rate Limiting

The adapter includes sophisticated rate limiting with adaptive throttling and circuit breaker patterns.

### Basic Rate Limiting

```bash
# Global RPM limit (0 = use provider default)
LLM_RATE_LIMIT_RPM=60

# Minimum delay between requests (seconds)
LLM_RATE_LIMIT_DELAY=0.0
```

### Model-Specific Rate Limits

Override global/provider defaults for specific models:

```bash
# Format: LLM_{MODEL_NAME}_RPM=requests_per_minute
LLM_MISTRAL_DEVSTRAL_RPM=24
LLM_OPENAI_GPT4OMINI_RPM=60
LLM_ANTHROPIC_HAIKU_RPM=30
LLM_OLLAMA_DEVSTRAL_RPM=0   # 0 = unlimited for local
```

### Provider Default Limits

| Provider | Default RPM |
|----------|-------------|
| Azure OpenAI | 60 |
| OpenAI | 60 |
| Anthropic | 60 |
| Mistral | 24 |
| Ollama | 0 (unlimited) |
| LM Studio | 0 (unlimited) |

### Adaptive Throttling

Automatically reduces request rate when hitting 429 errors:

```bash
LLM_THROTTLE_ENABLED=true      # Enable adaptive throttling
LLM_THROTTLE_MIN_FACTOR=0.25   # Minimum 25% of configured RPM
LLM_THROTTLE_RECOVERY_TIME=60  # Seconds before trying to increase RPM
```

**Behavior:**

- On rate limit (429): Halves effective RPM (down to min factor)
- After recovery time with no 429s: Gradually increases RPM by 25%
- Respects `Retry-After` header when provided by the API

### Circuit Breaker

Stops requests when a provider is experiencing outages:

```bash
LLM_CIRCUIT_BREAKER_ENABLED=true
LLM_CIRCUIT_FAILURE_THRESHOLD=5   # Consecutive failures to open circuit
LLM_CIRCUIT_RECOVERY_TIME=30      # Seconds before testing recovery
```

**Circuit States:**

| State | Behavior |
|-------|----------|
| CLOSED | Normal operation, requests allowed |
| OPEN | Requests rejected immediately with `CircuitOpenError` |
| HALF_OPEN | One test request allowed to check if service recovered |

**State Transitions:**

- CLOSED -> OPEN: After N consecutive failures (default: 5)
- OPEN -> HALF_OPEN: After recovery time elapses (default: 30s)
- HALF_OPEN -> CLOSED: On successful request
- HALF_OPEN -> OPEN: On failed request

### Retry Configuration

```bash
LLM_MAX_RETRIES=3            # Maximum retry attempts
LLM_RETRY_BASE_DELAY=2.0     # Base delay for exponential backoff (seconds)
LLM_RETRY_MAX_DELAY=60.0     # Maximum delay between retries (seconds)
```

Retries use exponential backoff with jitter and respect `Retry-After` headers.

## Structured Output (JSON Schema Enforcement)

Enable API-level JSON schema enforcement for guaranteed valid JSON responses:

```bash
# Per-model configuration in .env
LLM_OPENAI_GPT41MINI_STRUCTURED_OUTPUT=true
LLM_ANTHROPIC_HAIKU_STRUCTURED_OUTPUT=true
LLM_MISTRAL_DEVSTRAL_STRUCTURED_OUTPUT=true
LLM_OLLAMA_NEMOTRON_STRUCTURED_OUTPUT=true
```

**Supported Providers:**

| Provider | Support | Implementation |
|----------|---------|----------------|
| OpenAI | ✅ | `response_format: {type: "json_schema"}` |
| Azure | ✅ | Same as OpenAI |
| Anthropic | ✅ | `output_format` + beta header |
| Mistral | ✅ | `response_format: {type: "json_schema"}` |
| Ollama | ✅ | `format: <schema>` |
| LMStudio | ✅ | Same as OpenAI |
| ClaudeCode | ❌ | CLI-based, no structured output |

**Behavior:**

- `structured_output=true`: JSON schema passed to provider API for server-side enforcement
- `structured_output=false` (default): Only `json_mode` enabled, schema used for client-side validation only

**Programmatic Usage:**

```python
from deriva.adapters.llm import LLMManager
from deriva.adapters.llm.manager import load_benchmark_models

# Load model with structured_output=true from .env
models = load_benchmark_models()
llm = LLMManager.from_config(models["openai-gpt41mini"])

# The schema will be enforced at the API level
result = llm.query(
    "Extract business concepts...",
    schema={"type": "object", "properties": {...}}
)
```

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and LLM usage guidelines
