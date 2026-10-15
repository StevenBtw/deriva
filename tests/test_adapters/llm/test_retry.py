"""Tests for adapters.llm.retry module."""

from __future__ import annotations

import httpx2
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError

from deriva.adapters.llm.retry import (
    _extract_retry_after_from_exception,
    classify_exception,
    transport_error,
)
from deriva.common.exceptions import (
    CircuitOpenError,
    RateLimitError,
    TransientError,
)


def api_error(cause: Exception) -> ModelAPIError:
    """What pydantic-ai raises when a provider call fails: a ModelAPIError with the transport error as its cause."""
    try:
        raise ModelAPIError(model_name="test-model", message=str(cause)) from cause
    except ModelAPIError as error:
        return error


class TestClassifyException:
    """Tests for classify_exception function."""

    def test_classifies_rate_limit_error(self):
        """Should classify RateLimitError as rate_limited."""
        exc = RateLimitError("Rate limited", retry_after=30.0)
        category, retry_after = classify_exception(exc)
        assert category == "rate_limited"
        assert retry_after == 30.0

    def test_classifies_transient_error(self):
        """Should classify TransientError as transient."""
        exc = TransientError("Temporary failure")
        category, retry_after = classify_exception(exc)
        assert category == "transient"
        assert retry_after is None

    def test_classifies_circuit_open_error(self):
        """Should classify CircuitOpenError as permanent."""
        exc = CircuitOpenError("Circuit is open")
        category, retry_after = classify_exception(exc)
        assert category == "permanent"
        assert retry_after is None

    def test_classifies_connection_error(self):
        """Should classify ConnectionError as transient."""
        exc = ConnectionError("Connection refused")
        category, retry_after = classify_exception(exc)
        assert category == "transient"
        assert retry_after is None

    def test_classifies_timeout_error(self):
        """Should classify TimeoutError as transient."""
        exc = TimeoutError("Request timed out")
        category, retry_after = classify_exception(exc)
        assert category == "transient"
        assert retry_after is None

    def test_classifies_os_error(self):
        """Should classify OSError as transient."""
        exc = OSError("Network unreachable")
        category, retry_after = classify_exception(exc)
        assert category == "transient"
        assert retry_after is None

    def test_classifies_unknown_exception_as_transient(self):
        """Should classify unknown exceptions as transient by default."""
        exc = RuntimeError("Unknown error")
        category, retry_after = classify_exception(exc)
        assert category == "transient"
        assert retry_after is None


class TestClassifyExceptionModelHTTPError:
    """An HTTP status error is classified by its status code (pydantic-ai raises ModelHTTPError, not a raw httpx error)."""

    def test_429_is_rate_limited(self):
        category, retry_after = classify_exception(ModelHTTPError(status_code=429, model_name="m", body={"retry_after": 30.0}))
        assert category == "rate_limited"
        assert retry_after == 30.0

    def test_429_with_invalid_retry_after(self):
        """Should handle invalid retry-after body values."""
        category, retry_after = classify_exception(ModelHTTPError(status_code=429, model_name="m", body={"retry_after": "invalid"}))
        assert category == "rate_limited"
        assert retry_after is None

    def test_500_is_transient(self):
        assert classify_exception(ModelHTTPError(status_code=500, model_name="m")) == ("transient", None)

    def test_503_is_transient(self):
        assert classify_exception(ModelHTTPError(status_code=503, model_name="m")) == ("transient", None)

    def test_520_is_transient(self):
        """Cloudflare errors (520-524) are transient."""
        assert classify_exception(ModelHTTPError(status_code=520, model_name="m")) == ("transient", None)

    def test_400_is_permanent(self):
        assert classify_exception(ModelHTTPError(status_code=400, model_name="m")) == ("permanent", None)

    def test_401_is_permanent(self):
        assert classify_exception(ModelHTTPError(status_code=401, model_name="m")) == ("permanent", None)

    def test_404_is_permanent(self):
        assert classify_exception(ModelHTTPError(status_code=404, model_name="m")) == ("permanent", None)

    def test_unknown_5xx_is_transient(self):
        assert classify_exception(ModelHTTPError(status_code=599, model_name="m")) == ("transient", None)

    def test_unknown_status_defaults_to_transient(self):
        """A status code outside the known sets falls back to the ModelHTTPError default: transient."""
        assert classify_exception(ModelHTTPError(status_code=450, model_name="m")) == ("transient", None)


class TestClassifyExceptionTransport:
    """A transport failure wrapped by pydantic-ai is classified by the error behind the wrapper."""

    def test_wrapped_timeout_is_transient(self):
        assert classify_exception(api_error(httpx2.ReadTimeout("slow"))) == ("transient", None)

    def test_wrapped_connection_error_is_transient(self):
        assert classify_exception(api_error(httpx2.ConnectError("refused"))) == ("transient", None)

    def test_wrapped_local_protocol_error_is_permanent(self):
        """An illegal header value can never succeed on retry, also behind the wrapper."""
        assert classify_exception(api_error(httpx2.LocalProtocolError("Illegal header value b'key '"))) == ("permanent", None)

    def test_wrapped_unsupported_protocol_is_permanent(self):
        assert classify_exception(api_error(httpx2.UnsupportedProtocol("unsupported"))) == ("permanent", None)

    def test_raw_transport_error_is_transient(self):
        assert classify_exception(httpx2.ReadTimeout("slow")) == ("transient", None)


class TestTransportError:
    """The httpx2 transport error behind an exception, through pydantic-ai's and the SDK's wrappers."""

    def test_returns_the_error_itself(self):
        error = httpx2.ReadTimeout("slow")
        assert transport_error(error) is error

    def test_finds_the_error_behind_a_model_api_error(self):
        cause = httpx2.ConnectError("refused")
        assert transport_error(api_error(cause)) is cause

    def test_finds_the_error_behind_a_nested_chain(self):
        """pydantic-ai wraps the SDK's APIConnectionError, which wraps the httpx2 error."""
        caught: dict[str, BaseException] = {}
        try:
            try:
                raise httpx2.ReadTimeout("slow")
            except httpx2.ReadTimeout as transport:
                caught["transport"] = transport
                raise RuntimeError("APIConnectionError") from transport
        except RuntimeError as sdk_error:
            caught["sdk"] = sdk_error
            try:
                raise ModelAPIError(model_name="m", message="Connection error.") from sdk_error
            except ModelAPIError as error:
                caught["api"] = error

        assert transport_error(caught["api"]) is caught["transport"]

    def test_returns_none_without_a_transport_error(self):
        assert transport_error(ModelAPIError(model_name="m", message="unexpected model behavior")) is None
        assert transport_error(ValueError("nope")) is None

    def test_ignores_errors_of_the_httpx_package(self):
        """Only httpx2 matches: pydantic-ai and the provider SDKs run on httpx2, not on httpx."""
        import httpx

        assert transport_error(httpx.ReadTimeout("slow")) is None
        assert transport_error(api_error(httpx.ConnectError("refused"))) is None

    def test_survives_a_cyclic_cause_chain(self):
        error = ModelAPIError(model_name="m", message="loop")
        error.__cause__ = error
        assert transport_error(error) is None


class TestExtractRetryAfterFromException:
    """Tests for _extract_retry_after_from_exception function."""

    def test_returns_none_for_no_body(self):
        """Should return None when exception has no body."""
        exc = Exception("No body")
        result = _extract_retry_after_from_exception(exc)
        assert result is None

    def test_extracts_retry_after_from_dict_body(self):
        """Should extract retry_after from dict body."""
        exc = Exception("Has body")
        exc.body = {"retry_after": 30.0}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 30.0

    def test_extracts_retry_after_with_hyphen(self):
        """Should extract retry-after with hyphen."""
        exc = Exception("Has body")
        exc.body = {"retry-after": 45.0}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 45.0

    def test_extracts_retry_after_camel_case(self):
        """Should extract retryAfter in camelCase."""
        exc = Exception("Has body")
        exc.body = {"retryAfter": 60.0}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 60.0

    def test_extracts_from_nested_error_object(self):
        """Should extract retry_after from nested error object."""
        exc = Exception("Has nested body")
        exc.body = {"error": {"retry_after": 15.0}}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 15.0

    def test_returns_none_for_invalid_value(self):
        """Should return None for non-numeric values."""
        exc = Exception("Has body")
        exc.body = {"retry_after": "not-a-number"}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result is None

    def test_returns_none_for_non_dict_body(self):
        """Should return None for non-dict body."""
        exc = Exception("Has body")
        exc.body = "string body"  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result is None


class TestExtractRetryAfterNested:
    """Additional tests for _extract_retry_after_from_exception."""

    def test_extracts_from_nested_error_hyphen(self):
        """Should extract retry-after from nested error with hyphen."""
        exc = Exception("Has nested body")
        exc.body = {"error": {"retry-after": 25.0}}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 25.0

    def test_extracts_from_nested_error_camelcase(self):
        """Should extract retryAfter from nested error."""
        exc = Exception("Has nested body")
        exc.body = {"error": {"retryAfter": 35.0}}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result == 35.0

    def test_returns_none_for_nested_invalid_value(self):
        """Should return None for non-numeric nested values."""
        exc = Exception("Has nested body")
        exc.body = {"error": {"retry_after": "not-a-number"}}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result is None

    def test_returns_none_for_non_dict_error(self):
        """Should return None when error is not a dict."""
        exc = Exception("Has body")
        exc.body = {"error": "string error"}  # type: ignore
        result = _extract_retry_after_from_exception(exc)
        assert result is None
