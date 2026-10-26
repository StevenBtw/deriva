"""Tests for LLM Manager with PydanticAI."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai.exceptions import ModelAPIError

from deriva.adapters.llm.manager import (
    LLMManager,
    _is_retriable,
    _resolve_schema_to_model,
    _serialize_output,
    load_benchmark_models,
)
from deriva.adapters.llm.models import (
    BenchmarkModelConfig,
    CachedResponse,
    ConfigurationError,
    FailedResponse,
    LiveResponse,
)


def _api_error(cause: Exception) -> ModelAPIError:
    """What pydantic-ai raises when a provider call fails: a ModelAPIError with the transport error as its cause."""
    try:
        raise ModelAPIError(model_name="test-model", message=str(cause)) from cause
    except ModelAPIError as error:
        return error


class TestSchemaRegistry:
    """Schemas the modules send by name are enforced as structured output."""

    def test_the_concept_classification_answer_is_closed(self):
        from deriva.modules.extraction.concept_candidates import CLASSIFICATION_SCHEMA, LABELS

        model = _resolve_schema_to_model(CLASSIFICATION_SCHEMA)

        assert model is not None
        answer = model.model_validate({"classifications": [{"term": "Ledger", "label": "business_object"}]})
        assert answer.model_dump() == {"classifications": [{"term": "Ledger", "label": "business_object"}]}
        (item,) = model.model_json_schema()["$defs"].values()
        assert item["properties"]["label"]["enum"] == list(LABELS)
        with pytest.raises(ValidationError):
            model.model_validate({"classifications": [{"term": "Ledger", "label": "thing"}]})


# =============================================================================
# _serialize_output() Tests
# =============================================================================


class TestSerializeOutput:
    """Tests for _serialize_output helper."""

    def test_pydantic_model(self):
        """Should call model_dump_json() on Pydantic models."""

        class MyModel(BaseModel):
            name: str
            value: int

        result = _serialize_output(MyModel(name="test", value=42))
        assert '"name":"test"' in result
        assert '"value":42' in result

    def test_plain_string(self):
        """Should use str() for non-Pydantic objects."""
        assert _serialize_output("hello") == "hello"

    def test_none(self):
        """Should stringify None."""
        assert _serialize_output(None) == "None"


# =============================================================================
# load_benchmark_models() Tests
# =============================================================================


class TestLoadBenchmarkModels:
    """Tests for load_benchmark_models function."""

    def test_returns_empty_dict_when_no_env_vars(self, monkeypatch):
        """Should return empty dict when no LLM_*_PROVIDER vars exist."""
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                result = load_benchmark_models()

        assert result == {}

    def test_loads_single_model_config(self, monkeypatch):
        """Should load a single model config from env vars."""
        env_vars = {
            "LLM_AZURE_GPT4_PROVIDER": "azure",
            "LLM_AZURE_GPT4_MODEL": "gpt-4",
            "LLM_AZURE_GPT4_URL": "https://example.azure.com",
            "LLM_AZURE_GPT4_KEY": "sk-test-key",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert "azure-gpt4" in result
        assert result["azure-gpt4"].provider == "azure"
        assert result["azure-gpt4"].model == "gpt-4"
        assert result["azure-gpt4"].api_url == "https://example.azure.com"
        assert result["azure-gpt4"].api_key == "sk-test-key"

    def test_loads_multiple_model_configs(self, monkeypatch):
        """Should load multiple model configs from env vars."""
        env_vars = {
            "LLM_AZURE_GPT4_PROVIDER": "azure",
            "LLM_AZURE_GPT4_MODEL": "gpt-4",
            "LLM_AZURE_GPT4_URL": "https://azure.example.com",
            "LLM_OPENAI_GPT4_PROVIDER": "openai",
            "LLM_OPENAI_GPT4_MODEL": "gpt-4-turbo",
            "LLM_OPENAI_GPT4_URL": "https://api.openai.com/v1",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert len(result) == 2
        assert "azure-gpt4" in result
        assert "openai-gpt4" in result

    def test_skips_incomplete_configs(self, monkeypatch):
        """Should skip configs without a model specified."""
        env_vars = {
            "LLM_INCOMPLETE_PROVIDER": "azure",
            # No LLM_INCOMPLETE_MODEL
            "LLM_COMPLETE_PROVIDER": "openai",
            "LLM_COMPLETE_MODEL": "gpt-4",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert "incomplete" not in result
        assert "complete" in result

    def test_skips_invalid_provider(self, monkeypatch):
        """Should skip configs with invalid provider."""
        env_vars = {
            "LLM_INVALID_PROVIDER": "invalid_provider_xyz",
            "LLM_INVALID_MODEL": "some-model",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert "invalid" not in result

    def test_uses_api_key_env_reference(self, monkeypatch):
        """Should support LLM_*_KEY_ENV for indirect key lookup."""
        env_vars = {
            "LLM_AZURE_PROVIDER": "azure",
            "LLM_AZURE_MODEL": "gpt-4",
            "LLM_AZURE_URL": "https://example.com",
            "LLM_AZURE_KEY_ENV": "MY_SECRET_KEY",
            "MY_SECRET_KEY": "actual-secret-key",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert "azure" in result
        assert result["azure"].api_key_env == "MY_SECRET_KEY"

    def test_converts_name_to_lowercase_with_hyphens(self, monkeypatch):
        """Should convert UPPER_CASE to lower-case names."""
        env_vars = {
            "LLM_MY_CUSTOM_MODEL_PROVIDER": "ollama",
            "LLM_MY_CUSTOM_MODEL_MODEL": "llama3",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert "my-custom-model" in result


# =============================================================================
# LLMManager.__init__ Tests
# =============================================================================


class TestLLMManagerInit:
    """Tests for LLMManager initialization."""

    def test_init_loads_env_config(self, tmp_path, monkeypatch):
        """Should load configuration from environment."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_API_URL": "http://localhost:11434/api/chat",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.model == "llama3"
        assert manager.config["provider"] == "ollama"

    def test_init_creates_cache_manager(self, tmp_path, monkeypatch):
        """Should initialize cache manager."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        # The cache in LLM_CACHE_DIR
        assert (type(manager.cache).__name__, Path(manager.cache.cache_dir)) == ("CacheManager", tmp_path / "cache")

    def test_init_creates_pydantic_model(self, tmp_path, monkeypatch):
        """Should create PydanticAI model."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        # Ollama goes through the OpenAI-compatible client, for the configured model
        assert (type(manager._pydantic_model).__name__, manager._pydantic_model.model_name) == ("OpenAIChatModel", "llama3")

    def test_init_sets_default_values(self, tmp_path, monkeypatch):
        """Should set default values for optional config."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.max_retries == 3
        assert manager.cache_ttl == 0
        assert manager.nocache is False
        assert manager.temperature == 0.7

    def test_init_raises_for_missing_config(self, monkeypatch):
        """Should raise ConfigurationError for missing required fields."""
        env_vars = {
            "LLM_PROVIDER": "azure",
            # Missing API URL and key
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                # The variable to set is named
                with pytest.raises(ConfigurationError, match="LLM_AZURE_API_KEY"):
                    LLMManager()


# =============================================================================
# LLMManager.from_config Tests
# =============================================================================


class TestLLMManagerFromConfig:
    """Tests for LLMManager.from_config factory method."""

    def test_from_config_creates_instance(self, tmp_path, monkeypatch):
        """Should create instance from BenchmarkModelConfig."""
        config = BenchmarkModelConfig(
            name="test-model",
            provider="ollama",
            model="llama3",
            api_url="http://localhost:11434/api/chat",
        )

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))

        assert manager.model == "llama3"
        assert manager.config["provider"] == "ollama"

    def test_from_config_uses_provided_temperature(self, tmp_path, monkeypatch):
        """Should use provided temperature value."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama3",
            api_url="http://localhost:11434/api/chat",
        )

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"), temperature=0.5)

        assert manager.temperature == 0.5

    def test_from_config_uses_env_temperature_as_default(self, tmp_path, monkeypatch):
        """Should use LLM_TEMPERATURE from env when not provided."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama3",
            api_url="http://localhost:11434/api/chat",
        )

        env_vars = {"LLM_TEMPERATURE": "0.9"}

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))

        assert manager.temperature == 0.9

    def test_from_config_sets_nocache_true_by_default(self, tmp_path, monkeypatch):
        """Should default to nocache=True for benchmarking."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama3",
            api_url="http://localhost:11434/api/chat",
        )

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))

        assert manager.nocache is True

    def test_from_config_validates_config(self, tmp_path, monkeypatch):
        """Should validate configuration after building."""
        config = BenchmarkModelConfig(
            name="test",
            provider="azure",
            model="gpt-4",
            # Missing api_url and api_key for azure
        )

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(ConfigurationError, match="has no API key: set LLM_TEST_KEY"):
                    LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))


# =============================================================================
# LLMManager._load_config_from_env Tests
# =============================================================================


class TestLoadConfigFromEnv:
    """Tests for _load_config_from_env method."""

    def test_loads_azure_provider_config(self, tmp_path, monkeypatch):
        """Should load Azure provider configuration."""
        env_vars = {
            "LLM_PROVIDER": "azure",
            "LLM_AZURE_API_URL": "https://test.azure.com",
            "LLM_AZURE_API_KEY": "test-key",
            "LLM_AZURE_MODEL": "gpt-4o",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "azure"
        assert manager.config["api_url"] == "https://test.azure.com"
        assert manager.config["model"] == "gpt-4o"

    def test_loads_openai_provider_config(self, tmp_path, monkeypatch):
        """Should load OpenAI provider configuration."""
        env_vars = {
            "LLM_PROVIDER": "openai",
            "LLM_OPENAI_API_KEY": "sk-test-key",
            "LLM_OPENAI_MODEL": "gpt-4-turbo",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "openai"
        assert manager.config["api_url"] == "https://api.openai.com/v1/chat/completions"

    def test_loads_anthropic_provider_config(self, tmp_path, monkeypatch):
        """Should load Anthropic provider configuration."""
        env_vars = {
            "LLM_PROVIDER": "anthropic",
            "LLM_ANTHROPIC_API_KEY": "sk-ant-test",
            "LLM_ANTHROPIC_MODEL": "claude-3-opus",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
            # The Anthropic client looks for its config folder under the home folder when it is built
            **{name: os.environ[name] for name in ("HOME", "USERPROFILE", "APPDATA") if name in os.environ},
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "anthropic"
        assert manager.config["api_url"] == "https://api.anthropic.com/v1/messages"

    def test_loads_ollama_provider_config(self, tmp_path, monkeypatch):
        """Should load Ollama provider configuration (no API key required)."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "ollama"
        assert manager.config["api_key"] is None

    def test_loads_lmstudio_provider_config(self, tmp_path, monkeypatch):
        """Should load LM Studio provider configuration."""
        env_vars = {
            "LLM_PROVIDER": "lmstudio",
            "LLM_LMSTUDIO_MODEL": "local-model",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "lmstudio"
        assert "localhost:1234" in manager.config["api_url"]

    def test_loads_mistral_provider_config(self, tmp_path, monkeypatch):
        """Should load Mistral provider configuration."""
        env_vars = {
            "LLM_PROVIDER": "mistral",
            "LLM_MISTRAL_API_KEY": "test-key",
            "LLM_MISTRAL_MODEL": "mistral-large",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "mistral"
        assert "mistral.ai" in manager.config["api_url"]

    def test_raises_for_unknown_provider(self, tmp_path, monkeypatch):
        """Should raise ConfigurationError for unknown provider."""
        env_vars = {
            "LLM_PROVIDER": "unknown_provider",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError, match="Unknown LLM provider"):
                    LLMManager()

    def test_a_fresh_home_without_a_model_says_how_to_add_one(self, tmp_path):
        """No LLM_DEFAULT_MODEL and no provider settings: the error names the missing model, not a missing api_key."""
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {"LLM_CACHE_DIR": str(tmp_path / "cache")}, clear=True):
                with pytest.raises(ConfigurationError, match="No LLM model is configured.*General"):
                    LLMManager()

    def test_uses_default_model_reference(self, tmp_path, monkeypatch):
        """Should use LLM_DEFAULT_MODEL to reference benchmark model."""
        env_vars = {
            "LLM_DEFAULT_MODEL": "azure-gpt4",
            "LLM_AZURE_GPT4_PROVIDER": "azure",
            "LLM_AZURE_GPT4_MODEL": "gpt-4",
            "LLM_AZURE_GPT4_URL": "https://test.azure.com",
            "LLM_AZURE_GPT4_KEY": "test-key",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "azure"
        assert manager.config["model"] == "gpt-4"

    def test_a_missing_key_names_its_variable_and_the_env_file_read(self, tmp_path):
        """The variable the config points to is named (never a value), with the .env this install reads."""
        from deriva.common import settings

        env_vars = {
            "LLM_DEFAULT_MODEL": "azure-gpt4",
            "LLM_AZURE_GPT4_PROVIDER": "azure",
            "LLM_AZURE_GPT4_MODEL": "gpt-4",
            "LLM_AZURE_GPT4_URL": "https://test.azure.com",
            "LLM_AZURE_GPT4_KEY_ENV": "AZURE_OPENAI_API_KEY",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError) as raised:
                    LLMManager()

        message = str(raised.value)
        assert "AZURE_OPENAI_API_KEY" in message and "azure-gpt4" in message
        assert str(settings.env_file()) in message

    def test_a_config_without_key_or_reference_names_its_own_key_variable(self, tmp_path):
        env_vars = {
            "LLM_DEFAULT_MODEL": "azure-gpt4",
            "LLM_AZURE_GPT4_PROVIDER": "azure",
            "LLM_AZURE_GPT4_MODEL": "gpt-4",
            "LLM_AZURE_GPT4_URL": "https://test.azure.com",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError, match="LLM_AZURE_GPT4_KEY"):
                    LLMManager()

    def test_raises_for_invalid_default_model_reference(self, tmp_path, monkeypatch):
        """Should raise ConfigurationError for invalid default model reference."""
        env_vars = {
            "LLM_DEFAULT_MODEL": "nonexistent-model",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError, match="not found"):
                    LLMManager()

    def test_parses_max_tokens_from_env(self, tmp_path, monkeypatch):
        """Should parse LLM_MAX_TOKENS from environment."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_MAX_TOKENS": "1000",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.max_tokens == 1000

    def test_max_tokens_none_when_not_set(self, tmp_path, monkeypatch):
        """Should set max_tokens to None when not specified."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.max_tokens is None


# =============================================================================
# LLMManager.query Tests (with PydanticAI mocking)
# =============================================================================


class TestQuery:
    """Tests for query method."""

    def test_query_returns_live_response(self, tmp_path, monkeypatch):
        """Should return LiveResponse for successful API call."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
            "LLM_NOCACHE": "true",
        }

        mock_result = MagicMock()
        mock_result.output = "Hello back!"
        mock_result.usage = None

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                    mock_agent_class.return_value.run_sync.return_value = mock_result
                    manager = LLMManager()
                    response = manager.query("Hello")

        assert isinstance(response, LiveResponse)
        assert response.content == "Hello back!"

    def test_query_returns_cached_response(self, tmp_path, monkeypatch):
        """Should return CachedResponse when cache hit."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        cached_data = {
            "prompt": "Hello",
            "model": "llama3",
            "content": "Cached hello!",
            "cache_key": "test-key",
            "cached_at": "2024-01-01T00:00:00Z",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()
                manager.cache.get = MagicMock(return_value=cached_data)  # type: ignore[method-assign]

                response = manager.query("Hello")

        assert isinstance(response, CachedResponse)
        assert response.content == "Cached hello!"

    def test_query_returns_failed_response_on_validation_error(self, tmp_path, monkeypatch):
        """Should return FailedResponse for validation errors."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()
                response = manager.query("")

        assert isinstance(response, FailedResponse)
        assert "ValidationError" in response.error_type

    def test_query_with_response_model(self, tmp_path, monkeypatch):
        """Should parse and return Pydantic model instance."""

        class ResponseModel(BaseModel):
            message: str

        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
            "LLM_NOCACHE": "true",
        }

        mock_result = MagicMock()
        mock_result.output = ResponseModel(message="Hello!")
        mock_result.usage = None

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                    mock_agent_class.return_value.run_sync.return_value = mock_result
                    manager = LLMManager()
                    response = manager.query("Hello", response_model=ResponseModel)

        assert isinstance(response, ResponseModel)
        assert response.message == "Hello!"

    def test_query_caches_successful_response(self, tmp_path, monkeypatch):
        """Should cache successful responses when caching enabled."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        mock_result = MagicMock()
        mock_result.output = "Response"
        mock_result.usage = None

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                    mock_agent_class.return_value.run_sync.return_value = mock_result
                    manager = LLMManager()
                    manager.cache.get = MagicMock(return_value=None)  # type: ignore[method-assign]
                    manager.cache.set_response = MagicMock()  # type: ignore[method-assign]

                    manager.query("Hello")

        manager.cache.set_response.assert_called_once()
        cache_key, content, prompt, model, usage = manager.cache.set_response.call_args.args
        assert (content, prompt, model, usage) == ("Response", "Hello", "llama3", None)
        manager.cache.get.assert_called_once_with(cache_key)


# =============================================================================
# LLMManager utility methods Tests
# =============================================================================


class TestUtilityMethods:
    """Tests for utility methods."""

    def test_provider_name_property(self, tmp_path, monkeypatch):
        """Should return provider name."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.provider_name == "ollama"

    def test_clear_cache(self, tmp_path, monkeypatch):
        """Should clear all cached responses."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()
                manager.cache.clear_all = MagicMock()  # type: ignore[method-assign]

                manager.clear_cache()

        manager.cache.clear_all.assert_called_once_with()

    def test_get_cache_stats(self, tmp_path, monkeypatch):
        """Should return cache statistics."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        mock_stats = {"total_entries": 10, "cache_size_mb": 1.5}

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()
                manager.cache.get_cache_stats = MagicMock(return_value=mock_stats)  # type: ignore[method-assign]

                stats = manager.get_cache_stats()

        assert stats == mock_stats

    def test_repr(self, tmp_path, monkeypatch):
        """Should return string representation."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        repr_str = repr(manager)

        assert "LLMManager" in repr_str
        assert "ollama" in repr_str
        assert "llama3" in repr_str


class TestLastCall:
    """Per-call metrics for observability: latency, rate-limit wait, requests, tokens, cache, errors."""

    ENV = {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true"}

    def _manager(self, tmp_path):
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {**self.ENV, "LLM_CACHE_DIR": str(tmp_path / "cache")}, clear=True):
                return LLMManager()

    def test_live_call_records_latency_wait_requests_and_tokens(self, tmp_path):
        from pydantic_ai.usage import RunUsage

        manager = self._manager(tmp_path)
        manager._rate_limiter.wait_if_needed = MagicMock(return_value=0.25)  # type: ignore[method-assign]
        mock_result = MagicMock()
        mock_result.output = "ok"
        mock_result.usage = MagicMock(return_value=RunUsage(input_tokens=11, output_tokens=7, requests=2))

        with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
            mock_agent_class.return_value.run_sync.return_value = mock_result
            response = manager.query("Hello")

        call = manager.last_call
        assert call["cache_hit"] is False and call["error_type"] is None
        assert call["wait_ms"] == 250.0
        assert call["latency_ms"] >= 0
        assert (call["requests"], call["input_tokens"], call["output_tokens"]) == (2, 11, 7)
        assert call["cache_key"]
        assert response.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}

    @pytest.mark.parametrize(
        "change",
        [{"system_prompt": "other system"}, {"temperature": 0.9}, {"max_tokens": 123}],
    )
    def test_cache_key_changes_with_response_shaping_inputs(self, tmp_path, change):
        manager = self._manager(tmp_path)
        base = {"system_prompt": "system", "temperature": 0.1, "max_tokens": 100}

        def key(**kwargs):
            with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                mock_agent_class.return_value.run_sync.return_value = MagicMock(output="ok")
                manager.query("Hello", **kwargs)
            return manager.last_call["cache_key"]

        assert key(**base) == key(**base)
        assert key(**base) != key(**{**base, **change})

    def test_model_default_temperature_is_part_of_the_key(self, tmp_path):
        manager = self._manager(tmp_path)

        def key():
            with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                mock_agent_class.return_value.run_sync.return_value = MagicMock(output="ok")
                manager.query("Hello")
            return manager.last_call["cache_key"]

        first = key()
        manager.temperature = manager.temperature + 0.5
        assert key() != first

    def test_cache_hit_is_recorded(self, tmp_path):
        manager = self._manager(tmp_path)
        manager.nocache = False
        manager.cache.get = MagicMock(  # type: ignore[method-assign]
            return_value={"prompt": "p", "model": "m", "content": "c", "cache_key": "k", "cached_at": "t"}
        )

        manager.query("Hello")

        assert manager.last_call["cache_hit"] is True and manager.last_call["requests"] == 0

    def test_error_type_is_recorded(self, tmp_path):
        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
            mock_agent_class.return_value.run_sync.side_effect = RuntimeError("boom")
            manager.query("Hello")

        assert manager.last_call["error_type"] == "RuntimeError"

    def test_the_generation_settings_of_each_call_are_recorded(self, tmp_path):
        """The values the call ran with: a step's own temperature, else the manager's default."""
        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
            mock_agent_class.return_value.run_sync.return_value = MagicMock(output="ok")
            manager.query("Hello", temperature=0.0, max_tokens=500)
            own = dict(manager.last_call)
            manager.query("Hello again")
            default = dict(manager.last_call)

        assert (own["provider"], own["model"], own["temperature"], own["max_tokens"]) == ("ollama", "llama3", 0.0, 500)
        assert (default["temperature"], default["max_tokens"]) == (manager.temperature, manager.max_tokens)


class TestAgentReuse:
    """Building a pydantic-ai Agent costs ~0.2 s; one agent per output type and system prompt."""

    def test_agent_is_built_once_per_output_type_and_system_prompt(self, tmp_path):
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict(
                "os.environ",
                {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true", "LLM_CACHE_DIR": str(tmp_path)},
                clear=True,
            ):
                manager = LLMManager()
        result = MagicMock(output="ok", usage=MagicMock(return_value=None))

        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = result
            manager.query("one", system_prompt="s")
            manager.query("two", system_prompt="s")
            manager.query("three", system_prompt="other")

        assert agent_class.call_count == 2

    def test_structured_output_gets_its_own_agent(self, tmp_path):
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict(
                "os.environ",
                {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true", "LLM_CACHE_DIR": str(tmp_path)},
                clear=True,
            ):
                manager = LLMManager()

        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = MagicMock(output=Answer(text="ok"), usage=MagicMock(return_value=None))
            manager.query("one", system_prompt="s")
            manager.query("two", system_prompt="s", response_model=Answer)
            manager.query("three", system_prompt="s", response_model=Answer)

        assert agent_class.call_count == 2
        assert [c.kwargs["output_type"] for c in agent_class.call_args_list] == [str, Answer]


class TestCutAnswers:
    """An answer cut at the output limit: pydantic-ai asks again, and a shorter answer that validates can leave part
    of the question unanswered. A structured answer with a cut response in its run is a failure, never cached."""

    @staticmethod
    def _manager(tmp_path):
        env = {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "false", "LLM_CACHE_DIR": str(tmp_path / "cache")}
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env, clear=True):
                return LLMManager()

    @staticmethod
    def _result(output, *finish_reasons):
        from pydantic_ai.messages import ModelResponse, TextPart

        history = [ModelResponse(parts=[TextPart(content="...")], finish_reason=reason) for reason in finish_reasons]
        return MagicMock(output=output, usage=MagicMock(return_value=None), all_messages=MagicMock(return_value=history))

    def test_a_structured_answer_after_a_cut_response_is_a_failure_and_not_cached(self, tmp_path):
        from pydantic import BaseModel

        from deriva.adapters.llm.models import FailedResponse

        class Answer(BaseModel):
            items: list[str]

        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = self._result(Answer(items=["a"]), "length", "tool_call")
            first = manager.query("classify", response_model=Answer, max_tokens=60)
            agent_class.return_value.run_sync.return_value = self._result(Answer(items=["a", "b"]), "tool_call")
            second = manager.query("classify", response_model=Answer, max_tokens=60)

        assert isinstance(first, FailedResponse) and first.error_type == "IncompleteToolCall"
        assert "60" in first.error
        assert second.items == ["a", "b"] and agent_class.return_value.run_sync.call_count == 2

    def test_a_run_that_failed_after_a_cut_response_is_cut_and_not_retried(self, tmp_path):
        """pydantic-ai raises 'Exceeded maximum output retries' when the cut answer's retries fail otherwise."""
        from contextlib import contextmanager

        from pydantic_ai.exceptions import UnexpectedModelBehavior
        from pydantic_ai.messages import ModelResponse, TextPart

        from deriva.adapters.llm.models import FailedResponse

        @contextmanager
        def captured():
            yield [ModelResponse(parts=[TextPart(content="...")], finish_reason="length"), ModelResponse(parts=[TextPart(content="{}")], finish_reason="stop")]

        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class, patch("deriva.adapters.llm.manager.capture_run_messages", captured):
            agent_class.return_value.run_sync.side_effect = UnexpectedModelBehavior("Exceeded maximum output retries (3)")
            response = manager.query("classify", schema={"type": "object", "properties": {"items": {"type": "array"}}}, max_tokens=60)

        assert isinstance(response, FailedResponse) and response.error_type == "IncompleteToolCall"
        assert agent_class.return_value.run_sync.call_count == 1

    def test_other_failed_runs_keep_their_error(self, tmp_path):
        from contextlib import contextmanager

        from pydantic_ai.exceptions import UnexpectedModelBehavior

        from deriva.adapters.llm.models import FailedResponse

        @contextmanager
        def captured():
            yield []

        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class, patch("deriva.adapters.llm.manager.capture_run_messages", captured):
            agent_class.return_value.run_sync.side_effect = UnexpectedModelBehavior("Exceeded maximum output retries (3)")
            response = manager.query("classify", schema={"type": "object", "properties": {"items": {"type": "array"}}})

        assert isinstance(response, FailedResponse) and response.error_type == "UnexpectedModelBehavior"

    def test_a_text_answer_is_returned_as_it_came(self, tmp_path):
        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = self._result("long text", "length")
            response = manager.query("describe")

        assert response.content == "long text"

    def test_an_uncut_structured_answer_is_unchanged(self, tmp_path):
        from pydantic import BaseModel

        class Answer(BaseModel):
            items: list[str]

        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = self._result(Answer(items=["a"]), "tool_call")
            response = manager.query("classify", response_model=Answer)

        assert response.items == ["a"]


class TestUnusableAnswers:
    """An answer to a call that asked for a schema but holds no JSON cannot be used: it is not cached, and one already
    in the cache counts as a miss, so a re-ask goes to the model instead of replaying the same answer."""

    SCHEMA = {"name": "custom_classification", "schema": {}}

    def test_an_answer_without_json_is_not_cached_and_the_re_ask_reaches_the_model(self, tmp_path):
        manager = TestCutAnswers._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            for output in ('```json\n{"id": "file": "a"}\n```', '{"items": []}'):
                agent_class.return_value.run_sync.return_value = MagicMock(output=output, usage=None)
                answer = manager.query("classify", schema=self.SCHEMA)
            cached = manager.query("classify", schema=self.SCHEMA)

        assert answer.content == '{"items": []}' and agent_class.return_value.run_sync.call_count == 2
        assert cached.content == '{"items": []}' and manager.last_call["cache_hit"] is True

    def test_an_unusable_answer_in_the_cache_is_a_miss(self, tmp_path):
        manager = TestCutAnswers._manager(tmp_path)
        manager.cache.get = MagicMock(  # type: ignore[method-assign]
            return_value={"prompt": "p", "model": "m", "content": "No documentation was given.", "cache_key": "k", "cached_at": "t"}
        )
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = MagicMock(output='{"actors": {}}', usage=None)
            answer = manager.query("choose", schema=self.SCHEMA)

        assert answer.content == '{"actors": {}}' and manager.last_call["cache_hit"] is False

    def test_a_call_without_a_schema_caches_text_as_before(self, tmp_path):
        manager = TestCutAnswers._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = MagicMock(output="Plain text", usage=None)
            manager.query("describe")
            again = manager.query("describe")

        assert again.content == "Plain text" and agent_class.return_value.run_sync.call_count == 1


class TestTimeoutAndRetry:
    """LLM_TIMEOUT bounds every call; transient failures are retried with backoff, others fail at once."""

    ENV = {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true", "LLM_TIMEOUT": "7", "LLM_MAX_RETRIES": "2"}

    def _manager(self, tmp_path):
        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {**self.ENV, "LLM_CACHE_DIR": str(tmp_path / "cache")}, clear=True):
                return LLMManager()

    def _query(self, manager, side_effect):
        with (
            patch("deriva.adapters.llm.manager.Agent") as mock_agent_class,
            patch("deriva.adapters.llm.manager.time.sleep") as sleep,
        ):
            run = mock_agent_class.return_value.run_sync
            run.side_effect = side_effect
            response = manager.query("Hello")
        return response, run, sleep

    def test_timeout_is_applied_as_float_seconds(self, tmp_path):
        _, run, _ = self._query(self._manager(tmp_path), [MagicMock(output="ok")])

        timeout = run.call_args.kwargs["model_settings"]["timeout"]
        assert timeout == 7.0 and isinstance(timeout, float)

    def test_timeout_is_retried_then_succeeds(self, tmp_path):
        response, run, sleep = self._query(self._manager(tmp_path), [_api_error(httpx2.ReadTimeout("slow")), MagicMock(output="ok")])

        assert run.call_count == 2
        assert sleep.call_count == 1
        assert response.content == "ok"

    def test_rate_limit_is_retried(self, tmp_path):
        from pydantic_ai.exceptions import ModelHTTPError

        _, run, _ = self._query(self._manager(tmp_path), [ModelHTTPError(status_code=429, model_name="m"), MagicMock(output="ok")])

        assert run.call_count == 2

    def test_rate_limit_that_succeeds_on_retry_still_slows_the_limiter(self, tmp_path):
        """The adaptive throttle must see a 429 even when the retry then succeeds."""
        from pydantic_ai.exceptions import ModelHTTPError

        manager = self._manager(tmp_path)
        with patch.object(manager._rate_limiter, "record_rate_limit") as record:
            self._query(manager, [ModelHTTPError(status_code=429, model_name="m"), MagicMock(output="ok")])

        # Once, for the 429 (it named no Retry-After); the success after it is no rate limit
        record.assert_called_once_with(None)

    def test_final_rate_limit_is_recorded_once(self, tmp_path):
        """The last failed attempt is recorded by query(), not again by the retry loop."""
        from pydantic_ai.exceptions import ModelHTTPError

        manager = self._manager(tmp_path)
        with patch.object(manager._rate_limiter, "record_rate_limit") as record:
            self._query(manager, ModelHTTPError(status_code=429, model_name="m"))

        assert record.call_count == 3  # two retried attempts + the final failure

    def test_gives_up_after_max_retries(self, tmp_path):
        manager = self._manager(tmp_path)
        response, run, _ = self._query(manager, _api_error(httpx2.ReadTimeout("slow")))

        assert run.call_count == 3  # first try + LLM_MAX_RETRIES
        assert isinstance(response, FailedResponse)
        assert manager.last_call["error_type"] == "ReadTimeout"

    def test_permanent_error_is_not_retried(self, tmp_path):
        from pydantic_ai.exceptions import ModelHTTPError

        response, run, sleep = self._query(self._manager(tmp_path), ModelHTTPError(status_code=400, model_name="m"))

        assert run.call_count == 1 and sleep.call_count == 0
        assert isinstance(response, FailedResponse)

    def test_a_failed_query_counts_once_for_the_circuit_breaker(self, tmp_path):
        manager = self._manager(tmp_path)
        self._query(manager, _api_error(httpx2.ReadTimeout("slow")))

        assert manager._rate_limiter.get_stats()["consecutive_failures"] == 1

    def test_backoff_is_jittered(self, tmp_path):
        with patch("deriva.adapters.llm.manager.random.uniform", return_value=0.25) as uniform:
            _, _, sleep = self._query(self._manager(tmp_path), [_api_error(httpx2.ReadTimeout("slow")), MagicMock(output="ok")])

        uniform.assert_called_once_with(0, 2.0)
        sleep.assert_called_once_with(0.25)

    def test_latency_is_recorded_for_failed_calls(self, tmp_path):
        import itertools

        manager = self._manager(tmp_path)
        with patch("deriva.adapters.llm.manager.time.perf_counter", side_effect=itertools.count(0, 1.0)):
            self._query(manager, _api_error(httpx2.ReadTimeout("slow")))

        assert manager.last_call["latency_ms"] >= 1000

    def test_requests_include_failed_attempts(self, tmp_path):
        manager = self._manager(tmp_path)
        result = MagicMock(output="ok")
        result.usage.return_value = MagicMock(requests=1, input_tokens=3, output_tokens=2)
        self._query(manager, [_api_error(httpx2.ReadTimeout("slow")), result])

        assert manager.last_call["requests"] == 2

    def test_backoff_does_not_sleep_on_the_event_loop_thread(self, tmp_path):
        import threading

        sleeping_threads = []
        with (
            patch("deriva.adapters.llm.manager._is_event_loop_running", return_value=True),
            patch("deriva.adapters.llm.manager.Agent") as agent_class,
            patch("deriva.adapters.llm.manager.time.sleep", side_effect=lambda _: sleeping_threads.append(threading.current_thread())),
        ):
            agent_class.return_value.run_sync.side_effect = [_api_error(httpx2.ReadTimeout("slow")), MagicMock(output="ok")]
            self._manager(tmp_path).query("Hello")

        assert sleeping_threads and threading.main_thread() not in sleeping_threads


class TestAgentPerThread:
    """pydantic-ai agents hold an async HTTP client bound to one event loop; each thread gets its own agent."""

    def test_threads_get_separate_agents_and_reuse_their_own(self, tmp_path):
        import threading

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict(
                "os.environ",
                {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true", "LLM_CACHE_DIR": str(tmp_path)},
                clear=True,
            ):
                manager = LLMManager()

        with patch("deriva.adapters.llm.manager.Agent", side_effect=lambda **kw: object()):
            main_first = manager._agent(str, "s")
            main_again = manager._agent(str, "s")
            other: list[object] = []
            worker = threading.Thread(target=lambda: other.append(manager._agent(str, "s")))
            worker.start()
            worker.join()

        assert main_first is main_again
        assert other[0] is not main_first


def test_usage_as_property_is_recorded(tmp_path):
    """pydantic-ai 2 exposes result.usage as a property (1.x: a method); both give token counts."""
    from types import SimpleNamespace

    from pydantic_ai.usage import RunUsage

    with patch("deriva.common.settings.read_env_file", return_value={}):
        with patch.dict(
            "os.environ",
            {"LLM_PROVIDER": "ollama", "LLM_OLLAMA_MODEL": "llama3", "LLM_NOCACHE": "true", "LLM_CACHE_DIR": str(tmp_path)},
            clear=True,
        ):
            manager = LLMManager()

    result = SimpleNamespace(output="ok", usage=RunUsage(input_tokens=11, output_tokens=7, requests=1))
    with patch("deriva.adapters.llm.manager.Agent") as agent_class:
        agent_class.return_value.run_sync.return_value = result
        manager.query("Hello")

    assert (manager.last_call["input_tokens"], manager.last_call["output_tokens"]) == (11, 7)


def test_benchmark_models_and_rpm_come_from_the_merged_environment(monkeypatch):
    from deriva.adapters.llm.manager import get_model_rpm, load_benchmark_models

    file = {"LLM_FILE_ONLY_PROVIDER": "mistral", "LLM_FILE_ONLY_MODEL": "devstral-2512", "LLM_DEVSTRAL_2512_RPM": "24"}
    with patch("deriva.common.settings.read_env_file", return_value=file):
        models = load_benchmark_models()
        rpm = get_model_rpm("devstral-2512", "mistral")

    assert models["file-only"].model == "devstral-2512"
    assert rpm == 24


def test_a_string_model_finds_its_provider_key_in_the_home_env(monkeypatch, tmp_path):
    """mistral, openai, anthropic and ollama models are strings; pydantic-ai reads their key from os.environ."""
    import os

    from pydantic_ai.models import infer_model

    from deriva.adapters.llm.manager import LLMManager
    from deriva.adapters.llm.models import BenchmarkModelConfig
    from deriva.common import settings

    # Set first, so the variable the export writes is taken out again after the test
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-process")
    monkeypatch.delenv("MISTRAL_API_KEY")
    monkeypatch.setattr(settings, "_ORIGINAL_ENVIRONMENT", settings._ORIGINAL_ENVIRONMENT - {"MISTRAL_API_KEY"})
    monkeypatch.setattr(settings, "_EXPORTED", set())  # what this test exports is forgotten with it
    # No key of its own: the config names the variable, and the home .env holds it
    config = BenchmarkModelConfig(name="m", provider="mistral", model="devstral-2512", api_key_env="MISTRAL_API_KEY")
    with patch("deriva.common.settings.read_env_file", return_value={"MISTRAL_API_KEY": "sk-from-file"}):
        manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))

    assert manager.config["api_key"] == "sk-from-file"
    assert os.environ["MISTRAL_API_KEY"] == "sk-from-file"
    assert type(infer_model(manager._pydantic_model)).__name__ == "OpenAIChatModel"  # mistral goes through its OpenAI-compatible API


class TestModelSettings:
    """A model config can take no temperature (``sampling`` off) and set a reasoning level; each call records both and the model that served it."""

    def _manager(self, tmp_path, provider="anthropic", model="claude-haiku-5-5", **fields):
        from deriva.adapters.llm.models import BenchmarkModelConfig

        config = BenchmarkModelConfig(name="m", provider=provider, model=model, api_key="sk-test-0000", **fields)
        with patch("deriva.common.settings.read_env_file", return_value={}):
            return LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"), nocache=True)

    def _sent(self, manager, response=None, **kwargs):
        """The model settings the call was run with."""
        with patch("deriva.adapters.llm.manager.Agent") as agent_class:
            agent_class.return_value.run_sync.return_value = response or MagicMock(output="ok")
            manager.query("Hello", **kwargs)
            return agent_class.return_value.run_sync.call_args.kwargs["model_settings"]

    def test_top_p_and_seed_are_never_sent_and_recorded_as_none(self, tmp_path):
        manager = self._manager(tmp_path, provider="openai", model="gpt-6-luna", temperature=0.0)

        sent = self._sent(manager)

        assert "top_p" not in sent and "seed" not in sent
        assert (manager.last_call["temperature"], manager.last_call["top_p"], manager.last_call["seed"]) == (0.0, None, None)

    def test_a_model_without_sampling_gets_no_temperature(self, tmp_path):
        from deriva.adapters.llm.cache import CacheManager

        manager = self._manager(tmp_path, sampling=False)

        sent = self._sent(manager, temperature=0.0)

        assert "temperature" not in sent
        assert manager.last_call["temperature"] is None
        # The key names what was sent: no temperature
        assert manager.last_call["cache_key"] == CacheManager.generate_cache_key("Hello", "claude-haiku-5-5", None)

    def test_a_reasoning_level_reaches_the_call_and_its_key(self, tmp_path):
        plain = self._manager(tmp_path, provider="openai", model="gpt-6-luna")
        self._sent(plain, temperature=0.0)
        plain_key = plain.last_call["cache_key"]
        manager = self._manager(tmp_path, provider="openai", model="gpt-6-luna", reasoning="none")

        sent = self._sent(manager, temperature=0.0)

        assert sent["openai_reasoning_effort"] == "none"
        assert sent["temperature"] == 0.0  # without reasoning the model takes its temperature
        assert manager.last_call["reasoning"] == "none"
        assert manager.last_call["cache_key"] != plain_key

    def test_configs_without_these_settings_keep_their_cache_keys(self, tmp_path):
        from deriva.adapters.llm.cache import CacheManager

        manager = self._manager(tmp_path, provider="mistral", model="mistral-small-2603")

        sent = self._sent(manager, temperature=0.0, max_tokens=100)

        assert sent["temperature"] == 0.0 and "openai_reasoning_effort" not in sent and "anthropic_thinking" not in sent
        assert manager.last_call["reasoning"] is None
        assert manager.last_call["cache_key"] == CacheManager.generate_cache_key("Hello", "mistral-small-2603", None, temperature=0.0, max_tokens=100)

    @staticmethod
    def _answer(input_tokens, output_tokens):
        from types import SimpleNamespace

        usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        return SimpleNamespace(output="ok", usage=None, response=SimpleNamespace(model_name="qwen3:8b", usage=usage))

    def test_a_call_that_fills_the_model_context_is_warned(self, tmp_path, caplog):
        """Ollama cuts a prompt longer than its context without an error: a call that used the whole window says so."""
        with caplog.at_level("WARNING", logger="deriva.adapters.llm.manager"):
            self._sent(self._manager(tmp_path, provider="ollama", model="qwen3:8b", context=4096), response=self._answer(3900, 150))
            assert "context" not in caplog.text
            self._sent(self._manager(tmp_path, provider="ollama", model="qwen3:8b", context=4096), response=self._answer(4000, 96))

        assert "4096 tokens of qwen3:8b's 4096-token context" in caplog.text

    def test_without_a_context_size_no_call_is_warned(self, tmp_path, caplog):
        manager = self._manager(tmp_path, provider="ollama", model="qwen3:8b")

        with caplog.at_level("WARNING", logger="deriva.adapters.llm.manager"):
            self._sent(manager, response=self._answer(400000, 96))

        assert "context" not in caplog.text

    def test_the_model_that_served_the_call_is_recorded(self, tmp_path):
        """A provider can serve another model under a retired name (devstral-2512 answers as mistral-medium-3-5)."""
        from types import SimpleNamespace

        manager = self._manager(tmp_path, provider="mistral", model="devstral-2512")

        self._sent(manager, response=SimpleNamespace(output="ok", usage=None, response=SimpleNamespace(model_name="mistral-medium-3-5")))

        assert manager.last_call["served_model"] == "mistral-medium-3-5"


def test_benchmark_models_read_sampling_and_reasoning(monkeypatch):
    from deriva.adapters.llm.manager import load_benchmark_models

    env = {
        "LLM_HAIKU_PROVIDER": "anthropic",
        "LLM_HAIKU_MODEL": "claude-haiku-5-5",
        "LLM_HAIKU_SAMPLING": "false",
        "LLM_HAIKU_REASONING": "none",
        "LLM_SMALL_PROVIDER": "mistral",
        "LLM_SMALL_MODEL": "mistral-small-2603",
    }
    with patch("deriva.common.settings.read_env_file", return_value=env), patch.dict("os.environ", {}, clear=True):
        models = load_benchmark_models()

    assert (models["haiku"].sampling, models["haiku"].reasoning) == (False, "none")
    assert (models["small"].sampling, models["small"].reasoning) == (True, None)


def test_benchmark_models_read_the_context_size(monkeypatch):
    from deriva.adapters.llm.manager import load_benchmark_models

    env = {"LLM_QWEN_PROVIDER": "ollama", "LLM_QWEN_MODEL": "qwen3:8b", "LLM_QWEN_CONTEXT": "8192", "LLM_SMALL_PROVIDER": "mistral", "LLM_SMALL_MODEL": "m"}
    with patch("deriva.common.settings.read_env_file", return_value=env), patch.dict("os.environ", {}, clear=True):
        models = load_benchmark_models()

    assert (models["qwen"].context, models["small"].context) == (8192, None)


def test_unset_sampling_follows_the_model_profile(monkeypatch):
    """pydantic-ai drops a temperature the model refuses, with a warning on every call: unset sampling is off for it."""
    from deriva.adapters.llm.manager import load_benchmark_models

    env = {
        "LLM_NEW_PROVIDER": "anthropic",
        "LLM_NEW_MODEL": "claude-haiku-5-5",
        "LLM_OLD_PROVIDER": "anthropic",
        "LLM_OLD_MODEL": "claude-haiku-4-5-20251001",
        "LLM_KEPT_PROVIDER": "anthropic",
        "LLM_KEPT_MODEL": "claude-haiku-5-5",
        "LLM_KEPT_SAMPLING": "true",
    }
    with patch("deriva.common.settings.read_env_file", return_value=env), patch.dict("os.environ", {}, clear=True):
        models = load_benchmark_models()

    assert (models["new"].sampling, models["old"].sampling, models["kept"].sampling) == (False, True, True)


def test_the_provider_settings_follow_the_model_profile_too(monkeypatch):
    from deriva.adapters.llm.manager import LLMManager

    env = {"LLM_PROVIDER": "anthropic", "LLM_ANTHROPIC_MODEL": "claude-haiku-5-5", "LLM_ANTHROPIC_API_KEY": "k"}
    with patch("deriva.common.settings.read_env_file", return_value=env), patch.dict("os.environ", {}, clear=True):
        config = LLMManager.__new__(LLMManager)._load_config_from_env()

    assert config["sampling"] is False


class TestLoadBenchmarkModelsStripping:
    """Values from the environment are stripped before they reach the model config."""

    def test_strips_padding_from_credentials(self):
        env_vars = {
            "LLM_HAIKU_PROVIDER": " anthropic ",
            "LLM_HAIKU_MODEL": " claude-haiku-5-5 ",
            "LLM_HAIKU_URL": " https://api.anthropic.com/v1/messages ",
            "LLM_HAIKU_KEY": " sk-ant-123 ",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert result["haiku"].provider == "anthropic"
        assert result["haiku"].model == "claude-haiku-5-5"
        assert result["haiku"].api_url == "https://api.anthropic.com/v1/messages"
        assert result["haiku"].api_key == "sk-ant-123"

    def test_strips_quotes_from_credentials(self):
        """Quotes pasted around a value (a shell habit) come off like padding."""
        env_vars = {
            "LLM_HAIKU_PROVIDER": " 'anthropic' ",
            "LLM_HAIKU_MODEL": ' "claude-haiku-5-5" ',
            "LLM_HAIKU_URL": ' "https://api.anthropic.com/v1/messages" ',
            "LLM_HAIKU_KEY": ' "sk-ant-123" ',
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert result["haiku"].provider == "anthropic"
        assert result["haiku"].model == "claude-haiku-5-5"
        assert result["haiku"].api_url == "https://api.anthropic.com/v1/messages"
        assert result["haiku"].api_key == "sk-ant-123"

    def test_strips_padding_inside_quotes(self):
        """Padding inside the quotes goes too: ' sk-ant-123 ' comes out clean."""
        env_vars = {
            "LLM_HAIKU_PROVIDER": "' anthropic '",
            "LLM_HAIKU_MODEL": '" claude-haiku-5-5 "',
            "LLM_HAIKU_URL": '" https://api.anthropic.com/v1/messages "',
            "LLM_HAIKU_KEY": "' sk-ant-123 '",
        }

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", env_vars, clear=True):
                result = load_benchmark_models()

        assert result["haiku"].provider == "anthropic"
        assert result["haiku"].model == "claude-haiku-5-5"
        assert result["haiku"].api_url == "https://api.anthropic.com/v1/messages"
        assert result["haiku"].api_key == "sk-ant-123"


class TestIsRetriable:
    """Permanent client errors are not retried; transient network errors are, also behind pydantic-ai's wrapper."""

    def test_local_protocol_error_is_not_retriable(self):
        """An illegal header value can never succeed on retry."""
        assert _is_retriable(httpx2.LocalProtocolError("Illegal header value b'key '")) is False

    def test_unsupported_protocol_is_not_retriable(self):
        assert _is_retriable(httpx2.UnsupportedProtocol("unsupported")) is False

    def test_connect_error_is_retriable(self):
        assert _is_retriable(httpx2.ConnectError("connection refused")) is True

    def test_timeout_is_retriable(self):
        assert _is_retriable(TimeoutError("timed out")) is True

    def test_a_wrapped_timeout_is_retriable(self):
        """pydantic-ai wraps the httpx2 timeout in a ModelAPIError; the wrapper must not hide it."""
        assert _is_retriable(_api_error(httpx2.ReadTimeout("slow"))) is True

    def test_a_wrapped_connection_error_is_retriable(self):
        assert _is_retriable(_api_error(httpx2.ConnectError("connection refused"))) is True

    def test_a_wrapped_local_protocol_error_is_not_retriable(self):
        assert _is_retriable(_api_error(httpx2.LocalProtocolError("Illegal header value b'key '"))) is False

    def test_a_model_api_error_without_a_transport_error_is_not_retriable(self):
        assert _is_retriable(ModelAPIError(model_name="m", message="unexpected model behavior")) is False

    def test_an_httpx_error_is_not_retriable(self):
        """Only httpx2 matches: pydantic-ai and the provider SDKs run on httpx2, not on httpx."""
        import httpx

        assert _is_retriable(httpx.ReadTimeout("slow")) is False


class TestRedact:
    """The configured API key never reaches logs or error reports."""

    def test_redact_replaces_the_configured_key(self, tmp_path, monkeypatch):
        config = BenchmarkModelConfig(
            name="test-model",
            provider="ollama",
            model="llama3",
            api_url="http://localhost:11434/api/chat",
        )

        with patch("deriva.common.settings.read_env_file", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                manager = LLMManager.from_config(config, cache_dir=str(tmp_path / "cache"))
        manager.config["api_key"] = "sk-secret-123"

        text = "LocalProtocolError: Illegal header value b'sk-secret-123 '"
        assert manager._redact(text) == "LocalProtocolError: Illegal header value b'*** '"
        assert manager._redact("no secret here") == "no secret here"


class TestModelTemperature:
    """A model config's own temperature (LLM_{NAME}_TEMPERATURE) wins over LLM_TEMPERATURE; an explicit one over both."""

    def _config(self, temperature=None):
        return BenchmarkModelConfig(name="m", provider="ollama", model="llama3", api_url="http://localhost:11434/api/chat", temperature=temperature)

    def test_the_model_temperature_is_used(self, tmp_path):
        with patch("deriva.common.settings.read_env_file", return_value={}), patch.dict("os.environ", {"LLM_TEMPERATURE": "0.6"}, clear=True):
            own = LLMManager.from_config(self._config(0.0), cache_dir=str(tmp_path / "c"))
            explicit = LLMManager.from_config(self._config(0.0), cache_dir=str(tmp_path / "c"), temperature=0.3)
            plain = LLMManager.from_config(self._config(), cache_dir=str(tmp_path / "c"))

        assert (own.temperature, explicit.temperature, plain.temperature) == (0.0, 0.3, 0.6)

    def test_a_temperature_out_of_range_is_refused(self):
        with pytest.raises(ValueError, match="temperature"):
            self._config(3.0)

    def test_the_config_reads_the_model_temperature(self):
        from deriva.adapters.llm.manager import load_benchmark_models

        env = {"LLM_M_PROVIDER": "ollama", "LLM_M_MODEL": "llama3", "LLM_M_TEMPERATURE": "0"}
        with patch("deriva.common.settings.read_env_file", return_value={}), patch.dict("os.environ", env, clear=True):
            assert load_benchmark_models()["m"].temperature == 0.0
