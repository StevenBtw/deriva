"""
Error classification for LLM retries.

The retry loop itself is hand-written in ``LLMManager._run_with_retries``; this module
classifies what a failed call raised and finds the transport error behind pydantic-ai's
wrapper exceptions.
"""

from __future__ import annotations

import httpx2
from pydantic_ai.exceptions import IncompleteToolCall, ModelHTTPError

from deriva.common.exceptions import (
    CircuitOpenError,
    RateLimitError,
    TransientError,
)

# HTTP status codes that indicate transient errors (should retry)
TRANSIENT_STATUS_CODES = {500, 502, 503, 504, 520, 521, 522, 523, 524}

# HTTP status codes that indicate rate limiting
RATE_LIMIT_STATUS_CODES = {429}

# HTTP status codes that indicate permanent errors (should not retry)
PERMANENT_STATUS_CODES = {400, 401, 403, 404, 405, 410, 422}


def transport_error(error: BaseException) -> BaseException | None:
    """The httpx2 transport error behind an exception, if any.

    pydantic-ai and the provider SDKs run on httpx2 and wrap what the HTTP layer raises: a
    timeout or connection error reaches Deriva as a ``ModelAPIError`` whose ``__cause__`` chain
    ends in the httpx2 error (``ModelAPIError`` <- ``APIConnectionError`` <- ``httpx2.ReadTimeout``,
    say). That error is what says whether the failure is transient or a permanent client error.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx2.RequestError):
            return current
        current = current.__cause__ or current.__context__
    return None


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

    # An answer cut at the output limit is cut again for the same prompt; the caller can split it instead
    if isinstance(exception, IncompleteToolCall):
        return ("permanent", None)

    # An HTTP status error carries its own status code
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

    # A transport failure arrives wrapped by pydantic-ai; classify the error behind it
    transport = transport_error(exception)
    if transport is not None:
        # Client-side and permanent: a malformed header or URL never succeeds on retry
        if isinstance(transport, (httpx2.LocalProtocolError, httpx2.UnsupportedProtocol)):
            return ("permanent", None)
        return ("transient", None)

    # Check for connection/timeout errors
    if isinstance(exception, (ConnectionError, TimeoutError, OSError)):
        return ("transient", None)

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


__all__ = [
    "classify_exception",
    "transport_error",
    "TRANSIENT_STATUS_CODES",
    "RATE_LIMIT_STATUS_CODES",
    "PERMANENT_STATUS_CODES",
]
