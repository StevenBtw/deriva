"""
Main LLM Manager service with multi-provider support, caching, and structured output.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, overload

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError as PydanticValidationError

from .cache import CacheManager
from .models import (
    APIError,
    BenchmarkModelConfig,
    CachedResponse,
    ConfigurationError,
    FailedResponse,
    LiveResponse,
    LLMResponse,
    ValidationError,
)
from .providers import ProviderConfig, ProviderError, create_provider

logger = logging.getLogger(__name__)


def load_benchmark_models() -> dict[str, BenchmarkModelConfig]:
    """
    Load model configurations from environment variables.

    Looks for environment variables matching the pattern:
        LLM_{NAME}_PROVIDER
        LLM_{NAME}_MODEL
        LLM_{NAME}_URL (optional)
        LLM_{NAME}_KEY (optional, direct key)
        LLM_{NAME}_KEY_ENV (optional, env var name for key)

    Example .env:
        LLM_AZURE_GPT4_PROVIDER=azure
        LLM_AZURE_GPT4_MODEL=gpt-4
        LLM_AZURE_GPT4_URL=https://...
        LLM_AZURE_GPT4_KEY=sk-...

    Returns:
        Dict mapping config name to BenchmarkModelConfig
    """
    load_dotenv(override=True)

    configs: dict[str, BenchmarkModelConfig] = {}

    # Find all LLM_*_PROVIDER entries (but not legacy LLM_PROVIDER)
    prefix = "LLM_"
    suffix = "_PROVIDER"

    for key, value in os.environ.items():
        if key.startswith(prefix) and key.endswith(suffix) and key != "LLM_PROVIDER":
            # Extract the name part (e.g., "AZURE_GPT4" from "LLM_AZURE_GPT4_PROVIDER")
            name = key[len(prefix) : -len(suffix)]

            provider = value
            model = os.getenv(f"{prefix}{name}_MODEL", "")
            api_url = os.getenv(f"{prefix}{name}_URL")
            api_key = os.getenv(f"{prefix}{name}_KEY")
            api_key_env = os.getenv(f"{prefix}{name}_KEY_ENV")

            if not model:
                continue  # Skip incomplete configs

            # Convert name to lowercase with hyphens (AZURE_GPT4 -> azure-gpt4)
            friendly_name = name.lower().replace("_", "-")

            try:
                configs[friendly_name] = BenchmarkModelConfig(
                    name=friendly_name,
                    provider=provider.lower(),
                    model=model,
                    api_url=api_url,
                    api_key=api_key,
                    api_key_env=api_key_env,
                )
            except ValueError:
                # Invalid provider, skip
                continue

    return configs


# Type variable for structured output
T = TypeVar("T", bound=BaseModel)


class LLMManager:
    """
    Manages LLM API calls with intelligent caching and structured output support.

    Features:
    - Multi-provider support (Azure OpenAI, OpenAI, Anthropic, Ollama)
    - Automatic caching of responses
    - Structured output with Pydantic models
    - JSON schema validation
    - Response type indicators (live/cached/failed)

    Example:
        # Basic usage
        llm = LLMManager()
        response = llm.query("What is Python?")

        # Structured output
        class Concept(BaseModel):
            name: str
            description: str

        result = llm.query("Extract concept from...", response_model=Concept)
        print(result.name)  # Type-safe access
    """

    def __init__(self):
        """
        Initialize LLM Manager from .env configuration.

        Raises:
            ConfigurationError: If configuration is invalid
        """
        load_dotenv(override=True)

        self.config = self._load_config_from_env()
        self._validate_config()

        # Initialize cache manager
        cache_dir = self.config.get("cache_dir", "workspace/cache")
        cache_path = Path(cache_dir)
        if not cache_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            cache_path = project_root / cache_path
        self.cache = CacheManager(str(cache_path))

        # Create provider
        provider_config = ProviderConfig(
            api_url=self.config["api_url"],
            api_key=self.config["api_key"],
            model=self.config["model"],
            timeout=self.config.get("timeout", 60),
        )
        self.provider = create_provider(self.config["provider"], provider_config)

        # Store config values for easy access
        self.model = self.config["model"]
        self.max_retries = self.config.get("max_retries", 3)
        self.cache_ttl = self.config.get("cache_ttl", 0)
        self.nocache = self.config.get("nocache", False)
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens")  # None = provider default

    @classmethod
    def from_config(
        cls,
        config: BenchmarkModelConfig,
        cache_dir: str = "workspace/cache",
        max_retries: int = 3,
        timeout: int = 60,
        temperature: float | None = None,
        nocache: bool = True,  # Default to no cache for benchmarking
    ) -> "LLMManager":
        """
        Create an LLMManager from explicit configuration.

        This factory method allows creating LLMManager instances without
        relying on environment variables, useful for benchmarking multiple
        models in the same process.

        Args:
            config: BenchmarkModelConfig with provider/model settings
            cache_dir: Directory for response caching
            max_retries: Number of retry attempts
            timeout: Request timeout in seconds
            temperature: Sampling temperature, defaults to LLM_TEMPERATURE from env
            nocache: Whether to disable caching (default True for benchmarking)

        Returns:
            Configured LLMManager instance

        Raises:
            ConfigurationError: If configuration is invalid
        """
        load_dotenv(override=True)

        # Get temperature from env if not provided
        effective_temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", "0.7"))
        )

        # Create instance without calling __init__
        instance = object.__new__(cls)

        # Build config dict from BenchmarkModelConfig
        instance.config = {
            "provider": config.provider,
            "api_url": config.get_api_url(),
            "api_key": config.get_api_key(),
            "model": config.model,
            "cache_dir": cache_dir,
            "max_retries": max_retries,
            "timeout": timeout,
            "temperature": effective_temperature,
            "nocache": nocache,
        }

        # Validate
        instance._validate_config()

        # Initialize cache manager
        cache_path = Path(cache_dir)
        if not cache_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            cache_path = project_root / cache_path
        instance.cache = CacheManager(str(cache_path))

        # Create provider
        provider_config = ProviderConfig(
            api_url=instance.config["api_url"],
            api_key=instance.config["api_key"],
            model=instance.config["model"],
            timeout=timeout,
        )
        instance.provider = create_provider(config.provider, provider_config)

        # Store config values
        instance.model = config.model
        instance.max_retries = max_retries
        instance.cache_ttl = 0
        instance.nocache = nocache
        instance.temperature = effective_temperature
        instance.max_tokens = None  # None = use provider default

        return instance

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self.config.get("provider", "unknown")

    def _load_config_from_env(self) -> dict[str, Any]:
        """
        Load configuration from environment variables (.env file).

        Supports two modes:
        1. LLM_DEFAULT_MODEL: References a benchmark model config (e.g., "azure-gpt4mini")
        2. Legacy mode: Uses LLM_PROVIDER with provider-specific settings

        Returns:
            Configuration dictionary

        Raises:
            ConfigurationError: If required env vars are missing
        """
        # Check if using a benchmark model as default
        default_model = os.getenv("LLM_DEFAULT_MODEL")
        if default_model:
            # Load benchmark model configs and use the specified one
            benchmark_models = load_benchmark_models()
            if default_model not in benchmark_models:
                available = (
                    ", ".join(benchmark_models.keys()) if benchmark_models else "none"
                )
                raise ConfigurationError(
                    f"LLM_DEFAULT_MODEL '{default_model}' not found. Available: {available}"
                )
            config = benchmark_models[default_model]
            provider = config.provider
            api_url = config.get_api_url()
            api_key = config.get_api_key()
            model = config.model
        else:
            # Legacy mode: use LLM_PROVIDER with provider-specific settings
            provider = os.getenv("LLM_PROVIDER", "azure")

            # Get provider-specific settings
            if provider == "azure":
                api_url = os.getenv("LLM_AZURE_API_URL")
                api_key = os.getenv("LLM_AZURE_API_KEY")
                model = os.getenv("LLM_AZURE_MODEL", "gpt-4o-mini")
            elif provider == "openai":
                api_url = "https://api.openai.com/v1/chat/completions"
                api_key = os.getenv("LLM_OPENAI_API_KEY")
                model = os.getenv("LLM_OPENAI_MODEL", "gpt-4o-mini")
            elif provider == "anthropic":
                api_url = "https://api.anthropic.com/v1/messages"
                api_key = os.getenv("LLM_ANTHROPIC_API_KEY")
                model = os.getenv("LLM_ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            elif provider == "ollama":
                api_url = os.getenv(
                    "LLM_OLLAMA_API_URL", "http://localhost:11434/api/chat"
                )
                api_key = None  # Ollama doesn't require an API key
                model = os.getenv("LLM_OLLAMA_MODEL", "llama3.2")
            else:
                raise ConfigurationError(f"Unknown LLM provider: {provider}")

        # Parse max_tokens - None if not set or empty
        max_tokens_str = os.getenv("LLM_MAX_TOKENS", "")
        max_tokens = int(max_tokens_str) if max_tokens_str else None

        return {
            "provider": provider,
            "api_url": api_url,
            "api_key": api_key,
            "model": model,
            "cache_dir": os.getenv("LLM_CACHE_DIR", "workspace/cache"),
            "cache_ttl": int(os.getenv("LLM_CACHE_TTL", "0")),
            "max_retries": int(os.getenv("LLM_MAX_RETRIES", "3")),
            "timeout": int(os.getenv("LLM_TIMEOUT", "60")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
            "max_tokens": max_tokens,  # None = use provider default
            "nocache": os.getenv("LLM_NOCACHE", "false").strip("'\"").lower() == "true",
        }

    def _validate_config(self) -> None:
        """
        Validate configuration has required fields.

        Raises:
            ConfigurationError: If required fields are missing
        """
        # Ollama and ClaudeCode don't require api_key
        if self.config["provider"] in ("ollama", "claudecode"):
            required_fields = ["provider", "api_url", "model"]
        else:
            required_fields = ["provider", "api_url", "api_key", "model"]

        missing = [f for f in required_fields if not self.config.get(f)]

        if missing:
            raise ConfigurationError(
                f"Missing required config fields: {', '.join(missing)}"
            )

    def _validate_prompt(self, prompt: str) -> None:
        """
        Validate prompt input.

        Args:
            prompt: The prompt to validate

        Raises:
            ValidationError: If prompt is invalid
        """
        if not prompt or not isinstance(prompt, str):
            raise ValidationError("Prompt must be a non-empty string")

        if len(prompt.strip()) == 0:
            raise ValidationError("Prompt cannot be empty or whitespace only")

    def _build_messages(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Build message list for the provider.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt

        Returns:
            List of message dictionaries
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _augment_prompt_for_schema(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> str:
        """
        Augment prompt with schema instructions.

        Args:
            prompt: Original prompt
            schema: Raw JSON schema dict
            response_model: Pydantic model for structured output

        Returns:
            Augmented prompt with schema instructions
        """
        if response_model:
            schema = response_model.model_json_schema()

        if not schema:
            return prompt

        schema_str = json.dumps(schema, indent=2)
        return f"""{prompt}

Respond with a valid JSON object matching this schema:
```json
{schema_str}
```

Return only the JSON object, no additional text."""

    @overload
    def query(
        self,
        prompt: str,
        *,
        response_model: type[T],
        schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
        system_prompt: str | None = None,
    ) -> T | FailedResponse: ...

    @overload
    def query(
        self,
        prompt: str,
        *,
        response_model: None = None,
        schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
        system_prompt: str | None = None,
    ) -> LLMResponse: ...

    def query(
        self,
        prompt: str,
        *,
        response_model: type[T] | None = None,
        schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
        system_prompt: str | None = None,
    ) -> T | LLMResponse:
        """
        Query the LLM with automatic caching and optional structured output.

        Args:
            prompt: The prompt text
            response_model: Pydantic model for structured output (returns validated instance)
            schema: Optional raw JSON schema for structured output
            temperature: Sampling temperature (0-2), defaults to configured LLM_TEMPERATURE
            max_tokens: Maximum tokens in response
            use_cache: Whether to use caching (default: True)
            system_prompt: Optional system prompt

        Returns:
            If response_model is provided: Validated Pydantic model instance or FailedResponse
            Otherwise: LiveResponse, CachedResponse, or FailedResponse
        """
        # Use configured values if not explicitly provided
        effective_temperature = (
            temperature if temperature is not None else self.temperature
        )
        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        # Determine if we need JSON mode
        json_mode = schema is not None or response_model is not None

        # Augment prompt with schema if needed
        effective_prompt = self._augment_prompt_for_schema(
            prompt, schema, response_model
        )

        # Generate cache key
        cache_key = CacheManager.generate_cache_key(
            effective_prompt,
            self.model,
            response_model.model_json_schema() if response_model else schema,
        )

        # Determine cache behavior:
        # - read_cache: Whether to read from cache (disabled by nocache)
        # - write_cache: Whether to write to cache (always enabled unless use_cache=False)
        read_cache = use_cache and not self.nocache
        write_cache = use_cache  # Always write to cache if use_cache is True

        try:
            self._validate_prompt(prompt)

            # Check cache (only if reading is enabled)
            if read_cache:
                cached = self.cache.get(cache_key)
                if cached:
                    if cached.get("is_error"):
                        return FailedResponse(
                            prompt=cached["prompt"],
                            model=cached["model"],
                            error=cached["error"],
                            error_type=cached["error_type"],
                        )

                    content = cached["content"]

                    # If response_model, parse and return the model
                    if response_model:
                        try:
                            return response_model.model_validate_json(content)
                        except PydanticValidationError:
                            # Cached content doesn't match model, invalidate and retry
                            pass
                    else:
                        return CachedResponse(
                            prompt=cached["prompt"],
                            model=cached["model"],
                            content=content,
                            cache_key=cached["cache_key"],
                            cached_at=cached["cached_at"],
                        )

            # Build messages
            messages = self._build_messages(effective_prompt, system_prompt)

            # Attempt API call with retries
            last_error = None

            for attempt in range(self.max_retries):
                try:
                    result = self.provider.complete(
                        messages=messages,
                        temperature=effective_temperature,
                        max_tokens=effective_max_tokens,
                        json_mode=json_mode,
                    )

                    content = result.content

                    # Validate JSON if schema provided
                    if json_mode:
                        try:
                            parsed = json.loads(content)

                            # If response_model, validate and return
                            if response_model:
                                try:
                                    validated = response_model.model_validate(parsed)

                                    # Cache the raw content
                                    if write_cache:
                                        self.cache.set(
                                            cache_key,
                                            content,
                                            prompt,
                                            self.model,
                                            result.usage,
                                        )

                                    return validated

                                except PydanticValidationError as e:
                                    if attempt < self.max_retries - 1:
                                        last_error = f"Pydantic validation failed: {e}"
                                        messages = self._build_messages(
                                            f"{effective_prompt}\n\nPrevious attempt failed: {last_error}\nPlease fix the response.",
                                            system_prompt,
                                        )
                                        continue
                                    raise ValidationError(
                                        f"Failed to validate response after {self.max_retries} attempts: {e}"
                                    )

                        except json.JSONDecodeError as e:
                            if attempt < self.max_retries - 1:
                                last_error = f"JSON parsing failed: {e}"
                                messages = self._build_messages(
                                    f"{effective_prompt}\n\nPrevious attempt returned invalid JSON: {last_error}\nPlease return valid JSON.",
                                    system_prompt,
                                )
                                continue
                            raise ValidationError(
                                f"Failed to generate valid JSON after {self.max_retries} attempts: {e}"
                            )

                    # Success! Cache the response
                    if write_cache:
                        self.cache.set(
                            cache_key, content, prompt, self.model, result.usage
                        )

                    return LiveResponse(
                        prompt=prompt,
                        model=self.model,
                        content=content,
                        usage=result.usage,
                        finish_reason=result.finish_reason,
                    )

                except ProviderError as e:
                    last_error = str(e)
                    if attempt < self.max_retries - 1:
                        continue
                    raise APIError(str(e)) from e

            raise APIError(
                f"Failed after {self.max_retries} attempts. Last error: {last_error}"
            )

        except (ValidationError, APIError) as e:
            error_response = FailedResponse(
                prompt=prompt,
                model=self.model,
                error=str(e),
                error_type=type(e).__name__,
            )

            if write_cache:
                self._cache_error(cache_key, prompt, str(e), type(e).__name__)

            return error_response

        except Exception as e:
            error_response = FailedResponse(
                prompt=prompt,
                model=self.model,
                error=f"Unexpected error: {e}",
                error_type="UnexpectedError",
            )

            if write_cache:
                self._cache_error(
                    cache_key, prompt, f"Unexpected error: {e}", "UnexpectedError"
                )

            return error_response

    def _cache_error(
        self, cache_key: str, prompt: str, error: str, error_type: str
    ) -> None:
        """
        Cache an error response to prevent retrying failed prompts.

        Args:
            cache_key: The cache key
            prompt: The original prompt
            error: Error message
            error_type: Type of error
        """
        error_data = {
            "prompt": prompt,
            "model": self.model,
            "error": error,
            "error_type": error_type,
            "is_error": True,
            "cached_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "cache_key": cache_key,
        }

        cache_file = self.cache.cache_dir / f"{cache_key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to cache error response: %s", e)

    def clear_cache(self) -> None:
        """Clear all cached responses."""
        self.cache.clear_all()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        return self.cache.get_cache_stats()

    def __repr__(self) -> str:
        """String representation."""
        return f"LLMManager(provider={self.provider.name}, model={self.model})"
