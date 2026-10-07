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

    if provider == "openai":
        return f"openai:{model}"

    elif provider == "anthropic":
        return f"anthropic:{model}"

    elif provider == "mistral":
        return f"mistral:{model}"

    elif provider == "ollama":
        return f"ollama:{model}"

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
