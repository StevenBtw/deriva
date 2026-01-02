"""Tests for managers.llm.providers module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from deriva.adapters.llm.providers import (
    AnthropicProvider,
    AzureOpenAIProvider,
    CompletionResult,
    OllamaProvider,
    OpenAIProvider,
    ProviderConfig,
    ProviderError,
    create_provider,
)


class TestProviderConfig:
    """Tests for ProviderConfig."""

    def test_config_defaults(self):
        """Should use default timeout."""
        config = ProviderConfig(
            api_url="https://api.example.com",
            api_key="test-key",
            model="gpt-4",
        )
        assert config.timeout == 60

    def test_config_custom_timeout(self):
        """Should accept custom timeout."""
        config = ProviderConfig(
            api_url="https://api.example.com",
            api_key="test-key",
            model="gpt-4",
            timeout=120,
        )
        assert config.timeout == 120


class TestCreateProvider:
    """Tests for create_provider factory function."""

    @pytest.fixture
    def config(self):
        return ProviderConfig(
            api_url="https://api.example.com",
            api_key="test-key",
            model="gpt-4",
        )

    def test_create_azure_provider(self, config):
        """Should create Azure provider."""
        provider = create_provider("azure", config)
        assert isinstance(provider, AzureOpenAIProvider)
        assert provider.name == "azure"

    def test_create_openai_provider(self, config):
        """Should create OpenAI provider."""
        provider = create_provider("openai", config)
        assert isinstance(provider, OpenAIProvider)
        assert provider.name == "openai"

    def test_create_anthropic_provider(self, config):
        """Should create Anthropic provider."""
        provider = create_provider("anthropic", config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.name == "anthropic"

    def test_create_ollama_provider(self, config):
        """Should create Ollama provider."""
        provider = create_provider("ollama", config)
        assert isinstance(provider, OllamaProvider)
        assert provider.name == "ollama"

    def test_create_provider_case_insensitive(self, config):
        """Should handle case-insensitive provider names."""
        provider = create_provider("AZURE", config)
        assert isinstance(provider, AzureOpenAIProvider)

    def test_create_unknown_provider_raises(self, config):
        """Should raise ValueError for unknown provider."""
        with pytest.raises(ValueError) as exc_info:
            create_provider("unknown", config)
        assert "Unknown provider" in str(exc_info.value)
        assert "azure, openai, anthropic, ollama" in str(exc_info.value)


class TestAzureOpenAIProvider:
    """Tests for AzureOpenAIProvider."""

    @pytest.fixture
    def provider(self):
        config = ProviderConfig(
            api_url="https://azure.openai.com/test",
            api_key="test-key",
            model="gpt-4",
        )
        return AzureOpenAIProvider(config)

    def test_name(self, provider):
        """Should return 'azure' as name."""
        assert provider.name == "azure"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_complete_success(self, mock_post, provider):
        """Should parse Azure OpenAI response correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Hello, world!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = provider.complete(
            messages=[{"role": "user", "content": "Hi"}],
            temperature=0.5,
        )

        assert isinstance(result, CompletionResult)
        assert result.content == "Hello, world!"
        assert result.finish_reason == "stop"
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_complete_with_json_mode(self, mock_post, provider):
        """Should include response_format when json_mode is True."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(
            messages=[{"role": "user", "content": "Hi"}],
            json_mode=True,
        )

        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["response_format"] == {"type": "json_object"}


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    @pytest.fixture
    def provider(self):
        config = ProviderConfig(
            api_url="https://api.openai.com/v1/chat/completions",
            api_key="test-key",
            model="gpt-4",
        )
        return OpenAIProvider(config)

    def test_name(self, provider):
        """Should return 'openai' as name."""
        assert provider.name == "openai"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_complete_includes_model_in_body(self, mock_post, provider):
        """Should include model in request body (OpenAI requires it)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(messages=[{"role": "user", "content": "Hi"}])

        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["model"] == "gpt-4"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_uses_bearer_auth(self, mock_post, provider):
        """Should use Bearer token authentication."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(messages=[{"role": "user", "content": "Hi"}])

        call_args = mock_post.call_args
        headers = call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-key"


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    @pytest.fixture
    def provider(self):
        config = ProviderConfig(
            api_url="https://api.anthropic.com/v1/messages",
            api_key="test-key",
            model="claude-3-sonnet",
        )
        return AnthropicProvider(config)

    def test_name(self, provider):
        """Should return 'anthropic' as name."""
        assert provider.name == "anthropic"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_complete_parses_anthropic_format(self, mock_post, provider):
        """Should parse Anthropic's response format."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude!"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = provider.complete(messages=[{"role": "user", "content": "Hi"}])

        assert result.content == "Hello from Claude!"
        assert result.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        assert result.finish_reason == "end_turn"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_extracts_system_message(self, mock_post, provider):
        """Should extract system message and send separately."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hi"}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(
            messages=[
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
            ]
        )

        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["system"] == "You are helpful"
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"


class TestOllamaProvider:
    """Tests for OllamaProvider."""

    @pytest.fixture
    def provider(self):
        config = ProviderConfig(
            api_url="http://localhost:11434/api/chat",
            api_key=None,
            model="llama3.2",
        )
        return OllamaProvider(config)

    def test_name(self, provider):
        """Should return 'ollama' as name."""
        assert provider.name == "ollama"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_complete_parses_ollama_format(self, mock_post, provider):
        """Should parse Ollama's response format."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hello from Llama!"},
            "done": True,
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = provider.complete(messages=[{"role": "user", "content": "Hi"}])

        assert result.content == "Hello from Llama!"
        assert result.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        assert result.finish_reason == "stop"

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_uses_stream_false(self, mock_post, provider):
        """Should set stream to false."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Hi"},
            "done": True,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(messages=[{"role": "user", "content": "Hi"}])

        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["stream"] is False

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_json_mode_uses_format(self, mock_post, provider):
        """Should use 'format' key for JSON mode."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "{}"},
            "done": True,
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        provider.complete(
            messages=[{"role": "user", "content": "Hi"}],
            json_mode=True,
        )

        call_args = mock_post.call_args
        body = call_args.kwargs["json"]
        assert body["format"] == "json"


class TestProviderErrors:
    """Tests for provider error handling."""

    @pytest.fixture
    def provider(self):
        config = ProviderConfig(
            api_url="https://api.example.com",
            api_key="test-key",
            model="gpt-4",
        )
        return AzureOpenAIProvider(config)

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_timeout_raises_provider_error(self, mock_post, provider):
        """Should raise ProviderError on timeout."""
        import requests

        mock_post.side_effect = requests.exceptions.Timeout()

        with pytest.raises(ProviderError) as exc_info:
            provider.complete(messages=[{"role": "user", "content": "Hi"}])

        assert "timed out" in str(exc_info.value)

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_request_error_raises_provider_error(self, mock_post, provider):
        """Should raise ProviderError on request failure."""
        import requests

        mock_post.side_effect = requests.exceptions.ConnectionError("Connection failed")

        with pytest.raises(ProviderError) as exc_info:
            provider.complete(messages=[{"role": "user", "content": "Hi"}])

        assert "request failed" in str(exc_info.value)

    @patch("deriva.adapters.llm.providers.requests.post")
    def test_invalid_json_raises_provider_error(self, mock_post, provider):
        """Should raise ProviderError on invalid JSON response."""
        mock_response = MagicMock()
        mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with pytest.raises(ProviderError) as exc_info:
            provider.complete(messages=[{"role": "user", "content": "Hi"}])

        assert "invalid JSON" in str(exc_info.value)
