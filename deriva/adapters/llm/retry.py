"""
Retry utilities with exponential backoff.

Uses the backoff library for robust retry handling with jitter.
Includes error classification to distinguish transient from permanent errors.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Generator
from typing import TypeVar

import backoff
from backoff._typing import Details

from deriva.common.exceptions import (
    CircuitOpenError,
    RateLimitError,
    TransientError,
)

logger = logging.getLogger(__name__)

# Type variable for decorated function return type
T = TypeVar("T")

# Exceptions that should trigger retry
RETRIABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes network errors
)


def on_backoff(details: Details) -> None:
    """Log backoff events."""
    wait = details.get("wait", 0)
    tries = details.get("tries", 0)
    target = details.get("target")
    target_name = getattr(target, "__name__", "unknown") if target else "unknown"
    exception = details.get("exception")

    logger.warning(
        "Retry %d for %s, backing off %.2fs. Error: %s",
        tries,
        target_name,
        wait,
        exception,
    )


def on_giveup(details: Details) -> None:
    """Log when retries are exhausted."""
    tries = details.get("tries", 0)
    target = details.get("target")
    target_name = getattr(target, "__name__", "unknown") if target else "unknown"
    exception = details.get("exception")

    logger.error(
        "Giving up on %s after %d attempts. Final error: %s",
        target_name,
        tries,
        exception,
    )


def create_retry_decorator(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = RETRIABLE_EXCEPTIONS,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Create a retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay factor for exponential backoff (default: 2.0)
        max_delay: Maximum delay between retries (default: 60.0)
        exceptions: Tuple of exception types to retry on

    Returns:
        Decorator function

    Example:
        @create_retry_decorator(max_retries=5)
        def flaky_api_call():
            ...
    """
    return backoff.on_exception(
        backoff.expo,
        exception=exceptions,
        max_tries=max_retries + 1,  # backoff counts total tries, not retries
        factor=base_delay,
        max_value=max_delay,
        jitter=backoff.full_jitter,
        on_backoff=on_backoff,
        on_giveup=on_giveup,
    )


def retry_on_rate_limit(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for retrying on rate limit errors (HTTP 429).

    Uses exponential backoff with jitter to handle rate limits gracefully.

    Args:
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds

    Returns:
        Decorator function

    Example:
        @retry_on_rate_limit(max_retries=5)
        def api_call():
            response = requests.get(url)
            if response.status_code == 429:
                raise RateLimitError("Rate limited")
            return response
    """
    # Import here to avoid issues if these aren't installed
    try:
        from httpx import HTTPStatusError
        from pydantic_ai import exceptions as pai_exceptions

        rate_limit_exceptions = (
            ConnectionError,
            TimeoutError,
            HTTPStatusError,
        )

        # Add PydanticAI rate limit exception if available
        if hasattr(pai_exceptions, "RateLimitError"):
            rate_limit_exceptions = (
                *rate_limit_exceptions,
                pai_exceptions.RateLimitError,
            )
    except ImportError:
        rate_limit_exceptions = (ConnectionError, TimeoutError)

    return backoff.on_exception(
        backoff.expo,
        exception=rate_limit_exceptions,
        max_tries=max_retries + 1,
        factor=base_delay,
        max_value=max_delay,
        jitter=backoff.full_jitter,
        on_backoff=on_backoff,
        on_giveup=on_giveup,
    )


# =============================================================================
# Error Classification
# =============================================================================

# HTTP status codes that indicate transient errors (should retry)
TRANSIENT_STATUS_CODES = {500, 502, 503, 504, 520, 521, 522, 523, 524}

# HTTP status codes that indicate rate limiting
RATE_LIMIT_STATUS_CODES = {429}

# HTTP status codes that indicate permanent errors (should not retry)
PERMANENT_STATUS_CODES = {400, 401, 403, 404, 405, 410, 422}


def classify_exception(
    exception: Exception,
) -> tuple[str, float | None]:
    """
    Classify an exception for retry handling.

    Categorizes exceptions into:
    - "rate_limited": Rate limit errors (429), may have retry_after
    - "transient": Temporary errors that should be retried (5xx, timeouts)
    - "permanent": Errors that should not be retried (4xx except 429)

    Args:
        exception: The exception to classify

    Returns:
        Tuple of (category, retry_after_seconds or None)
    """
    # Check for our custom exceptions first
    if isinstance(exception, RateLimitError):
        return ("rate_limited", exception.retry_after)

    if isinstance(exception, TransientError):
        return ("transient", None)

    if isinstance(exception, CircuitOpenError):
        return ("permanent", None)

    # Check for connection/timeout errors
    if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
        return ("transient", None)

    # Try to get HTTP status code from PydanticAI exceptions
    try:
        from pydantic_ai.exceptions import ModelHTTPError

        if isinstance(exception, ModelHTTPError):
            status_code = getattr(exception, "status_code", None)
            if status_code:
                # Extract retry-after from body if available
                retry_after = _extract_retry_after_from_exception(exception)

                if status_code in RATE_LIMIT_STATUS_CODES:
                    return ("rate_limited", retry_after)
                if status_code in TRANSIENT_STATUS_CODES:
                    return ("transient", None)
                if status_code in PERMANENT_STATUS_CODES:
                    return ("permanent", None)

            # Default ModelHTTPError to transient
            return ("transient", None)
    except ImportError:
        pass

    # Check for httpx HTTPStatusError
    try:
        from httpx import HTTPStatusError

        if isinstance(exception, HTTPStatusError):
            status_code = exception.response.status_code
            retry_after = None

            # Try to extract retry-after header
            retry_after_header = exception.response.headers.get("retry-after")
            if retry_after_header:
                try:
                    retry_after = float(retry_after_header)
                except ValueError:
                    pass

            if status_code in RATE_LIMIT_STATUS_CODES:
                return ("rate_limited", retry_after)
            if status_code in TRANSIENT_STATUS_CODES:
                return ("transient", None)
            if status_code in PERMANENT_STATUS_CODES:
                return ("permanent", None)

            # Unknown status code - default to transient for 5xx range
            if 500 <= status_code < 600:
                return ("transient", None)
            return ("permanent", None)
    except ImportError:
        pass

    # Default: treat unknown exceptions as transient (will be retried)
    return ("transient", None)


def _extract_retry_after_from_exception(exception: Exception) -> float | None:
    """
    Extract retry-after value from exception body.

    Some providers include retry information in the response body.
    """
    body = getattr(exception, "body", None)
    if not body:
        return None

    # Handle dict body
    if isinstance(body, dict):
        # Check common locations for retry-after
        for key in ["retry_after", "retry-after", "retryAfter"]:
            if key in body:
                try:
                    return float(body[key])
                except ValueError, TypeError:
                    pass

        # Check nested error object
        error = body.get("error", {})
        if isinstance(error, dict):
            for key in ["retry_after", "retry-after", "retryAfter"]:
                if key in error:
                    try:
                        return float(error[key])
                    except ValueError, TypeError:
                        pass

    return None


def is_transient(exception: Exception) -> bool:
    """Check if an exception is transient and should be retried."""
    category, _ = classify_exception(exception)
    return category in ("transient", "rate_limited")


def should_giveup(exception: Exception) -> bool:
    """
    Determine if we should give up retrying on this exception.

    Returns True for permanent errors that should not be retried.
    Used as a giveup predicate for the backoff library.
    """
    category, _ = classify_exception(exception)
    return category == "permanent"


# =============================================================================
# Custom Wait Generators
# =============================================================================


def wait_with_retry_after(
    base: float = 2.0,
    max_value: float = 60.0,
) -> Generator[float, Exception | None, None]:
    """
    Wait generator that respects Retry-After headers.

    If the exception contains retry-after information, uses that value.
    Otherwise, falls back to exponential backoff with jitter.

    Args:
        base: Base delay for exponential backoff
        max_value: Maximum delay between retries

    Yields:
        Wait time in seconds
    """
    attempt = 0
    while True:
        exception = yield 0.0  # First yield is just to receive the exception

        retry_after: float | None = None
        if exception is not None:
            _, retry_after = classify_exception(exception)

        if retry_after is not None and retry_after > 0:
            # Use the server-provided retry-after, capped at max_value
            wait_time = min(retry_after, max_value)
            logger.debug("Using retry-after value: %.2fs", wait_time)
        else:
            # Exponential backoff with full jitter
            exp_delay = base * (2**attempt)
            capped_delay = min(exp_delay, max_value)
            wait_time = random.uniform(0, capped_delay)

        attempt += 1
        yield wait_time


def create_retry_with_classification(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Create a retry decorator that uses error classification.

    This decorator:
    - Retries on transient and rate_limited errors
    - Gives up immediately on permanent errors
    - Respects Retry-After headers when available
    - Uses exponential backoff with jitter as fallback

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay for exponential backoff
        max_delay: Maximum delay between retries

    Returns:
        Decorator function
    """
    # Get all retriable exceptions
    retriable: tuple[type[Exception], ...] = RETRIABLE_EXCEPTIONS

    try:
        from httpx import HTTPStatusError

        retriable = (*retriable, HTTPStatusError)
    except ImportError:
        pass

    try:
        from pydantic_ai.exceptions import ModelHTTPError

        retriable = (*retriable, ModelHTTPError)
    except ImportError:
        pass

    def wait_gen() -> Generator[float, Exception | None, None]:
        return wait_with_retry_after(base_delay, max_delay)

    return backoff.on_exception(
        wait_gen,
        exception=retriable,
        max_tries=max_retries + 1,
        giveup=should_giveup,
        on_backoff=on_backoff,
        on_giveup=on_giveup,
    )


__all__ = [
    "create_retry_decorator",
    "retry_on_rate_limit",
    "create_retry_with_classification",
    "classify_exception",
    "is_transient",
    "should_giveup",
    "wait_with_retry_after",
    "RETRIABLE_EXCEPTIONS",
    "TRANSIENT_STATUS_CODES",
    "RATE_LIMIT_STATUS_CODES",
    "PERMANENT_STATUS_CODES",
]
