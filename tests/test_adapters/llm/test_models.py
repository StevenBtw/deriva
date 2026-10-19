"""Tests for managers.llm.models module."""

import pytest

from deriva.adapters.llm.models import (
    BaseResponse,
    BenchmarkModelConfig,
    CachedResponse,
    FailedResponse,
    LiveResponse,
    LLMResponse,
    ResponseType,
)


class TestResponseType:
    """Tests for ResponseType enum."""

    def test_response_type_values(self):
        """Should have correct string values."""
        assert ResponseType.LIVE.value == "live"
        assert ResponseType.CACHED.value == "cached"
        assert ResponseType.FAILED.value == "failed"


class TestLiveResponse:
    """Tests for LiveResponse model."""

    def test_create_live_response(self):
        """Should create a valid LiveResponse."""
        response = LiveResponse(
            prompt="test prompt",
            model="gpt-4",
            content="test content",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            finish_reason="stop",
        )

        assert response.response_type == ResponseType.LIVE
        assert response.prompt == "test prompt"
        assert response.model == "gpt-4"
        assert response.content == "test content"
        assert response.usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert response.finish_reason == "stop"

    def test_live_response_optional_fields(self):
        """Should allow optional fields to be None."""
        response = LiveResponse(
            prompt="test",
            model="gpt-4",
            content="content",
        )

        assert response.usage is None
        assert response.finish_reason is None

    def test_live_response_to_dict(self):
        """Should convert to dictionary."""
        response = LiveResponse(
            prompt="test",
            model="gpt-4",
            content="content",
        )

        data = response.model_dump()
        assert data["response_type"] == ResponseType.LIVE
        assert data["content"] == "content"


class TestCachedResponse:
    """Tests for CachedResponse model."""

    def test_create_cached_response(self):
        """Should create a valid CachedResponse."""
        response = CachedResponse(
            prompt="test prompt",
            model="gpt-4",
            content="cached content",
            cache_key="abc123",
            cached_at="2024-01-01T00:00:00Z",
        )

        assert response.response_type == ResponseType.CACHED
        assert response.cache_key == "abc123"
        assert response.cached_at == "2024-01-01T00:00:00Z"


class TestFailedResponse:
    """Tests for FailedResponse model."""

    def test_create_failed_response(self):
        """Should create a valid FailedResponse."""
        response = FailedResponse(
            prompt="test prompt",
            model="gpt-4",
            error="API timeout",
            error_type="APIError",
        )

        assert response.response_type == ResponseType.FAILED
        assert response.error == "API timeout"
        assert response.error_type == "APIError"


class TestLLMResponseTypeAlias:
    """Tests for LLMResponse type alias."""

    def test_live_response_is_llm_response(self):
        """LiveResponse should be a valid LLMResponse."""
        response: LLMResponse = LiveResponse(
            prompt="test",
            model="gpt-4",
            content="content",
        )
        assert isinstance(response, BaseResponse)
        assert (response.response_type.value, response.content) == ("live", "content")

    def test_cached_response_is_llm_response(self):
        """CachedResponse should be a valid LLMResponse."""
        response: LLMResponse = CachedResponse(
            prompt="test",
            model="gpt-4",
            content="content",
            cache_key="key",
            cached_at="2024-01-01T00:00:00Z",
        )
        assert isinstance(response, BaseResponse)
        assert (response.response_type.value, response.cache_key) == ("cached", "key")

    def test_failed_response_is_llm_response(self):
        """FailedResponse should be a valid LLMResponse."""
        response: LLMResponse = FailedResponse(
            prompt="test",
            model="gpt-4",
            error="error",
            error_type="APIError",
        )
        assert isinstance(response, BaseResponse)
        assert (response.response_type.value, response.error, response.error_type) == ("failed", "error", "APIError")


class TestBenchmarkModelConfig:
    """Tests for BenchmarkModelConfig dataclass."""

    def test_creates_with_valid_provider(self):
        """Should create config with valid provider."""
        config = BenchmarkModelConfig(
            name="test-azure",
            provider="azure",
            model="gpt-4",
        )
        assert config.name == "test-azure"
        assert config.provider == "azure"
        assert config.model == "gpt-4"

    def test_creates_with_openai_provider(self):
        """Should accept openai provider."""
        config = BenchmarkModelConfig(
            name="test-openai",
            provider="openai",
            model="gpt-4-turbo",
        )
        assert config.provider == "openai"

    def test_creates_with_anthropic_provider(self):
        """Should accept anthropic provider."""
        config = BenchmarkModelConfig(
            name="test-anthropic",
            provider="anthropic",
            model="claude-3-sonnet",
        )
        assert config.provider == "anthropic"

    def test_creates_with_ollama_provider(self):
        """Should accept ollama provider."""
        config = BenchmarkModelConfig(
            name="test-ollama",
            provider="ollama",
            model="llama2",
        )
        assert config.provider == "ollama"

    def test_creates_with_mistral_provider(self):
        """Should accept mistral provider."""
        config = BenchmarkModelConfig(
            name="test-mistral",
            provider="mistral",
            model="mistral-large",
        )
        assert config.provider == "mistral"

    def test_creates_with_lmstudio_provider(self):
        """Should accept lmstudio provider."""
        config = BenchmarkModelConfig(
            name="test-lmstudio",
            provider="lmstudio",
            model="local-model",
        )
        assert config.provider == "lmstudio"

    def test_rejects_invalid_provider(self):
        """Should raise ValueError for invalid provider."""
        with pytest.raises(ValueError, match="Invalid provider: invalid_provider") as exc_info:
            BenchmarkModelConfig(
                name="test",
                provider="invalid_provider",
                model="model",
            )
        assert "Invalid provider" in str(exc_info.value)
        assert "invalid_provider" in str(exc_info.value)

    def test_get_api_key_direct(self):
        """Should return direct api_key when set."""
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
            api_key="sk-direct-key",
        )
        assert config.get_api_key() == "sk-direct-key"

    def test_get_api_key_from_env(self, monkeypatch):
        """Should read api_key from environment variable."""
        monkeypatch.setenv("TEST_API_KEY", "sk-from-env")
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
            api_key_env="TEST_API_KEY",
        )
        assert config.get_api_key() == "sk-from-env"

    def test_get_api_key_direct_takes_precedence(self, monkeypatch):
        """Direct api_key should take precedence over env."""
        monkeypatch.setenv("TEST_API_KEY", "sk-from-env")
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
            api_key="sk-direct",
            api_key_env="TEST_API_KEY",
        )
        assert config.get_api_key() == "sk-direct"

    def test_get_api_key_returns_none(self):
        """Should return None when no key configured."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama2",
        )
        assert config.get_api_key() is None

    def test_get_api_url_direct(self):
        """Should return direct api_url when set."""
        config = BenchmarkModelConfig(
            name="test",
            provider="azure",
            model="gpt-4",
            api_url="https://my-azure.openai.azure.com/",
        )
        assert config.get_api_url() == "https://my-azure.openai.azure.com/"

    def test_get_api_url_openai_default(self):
        """Should return OpenAI default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
        )
        assert config.get_api_url() == "https://api.openai.com/v1/chat/completions"

    def test_get_api_url_anthropic_default(self):
        """Should return Anthropic default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="anthropic",
            model="claude-3",
        )
        assert config.get_api_url() == "https://api.anthropic.com/v1/messages"

    def test_get_api_url_ollama_default(self):
        """Should return Ollama default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama2",
        )
        assert "localhost:11434" in config.get_api_url()

    def test_get_api_url_mistral_default(self):
        """Should return Mistral default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="mistral",
            model="mistral-large",
        )
        assert "mistral.ai" in config.get_api_url()

    def test_get_api_url_azure_no_default(self):
        """Azure has no default URL (requires custom endpoint)."""
        config = BenchmarkModelConfig(
            name="test",
            provider="azure",
            model="gpt-4",
        )
        # Azure returns empty string if no url set
        assert config.get_api_url() == ""


class TestBenchmarkModelConfigCredentials:
    """A pasted key, URL or model name with padding or quotes is stripped."""

    def test_strips_padding(self):
        config = BenchmarkModelConfig(
            name="test-anthropic",
            provider=" anthropic ",
            model=" claude-3-sonnet ",
            api_url=" https://api.anthropic.com/v1/messages ",
            api_key=" sk-ant-123 ",
            api_key_env=" MY_KEY ",
        )

        assert (config.provider, config.model) == ("anthropic", "claude-3-sonnet")
        assert config.api_url == "https://api.anthropic.com/v1/messages"
        assert config.api_key == "sk-ant-123"
        assert config.api_key_env == "MY_KEY"

    def test_strips_quotes(self):
        """Quotes pasted around a value (a shell habit) come off like padding."""
        config = BenchmarkModelConfig(
            name="test-anthropic",
            provider="'anthropic'",
            model='"claude-3-sonnet"',
            api_url="'https://api.anthropic.com/v1/messages'",
            api_key='"sk-ant-123"',
            api_key_env="'MY_KEY'",
        )

        assert (config.provider, config.model) == ("anthropic", "claude-3-sonnet")
        assert config.api_url == "https://api.anthropic.com/v1/messages"
        assert config.api_key == "sk-ant-123"
        assert config.api_key_env == "MY_KEY"

    def test_strips_padding_inside_quotes(self):
        """Padding inside the quotes goes too: ' sk-ant-123 ' comes out clean."""
        config = BenchmarkModelConfig(
            name="test-anthropic",
            provider="' anthropic '",
            model='" claude-3-sonnet "',
            api_url="' https://api.anthropic.com/v1/messages '",
            api_key='" sk-ant-123 "',
            api_key_env="' MY_KEY '",
        )

        assert (config.provider, config.model) == ("anthropic", "claude-3-sonnet")
        assert config.api_url == "https://api.anthropic.com/v1/messages"
        assert config.api_key == "sk-ant-123"
        assert config.api_key_env == "MY_KEY"

    def test_get_api_key_strips_the_env_value(self, monkeypatch):
        monkeypatch.setenv("DERIVA_TEST_LLM_KEY", "  sk-env-key ")
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
            api_key_env="DERIVA_TEST_LLM_KEY",
        )

        assert config.get_api_key() == "sk-env-key"

    def test_get_api_key_strips_quotes_from_the_env_value(self, monkeypatch):
        monkeypatch.setenv("DERIVA_TEST_LLM_KEY", ' "sk-env-key" ')
        config = BenchmarkModelConfig(
            name="test",
            provider="openai",
            model="gpt-4",
            api_key_env="DERIVA_TEST_LLM_KEY",
        )

        assert config.get_api_key() == "sk-env-key"
