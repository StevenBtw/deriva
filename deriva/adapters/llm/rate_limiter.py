"""
Rate limiter for LLM API requests.

Implements token bucket algorithm with support for:
- Requests per minute (RPM) limits
- Minimum delay between requests
- Exponential backoff on rate limit errors
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# Default rate limits by provider (requests per minute)
# These are conservative defaults - actual limits vary by tier/plan
DEFAULT_RATE_LIMITS: dict[str, int] = {
    "azure": 60,  # Azure OpenAI: varies by deployment
    "openai": 60,  # OpenAI: varies by tier (60-10000 RPM)
    "anthropic": 60,  # Anthropic: varies by tier
    "mistral": 60,  # Mistral: varies by tier
    "ollama": 0,  # Local - no limit
    "lmstudio": 0,  # Local - no limit
    "claudecode": 30,  # Conservative for CLI-based calls
}


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    requests_per_minute: int = 60  # 0 = no limit
    min_request_delay: float = 0.0  # Minimum seconds between requests
    backoff_base: float = 2.0  # Base for exponential backoff
    backoff_max: float = 60.0  # Maximum backoff delay in seconds
    backoff_jitter: float = 0.1  # Jitter factor (0-1) for randomization


@dataclass
class RateLimiter:
    """
    Token bucket rate limiter with exponential backoff support.

    Thread-safe implementation that tracks request timestamps and
    enforces rate limits across concurrent calls.
    """

    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _request_times: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _consecutive_rate_limits: int = field(default=0)
    _last_request_time: float = field(default=0.0)

    def wait_if_needed(self) -> float:
        """
        Wait if necessary to respect rate limits.

        Returns:
            float: Actual wait time in seconds (0 if no wait needed)
        """
        if self.config.requests_per_minute <= 0 and self.config.min_request_delay <= 0:
            return 0.0

        with self._lock:
            now = time.time()
            wait_time = 0.0

            # Check minimum delay between requests
            if self.config.min_request_delay > 0 and self._last_request_time > 0:
                elapsed = now - self._last_request_time
                if elapsed < self.config.min_request_delay:
                    wait_time = max(wait_time, self.config.min_request_delay - elapsed)

            # Check RPM limit
            if self.config.requests_per_minute > 0:
                # Clean up old timestamps (older than 1 minute)
                cutoff = now - 60.0
                self._request_times = [t for t in self._request_times if t > cutoff]

                # If at limit, wait until oldest request expires
                if len(self._request_times) >= self.config.requests_per_minute:
                    oldest = min(self._request_times)
                    wait_until = oldest + 60.0
                    wait_time = max(wait_time, wait_until - now)

            # Apply wait if needed
            if wait_time > 0:
                logger.debug("Rate limiting: waiting %.2fs", wait_time)
                # Release lock during sleep
                self._lock.release()
                try:
                    time.sleep(wait_time)
                finally:
                    self._lock.acquire()
                now = time.time()

            # Record this request
            self._request_times.append(now)
            self._last_request_time = now

            return wait_time

    def record_success(self) -> None:
        """Record a successful request, resetting backoff counter."""
        with self._lock:
            self._consecutive_rate_limits = 0

    def record_rate_limit(self) -> float:
        """
        Record a rate limit error and calculate backoff delay.

        Returns:
            float: Recommended wait time before retry
        """
        import random

        with self._lock:
            self._consecutive_rate_limits += 1

            # Calculate exponential backoff with jitter
            delay = min(
                self.config.backoff_base**self._consecutive_rate_limits,
                self.config.backoff_max,
            )

            # Add jitter to prevent thundering herd
            if self.config.backoff_jitter > 0:
                jitter = delay * self.config.backoff_jitter * random.random()
                delay += jitter

            logger.warning(
                "Rate limit hit (attempt %d), backing off %.2fs",
                self._consecutive_rate_limits,
                delay,
            )

            return delay

    def get_stats(self) -> dict[str, float | int]:
        """Get current rate limiter statistics."""
        with self._lock:
            now = time.time()
            cutoff = now - 60.0
            recent_requests = len([t for t in self._request_times if t > cutoff])

            return {
                "requests_last_minute": recent_requests,
                "rpm_limit": self.config.requests_per_minute,
                "consecutive_rate_limits": self._consecutive_rate_limits,
                "min_request_delay": self.config.min_request_delay,
            }


def get_default_rate_limit(provider: str) -> int:
    """Get the default rate limit for a provider."""
    return DEFAULT_RATE_LIMITS.get(provider.lower(), 60)
