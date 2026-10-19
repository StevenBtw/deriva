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

import asyncio
import concurrent.futures
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, TypeVar, cast, overload

import httpx2
from pydantic import BaseModel
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import IncompleteToolCall, ModelHTTPError
from pydantic_ai.messages import ModelResponse
from pydantic_ai.settings import ModelSettings

from deriva.common import settings
from deriva.common.exceptions import CircuitOpenError
from deriva.common.paths import resolve
from deriva.common.settings import LlmSettings

from .cache import CacheManager
from .model_registry import VALID_PROVIDERS, default_sampling, get_pydantic_ai_model, parse_sampling, reasoning_settings
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
from .retry import classify_exception, transport_error
from .schemas import EXTRACTION_SCHEMAS, ArchiMateModelResponse

# Thread pool for running LLM calls outside of existing event loops
_llm_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _get_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or create the thread pool executor for LLM calls."""
    global _llm_executor
    if _llm_executor is None:
        _llm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm_")
    return _llm_executor


def _is_retriable(error: Exception) -> bool:
    """Timeouts, connection errors, rate limits and 5xx are worth another try; other errors are not.

    pydantic-ai wraps what the HTTP layer raises (a timeout arrives as a ``ModelAPIError`` whose
    cause chain ends in the httpx2 transport error), so the transport error is looked for behind
    the exception, not only on it. Output validation retries are handled by the pydantic-ai agent
    itself.
    """
    transport = transport_error(error)
    if transport is not None:
        # Client-side and permanent: a malformed header or URL never succeeds on retry
        return not isinstance(transport, (httpx2.LocalProtocolError, httpx2.UnsupportedProtocol))
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return isinstance(error, ModelHTTPError) and classify_exception(error)[0] in (
        "rate_limited",
        "transient",
    )


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
    "business_concept_classification": EXTRACTION_SCHEMAS["BusinessConcept"],
    "type_definitions_extraction": EXTRACTION_SCHEMAS["TypeDefinition"],
    "technology_classification": EXTRACTION_SCHEMAS["Technology"],
    "external_dependency_extraction": EXTRACTION_SCHEMAS["ExternalDependency"],
    "test_extraction": EXTRACTION_SCHEMAS["Test"],
    "methods_extraction": EXTRACTION_SCHEMAS["Method"],
    "directory_classification": EXTRACTION_SCHEMAS["DirectoryClassification"],
    "archimate_model_generation": ArchiMateModelResponse,
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
    model_rpm_str = settings.get(f"LLM_{model_key}_RPM")
    if model_rpm_str:
        try:
            return int(model_rpm_str)
        except ValueError:
            pass

    # Check global RPM setting
    global_rpm = LlmSettings().rate_limit_rpm
    if global_rpm > 0:
        return global_rpm

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
        LLM_{NAME}_SAMPLING (optional, false: the model takes no temperature)
        LLM_{NAME}_REASONING (optional, reasoning level; none turns reasoning off)
        LLM_{NAME}_TEMPERATURE (optional, the model's own temperature over LLM_TEMPERATURE)

    Returns:
        Dict mapping config name to BenchmarkModelConfig
    """
    configs: dict[str, BenchmarkModelConfig] = {}

    for name, fields in settings.model_configs().items():
        provider = fields["provider"] or ""
        model = fields["model"] or ""
        if not model:
            continue

        friendly_name = name.lower().replace("_", "-")

        try:
            configs[friendly_name] = BenchmarkModelConfig(
                name=friendly_name,
                provider=provider.lower(),
                model=model,
                api_url=fields["url"],
                api_key=fields["key"],
                api_key_env=fields["key_env"],
                sampling=parse_sampling(fields.get("sampling"), provider.lower(), model),
                reasoning=(fields.get("reasoning") or "").strip().lower() or None,
                temperature=float(own) if (own := (fields.get("temperature") or "").strip()) else None,
                context=int(size) if (size := (fields.get("context") or "").strip()) else None,
            )
        except ValueError:
            continue

    return configs


def _key_variable(config: BenchmarkModelConfig) -> str:
    """The variable a model config's key is read from: its KEY_ENV reference, or its own LLM_{NAME}_KEY."""
    return config.api_key_env or f"LLM_{config.name.upper().replace('-', '_')}_KEY"


def _has_cut_response(history: Any) -> bool:
    """Whether a model response in a run's messages stopped at the output limit (finish reason ``length``)."""
    return any(isinstance(m, ModelResponse) and m.finish_reason == "length" for m in history or [])


def _was_cut(result: Any) -> bool:
    """Whether a model response in the run's result stopped at the output limit."""
    messages = getattr(result, "all_messages", None)
    return _has_cut_response(messages() if callable(messages) else [])


def _serialize_output(output: object) -> str:
    """Serialize a pydantic model or arbitrary output to a JSON string."""
    dump = getattr(output, "model_dump_json", None)
    if callable(dump):
        return dump()
    return str(output)


def _cache_path(cache_dir: str | None) -> Path:
    """The LLM cache folder: LLM_CACHE_DIR or the given folder, relative values against the home folder."""
    return resolve(cache_dir or "workspace/cache/llm")


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
        settings.export_provider_keys()  # pydantic-ai providers read their keys from the process environment
        self.config = self._load_config_from_env()
        try:
            self._validate_config()
        except ConfigurationError as e:
            if LlmSettings().default_model:
                raise
            raise ConfigurationError(
                f"No LLM model is configured ({e}): add one in the studio's General page, or set LLM_{{NAME}}_* settings and LLM_DEFAULT_MODEL in .env in the home folder"
            ) from e

        # Initialize cache manager
        self.cache = CacheManager(str(_cache_path(self.config.get("cache_dir"))))

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
                circuit_breaker_enabled=self.config.get("circuit_breaker_enabled", True),
                circuit_failure_threshold=self.config.get("circuit_failure_threshold", 5),
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
        self.sampling = self.config.get("sampling", True)
        self.reasoning = self.config.get("reasoning")
        self.context = self.config.get("context")

    @classmethod
    def from_config(
        cls,
        config: BenchmarkModelConfig,
        cache_dir: str | None = None,
        max_retries: int = 3,
        timeout: int = 60,
        temperature: float | None = None,
        nocache: bool = True,
    ) -> LLMManager:
        """
        Create an LLMManager from explicit configuration.

        Args:
            config: BenchmarkModelConfig with provider/model settings
            cache_dir: Directory for response caching (default: workspace/cache/llm in the Deriva home folder)
            max_retries: Number of retry attempts
            timeout: Request timeout in seconds
            temperature: Sampling temperature, defaults to the model config's own, then LLM_TEMPERATURE from env
            nocache: Whether to disable caching (default True for benchmarking)

        Returns:
            Configured LLMManager instance
        """
        settings.export_provider_keys()  # pydantic-ai providers read their keys from the process environment
        llm = LlmSettings()
        effective_temperature = temperature if temperature is not None else config.temperature if config.temperature is not None else llm.temperature

        instance = object.__new__(cls)

        instance.config = {
            "provider": config.provider,
            "api_url": config.get_api_url(),
            "api_key": config.get_api_key(),
            "api_key_variable": _key_variable(config),
            "label": config.name,
            "model": config.model,
            "cache_dir": cache_dir,
            "max_retries": max_retries,
            "timeout": timeout,
            "temperature": effective_temperature,
            "nocache": nocache,
            "sampling": config.sampling,
            "reasoning": config.reasoning,
            "context": config.context,
        }

        instance._validate_config()

        instance.cache = CacheManager(str(_cache_path(cache_dir)))

        rpm = get_model_rpm(config.model, config.provider)
        instance._rate_limiter = RateLimiter(
            config=RateLimitConfig(
                requests_per_minute=rpm,
                min_request_delay=llm.rate_limit_delay,
                # Adaptive throttling
                throttle_enabled=llm.throttle_enabled,
                throttle_min_factor=llm.throttle_min_factor,
                throttle_recovery_time=llm.throttle_recovery_time,
                # Circuit breaker
                circuit_breaker_enabled=llm.circuit_breaker_enabled,
                circuit_failure_threshold=llm.circuit_failure_threshold,
                circuit_recovery_time=llm.circuit_recovery_time,
            )
        )

        instance._pydantic_model = get_pydantic_ai_model(instance.config)

        instance.model = config.model
        instance.max_retries = max_retries
        instance.cache_ttl = 0
        instance.nocache = nocache
        instance.temperature = effective_temperature
        instance.max_tokens = None
        instance.sampling = config.sampling
        instance.reasoning = config.reasoning
        instance.context = config.context

        return instance

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return self.config.get("provider", "unknown")

    def _warn_on_a_full_context(self, result: Any) -> None:
        """A call whose last request used the model's whole context (when the config names it) lost part of its prompt
        or answer: a local server such as Ollama cuts a prompt longer than its window without an error."""
        if not self.context:
            return
        usage = getattr(getattr(result, "response", None), "usage", None)
        used = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        if used >= self.context:
            logger.warning(
                "An LLM call used %d tokens of %s's %d-token context: part of the prompt or the answer was cut. "
                "Raise the server's context (Ollama: OLLAMA_CONTEXT_LENGTH) and the model's context setting",
                used,
                self.model,
                self.context,
            )

    def _redact(self, text: str) -> str:
        """Keep the configured API key out of exception text: h11 quotes header values in its errors."""
        key = self.config.get("api_key")
        if key and key in text:
            return text.replace(key, "***")
        return text

    def _load_config_from_env(self) -> dict[str, Any]:
        """Load configuration from the settings (home .env under the process environment)."""
        llm = LlmSettings()
        default_model = llm.default_model
        if default_model:
            benchmark_models = load_benchmark_models()
            if default_model not in benchmark_models:
                available = ", ".join(benchmark_models.keys()) if benchmark_models else "none"
                raise ConfigurationError(f"LLM_DEFAULT_MODEL '{default_model}' not found. Available: {available}")
            config = benchmark_models[default_model]
            provider = config.provider
            api_url = config.get_api_url()
            api_key = config.get_api_key()
            key_variable, label = _key_variable(config), config.name
            model = config.model
            sampling, reasoning, context = config.sampling, config.reasoning, config.context
        else:
            provider = llm.provider
            reasoning, context = None, None
            key_variable, label = f"LLM_{(provider or '').upper()}_API_KEY", provider

            if provider == "azure":
                api_url = llm.azure_api_url
                api_key = llm.azure_api_key
                model = llm.azure_model
            elif provider == "openai":
                api_url = "https://api.openai.com/v1/chat/completions"
                api_key = llm.openai_api_key
                model = llm.openai_model
            elif provider == "anthropic":
                api_url = "https://api.anthropic.com/v1/messages"
                api_key = llm.anthropic_api_key
                model = llm.anthropic_model
            elif provider == "ollama":
                api_url = llm.ollama_api_url
                api_key = None
                model = llm.ollama_model
            elif provider == "mistral":
                api_url = "https://api.mistral.ai/v1/chat/completions"
                api_key = llm.mistral_api_key
                model = llm.mistral_model
            elif provider == "lmstudio":
                api_url = llm.lmstudio_api_url
                api_key = None
                model = llm.lmstudio_model
            else:
                raise ConfigurationError(f"Unknown LLM provider: {provider}")
            sampling = default_sampling(provider, model)

        max_tokens = llm.max_tokens

        return {
            "provider": provider,
            "api_url": api_url,
            "api_key": api_key,
            "api_key_variable": key_variable,
            "label": label,
            "model": model,
            "cache_dir": llm.cache_dir,
            "cache_ttl": llm.cache_ttl,
            "max_retries": llm.max_retries,
            "timeout": llm.timeout,
            "temperature": llm.temperature,
            "max_tokens": max_tokens,
            "nocache": llm.nocache,
            "sampling": sampling,
            "reasoning": reasoning,
            "context": context,
            "requests_per_minute": llm.rate_limit_rpm,
            "min_request_delay": llm.rate_limit_delay,
            # Retry configuration
            "retry_base_delay": llm.retry_base_delay,
            "retry_max_delay": llm.retry_max_delay,
            # Adaptive throttling
            "throttle_enabled": llm.throttle_enabled,
            "throttle_min_factor": llm.throttle_min_factor,
            "throttle_recovery_time": llm.throttle_recovery_time,
            # Circuit breaker
            "circuit_breaker_enabled": llm.circuit_breaker_enabled,
            "circuit_failure_threshold": llm.circuit_failure_threshold,
            "circuit_recovery_time": llm.circuit_recovery_time,
        }

    def _validate_config(self) -> None:
        """Validate configuration has required fields."""
        provider = self.config.get("provider", "")
        if provider not in VALID_PROVIDERS:
            raise ConfigurationError(f"Invalid provider: {provider}. Must be one of {VALID_PROVIDERS}")

        # Ollama and LM Studio don't require api_key
        if provider in ("ollama", "lmstudio"):
            required_fields = ["provider", "model"]
        else:
            required_fields = ["provider", "api_key", "model"]

        missing = [f for f in required_fields if not self.config.get(f)]
        # The variable to set and the .env this install reads, never a value
        if "api_key" in missing and self.config.get("api_key_variable"):
            raise ConfigurationError(
                f"The model config {self.config.get('label') or provider} has no API key: set {self.config['api_key_variable']} "
                f"in {settings.env_file()} or in the environment (General in the studio saves a key there)"
            )
        if missing:
            raise ConfigurationError(f"Missing required config fields: {', '.join(missing)}")

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

    @property
    def last_call(self) -> dict[str, Any] | None:
        """Metrics of the latest query() on the current thread.

        Keys: cache_key, provider, model, temperature, max_tokens (the settings the call
        ran with), cache_hit, latency_ms, wait_ms, requests, input_tokens, output_tokens, error_type.
        """
        return getattr(self._call_store(), "call", None)

    def _run_agent(self, agent: Agent[None, Any], prompt: str, settings: ModelSettings) -> tuple[Any, int]:
        """Run one agent call with retries; returns the result and the number of failed attempts."""
        if _is_event_loop_running():
            # Running inside an async context (marimo/Jupyter): run the whole retry loop
            # in the thread pool, so backoff waits do not block the event loop
            return _get_executor().submit(self._run_with_retries, agent, prompt, settings).result()
        return self._run_with_retries(agent, prompt, settings)

    def _run_with_retries(self, agent: Agent[None, Any], prompt: str, settings: ModelSettings) -> tuple[Any, int]:
        """Retry transient failures with jittered exponential backoff.

        A stalled request is bounded by the timeout in ``settings``; timeouts,
        connection errors, rate limits and 5xx responses are retried up to
        ``max_retries`` times (honouring Retry-After), anything else is raised at once.
        The circuit breaker counts the query once, in ``query()``; every rate-limited
        attempt slows the adaptive throttle.
        """
        base_delay = self.config.get("retry_base_delay", 2.0)
        max_delay = self.config.get("retry_max_delay", 60.0)
        for attempt in range(self.max_retries + 1):
            try:
                return self._run_once(agent, prompt, settings), attempt
            except Exception as e:
                if attempt == self.max_retries or not _is_retriable(e):
                    raise
                category, retry_after = classify_exception(e)
                if category == "rate_limited":
                    # Slow the adaptive throttle even if the retry succeeds (the final
                    # failed attempt is recorded by query())
                    self._rate_limiter.record_rate_limit(retry_after)
                if retry_after:
                    delay = min(retry_after, max_delay)
                else:
                    delay = random.uniform(0, min(base_delay * 2**attempt, max_delay))
                logger.warning(
                    "LLM call failed (%s: %s), retry %d/%d in %.1fs",
                    type(e).__name__,
                    self._redact(str(e)),
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _run_once(agent: Agent[None, Any], prompt: str, settings: ModelSettings) -> Any:
        """One agent run. pydantic-ai asks again after an answer cut at the output limit; when those answers fail
        too it raises "Exceeded maximum output retries", which is the cut: raised as IncompleteToolCall."""
        with capture_run_messages() as messages:
            try:
                return agent.run_sync(prompt, model_settings=settings)
            except Exception as e:
                if not isinstance(e, IncompleteToolCall) and _has_cut_response(messages):
                    limit = settings.get("max_tokens") or "provider default"
                    raise IncompleteToolCall(f"Model token limit ({limit}) reached: the answer was cut, and the answers after it failed ({e})") from e
                raise

    def _agent(self, output_type: Any, system_prompt: str) -> Agent[None, Any]:
        """Reusable agent for this output type and system prompt, per thread (created lazily).

        An agent's HTTP client belongs to the event loop of the thread that used it
        first; sharing one agent across threads (parallel samples) made calls hang
        until the timeout. Each thread therefore gets its own agents.
        """
        agents = self.__dict__.setdefault("_agents", {})
        key = (output_type, system_prompt, self.max_retries, threading.get_ident())
        if key not in agents:
            agents[key] = Agent(
                model=self._pydantic_model,
                output_type=output_type,
                system_prompt=system_prompt,
                retries=self.max_retries,
            )
        return agents[key]

    def _call_store(self) -> threading.local:
        if "_calls" not in self.__dict__:
            self.__dict__["_calls"] = threading.local()
        return self.__dict__["_calls"]

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
        # A model that takes no temperature (sampling off) gets none: the key and the record say so
        effective_temperature = (temperature if temperature is not None else self.temperature) if self.sampling else None
        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        # Generate cache key
        cache_key = CacheManager.generate_cache_key(
            prompt,
            self.model,
            response_model.model_json_schema() if response_model else schema,
            bench_hash=bench_hash,
            system_prompt=system_prompt,
            temperature=effective_temperature,
            max_tokens=effective_max_tokens,
            reasoning=self.reasoning,
        )

        read_cache = use_cache and not self.nocache
        write_cache = use_cache

        # Filled in along the way so every return path leaves complete metrics
        call: dict[str, Any] = {
            "cache_key": cache_key,
            # The generation settings the call ran with (after defaults), as in the cache key
            "provider": self.provider_name,
            "model": self.model,
            "temperature": effective_temperature,
            # Never sent: the provider's defaults apply (recorded so a settings table can say so)
            "top_p": None,
            "seed": None,
            "max_tokens": effective_max_tokens,
            "reasoning": self.reasoning,
            # The model the provider says answered (a retired id can be served by another model)
            "served_model": None,
            "cache_hit": False,
            "latency_ms": 0.0,
            "wait_ms": 0.0,
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "error_type": None,
        }
        self._call_store().call = call

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
                                validated = response_model.model_validate_json(content)
                                call["cache_hit"] = True
                                return validated
                            except Exception:
                                pass  # Cache miss, continue to API call
                        else:
                            call["cache_hit"] = True
                            return CachedResponse(
                                prompt=cached["prompt"],
                                model=cached["model"],
                                content=content,
                                cache_key=cached["cache_key"],
                                cached_at=cached["cached_at"],
                            )

            # Rate limit
            call["wait_ms"] = round(self._rate_limiter.wait_if_needed() * 1000, 1)

            # Resolve output type:
            # 1. Use explicit response_model if provided
            # 2. Otherwise, try to resolve schema dict to Pydantic model
            # 3. Fall back to str (unstructured) if neither works
            resolved_model = response_model or _resolve_schema_to_model(schema)
            output_type = resolved_model if resolved_model else str

            # Track if we're using schema-resolved model (for response handling)
            using_schema_model = resolved_model is not None and response_model is None

            # One PydanticAI agent per output type and system prompt (building one costs ~0.2 s)
            agent = self._agent(output_type, system_prompt or "")

            # Run query
            settings: ModelSettings = {
                # pydantic-ai's Mistral model only accepts a float timeout
                "timeout": float(self.config.get("timeout", 60)),
            }
            if effective_temperature is not None:
                settings["temperature"] = effective_temperature
            if effective_max_tokens is not None:
                settings["max_tokens"] = effective_max_tokens
            settings.update(cast("ModelSettings", reasoning_settings(self.provider_name, self.reasoning)))

            # Handle event loop conflict (e.g., running inside marimo/Jupyter)
            # pydantic_ai's run_sync() uses run_until_complete() which fails
            # if there's already a running event loop. In that case, we run
            # the LLM call in a separate thread.
            started = time.perf_counter()
            try:
                result, failed_attempts = self._run_agent(agent, prompt, settings)
            finally:
                call["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            self._rate_limiter.record_success()
            call["served_model"] = getattr(getattr(result, "response", None), "model_name", None)

            # Extract usage (pydantic-ai: result.usage() returns RunUsage)
            usage = None
            # pydantic-ai 2: result.usage is a property; 1.x: a method
            usage_attr = getattr(result, "usage", None)
            run_usage = usage_attr() if callable(usage_attr) else usage_attr
            if run_usage is not None:
                call["requests"] = run_usage.requests + failed_attempts
                call["input_tokens"] = run_usage.input_tokens
                call["output_tokens"] = run_usage.output_tokens
                usage = {
                    "prompt_tokens": run_usage.input_tokens,
                    "completion_tokens": run_usage.output_tokens,
                    "total_tokens": run_usage.input_tokens + run_usage.output_tokens,
                }

            self._warn_on_a_full_context(result)

            # A structured answer cut at the output limit is asked again by pydantic-ai, and a shorter answer that
            # validates can leave part of the question out: a failure (never cached), which a caller can split
            if output_type is not str and _was_cut(result):
                call["error_type"] = "IncompleteToolCall"
                message = f"Model token limit ({effective_max_tokens or 'provider default'}) reached: the answer was cut, and the shorter answer after it may leave part of it out"
                logger.warning("LLM answer cut at the output limit (%s)", self.model)
                return FailedResponse(prompt=prompt, model=self.model, error=message, error_type="IncompleteToolCall")

            # Handle response
            output: Any = result.output

            def _try_cache_write(content: str) -> None:
                """Cache-write is best-effort; disk-full must not fail the call."""
                try:
                    self.cache.set_response(cache_key, content, prompt, self.model, usage)
                except Exception as cache_err:
                    logger.warning("LLM cache write failed (non-fatal): %s", cache_err)

            if response_model:
                # Explicit response_model: return the Pydantic instance
                if write_cache:
                    _try_cache_write(_serialize_output(output))
                return cast(T, output)
            elif using_schema_model:
                # Schema-resolved model: serialize to JSON for backwards compatibility
                content = _serialize_output(output)
                if write_cache:
                    _try_cache_write(content)
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
                    _try_cache_write(content)
                return LiveResponse(
                    prompt=prompt,
                    model=self.model,
                    content=content,
                    usage=usage,
                    finish_reason="stop",
                )

        except CircuitOpenError as e:
            call["error_type"] = "CircuitOpenError"
            # Circuit breaker is open - fail fast without attempting request
            logger.warning(
                "LLM query blocked by circuit breaker: %s",
                self._redact(str(e)),
            )
            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=self._redact(str(e)),
                error_type="CircuitOpenError",
            )

        except ValidationError as e:
            call["error_type"] = "ValidationError"
            logger.warning("LLM query failed with ValidationError: %s", self._redact(str(e)))
            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=self._redact(str(e)),
                error_type="ValidationError",
            )

        except Exception as e:
            # A wrapped transport error is reported under its own name (ReadTimeout, not ModelAPIError)
            call["error_type"] = type(transport_error(e) or e).__name__
            # Classify the error and update rate limiter state
            category, retry_after = classify_exception(e)

            if category == "rate_limited":
                self._rate_limiter.record_rate_limit(retry_after)
                logger.warning(
                    "LLM query rate limited: %s (retry_after: %s)",
                    self._redact(str(e)),
                    retry_after,
                )
            elif category == "transient":
                self._rate_limiter.record_failure()
                logger.warning("LLM query failed with transient error: %s", self._redact(str(e)))
            else:
                # Permanent error - don't update failure counters
                logger.warning(
                    "LLM query failed with permanent error (%s): %s",
                    type(e).__name__,
                    self._redact(str(e)),
                )

            return FailedResponse(
                prompt=prompt,
                model=self.model,
                error=self._redact(str(e)),
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
            "avg_completion_tokens": total_completion / total_calls if total_calls else 0,
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"LLMManager(provider={self.provider_name}, model={self.model})"
