"""Tests for LLM Manager with PydanticAI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from deriva.adapters.llm.manager import (
    LLMManager,
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
        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.cache is not None

    def test_init_creates_pydantic_model(self, tmp_path, monkeypatch):
        """Should create PydanticAI model."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager._pydantic_model is not None

    def test_init_sets_default_values(self, tmp_path, monkeypatch):
        """Should set default values for optional config."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(ConfigurationError):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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
        }

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                with pytest.raises(ConfigurationError, match="Unknown LLM provider"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        assert manager.config["provider"] == "azure"
        assert manager.config["model"] == "gpt-4"

    def test_raises_for_invalid_default_model_reference(self, tmp_path, monkeypatch):
        """Should raise ConfigurationError for invalid default model reference."""
        env_vars = {
            "LLM_DEFAULT_MODEL": "nonexistent-model",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                with patch("deriva.adapters.llm.manager.Agent") as mock_agent_class:
                    mock_agent_class.return_value.run_sync.return_value = mock_result
                    manager = LLMManager()
                    manager.cache.get = MagicMock(return_value=None)  # type: ignore[method-assign]
                    manager.cache.set_response = MagicMock()  # type: ignore[method-assign]

                    manager.query("Hello")

        manager.cache.set_response.assert_called_once()


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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()
                manager.cache.clear_all = MagicMock()  # type: ignore[method-assign]

                manager.clear_cache()

        manager.cache.clear_all.assert_called_once()

    def test_get_cache_stats(self, tmp_path, monkeypatch):
        """Should return cache statistics."""
        env_vars = {
            "LLM_PROVIDER": "ollama",
            "LLM_OLLAMA_MODEL": "llama3",
            "LLM_CACHE_DIR": str(tmp_path / "cache"),
        }

        mock_stats = {"total_entries": 10, "cache_size_mb": 1.5}

        with patch("deriva.adapters.llm.manager.load_dotenv"):
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

        with patch("deriva.adapters.llm.manager.load_dotenv"):
            with patch.dict("os.environ", env_vars, clear=True):
                manager = LLMManager()

        repr_str = repr(manager)

        assert "LLMManager" in repr_str
        assert "ollama" in repr_str
        assert "llama3" in repr_str
