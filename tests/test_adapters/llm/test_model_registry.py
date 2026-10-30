"""Each model config reaches pydantic-ai with its own key and URL, not only through the providers' environment variables."""

from __future__ import annotations

import pytest
from pydantic_ai.models import infer_model
from pydantic_ai.models.openai import OpenAIChatModel

from deriva.adapters.llm.model_registry import get_pydantic_ai_model

PROVIDER_VARIABLES = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "OLLAMA_BASE_URL", "OLLAMA_API_KEY")


@pytest.fixture
def no_provider_environment(monkeypatch):
    for name in PROVIDER_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(("provider", "model"), [("mistral", "devstral-2512"), ("openai", "gpt-4o-mini"), ("anthropic", "claude-haiku")])
def test_a_models_own_key_is_used(no_provider_environment, provider, model):
    """A key saved in the studio (LLM_{NAME}_KEY) works without the provider's own environment variable."""
    resolved = infer_model(get_pydantic_ai_model({"provider": provider, "model": model, "api_key": "sk-test-0000"}))

    assert resolved.model_name == model


def test_without_a_key_the_providers_environment_variable_still_applies(no_provider_environment, monkeypatch):
    """Without a config key, the mistral client reads MISTRAL_API_KEY (the home .env exports it)."""
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-env-0000")
    resolved = infer_model(get_pydantic_ai_model({"provider": "mistral", "model": "devstral-2512"}))

    assert resolved.model_name == "devstral-2512"
    assert str(resolved.base_url).rstrip("/") == "https://api.mistral.ai/v1"
    assert isinstance(resolved, OpenAIChatModel)
    assert resolved.client.api_key == "sk-env-0000"


def test_mistral_goes_through_the_openai_compatible_client(no_provider_environment):
    """Mistral's API is OpenAI-compatible, so the mistralai package is not needed."""
    resolved = infer_model(get_pydantic_ai_model({"provider": "mistral", "model": "devstral-2512", "api_key": "sk-test-0000"}))

    assert type(resolved).__name__ == "OpenAIChatModel"
    assert str(resolved.base_url).rstrip("/") == "https://api.mistral.ai/v1"


def test_a_mistral_model_uses_its_configured_url(no_provider_environment):
    resolved = infer_model(
        get_pydantic_ai_model({"provider": "mistral", "model": "devstral-2512", "api_key": "sk-test-0000", "api_url": "https://mistral.example.com/v1/chat/completions"})
    )

    assert str(resolved.base_url).rstrip("/") == "https://mistral.example.com/v1"


def test_a_mistral_model_without_any_key_is_refused(no_provider_environment):
    """A clear error, not a client that would silently use another provider's key."""
    with pytest.raises(ValueError, match="MISTRAL_API_KEY"):
        get_pydantic_ai_model({"provider": "mistral", "model": "devstral-2512"})


def test_an_ollama_model_uses_its_configured_url(no_provider_environment):
    """The native chat URL of the model config becomes the OpenAI-compatible base URL pydantic-ai talks to."""
    resolved = infer_model(get_pydantic_ai_model({"provider": "ollama", "model": "llama3.2", "api_url": "http://localhost:11434/api/chat"}))

    assert str(resolved.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_a_reasoning_level_becomes_each_providers_setting():
    """``none`` turns reasoning off (OpenAI keeps the temperature then); other levels set the effort."""
    from deriva.adapters.llm.model_registry import reasoning_settings

    assert reasoning_settings("openai", "none") == {"openai_reasoning_effort": "none"}
    assert reasoning_settings("azure", "low") == {"openai_reasoning_effort": "low"}
    assert reasoning_settings("anthropic", "none") == {"anthropic_thinking": {"type": "disabled"}}
    assert reasoning_settings("anthropic", "low") == {"anthropic_thinking": {"type": "adaptive"}, "extra_body": {"output_config": {"effort": "low"}}}
    assert reasoning_settings("mistral", None) == {}


def test_reasoning_is_refused_for_providers_deriva_cannot_set_it_for():
    from deriva.adapters.llm.model_registry import reasoning_settings

    with pytest.raises(ValueError, match="mistral"):
        reasoning_settings("mistral", "none")


def test_a_level_the_provider_does_not_know_is_refused():
    from deriva.adapters.llm.model_registry import reasoning_settings

    with pytest.raises(ValueError, match="openai"):
        reasoning_settings("openai", "max")
    with pytest.raises(ValueError, match="anthropic"):
        reasoning_settings("anthropic", "minimal")
    assert reasoning_settings("anthropic", "max") and reasoning_settings("azure", "xhigh")


def test_an_azure_v1_url_uses_the_openai_compatible_client_without_an_api_version():
    """Azure's /openai/v1/ API takes no api_version (pydantic-ai refuses one for it); its client is the OpenAI one."""
    from pydantic_ai.providers.azure import AzureProvider
    from pydantic_ai.providers.openai import OpenAIProvider

    from deriva.adapters.llm.model_registry import get_pydantic_ai_model

    v1 = get_pydantic_ai_model({"provider": "azure", "model": "gpt-5-mini", "api_url": "https://res.openai.azure.com/openai/v1/", "api_key": "k"})
    root = get_pydantic_ai_model({"provider": "azure", "model": "gpt-5-mini", "api_url": "https://res.openai.azure.com/", "api_key": "k"})

    assert isinstance(v1, OpenAIChatModel) and isinstance(root, OpenAIChatModel)
    assert isinstance(v1._provider, OpenAIProvider) and not isinstance(v1._provider, AzureProvider)
    assert str(v1._provider.base_url).rstrip("/") == "https://res.openai.azure.com/openai/v1"
    assert isinstance(root._provider, AzureProvider)
