"""Tests for common.exceptions module."""

from __future__ import annotations

from deriva.common.exceptions import (
    APIError,
    BaseError,
    CacheError,
    CloneError,
    ConfigurationError,
    DeleteError,
    LLMError,
    MetadataError,
    ProviderError,
    RepositoryError,
    ServiceConnectionError,
    ValidationError,
)


class TestBaseError:
    """Tests for BaseError class."""

    def test_creates_with_message(self):
        """Should create error with message."""
        error = BaseError("Something went wrong")
        assert error.message == "Something went wrong"
        assert str(error) == "Something went wrong"

    def test_creates_with_context(self):
        """Should create error with context."""
        error = BaseError("Failed", context={"key": "value", "count": 5})
        assert error.context == {"key": "value", "count": 5}

    def test_str_includes_context(self):
        """Should include context in string representation."""
        error = BaseError("Error occurred", context={"file": "test.py", "line": 42})
        error_str = str(error)
        assert "Error occurred" in error_str
        assert "file='test.py'" in error_str
        assert "line=42" in error_str

    def test_defaults_to_empty_context(self):
        """Should default to empty context."""
        error = BaseError("Error")
        assert error.context == {}


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_configuration_error_is_base_error(self):
        """ConfigurationError should inherit from BaseError."""
        error = ConfigurationError("Config missing")
        assert isinstance(error, BaseError)

    def test_api_error_is_base_error(self):
        """APIError should inherit from BaseError."""
        error = APIError("API failed")
        assert isinstance(error, BaseError)

    def test_provider_error_is_api_error(self):
        """ProviderError should inherit from APIError."""
        error = ProviderError("Provider failed")
        assert isinstance(error, APIError)
        assert isinstance(error, BaseError)

    def test_validation_error_is_base_error(self):
        """ValidationError should inherit from BaseError."""
        error = ValidationError("Invalid input")
        assert isinstance(error, BaseError)

    def test_cache_error_is_base_error(self):
        """CacheError should inherit from BaseError."""
        error = CacheError("Cache miss")
        assert isinstance(error, BaseError)

    def test_repository_error_is_base_error(self):
        """RepositoryError should inherit from BaseError."""
        error = RepositoryError("Repo error")
        assert isinstance(error, BaseError)

    def test_clone_error_is_repository_error(self):
        """CloneError should inherit from RepositoryError."""
        error = CloneError("Clone failed")
        assert isinstance(error, RepositoryError)

    def test_delete_error_is_repository_error(self):
        """DeleteError should inherit from RepositoryError."""
        error = DeleteError("Delete failed")
        assert isinstance(error, RepositoryError)

    def test_metadata_error_is_repository_error(self):
        """MetadataError should inherit from RepositoryError."""
        error = MetadataError("Metadata extraction failed")
        assert isinstance(error, RepositoryError)

    def test_llm_error_is_base_error(self):
        """LLMError should inherit from BaseError."""
        error = LLMError("LLM failed")
        assert isinstance(error, BaseError)

    def test_service_connection_error_is_base_error(self):
        """ServiceConnectionError should inherit from BaseError."""
        error = ServiceConnectionError("Connection failed")
        assert isinstance(error, BaseError)


class TestExceptionContext:
    """Tests for exception context handling."""

    def test_all_errors_support_context(self):
        """All error types should support context parameter."""
        errors = [
            ConfigurationError("msg", context={"key": "val"}),
            APIError("msg", context={"key": "val"}),
            ValidationError("msg", context={"key": "val"}),
            CacheError("msg", context={"key": "val"}),
            RepositoryError("msg", context={"key": "val"}),
            LLMError("msg", context={"key": "val"}),
        ]
        for error in errors:
            assert error.context == {"key": "val"}
