"""
Model registry for PydanticAI provider configuration.

Maps Deriva environment config to PydanticAI model identifiers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Valid provider names
VALID_PROVIDERS = frozenset({"azure", "openai", "anthropic", "ollama", "mistral", "lmstudio"})

# Reasoning levels a model config can set (LLM_{NAME}_REASONING); "none" turns reasoning off
REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

_SAMPLING_VALUES = {"true": True, "1": True, "yes": True, "on": True, "false": False, "0": False, "no": False, "off": False}


def parse_sampling(value: str | None) -> bool:
    """LLM_{NAME}_SAMPLING: off for models that take no temperature (unset means on)."""
    if value is None or not value.strip():
        return True
    if value.strip().lower() not in _SAMPLING_VALUES:
        raise ValueError(f"sampling must be true or false, got {value!r}")
    return _SAMPLING_VALUES[value.strip().lower()]


def reasoning_settings(provider: str, reasoning: str | None) -> dict[str, Any]:
    """The pydantic-ai settings for a model config's reasoning level.

    OpenAI (and Azure) take it as ``openai_reasoning_effort``; with ``none`` a model such as
    gpt-6-luna keeps its temperature. Anthropic turns thinking off for ``none`` and sets the
    effort otherwise. Other providers have no setting here.
    """
    if reasoning is None:
        return {}
    if reasoning not in REASONING_LEVELS:
        raise ValueError(f"reasoning must be one of {', '.join(REASONING_LEVELS)}, got {reasoning!r}")
    if provider in ("openai", "azure"):
        return {"openai_reasoning_effort": reasoning}
    if provider == "anthropic":
        if reasoning == "none":
            return {"anthropic_thinking": {"type": "disabled"}}
        return {"anthropic_thinking": {"type": "adaptive"}, "extra_body": {"output_config": {"effort": reasoning}}}
    raise ValueError(f"A reasoning level cannot be set for provider {provider!r} (openai, azure and anthropic only)")


def get_pydantic_ai_model(config: dict[str, Any]) -> Model | str:
    """
    Convert Deriva config to PydanticAI model.

    Args:
        config: Dict with provider, model, api_url, api_key

    Returns:
        PydanticAI model string or Model instance

    Raises:
        ValueError: If provider is unknown
    """
    provider = config.get("provider", "").lower()
    model = config.get("model", "")
    api_url = config.get("api_url")
    api_key = config.get("api_key")

    # A model config's own key (LLM_{NAME}_KEY, as the studio saves it) goes to the provider;
    # without one, pydantic-ai reads the provider's environment variable (OPENAI_API_KEY and so on)
    if provider == "openai":
        if not api_key:
            return f"openai:{model}"
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(model, provider=OpenAIProvider(api_key=api_key))

    elif provider == "anthropic":
        if not api_key:
            return f"anthropic:{model}"
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        return AnthropicModel(model, provider=AnthropicProvider(api_key=api_key))

    elif provider == "mistral":
        if not api_key:
            return f"mistral:{model}"
        from pydantic_ai.models.mistral import MistralModel
        from pydantic_ai.providers.mistral import MistralProvider

        return MistralModel(model, provider=MistralProvider(api_key=api_key))

    elif provider == "ollama":
        if not api_url:
            return f"ollama:{model}"
        # The config holds Ollama's native chat URL; pydantic-ai talks to its OpenAI-compatible /v1
        from urllib.parse import urlsplit

        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.ollama import OllamaProvider

        parts = urlsplit(api_url)
        return OpenAIChatModel(model, provider=OllamaProvider(base_url=f"{parts.scheme}://{parts.netloc}/v1", api_key=api_key))

    elif provider == "azure":
        # Azure uses OpenAI-compatible API with custom endpoint via AzureProvider
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.azure import AzureProvider

        azure_endpoint = _normalize_azure_url(api_url) if api_url else None
        azure_provider = AzureProvider(
            azure_endpoint=azure_endpoint,
            api_key=api_key,
            api_version="2024-06-01",
        )
        return OpenAIChatModel(model, provider=azure_provider)

    elif provider == "lmstudio":
        # LM Studio uses OpenAI-compatible API via OpenAIProvider with custom base_url
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        base_url = _normalize_openai_url(api_url) if api_url else "http://localhost:1234/v1"
        openai_provider = OpenAIProvider(base_url=base_url)
        return OpenAIChatModel(model, provider=openai_provider)

    else:
        raise ValueError(f"Unknown provider: {provider}. Valid providers: {VALID_PROVIDERS}")


def _normalize_azure_url(url: str) -> str:
    """Normalize Azure OpenAI URL to endpoint format for PydanticAI."""
    # Azure URLs should be the endpoint without /chat/completions
    url = url.rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    # Also remove /openai/deployments/... if present
    if "/openai/deployments/" in url:
        idx = url.index("/openai/deployments/")
        url = url[:idx]
    return url


def _normalize_openai_url(url: str) -> str:
    """Normalize OpenAI-compatible URL to base URL format."""
    url = url.rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    # Ensure /v1 suffix for OpenAI-compatible APIs
    if not url.endswith("/v1"):
        if not url.endswith("/"):
            url = url + "/v1"
        else:
            url = url + "v1"
    return url
