"""Tests for common.exceptions module."""

from __future__ import annotations

import pytest

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
    """Each error has one direct parent, so a handler for the parent catches it (and nothing else changes it)."""

    @pytest.mark.parametrize(
        "error_class, parent",
        [
            (ConfigurationError, BaseError),
            (APIError, BaseError),
            (ProviderError, APIError),
            (ValidationError, BaseError),
            (CacheError, BaseError),
            (RepositoryError, BaseError),
            (CloneError, RepositoryError),
            (DeleteError, RepositoryError),
            (MetadataError, RepositoryError),
            (LLMError, BaseError),
            (ServiceConnectionError, BaseError),
        ],
    )
    def test_each_error_has_its_parent(self, error_class, parent):
        assert error_class.__bases__ == (parent,)
        with pytest.raises(parent) as raised:
            raise error_class("it failed")
        assert (type(raised.value), raised.value.message, str(raised.value)) == (error_class, "it failed", "it failed")


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
