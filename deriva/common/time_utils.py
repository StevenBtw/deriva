"""Time utilities for Deriva.

Provides consistent timestamp formatting across the application.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["current_timestamp", "calculate_duration_ms"]


def current_timestamp() -> str:
    """Get current UTC timestamp in ISO format.

    Returns:
        ISO 8601 formatted timestamp with 'Z' suffix (e.g., '2024-01-15T10:30:00.123456Z')
    """
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def calculate_duration_ms(start_time: datetime) -> int:
    """Calculate duration in milliseconds from start time to now.

    Args:
        start_time: Start datetime (should be UTC-aware)

    Returns:
        Duration in milliseconds
    """
    delta = datetime.now(UTC) - start_time
    return int(delta.total_seconds() * 1000)
