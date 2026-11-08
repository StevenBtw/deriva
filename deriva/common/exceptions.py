"""
Unified exception hierarchy for the application.

This module provides a consistent exception structure across all layers:
- Base exceptions for common error categories
- Domain-specific exceptions for LLM, Repository, and Validation operations

Usage:
    from deriva.common.exceptions import ValidationError, ConfigurationError, APIError

    # Raise with context
    raise ValidationError("Invalid element type", context={"type": element_type})

    # Chain from original exception
    raise APIError("Request failed") from original_error
"""

from __future__ import annotations

from typing import Any


class BaseError(Exception):
    """
    Base exception for all application errors.

    Provides consistent error handling with optional context for debugging.

    Attributes:
        message: Human-readable error description
        context: Optional dictionary with additional error context
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None):
        self.message = message
        self.context = context or {}
        super().__init__(message)

    def __str__(self) -> str:
        if self.context:
            context_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({context_str})"
        return self.message


# =============================================================================
# Configuration Errors
# =============================================================================


class ConfigurationError(BaseError):
    """Raised when configuration is invalid or missing."""


class NoModelConfigured(ConfigurationError):
    """No LLM model is configured at all, which is a valid setup: only the structural steps run."""


class RunStopped(RuntimeError):
    """The run must stop (cancelled, out of budget). Every further LLM call of the run raises it, so none reaches the
    model. sample_llm passes it on instead of counting a failed sample; a step that catches every exception records
    the refused calls as errors and goes on, and the studio stops a cancelled run before its next step."""


# =============================================================================
# API and External Service Errors
# =============================================================================


class APIError(BaseError):
    """Raised when an external API call fails."""


class ProviderError(APIError):
    """Raised when an LLM provider operation fails."""


class ServiceConnectionError(BaseError):
    """Raised when a connection to an external service fails."""


# =============================================================================
# Validation Errors
# =============================================================================


class ValidationError(BaseError):
    """Raised when validation fails (input, schema, or model validation)."""


# =============================================================================
# Cache Errors
# =============================================================================


class CacheError(BaseError):
    """Raised when cache operations fail."""


# =============================================================================
# Repository Errors
# =============================================================================


class RepositoryError(BaseError):
    """Base exception for repository operations."""


class CloneError(RepositoryError):
    """Raised when repository cloning fails."""


class DeleteError(RepositoryError):
    """Raised when repository deletion fails."""


class MetadataError(RepositoryError):
    """Raised when metadata extraction fails."""


# =============================================================================
# LLM Errors
# =============================================================================


class LLMError(BaseError):
    """Base exception for LLM operations."""


class RateLimitError(LLMError):
    """Raised when rate limited by provider (HTTP 429)."""

    def __init__(
        self,
        message: str,
        retry_after: float | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message, context)
        self.retry_after = retry_after


class TransientError(LLMError):
    """Raised for transient errors that should be retried (5xx, timeouts)."""


class CircuitOpenError(LLMError):
    """Raised when circuit breaker is open and requests are being rejected."""


# =============================================================================
# Convenience aliases for backwards compatibility
# =============================================================================

# These allow existing code to continue working with minimal changes
# while new code can use the unified hierarchy

__all__ = [
    # Base
    "BaseError",
    # Configuration
    "ConfigurationError",
    "NoModelConfigured",
    # Run
    "RunStopped",
    # API/External
    "APIError",
    "ProviderError",
    "ServiceConnectionError",
    # Validation
    "ValidationError",
    # Cache
    "CacheError",
    # Repository
    "RepositoryError",
    "CloneError",
    "DeleteError",
    "MetadataError",
    # LLM
    "LLMError",
    "RateLimitError",
    "TransientError",
    "CircuitOpenError",
]
