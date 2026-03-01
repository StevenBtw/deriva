"""
LLM Manager - Unified interface for LLM API calls with caching and structured output.

Uses PydanticAI for model-agnostic LLM interactions.

Supported Providers:
    - Azure OpenAI
    - OpenAI
    - Anthropic
    - Ollama
    - Mistral
    - LM Studio

Usage:
    from deriva.adapters.llm import LLMManager

    # Basic query
    llm = LLMManager()
    response = llm.query("Explain Python decorators")
    print(response.content)

    # Structured output with Pydantic
    from pydantic import BaseModel

    class Concept(BaseModel):
        name: str
        description: str

    result = llm.query("Extract concept...", response_model=Concept)
    print(result.name)  # Type-safe access
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, TypeVar, cast, overload

import asyncio
import concurrent.futures
from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from deriva.common.exceptions import CircuitOpenError

from .cache import CacheManager
from .model_registry import VALID_PROVIDERS, get_pydantic_ai_model
from .models import (
    BenchmarkModelConfig,
    CachedResponse,
    ConfigurationError,
    FailedResponse,
    LiveResponse,
    LLMResponse,
    ValidationError,
)
from .rate_limiter import RateLimitConfig, RateLimiter, get_default_rate_limit
from .retry import classify_exception
from .schemas import EXTRACTION_SCHEMAS

# Thread pool for running LLM calls outside of existing event loops
_llm_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or create the thread pool executor for LLM calls."""
    global _llm_executor
    if _llm_executor is None:
        _llm_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="llm_"
        )
    return _llm_executor


def _is_event_loop_running() -> bool:
    """Check if there's currently a running event loop."""
    try:
        loop = asyncio.get_running_loop()
        return loop is not None
    except RuntimeError:
        return False


logger = logging.getLogger(__name__)

# Map JSON schema names to Pydantic models
_SCHEMA_NAME_TO_MODEL: dict[str, type[BaseModel]] = {
    "business_concepts_extraction": EXTRACTION_SCHEMAS["BusinessConcept"],
    "business_concepts_multi_extraction": EXTRACTION_SCHEMAS["BusinessConceptMulti"],
    "type_definitions_extraction": EXTRACTION_SCHEMAS["TypeDefinition"],
    "technology_extraction": EXTRACTION_SCHEMAS["Technology"],
    "external_dependency_extraction": EXTRACTION_SCHEMAS["ExternalDependency"],
    "test_extraction": EXTRACTION_SCHEMAS["Test"],
    "methods_extraction": EXTRACTION_SCHEMAS["Method"],
    "directory_classification": EXTRACTION_SCHEMAS["DirectoryClassification"],
}


def _resolve_schema_to_model(schema: dict[str, Any] | None) -> type[BaseModel] | None:
    """
    Resolve a JSON schema dict to its corresponding Pydantic model.

    Args:
        schema: JSON schema dict with 'name' field

    Returns:
        Corresponding Pydantic model class, or None if not found
    """
    if not schema:
        return None

    schema_name = schema.get("name")
    if not schema_name:
        return None

    return _SCHEMA_NAME_TO_MODEL.get(schema_name)


# Type variable for structured output
T = TypeVar("T", bound=BaseModel)


def get_model_rpm(model_name: str, provider: str) -> int:
    """
    Get RPM for a specific model, falling back to provider default.

    Checks for model-specific env var: LLM_{MODEL_NAME}_RPM
    Falls back to global LLM_RATE_LIMIT_RPM, then provider default.

    Args:
        model_name: The model name (e.g., "mistral-devstral")
        provider: The provider name (e.g., "mistral")

    Returns:
        Requests per minute limit
    """
    # Check for model-specific RPM: LLM_{MODEL_NAME}_RPM
    model_key = model_name.upper().replace("-", "_")
    model_rpm_str = os.getenv(f"LLM_{model_key}_RPM")
    if model_rpm_str:
        try:
            return int(model_rpm_str)
        except ValueError:
            pass

    # Check global RPM setting
    global_rpm_str = os.getenv("LLM_RATE_LIMIT_RPM", "0")
    try:
        global_rpm = int(global_rpm_str)
        if global_rpm > 0:
            return global_rpm
    except ValueError:
        pass

    # Fall back to provider default
    return get_default_rate_limit(provider)


def load_benchmark_models() -> dict[str, BenchmarkModelConfig]:
    """
    Load model configurations from environment variables.

    Looks for environment variables matching the pattern:
        LLM_{NAME}_PROVIDER
        LLM_{NAME}_MODEL
        LLM_{NAME}_URL (optional)
        LLM_{NAME}_KEY (optional, direct key)
        LLM_{NAME}_KEY_ENV (optional, env var name for key)

    Returns:
        Dict mapping config name to BenchmarkModelConfig
    """
    load_dotenv(override=True)

    configs: dict[str, BenchmarkModelConfig] = {}

    prefix = "LLM_"
    suffix = "_PROVIDER"

    for key, value in os.environ.items():
        if key.startswith(prefix) and key.endswith(suffix) and key != "LLM_PROVIDER":
            name = key[len(prefix) : -len(suffix)]

            provider = value
            model = os.getenv(f"{prefix}{name}_MODEL", "")
            api_url = os.getenv(f"{prefix}{name}_URL")
            api_key = os.getenv(f"{prefix}{name}_KEY")
            api_key_env = os.getenv(f"{prefix}{name}_KEY_ENV")

            if not model:
                continue

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
                continue

    return configs


def _serialize_output(output: object) -> str:
    """Serialize a pydantic model or arbitrary output to a JSON string."""
    dump = getattr(output, "model_dump_json", None)
    if callable(dump):
        return dump()
    return str(output)


class LLMManager:
    """
    Manages LLM API calls with intelligent caching and structured output support.

    Uses PydanticAI for model interactions with caching layer on top.

    Features:
    - Multi-provider support (Azure OpenAI, OpenAI, Anthropic, Ollama, Mistral, LM Studio)
    - Automatic caching of responses
    - Structured output with Pydantic models
    - Rate limiting
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
        cache_dir = self.config.get("cache_dir", "workspace/cache/llm")
        cache_path = Path(cache_dir)
        if not cache_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            cache_path = project_root / cache_path
        self.cache = CacheManager(str(cache_path))

        # Initialize rate limiter with model-specific RPM and adaptive features
        rpm = get_model_rpm(self.config["model"], self.config["provider"])
        self._rate_limiter = RateLimiter(
            config=RateLimitConfig(
                requests_per_minute=rpm,
                min_request_delay=self.config.get("min_request_delay", 0.0),
                # Adaptive throttling
                throttle_enabled=self.config.get("throttle_enabled", True),
                throttle_min_factor=self.config.get("throttle_min_factor", 0.25),
                throttle_recovery_time=self.config.get("throttle_recovery_time", 60.0),
                # Circuit breaker
                circuit_breaker_enabled=self.config.get(
                    "circuit_breaker_enabled", True
                ),
                circuit_failure_threshold=self.config.get(
                    "circuit_failure_threshold", 5
                ),
                circuit_recovery_time=self.config.get("circuit_recovery_time", 30.0),
            )
        )

        # Get PydanticAI model
        self._pydantic_model = get_pydantic_ai_model(self.config)

        # Store config values for easy access
        self.model = self.config["model"]
        self.max_retries = self.config.get("max_retries", 3)
        self.cache_ttl = self.config.get("cache_ttl", 0)
        self.nocache = self.config.get("nocache", False)
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens")

    @classmethod
    def from_config(
        cls,
        config: BenchmarkModelConfig,
        cache_dir: str = "workspace/cache/llm",
        max_retries: int = 3,
        timeout: int = 60,
        temperature: float | None = None,
        nocache: bool = True,
    ) -> "LLMManager":
        """
        Create an LLMManager from explicit configuration.

        Args:
            config: BenchmarkModelConfig with provider/model settings
            cache_dir: Directory for response caching
            max_retries: Number of retry attempts
            timeout: Request timeout in seconds
            temperature: Sampling temperature, defaults to LLM_TEMPERATURE from env
            nocache: Whether to disable caching (default True for benchmarking)

        Returns:
            Configured LLMManager instance
        """
        load_dotenv(override=True)

        effective_temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", "0.7"))
        )

        instance = object.__new__(cls)

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

        instance._validate_config()

        cache_path = Path(cache_dir)
        if not cache_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent.parent
            cache_path = project_root / cache_path
        instance.cache = CacheManager(str(cache_path))

        rpm = get_model_rpm(config.model, config.provider)
        instance._rate_limiter = RateLimiter(
            config=RateLimitConfig(
                requests_per_minute=rpm,
                min_request_delay=float(os.getenv("LLM_RATE_LIMIT_DELAY", "0.0")),
                # Adaptive throttling
                throttle_enabled=os.getenv("LLM_THROTTLE_ENABLED", "true").lower()
                == "true",
                throttle_min_factor=float(os.getenv("LLM_THROTTLE_MIN_FACTOR", "0.25")),
                throttle_recovery_time=float(
                    os.getenv("LLM_THROTTLE_RECOVERY_TIME", "60.0")
                ),
                # Circuit breaker
                circuit_breaker_enabled=os.getenv(
                    "LLM_CIRCUIT_BREAKER_ENABLED", "true"
                ).lower()
                == "true",
                circuit_failure_threshold=int(
                    os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "5")
                ),
                circuit_recovery_time=float(
                    os.getenv("LLM_CIRCUIT_RECOVERY_TIME", "30.0")
                ),
            )
        )

        instance._pydantic_model = get_pydantic_ai_model(instance.config)

        instance.model = config.model
        instance.max_retries = max_retries
        instance.cache_ttl = 0
        instance.nocache = nocache
        instance.temperature = effective_temperature
        instance.max_tokens = None

        return instance

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self.config.get("provider", "unknown")

    def _load_config_from_env(self) -> dict[str, Any]:
        """Load configuration from environment variables."""
        default_model = os.getenv("LLM_DEFAULT_MODEL")
        if default_model:
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
            provider = os.getenv("LLM_PROVIDER", "azure")

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
                model = os.getenv("LLM_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
            elif provider == "ollama":
                api_url = os.getenv(
                    "LLM_OLLAMA_API_URL", "http://localhost:11434/api/chat"
                )
                api_key = None
                model = os.getenv("LLM_OLLAMA_MODEL", "llama3.2")
            elif provider == "mistral":
                api_url = "https://api.mistral.ai/v1/chat/completions"
                api_key = os.getenv("LLM_MISTRAL_API_KEY")
                model = os.getenv("LLM_MISTRAL_MODEL", "mistral-large-latest")
            elif provider == "lmstudio":
                api_url = os.getenv(
                    "LLM_LMSTUDIO_API_URL", "http://localhost:1234/v1/chat/completions"
                )
                api_key = None
                model = os.getenv("LLM_LMSTUDIO_MODEL", "local-model")
            else:
                raise ConfigurationError(f"Unknown LLM provider: {provider}")

        max_tokens_str = os.getenv("LLM_MAX_TOKENS", "")
        max_tokens = int(max_tokens_str) if max_tokens_str else None

        return {
            "provider": provider,
            "api_url": api_url,
            "api_key": api_key,
            "model": model,
            "cache_dir": os.getenv("LLM_CACHE_DIR", "workspace/cache/llm"),
            "cache_ttl": int(os.getenv("LLM_CACHE_TTL", "0")),
            "max_retries": int(os.getenv("LLM_MAX_RETRIES", "3")),
            "timeout": int(os.getenv("LLM_TIMEOUT", "60")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
            "max_tokens": max_tokens,
            "nocache": os.getenv("LLM_NOCACHE", "false").strip("'\"").lower() == "true",
            "requests_per_minute": int(os.getenv("LLM_RATE_LIMIT_RPM", "0")),
            "min_request_delay": float(os.getenv("LLM_RATE_LIMIT_DELAY", "0.0")),
            # Retry configuration
            "retry_base_delay": float(os.getenv("LLM_RETRY_BASE_DELAY", "2.0")),
            "retry_max_delay": float(os.getenv("LLM_RETRY_MAX_DELAY", "60.0")),
            # Adaptive throttling
            "throttle_enabled": os.getenv("LLM_THROTTLE_ENABLED", "true").lower()
            == "true",
            "throttle_min_factor": float(os.getenv("LLM_THROTTLE_MIN_FACTOR", "0.25")),
            "throttle_recovery_time": float(
                os.getenv("LLM_THROTTLE_RECOVERY_TIME", "60.0")
            ),
            # Circuit breaker
            "circuit_breaker_enabled": os.getenv(
                "LLM_CIRCUIT_BREAKER_ENABLED", "true"
            ).lower()
            == "true",
            "circuit_failure_threshold": int(
                os.getenv("LLM_CIRCUIT_FAILURE_THRESHOLD", "5")
            ),
            "circuit_recovery_time": float(
                os.getenv("LLM_CIRCUIT_RECOVERY_TIME", "30.0")
            ),
        }

    def _validate_config(self) -> None:
        """Validate configuration has required fields."""
        provider = self.config.get("provider", "")
        if provider not in VALID_PROVIDERS:
            raise ConfigurationError(
                f"Invalid provider: {provider}. Must be one of {VALID_PROVIDERS}"
            )

        # Ollama and LM Studio don't require api_key
        if provider in ("ollama", "lmstudio"):
            required_fields = ["provider", "model"]
        else:
            required_fields = ["provider", "api_key", "model"]

        missing = [f for f in required_fields if not self.config.get(f)]
        if missing:
            raise ConfigurationError(
                f"Missing required config fields: {', '.join(missing)}"
            )

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
        bench_hash: str | None = None,
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
        bench_hash: str | None = None,
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
        bench_hash: str | None = None,
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
            bench_hash: Optional benchmark hash for per-run cache isolation

        Returns:
            If response_model is provided: Validated Pydantic model instance or FailedResponse
            Otherwise: LiveResponse, CachedResponse, or FailedResponse
        """
        effective_temperature = (
            temperature if temperature is not None else self.temperature
        )
        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        # Generate cache key
        cache_key = CacheManager.generate_cache_key(
            prompt,
            self.model,
            response_model.model_json_schema() if response_model else schema,
            bench_hash=bench_hash,
        )

        read_cache = use_cache and not self.nocache
        write_cache = use_cache

        try:
            # Validate prompt
            if not prompt or not isinstance(prompt, str) or len(prompt.strip()) == 0:
                raise ValidationError("Prompt must be a non-empty string")

            # Check cache
            if read_cache:
                cached = self.cache.get(cache_key)
                if cached and not cached.get("is_error"):
                    content = cached["content"]
                    if content and content.strip():
                        if response_model:
                            try:
                                return response_model.model_validate_json(content)
                            except Exception:
                                pass  # Cache miss, continue to API call
                        else:
                            return CachedResponse(
                                prompt=cached["prompt"],
                                model=cached["model"],
                                content=content,
                                cache_key=cached["cache_key"],
                                cached_at=cached["cached_at"],
                            )

            # Rate limit
            self._rate_limiter.wait_if_needed()

            # Resolve output type:
            # 1. Use explicit response_model if provided
            # 2. Otherwise, try to resolve schema dict to Pydantic model
            # 3. Fall back to str (unstructured) if neither works
            resolved_model = response_model or _resolve_schema_to_model(schema)
            output_type = resolved_model if resolved_model else str

            # Track if we're using schema-resolved model (for response handling)
            using_schema_model = resolved_model is not None and response_model is None

            # Create PydanticAI agent
            agent: Agent[None, Any] = Agent(
                model=self._pydantic_model,
                output_type=output_type,
                system_prompt=system_prompt or "",
                retries=self.max_retries,
            )

            # Run query
            settings: ModelSettings = {"temperature": effective_temperature}
            if effective_max_tokens is not None:
                settings["max_tokens"] = effective_max_tokens

            # Handle event loop conflict (e.g., running inside marimo/Jupyter)
            # pydantic_ai's run_sync() uses run_until_complete() which fails
            # if there's already a running event loop. In that case, we run
            # the LLM call in a separate thread.
            if _is_event_loop_running():
                # Running inside an async context (marimo/Jupyter) - use thread pool
                def _run_in_thread() -> Any:
                    return agent.run_sync(prompt, model_settings=settings)

                future = _get_executor().submit(_run_in_thread)
                result = future.result()
            else:
                # No event loop conflict - use run_sync directly
                result = agent.run_sync(
                    prompt,
                    model_settings=settings,
                )

            self._rate_limiter.record_success()

            # Extract usage
            usage = None
            if hasattr(result, "usage") and result.usage:
                usage = {
                    "prompt_tokens": getattr(result.usage, "request_tokens", 0) or 0,
                    "completion_tokens": getattr(result.usage, "response_tokens", 0)
                    or 0,
                    "total_tokens": getattr(result.usage, "total_tokens", 0) or 0,
                }

            # Handle response
            output: Any = result.output
            if response_model:
                # Explicit response_model: return the Pydantic instance
                if write_cache:
                    content = _serialize_output(output)
                    self.cache.set_response(
                        cache_key, content, prompt, self.model, usage
                    )
                return cast(T, output)
            elif using_schema_model:
                # Schema-resolved model: serialize to JSON for backwards compatibility
                content = _serialize_output(output)
                if write_cache:
                    self.cache.set_response(
                        cache_key, content, prompt, self.model, usage
                    )
                return LiveResponse(
                    prompt=prompt,
                    model=self.model,
                    content=content,
                    usage=usage,
                    finish_reason="stop",
                )
            else:
                # Unstructured string output
                content = str(result.output) if result.output else ""
                if write_cache:
                    self.cache.set_response(
                        cache_key, content, prompt, self.model, usage
                    )
                return LiveResponse(
                    prompt=prompt,
                    model=self.model,
                    content=content,
                    usage=usage,
                    finish_reason="stop",
                )

        except CircuitOpenError as e:
            # Circuit breaker is open - fail fast without attempting request
            logger.warning(
                "LLM query blocked by circuit breaker: %s",
                e,
            )
            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=str(e),
                error_type="CircuitOpenError",
            )

        except ValidationError as e:
            logger.warning("LLM query failed with ValidationError: %s", e)
            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=str(e),
                error_type="ValidationError",
            )

        except Exception as e:
            # Classify the error and update rate limiter state
            category, retry_after = classify_exception(e)

            if category == "rate_limited":
                self._rate_limiter.record_rate_limit(retry_after)
                logger.warning(
                    "LLM query rate limited: %s (retry_after: %s)",
                    e,
                    retry_after,
                )
            elif category == "transient":
                self._rate_limiter.record_failure()
                logger.warning("LLM query failed with transient error: %s", e)
            else:
                # Permanent error - don't update failure counters
                logger.warning(
                    "LLM query failed with permanent error (%s): %s",
                    type(e).__name__,
                    e,
                )

            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=str(e),
                error_type=type(e).__name__,
            )

    def clear_cache(self) -> None:
        """Clear all cached responses."""
        self.cache.clear_all()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self.cache.get_cache_stats()

    def get_token_usage_stats(self) -> dict[str, Any]:
        """
        Aggregate token usage statistics from all cached entries.

        Returns:
            Dictionary with token usage statistics
        """
        import json

        total_prompt = 0
        total_completion = 0
        total_calls = 0

        for cache_file in self.cache.cache_dir.glob("*.json"):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                    usage = data.get("usage", {})
                    if usage and not data.get("is_error"):
                        total_prompt += usage.get("prompt_tokens", 0)
                        total_completion += usage.get("completion_tokens", 0)
                        total_calls += 1
            except json.JSONDecodeError, OSError:
                continue

        return {
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_calls": total_calls,
            "avg_prompt_tokens": total_prompt / total_calls if total_calls else 0,
            "avg_completion_tokens": total_completion / total_calls
            if total_calls
            else 0,
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"LLMManager(provider={self.provider_name}, model={self.model})"
