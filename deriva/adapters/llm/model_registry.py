"""
Model registry for PydanticAI provider configuration.

Maps Deriva environment config to PydanticAI model identifiers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deriva.common import settings

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Valid provider names
VALID_PROVIDERS = frozenset({"azure", "openai", "anthropic", "ollama", "mistral", "lmstudio"})

# Reasoning levels a model config can set (LLM_{NAME}_REASONING); "none" turns reasoning off
REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")

# The levels each provider's API accepts; a level outside them is rejected there
PROVIDER_REASONING_LEVELS = {
    "openai": ("none", "minimal", "low", "medium", "high", "xhigh"),
    "azure": ("none", "minimal", "low", "medium", "high", "xhigh"),
    "anthropic": ("none", "low", "medium", "high", "xhigh", "max"),
}

_SAMPLING_VALUES = {"true": True, "1": True, "yes": True, "on": True, "false": False, "0": False, "no": False, "off": False}


def default_sampling(provider: str, model: str) -> bool:
    """Whether a model takes a temperature when its config does not say. pydantic-ai's model profile knows the Anthropic
    models that refuse sampling settings (it drops them, with a warning on every call); any other model takes one."""
    if provider == "anthropic":
        from pydantic_ai.profiles.anthropic import anthropic_model_profile

        profile = anthropic_model_profile(model) or {}
        return not profile.get("anthropic_disallows_sampling_settings", False)
    return True


def parse_sampling(value: str | None, provider: str = "", model: str = "") -> bool:
    """LLM_{NAME}_SAMPLING: off for models that take no temperature (unset: what the model's profile says)."""
    if value is None or not value.strip():
        return default_sampling(provider, model)
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
    allowed = PROVIDER_REASONING_LEVELS.get(provider)
    if allowed is not None and reasoning not in allowed:
        raise ValueError(f"reasoning for {provider} must be one of {', '.join(allowed)}, got {reasoning!r}")
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
        # Mistral's API is OpenAI-compatible (https://api.mistral.ai/v1): it goes through the openai client, like azure, ollama and lmstudio
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        base_url = _normalize_openai_url(api_url) if api_url else "https://api.mistral.ai/v1"
        # The merged environment (process and home .env), read in the settings layer only
        key = api_key or settings.get("MISTRAL_API_KEY")
        if not key:
            raise ValueError("A mistral model needs a key: set the model config's key (LLM_{NAME}_KEY) in the studio's models page, or MISTRAL_API_KEY in the environment")
        return OpenAIChatModel(model, provider=OpenAIProvider(base_url=base_url, api_key=key))

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

        # Azure's v1 API (<resource>/openai/v1/) is OpenAI's and takes no api_version: the OpenAI client goes there
        if api_url and "/openai/v1" in api_url:
            from pydantic_ai.providers.openai import OpenAIProvider

            base_url = api_url[: api_url.index("/openai/v1") + len("/openai/v1")]
            return OpenAIChatModel(model, provider=OpenAIProvider(base_url=base_url, api_key=api_key))
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
