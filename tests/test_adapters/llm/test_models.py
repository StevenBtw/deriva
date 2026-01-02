"""Tests for managers.llm.models module."""

import pytest
from pydantic import BaseModel, Field

from deriva.adapters.llm.models import (
    BaseResponse,
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
