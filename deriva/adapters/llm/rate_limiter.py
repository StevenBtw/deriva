"""
Rate limiter for LLM API requests.

Implements token bucket algorithm for:
- Requests per minute (RPM) limits
- Minimum delay between requests
- Adaptive throttling on rate limit errors
- Circuit breaker for provider outages

For retry logic with exponential backoff, use retry.py instead.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from deriva.common.exceptions import CircuitOpenError

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests allowed
    OPEN = "open"  # Circuit tripped, requests rejected
    HALF_OPEN = "half_open"  # Testing if service recovered


# Default rate limits by provider (requests per minute)
# These are conservative defaults - actual limits vary by tier/plan
DEFAULT_RATE_LIMITS: dict[str, int] = {
    "azure": 60,  # Azure OpenAI: varies by deployment
    "openai": 60,  # OpenAI: varies by tier (60-10000 RPM)
    "anthropic": 60,  # Anthropic: varies by tier
    "mistral": 24,  # Mistral: varies by tier
    "ollama": 0,  # Local - no limit
    "lmstudio": 0,  # Local - no limit
}


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting, adaptive throttling, and circuit breaker."""

    # Basic rate limiting
    requests_per_minute: int = 60  # 0 = no limit
    min_request_delay: float = 0.0  # Minimum seconds between requests

    # Adaptive throttling - reduces RPM when hitting rate limits
    throttle_enabled: bool = True
    throttle_min_factor: float = 0.25  # Minimum 25% of configured RPM
    throttle_recovery_time: float = 60.0  # Seconds before trying to increase RPM

    # Circuit breaker - stops requests when provider is failing
    circuit_breaker_enabled: bool = True
    circuit_failure_threshold: int = 5  # Consecutive failures to open circuit
    circuit_recovery_time: float = 30.0  # Seconds before half-open test


@dataclass
class RateLimiter:
    """
    Token bucket rate limiter for API requests.

    Thread-safe implementation that tracks request timestamps and
    enforces rate limits across concurrent calls.

    Features:
    - Token bucket for RPM limits
    - Adaptive throttling on rate limit errors
    - Circuit breaker for provider outages

    Uses deque for O(1) operations when expiring old timestamps.
    """

    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _request_times: deque = field(default_factory=deque)  # O(1) popleft
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_request_time: float = field(default=0.0)
    _successful_requests: int = field(default=0)

    # Adaptive throttling state
    _consecutive_rate_limits: int = field(default=0)
    _throttle_factor: float = field(default=1.0)  # 1.0 = full speed
    _last_rate_limit_time: float = field(default=0.0)
    _last_throttle_recovery: float = field(default=0.0)

    # Circuit breaker state
    _circuit_state: CircuitState = field(default=CircuitState.CLOSED)
    _consecutive_failures: int = field(default=0)
    _circuit_opened_at: float = field(default=0.0)

    def wait_if_needed(self) -> float:
        """
        Wait if necessary to respect rate limits.

        Also checks circuit breaker state and attempts throttle recovery.

        Returns:
            float: Actual wait time in seconds (0 if no wait needed)

        Raises:
            CircuitOpenError: If circuit breaker is open
        """
        # Check circuit breaker first (outside main lock for performance)
        self._check_circuit()

        # Try throttle recovery before calculating wait
        self._try_throttle_recovery()

        effective_rpm = self.get_effective_rpm()
        if effective_rpm <= 0 and self.config.min_request_delay <= 0:
            return 0.0

        with self._lock:
            now = time.time()
            wait_time = 0.0

            # Check minimum delay between requests
            if self.config.min_request_delay > 0 and self._last_request_time > 0:
                elapsed = now - self._last_request_time
                if elapsed < self.config.min_request_delay:
                    wait_time = max(wait_time, self.config.min_request_delay - elapsed)

            # Check RPM limit using effective (throttled) RPM
            if effective_rpm > 0:
                # Clean up old timestamps using O(1) popleft (deque is sorted by time)
                cutoff = now - 60.0
                while self._request_times and self._request_times[0] <= cutoff:
                    self._request_times.popleft()

                # If at limit, wait until oldest request expires
                if len(self._request_times) >= effective_rpm:
                    oldest = self._request_times[0]  # O(1) access to front
                    wait_until = oldest + 60.0
                    wait_time = max(wait_time, wait_until - now)

            # Apply wait if needed
            if wait_time > 0:
                logger.debug(
                    "Rate limiting: waiting %.2fs (effective RPM: %d, throttle: %.0f%%)",
                    wait_time,
                    effective_rpm,
                    self._throttle_factor * 100,
                )
                # Release lock during sleep
                self._lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._lock.acquire()
                now = time.time()

            # Record this request (O(1) append)
            self._request_times.append(now)
            self._last_request_time = now

            return wait_time

    def record_success(self) -> None:
        """
        Record a successful request.

        Resets failure counters and handles circuit breaker state transitions.
        """
        with self._lock:
            self._successful_requests += 1
            self._consecutive_failures = 0

            # Handle circuit breaker state transitions
            if self._circuit_state == CircuitState.HALF_OPEN:
                # Success in half-open means we can close the circuit
                self._circuit_state = CircuitState.CLOSED
                logger.info("Circuit breaker closed after successful request")

    def record_failure(self) -> None:
        """
        Record a failed request for circuit breaker tracking.

        Call this for non-rate-limit failures (timeouts, server errors).
        """
        if not self.config.circuit_breaker_enabled:
            return

        with self._lock:
            self._consecutive_failures += 1

            if self._circuit_state == CircuitState.HALF_OPEN:
                # Failure in half-open means we need to reopen
                self._circuit_state = CircuitState.OPEN
                self._circuit_opened_at = time.time()
                logger.warning("Circuit breaker reopened after failure in half-open state")

            elif self._circuit_state == CircuitState.CLOSED:
                if self._consecutive_failures >= self.config.circuit_failure_threshold:
                    self._circuit_state = CircuitState.OPEN
                    self._circuit_opened_at = time.time()
                    logger.warning(
                        "Circuit breaker opened after %d consecutive failures",
                        self._consecutive_failures,
                    )

    def record_rate_limit(self, retry_after: float | None = None) -> None:
        """
        Record a rate limit hit and adapt throttling.

        Args:
            retry_after: Server-provided retry-after value in seconds
        """
        if not self.config.throttle_enabled:
            return

        with self._lock:
            self._consecutive_rate_limits += 1
            self._last_rate_limit_time = time.time()

            # Reduce throttle factor with each consecutive rate limit
            # Each rate limit halves the factor (but not below min_factor)
            new_factor = self._throttle_factor * 0.5
            min_factor = self.config.throttle_min_factor
            self._throttle_factor = max(new_factor, min_factor)

            logger.warning(
                "Rate limit hit (%d consecutive). Throttle reduced to %.0f%% of RPM.%s",
                self._consecutive_rate_limits,
                self._throttle_factor * 100,
                f" Server suggests retry after {retry_after:.1f}s" if retry_after else "",
            )

    def _check_circuit(self) -> None:
        """
        Check circuit breaker state and raise if open.

        Raises:
            CircuitOpenError: If circuit is open and not ready for testing
        """
        if not self.config.circuit_breaker_enabled:
            return

        with self._lock:
            if self._circuit_state == CircuitState.CLOSED:
                return

            now = time.time()

            if self._circuit_state == CircuitState.OPEN:
                # Check if enough time has passed to try half-open
                elapsed = now - self._circuit_opened_at
                if elapsed >= self.config.circuit_recovery_time:
                    self._circuit_state = CircuitState.HALF_OPEN
                    logger.info(
                        "Circuit breaker entering half-open state after %.1fs",
                        elapsed,
                    )
                    return  # Allow one test request
                else:
                    remaining = self.config.circuit_recovery_time - elapsed
                    raise CircuitOpenError(
                        f"Circuit breaker is open. Retry in {remaining:.1f}s",
                        context={"retry_after": remaining},
                    )

            # HALF_OPEN state allows requests through for testing
            return

    def _try_throttle_recovery(self) -> None:
        """
        Try to recover throttle factor if enough time has passed.

        Gradually increases throttle factor back towards 1.0.
        """
        if not self.config.throttle_enabled:
            return

        if self._throttle_factor >= 1.0:
            return

        with self._lock:
            now = time.time()
            time_since_rate_limit = now - self._last_rate_limit_time
            time_since_recovery = now - self._last_throttle_recovery

            # Only try recovery if enough time has passed since last rate limit
            # and since last recovery attempt
            if time_since_rate_limit >= self.config.throttle_recovery_time and time_since_recovery >= self.config.throttle_recovery_time:
                # Increase throttle by 25% (multiplicative recovery)
                old_factor = self._throttle_factor
                self._throttle_factor = min(self._throttle_factor * 1.25, 1.0)
                self._last_throttle_recovery = now
                self._consecutive_rate_limits = 0

                if self._throttle_factor != old_factor:
                    logger.info(
                        "Throttle recovering: %.0f%% -> %.0f%% of RPM",
                        old_factor * 100,
                        self._throttle_factor * 100,
                    )

    def get_effective_rpm(self) -> int:
        """
        Get the current effective RPM after applying throttle factor.

        Returns:
            Effective requests per minute (may be lower than configured)
        """
        if self.config.requests_per_minute <= 0:
            return 0

        with self._lock:
            return max(1, int(self.config.requests_per_minute * self._throttle_factor))

    def is_circuit_open(self) -> bool:
        """Check if the circuit breaker is currently open."""
        with self._lock:
            return self._circuit_state == CircuitState.OPEN

    def get_circuit_state(self) -> str:
        """Get the current circuit breaker state as a string."""
        with self._lock:
            return self._circuit_state.value

    def reset(self) -> None:
        """Reset all state (useful for testing or manual recovery)."""
        with self._lock:
            self._consecutive_rate_limits = 0
            self._throttle_factor = 1.0
            self._last_rate_limit_time = 0.0
            self._last_throttle_recovery = 0.0
            self._circuit_state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._circuit_opened_at = 0.0
            self._request_times.clear()
            logger.info("Rate limiter state reset")

    def get_stats(self) -> dict[str, float | int | str]:
        """Get current rate limiter statistics including throttle and circuit state."""
        with self._lock:
            now = time.time()
            cutoff = now - 60.0
            # Clean expired entries first (using efficient popleft)
            while self._request_times and self._request_times[0] <= cutoff:
                self._request_times.popleft()
            recent_requests = len(self._request_times)

            effective_rpm = max(1, int(self.config.requests_per_minute * self._throttle_factor)) if self.config.requests_per_minute > 0 else 0

            return {
                # Basic stats
                "requests_last_minute": recent_requests,
                "rpm_limit": self.config.requests_per_minute,
                "effective_rpm": effective_rpm,
                "successful_requests": self._successful_requests,
                "min_request_delay": self.config.min_request_delay,
                # Throttle stats
                "throttle_factor": self._throttle_factor,
                "consecutive_rate_limits": self._consecutive_rate_limits,
                # Circuit breaker stats
                "circuit_state": self._circuit_state.value,
                "consecutive_failures": self._consecutive_failures,
            }


def get_default_rate_limit(provider: str) -> int:
    """Get the default rate limit for a provider."""
    return DEFAULT_RATE_LIMITS.get(provider.lower(), 60)


def parse_retry_after(headers: dict[str, str] | None) -> float | None:
    """
    Parse the retry-after header from API response headers.

    Handles both integer seconds and HTTP-date formats.
    Checks common header name variations used by different providers.

    Args:
        headers: Response headers dict (case-insensitive lookup)

    Returns:
        Retry-after value in seconds, or None if not found/invalid
    """
    if not headers:
        return None

    # Normalize header names to lowercase for case-insensitive lookup
    normalized = {k.lower(): v for k, v in headers.items()}

    # Check common header names (all lowercase)
    header_names = ["retry-after", "x-retry-after", "x-ratelimit-reset"]

    for name in header_names:
        value = normalized.get(name)
        if value:
            try:
                # Try parsing as integer seconds
                return float(value)
            except ValueError:
                # Could be HTTP-date format, but we only support seconds for simplicity
                logger.debug("Could not parse retry-after value: %s", value)
                continue

    return None


__all__ = [
    "CircuitState",
    "RateLimitConfig",
    "RateLimiter",
    "get_default_rate_limit",
    "parse_retry_after",
    "DEFAULT_RATE_LIMITS",
]
