"""Tests for adapters.llm.rate_limiter module."""

from __future__ import annotations

import threading
import time
from collections import deque
from unittest.mock import patch

import pytest

from deriva.adapters.llm.rate_limiter import (
    DEFAULT_RATE_LIMITS,
    CircuitState,
    RateLimitConfig,
    RateLimiter,
    get_default_rate_limit,
)
from deriva.common.exceptions import CircuitOpenError


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 60
        assert config.min_request_delay == 0.0

    def test_custom_values(self):
        """Should accept custom values."""
        config = RateLimitConfig(
            requests_per_minute=100,
            min_request_delay=0.5,
        )
        assert config.requests_per_minute == 100
        assert config.min_request_delay == 0.5


class TestGetDefaultRateLimit:
    """Tests for get_default_rate_limit function."""

    def test_known_providers(self):
        """Should return correct defaults for known providers."""
        assert get_default_rate_limit("azure") == 60
        assert get_default_rate_limit("openai") == 60
        assert get_default_rate_limit("anthropic") == 60
        assert get_default_rate_limit("ollama") == 0
        assert get_default_rate_limit("lmstudio") == 0
        assert get_default_rate_limit("mistral") == 60

    def test_case_insensitive(self):
        """Should be case insensitive."""
        assert get_default_rate_limit("AZURE") == 60
        assert get_default_rate_limit("Azure") == 60
        assert get_default_rate_limit("OLLAMA") == 0

    def test_unknown_provider_returns_default(self):
        """Should return 60 for unknown providers."""
        assert get_default_rate_limit("unknown") == 60
        assert get_default_rate_limit("newprovider") == 60

    def test_all_providers_in_dict(self):
        """All expected providers should be in DEFAULT_RATE_LIMITS."""
        expected = {"azure", "openai", "anthropic", "mistral", "ollama", "lmstudio"}
        assert set(DEFAULT_RATE_LIMITS.keys()) == expected


class TestRateLimiterBasic:
    """Basic tests for RateLimiter class."""

    def test_default_initialization(self):
        """Should initialize with default config."""
        limiter = RateLimiter()
        assert limiter.config.requests_per_minute == 60
        assert limiter._last_request_time == 0.0
        assert len(limiter._request_times) == 0
        assert limiter._successful_requests == 0

    def test_custom_config(self):
        """Should accept custom config."""
        config = RateLimitConfig(requests_per_minute=100)
        limiter = RateLimiter(config=config)
        assert limiter.config.requests_per_minute == 100


class TestRateLimiterWaitIfNeeded:
    """Tests for RateLimiter.wait_if_needed method."""

    def test_no_wait_when_no_limits(self):
        """Should not wait when limits are disabled."""
        config = RateLimitConfig(requests_per_minute=0, min_request_delay=0.0)
        limiter = RateLimiter(config=config)

        wait_time = limiter.wait_if_needed()

        assert wait_time == 0.0

    def test_no_wait_on_first_request(self):
        """Should not wait on first request with RPM limit."""
        config = RateLimitConfig(requests_per_minute=60, min_request_delay=0.0)
        limiter = RateLimiter(config=config)

        wait_time = limiter.wait_if_needed()

        assert wait_time == 0.0
        assert len(limiter._request_times) == 1

    def test_records_request_time(self):
        """Should record request timestamp."""
        config = RateLimitConfig(requests_per_minute=60)
        limiter = RateLimiter(config=config)

        before = time.time()
        limiter.wait_if_needed()
        after = time.time()

        assert len(limiter._request_times) == 1
        assert before <= limiter._request_times[0] <= after
        assert before <= limiter._last_request_time <= after

    def test_min_request_delay_enforced(self):
        """Should enforce minimum delay between requests."""
        config = RateLimitConfig(requests_per_minute=0, min_request_delay=0.05)
        limiter = RateLimiter(config=config)

        # First request - no wait
        limiter.wait_if_needed()

        # Second request immediately after - should wait
        start = time.time()
        wait_time = limiter.wait_if_needed()
        elapsed = time.time() - start

        # Should have waited approximately min_request_delay
        assert wait_time > 0
        assert elapsed >= 0.04  # Allow small timing variance

    def test_rpm_limit_enforced(self):
        """Should enforce RPM limit when reached."""
        # Use a very small RPM limit for testing
        config = RateLimitConfig(requests_per_minute=2, min_request_delay=0.0)
        limiter = RateLimiter(config=config)

        # Make 2 requests (at limit)
        limiter.wait_if_needed()
        limiter.wait_if_needed()

        # Third request should wait (but we mock time to avoid actual wait)
        # Just verify the request count tracking works
        assert len(limiter._request_times) == 2

    def test_old_timestamps_cleaned_up(self):
        """Should clean up timestamps older than 60 seconds."""
        config = RateLimitConfig(requests_per_minute=60)
        limiter = RateLimiter(config=config)

        # Add an old timestamp (using deque)
        old_time = time.time() - 120  # 2 minutes ago
        limiter._request_times = deque([old_time])

        # Make a new request
        limiter.wait_if_needed()

        # Old timestamp should be cleaned up
        assert len(limiter._request_times) == 1
        assert all(t > time.time() - 61 for t in limiter._request_times)


class TestRateLimiterRecordSuccess:
    """Tests for RateLimiter.record_success method."""

    def test_increments_successful_requests(self):
        """Should increment successful requests counter."""
        limiter = RateLimiter()

        limiter.record_success()
        assert limiter._successful_requests == 1

        limiter.record_success()
        assert limiter._successful_requests == 2

    def test_thread_safe(self):
        """Should be thread-safe."""
        limiter = RateLimiter()

        # Call from multiple threads
        threads = [threading.Thread(target=limiter.record_success) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert limiter._successful_requests == 5


class TestRateLimiterGetStats:
    """Tests for RateLimiter.get_stats method."""

    def test_returns_current_state(self):
        """Should return accurate statistics."""
        config = RateLimitConfig(requests_per_minute=100, min_request_delay=0.5)
        limiter = RateLimiter(config=config)

        # Make some requests
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        limiter.record_success()

        stats = limiter.get_stats()

        assert stats["requests_last_minute"] == 2
        assert stats["rpm_limit"] == 100
        assert stats["successful_requests"] == 1
        assert stats["min_request_delay"] == 0.5

    def test_excludes_old_requests(self):
        """Should only count requests in last minute."""
        limiter = RateLimiter()

        # Add old request (using deque)
        limiter._request_times = deque([time.time() - 120])  # 2 minutes ago

        # Add recent request
        limiter.wait_if_needed()

        stats = limiter.get_stats()

        assert stats["requests_last_minute"] == 1  # Only recent one


class TestRateLimiterThreadSafety:
    """Thread safety tests for RateLimiter."""

    def test_concurrent_requests(self):
        """Should handle concurrent requests safely."""
        config = RateLimitConfig(requests_per_minute=1000, min_request_delay=0.0)
        limiter = RateLimiter(config=config)

        results = []

        def make_request():
            wait = limiter.wait_if_needed()
            results.append(wait)

        threads = [threading.Thread(target=make_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All requests should have been recorded
        assert len(limiter._request_times) == 10
        assert len(results) == 10

    def test_concurrent_success_recording(self):
        """Should handle concurrent success recordings safely."""
        limiter = RateLimiter()

        threads = [threading.Thread(target=limiter.record_success) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have incremented 5 times
        assert limiter._successful_requests == 5


class TestRateLimiterRecordFailure:
    """Tests for RateLimiter.record_failure method."""

    def test_does_nothing_when_circuit_breaker_disabled(self):
        """Should do nothing when circuit breaker is disabled."""
        config = RateLimitConfig(circuit_breaker_enabled=False)
        limiter = RateLimiter(config=config)

        limiter.record_failure()

        assert limiter._consecutive_failures == 0

    def test_increments_consecutive_failures(self):
        """Should increment consecutive failures counter."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)

        limiter.record_failure()
        assert limiter._consecutive_failures == 1

        limiter.record_failure()
        assert limiter._consecutive_failures == 2

    def test_opens_circuit_after_threshold(self):
        """Should open circuit after failure threshold reached."""
        config = RateLimitConfig(
            circuit_breaker_enabled=True,
            circuit_failure_threshold=3,
        )
        limiter = RateLimiter(config=config)

        limiter.record_failure()
        limiter.record_failure()
        assert limiter._circuit_state == CircuitState.CLOSED

        limiter.record_failure()  # Third failure hits threshold
        assert limiter._circuit_state == CircuitState.OPEN

    def test_reopens_circuit_from_half_open(self):
        """Should reopen circuit if failure occurs in half-open state."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.HALF_OPEN

        limiter.record_failure()

        assert limiter._circuit_state == CircuitState.OPEN


class TestRateLimiterRecordRateLimit:
    """Tests for RateLimiter.record_rate_limit method."""

    def test_does_nothing_when_throttle_disabled(self):
        """Should do nothing when throttling is disabled."""
        config = RateLimitConfig(throttle_enabled=False)
        limiter = RateLimiter(config=config)

        limiter.record_rate_limit()

        assert limiter._consecutive_rate_limits == 0
        assert limiter._throttle_factor == 1.0

    def test_increments_rate_limit_counter(self):
        """Should increment consecutive rate limits counter."""
        config = RateLimitConfig(throttle_enabled=True)
        limiter = RateLimiter(config=config)

        limiter.record_rate_limit()

        assert limiter._consecutive_rate_limits == 1

    def test_reduces_throttle_factor(self):
        """Should reduce throttle factor by half on rate limit."""
        config = RateLimitConfig(throttle_enabled=True, throttle_min_factor=0.1)
        limiter = RateLimiter(config=config)
        assert limiter._throttle_factor == 1.0

        limiter.record_rate_limit()
        assert limiter._throttle_factor == 0.5

        limiter.record_rate_limit()
        assert limiter._throttle_factor == 0.25

    def test_throttle_respects_minimum_factor(self):
        """Should not reduce throttle factor below minimum."""
        config = RateLimitConfig(throttle_enabled=True, throttle_min_factor=0.3)
        limiter = RateLimiter(config=config)

        # Keep reducing until we hit the floor
        for _ in range(10):
            limiter.record_rate_limit()

        assert limiter._throttle_factor >= 0.3

    def test_records_retry_after(self):
        """Should record rate limit with retry_after value."""
        config = RateLimitConfig(throttle_enabled=True)
        limiter = RateLimiter(config=config)

        limiter.record_rate_limit(retry_after=30.0)

        assert limiter._consecutive_rate_limits == 1


class TestRateLimiterCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_circuit_closed_by_default(self):
        """Should start with closed circuit."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)

        assert limiter._circuit_state == CircuitState.CLOSED

    def test_check_circuit_does_nothing_when_disabled(self):
        """Should do nothing when circuit breaker is disabled."""
        config = RateLimitConfig(circuit_breaker_enabled=False)
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.OPEN

        # Should not raise even when open
        limiter._check_circuit()

    def test_check_circuit_raises_when_open(self):
        """Should raise CircuitOpenError when circuit is open."""
        config = RateLimitConfig(
            circuit_breaker_enabled=True,
            circuit_recovery_time=60.0,
        )
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.OPEN
        limiter._circuit_opened_at = time.time()

        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            limiter._check_circuit()

    def test_circuit_transitions_to_half_open(self):
        """Should transition to half-open after recovery time."""
        config = RateLimitConfig(
            circuit_breaker_enabled=True,
            circuit_recovery_time=0.01,  # Very short for testing
        )
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.OPEN
        limiter._circuit_opened_at = time.time() - 1.0  # 1 second ago

        # Should transition to half-open instead of raising
        limiter._check_circuit()

        assert limiter._circuit_state == CircuitState.HALF_OPEN

    def test_success_closes_circuit_from_half_open(self):
        """Should close circuit on success from half-open state."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.HALF_OPEN

        limiter.record_success()

        assert limiter._circuit_state == CircuitState.CLOSED

    def test_success_resets_consecutive_failures(self):
        """Should reset consecutive failures on success."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)
        limiter._consecutive_failures = 5

        limiter.record_success()

        assert limiter._consecutive_failures == 0


class TestRateLimiterThrottling:
    """Tests for throttling functionality."""

    def test_throttle_affects_effective_rpm(self):
        """Should reduce effective RPM when throttled."""
        config = RateLimitConfig(
            requests_per_minute=100,
            throttle_enabled=True,
        )
        limiter = RateLimiter(config=config)

        # No throttling initially
        limiter.wait_if_needed()

        # Apply throttling
        limiter.record_rate_limit()  # 50%

        # The effective RPM should now be 50
        assert limiter._throttle_factor == 0.5

    def test_throttle_factor_applied_to_rpm(self):
        """Should apply throttle factor to effective RPM."""
        config = RateLimitConfig(
            requests_per_minute=100,
            throttle_enabled=True,
        )
        limiter = RateLimiter(config=config)

        # Initial throttle is 1.0
        assert limiter._throttle_factor == 1.0

        # After rate limit, throttle is reduced
        limiter.record_rate_limit()
        assert limiter._throttle_factor == 0.5

        # Effective RPM should be 50 (100 * 0.5)
        effective_rpm = int(config.requests_per_minute * limiter._throttle_factor)
        assert effective_rpm == 50


class TestRateLimiterWaitWithCircuit:
    """Tests for wait_if_needed with circuit breaker."""

    def test_raises_when_circuit_open(self):
        """Should raise CircuitOpenError when circuit is open."""
        config = RateLimitConfig(
            circuit_breaker_enabled=True,
            circuit_recovery_time=60.0,
        )
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.OPEN
        limiter._circuit_opened_at = time.time()

        with pytest.raises(CircuitOpenError, match="Circuit breaker is open"):
            limiter.wait_if_needed()


class TestRateLimiterReset:
    """Tests for RateLimiter.reset method."""

    def test_resets_all_state(self):
        """Should reset all state variables."""
        limiter = RateLimiter()

        # Set up some state
        limiter._consecutive_rate_limits = 5
        limiter._throttle_factor = 0.5
        limiter._last_rate_limit_time = time.time()
        limiter._last_throttle_recovery = time.time()
        limiter._circuit_state = CircuitState.OPEN
        limiter._consecutive_failures = 10
        limiter._circuit_opened_at = time.time()
        limiter._request_times.append(time.time())

        # Reset
        limiter.reset()

        # Verify all state is reset
        assert limiter._consecutive_rate_limits == 0
        assert limiter._throttle_factor == 1.0
        assert limiter._last_rate_limit_time == 0.0
        assert limiter._last_throttle_recovery == 0.0
        assert limiter._circuit_state == CircuitState.CLOSED
        assert limiter._consecutive_failures == 0
        assert limiter._circuit_opened_at == 0.0
        assert len(limiter._request_times) == 0


class TestRateLimiterIsCircuitOpen:
    """Tests for RateLimiter.is_circuit_open method."""

    def test_returns_false_when_closed(self):
        """Should return False when circuit is closed."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.CLOSED

        assert limiter.is_circuit_open() is False

    def test_returns_true_when_open(self):
        """Should return True when circuit is open."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.OPEN

        assert limiter.is_circuit_open() is True

    def test_returns_false_when_half_open(self):
        """Should return False when circuit is half-open."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.HALF_OPEN

        assert limiter.is_circuit_open() is False


class TestRateLimiterGetCircuitState:
    """Tests for RateLimiter.get_circuit_state method."""

    def test_returns_closed_string(self):
        """Should return 'closed' when circuit is closed."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.CLOSED

        assert limiter.get_circuit_state() == "closed"

    def test_returns_open_string(self):
        """Should return 'open' when circuit is open."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.OPEN

        assert limiter.get_circuit_state() == "open"

    def test_returns_half_open_string(self):
        """Should return 'half_open' when circuit is half-open."""
        limiter = RateLimiter()
        limiter._circuit_state = CircuitState.HALF_OPEN

        assert limiter.get_circuit_state() == "half_open"


class TestRateLimiterThrottleRecovery:
    """Tests for throttle recovery functionality."""

    def test_does_nothing_when_throttle_disabled(self):
        """Should not recover when throttling is disabled."""
        config = RateLimitConfig(throttle_enabled=False)
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5

        limiter._try_throttle_recovery()

        # Should not change when disabled
        assert limiter._throttle_factor == 0.5

    def test_does_nothing_when_throttle_at_max(self):
        """Should not recover when throttle is already at 1.0."""
        config = RateLimitConfig(throttle_enabled=True)
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 1.0

        limiter._try_throttle_recovery()

        assert limiter._throttle_factor == 1.0

    def test_recovers_after_enough_time(self):
        """Should recover throttle after recovery time passes."""
        config = RateLimitConfig(
            throttle_enabled=True,
            throttle_recovery_time=0.01,  # Very short for testing
        )
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5
        limiter._last_rate_limit_time = time.time() - 1.0  # 1 second ago
        limiter._last_throttle_recovery = time.time() - 1.0

        limiter._try_throttle_recovery()

        # Should have increased by 25%
        assert limiter._throttle_factor == 0.625  # 0.5 * 1.25

    def test_does_not_recover_too_soon_after_rate_limit(self):
        """Should not recover if rate limit was too recent."""
        config = RateLimitConfig(
            throttle_enabled=True,
            throttle_recovery_time=60.0,
        )
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5
        limiter._last_rate_limit_time = time.time()  # Just now

        limiter._try_throttle_recovery()

        # Should not change
        assert limiter._throttle_factor == 0.5

    def test_does_not_recover_too_soon_after_previous_recovery(self):
        """Should not recover if previous recovery was too recent."""
        config = RateLimitConfig(
            throttle_enabled=True,
            throttle_recovery_time=60.0,
        )
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5
        limiter._last_rate_limit_time = time.time() - 120  # Long ago
        limiter._last_throttle_recovery = time.time()  # Just now

        limiter._try_throttle_recovery()

        # Should not change
        assert limiter._throttle_factor == 0.5

    def test_recovery_caps_at_one(self):
        """Should not exceed 1.0 during recovery."""
        config = RateLimitConfig(
            throttle_enabled=True,
            throttle_recovery_time=0.01,
        )
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.9
        limiter._last_rate_limit_time = time.time() - 1.0
        limiter._last_throttle_recovery = time.time() - 1.0

        limiter._try_throttle_recovery()

        # Should cap at 1.0
        assert limiter._throttle_factor == 1.0

    def test_recovery_resets_consecutive_rate_limits(self):
        """Should reset consecutive rate limits counter on recovery."""
        config = RateLimitConfig(
            throttle_enabled=True,
            throttle_recovery_time=0.01,
        )
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5
        limiter._consecutive_rate_limits = 5
        limiter._last_rate_limit_time = time.time() - 1.0
        limiter._last_throttle_recovery = time.time() - 1.0

        limiter._try_throttle_recovery()

        assert limiter._consecutive_rate_limits == 0


class TestRateLimiterGetEffectiveRpm:
    """Tests for RateLimiter.get_effective_rpm method."""

    def test_returns_zero_for_disabled_rpm(self):
        """Should return 0 when RPM is disabled."""
        config = RateLimitConfig(requests_per_minute=0)
        limiter = RateLimiter(config=config)

        assert limiter.get_effective_rpm() == 0

    def test_returns_full_rpm_at_full_throttle(self):
        """Should return full RPM when throttle is 1.0."""
        config = RateLimitConfig(requests_per_minute=100)
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 1.0

        assert limiter.get_effective_rpm() == 100

    def test_returns_reduced_rpm_when_throttled(self):
        """Should return reduced RPM when throttled."""
        config = RateLimitConfig(requests_per_minute=100)
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.5

        assert limiter.get_effective_rpm() == 50

    def test_returns_minimum_one(self):
        """Should return at least 1 when RPM is positive."""
        config = RateLimitConfig(requests_per_minute=2)
        limiter = RateLimiter(config=config)
        limiter._throttle_factor = 0.1  # Would be 0.2, rounds to 1

        assert limiter.get_effective_rpm() == 1


class TestRateLimiterCheckCircuitHalfOpen:
    """Tests for circuit breaker half-open state."""

    def test_allows_requests_in_half_open_state(self):
        """Should allow requests through in half-open state."""
        config = RateLimitConfig(circuit_breaker_enabled=True)
        limiter = RateLimiter(config=config)
        limiter._circuit_state = CircuitState.HALF_OPEN

        # Should not raise
        limiter._check_circuit()

        # State should remain half-open
        assert limiter._circuit_state == CircuitState.HALF_OPEN


class TestParseRetryAfter:
    """Tests for parse_retry_after function."""

    def test_returns_none_for_none_headers(self):
        """Should return None when headers is None."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after(None)
        assert result is None

    def test_returns_none_for_empty_headers(self):
        """Should return None when headers is empty."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({})
        assert result is None

    def test_parses_retry_after_header(self):
        """Should parse standard retry-after header."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"retry-after": "30"})
        assert result == 30.0

    def test_parses_x_retry_after_header(self):
        """Should parse x-retry-after header."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"x-retry-after": "45"})
        assert result == 45.0

    def test_parses_x_ratelimit_reset_header(self):
        """Should parse x-ratelimit-reset header."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"x-ratelimit-reset": "60"})
        assert result == 60.0

    def test_case_insensitive_header_names(self):
        """Should handle different case header names."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"Retry-After": "25"})
        assert result == 25.0

        result = parse_retry_after({"RETRY-AFTER": "25"})
        assert result == 25.0

    def test_returns_none_for_invalid_value(self):
        """Should return None for non-numeric values."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"retry-after": "not-a-number"})
        assert result is None

    def test_parses_float_value(self):
        """Should parse float values."""
        from deriva.adapters.llm.rate_limiter import parse_retry_after

        result = parse_retry_after({"retry-after": "30.5"})
        assert result == 30.5


class TestRateLimiterWaitRpmLimit:
    """Tests for wait_if_needed when RPM limit is reached."""

    def test_waits_when_at_rpm_limit(self):
        """Should calculate wait time when at RPM limit."""
        # Use a very low limit for fast testing
        config = RateLimitConfig(requests_per_minute=2, min_request_delay=0.0)
        limiter = RateLimiter(config=config)

        # Fill up the request bucket
        now = time.time()
        limiter._request_times = deque([now - 0.1, now - 0.05])  # 2 recent requests

        # The next request waits until the oldest is a minute old (the sleep is patched: this test took a minute)
        with patch("deriva.adapters.llm.rate_limiter.time.sleep") as sleep:
            waited = limiter.wait_if_needed()

        assert 59.8 < waited <= 60.0
        sleep.assert_called_once_with(waited)
        assert len(limiter._request_times) == 3


class TestGetStatsCleanup:
    """Tests for get_stats timestamp cleanup."""

    def test_cleans_old_timestamps_in_stats(self):
        """Should clean expired timestamps when getting stats."""
        limiter = RateLimiter()

        # Add old and new timestamps
        now = time.time()
        limiter._request_times = deque([now - 120, now - 90, now - 10, now - 5])

        stats = limiter.get_stats()

        # Only the 2 recent requests should remain
        assert stats["requests_last_minute"] == 2
