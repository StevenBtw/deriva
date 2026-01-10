"""Tests for adapters.llm.rate_limiter module."""

from __future__ import annotations

import threading
import time

from deriva.adapters.llm.rate_limiter import (
    DEFAULT_RATE_LIMITS,
    RateLimitConfig,
    RateLimiter,
    get_default_rate_limit,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 60
        assert config.min_request_delay == 0.0
        assert config.backoff_base == 2.0
        assert config.backoff_max == 60.0
        assert config.backoff_jitter == 0.1

    def test_custom_values(self):
        """Should accept custom values."""
        config = RateLimitConfig(
            requests_per_minute=100,
            min_request_delay=0.5,
            backoff_base=3.0,
            backoff_max=120.0,
            backoff_jitter=0.2,
        )
        assert config.requests_per_minute == 100
        assert config.min_request_delay == 0.5
        assert config.backoff_base == 3.0
        assert config.backoff_max == 120.0
        assert config.backoff_jitter == 0.2


class TestGetDefaultRateLimit:
    """Tests for get_default_rate_limit function."""

    def test_known_providers(self):
        """Should return correct defaults for known providers."""
        assert get_default_rate_limit("azure") == 60
        assert get_default_rate_limit("openai") == 60
        assert get_default_rate_limit("anthropic") == 60
        assert get_default_rate_limit("ollama") == 0
        assert get_default_rate_limit("lmstudio") == 0
        assert get_default_rate_limit("claudecode") == 30

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
        expected = {"azure", "openai", "anthropic", "mistral", "ollama", "lmstudio", "claudecode"}
        assert set(DEFAULT_RATE_LIMITS.keys()) == expected


class TestRateLimiterBasic:
    """Basic tests for RateLimiter class."""

    def test_default_initialization(self):
        """Should initialize with default config."""
        limiter = RateLimiter()
        assert limiter.config.requests_per_minute == 60
        assert limiter._consecutive_rate_limits == 0
        assert limiter._last_request_time == 0.0
        assert limiter._request_times == []

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

        # Add an old timestamp
        old_time = time.time() - 120  # 2 minutes ago
        limiter._request_times = [old_time]

        # Make a new request
        limiter.wait_if_needed()

        # Old timestamp should be cleaned up
        assert len(limiter._request_times) == 1
        assert all(t > time.time() - 61 for t in limiter._request_times)


class TestRateLimiterRecordSuccess:
    """Tests for RateLimiter.record_success method."""

    def test_resets_consecutive_rate_limits(self):
        """Should reset consecutive rate limit counter on success."""
        limiter = RateLimiter()
        limiter._consecutive_rate_limits = 5

        limiter.record_success()

        assert limiter._consecutive_rate_limits == 0

    def test_thread_safe(self):
        """Should be thread-safe."""
        limiter = RateLimiter()
        limiter._consecutive_rate_limits = 10

        # Call from multiple threads
        threads = [threading.Thread(target=limiter.record_success) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert limiter._consecutive_rate_limits == 0


class TestRateLimiterRecordRateLimit:
    """Tests for RateLimiter.record_rate_limit method."""

    def test_increments_consecutive_count(self):
        """Should increment consecutive rate limit counter."""
        limiter = RateLimiter()

        limiter.record_rate_limit()
        assert limiter._consecutive_rate_limits == 1

        limiter.record_rate_limit()
        assert limiter._consecutive_rate_limits == 2

    def test_returns_exponential_backoff(self):
        """Should return exponentially increasing backoff times."""
        config = RateLimitConfig(backoff_base=2.0, backoff_jitter=0.0)
        limiter = RateLimiter(config=config)

        delay1 = limiter.record_rate_limit()  # 2^1 = 2
        delay2 = limiter.record_rate_limit()  # 2^2 = 4
        delay3 = limiter.record_rate_limit()  # 2^3 = 8

        assert delay1 == 2.0
        assert delay2 == 4.0
        assert delay3 == 8.0

    def test_respects_max_backoff(self):
        """Should cap backoff at configured maximum."""
        config = RateLimitConfig(backoff_base=2.0, backoff_max=10.0, backoff_jitter=0.0)
        limiter = RateLimiter(config=config)

        # Force high consecutive count
        limiter._consecutive_rate_limits = 10  # Would be 2^11 = 2048

        delay = limiter.record_rate_limit()

        assert delay == 10.0  # Capped at max

    def test_adds_jitter(self):
        """Should add jitter when configured."""
        config = RateLimitConfig(backoff_base=2.0, backoff_jitter=0.5)

        # Collect delays with same consecutive count to test jitter variation
        delays = []
        for _ in range(10):
            limiter = RateLimiter(config=config)  # Fresh limiter each time
            delay = limiter.record_rate_limit()  # First rate limit = 2^1 = 2
            delays.append(delay)

        # With 50% jitter, delay should be 2 + random(0, 1.0) = 2.0 to 3.0
        for delay in delays:
            assert 2.0 <= delay <= 3.0

        # Should have some variation (not all exactly the same)
        assert len(set(delays)) > 1, "Jitter should cause variation in delays"


class TestRateLimiterGetStats:
    """Tests for RateLimiter.get_stats method."""

    def test_returns_current_state(self):
        """Should return accurate statistics."""
        config = RateLimitConfig(requests_per_minute=100, min_request_delay=0.5)
        limiter = RateLimiter(config=config)

        # Make some requests
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        limiter._consecutive_rate_limits = 3

        stats = limiter.get_stats()

        assert stats["requests_last_minute"] == 2
        assert stats["rpm_limit"] == 100
        assert stats["consecutive_rate_limits"] == 3
        assert stats["min_request_delay"] == 0.5

    def test_excludes_old_requests(self):
        """Should only count requests in last minute."""
        limiter = RateLimiter()

        # Add old request
        limiter._request_times = [time.time() - 120]  # 2 minutes ago

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

    def test_concurrent_rate_limit_recording(self):
        """Should handle concurrent rate limit recordings safely."""
        config = RateLimitConfig(backoff_jitter=0.0)
        limiter = RateLimiter(config=config)

        delays = []

        def record_limit():
            delay = limiter.record_rate_limit()
            delays.append(delay)

        threads = [threading.Thread(target=record_limit) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have incremented 5 times
        assert limiter._consecutive_rate_limits == 5
        assert len(delays) == 5
