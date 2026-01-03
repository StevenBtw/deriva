"""Tests for managers.llm.models module."""

import pytest
from pydantic import BaseModel, Field

from deriva.adapters.llm.models import (
    BaseResponse,
    BenchmarkModelConfig,
    CachedResponse,
    FailedResponse,
    LiveResponse,
    LLMResponse,
    ResponseType,
    StructuredOutputMixin,
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

    def test_failed_response_is_llm_response(self):
        """FailedResponse should be a valid LLMResponse."""
        response: LLMResponse = FailedResponse(
            prompt="test",
            model="gpt-4",
            error="error",
            error_type="APIError",
        )
        assert isinstance(response, BaseResponse)


class TestStructuredOutputMixin:
    """Tests for StructuredOutputMixin."""

    def test_to_prompt_schema(self):
        """Should generate prompt-friendly schema."""

        class TestModel(StructuredOutputMixin):
            name: str = Field(description="The name")
            count: int = Field(description="The count")

        schema = TestModel.to_prompt_schema()

        assert '"name"' in schema
        assert '"count"' in schema
        assert "The name" in schema
        assert "The count" in schema

    def test_model_json_schema(self):
        """Should generate valid JSON schema."""

        class TestModel(StructuredOutputMixin):
            name: str
            value: int

        schema = TestModel.model_json_schema()

        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "value" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["value"]["type"] == "integer"

    def test_extra_forbid(self):
        """Should reject extra fields."""

        class StrictModel(StructuredOutputMixin):
            name: str

        with pytest.raises(Exception):  # Pydantic ValidationError
            StrictModel.model_validate({"name": "test", "extra_field": "not allowed"})

    def test_nested_objects_in_schema(self):
        """Should handle nested objects in schema."""

        class Inner(BaseModel):
            value: str

        class Outer(StructuredOutputMixin):
            inner: Inner = Field(description="Nested object")

        schema = Outer.to_prompt_schema()
        # Should not crash and should include the field
        assert '"inner"' in schema

    def test_array_type_in_schema(self):
        """Should handle array types in schema."""

        class WithArray(StructuredOutputMixin):
            items: list[str] = Field(description="List of items")

        schema = WithArray.to_prompt_schema()
        assert '"items"' in schema
        assert "List of items" in schema

    def test_enum_type_in_schema(self):
        """Should handle enum types in schema."""
        from enum import Enum

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class WithEnum(StructuredOutputMixin):
            status: Status = Field(description="Current status")

        schema = WithEnum.to_prompt_schema()
        assert '"status"' in schema


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

    def test_rejects_invalid_provider(self):
        """Should raise ValueError for invalid provider."""
        with pytest.raises(ValueError) as exc_info:
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
        assert "openai.com" in config.get_api_url()

    def test_get_api_url_anthropic_default(self):
        """Should return Anthropic default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="anthropic",
            model="claude-3",
        )
        assert "anthropic.com" in config.get_api_url()

    def test_get_api_url_ollama_default(self):
        """Should return Ollama default URL."""
        config = BenchmarkModelConfig(
            name="test",
            provider="ollama",
            model="llama2",
        )
        assert "localhost:11434" in config.get_api_url()

    def test_get_api_url_azure_no_default(self):
        """Azure has no default URL (requires custom endpoint)."""
        config = BenchmarkModelConfig(
            name="test",
            provider="azure",
            model="gpt-4",
        )
        # Azure returns empty string if no url set
        assert config.get_api_url() == ""
