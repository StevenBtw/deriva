"""Tests for common.time_utils module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from deriva.common.time_utils import calculate_duration_ms, current_timestamp


class TestCurrentTimestamp:
    """Tests for current_timestamp function."""

    def test_returns_iso_format(self):
        """Should return ISO 8601 formatted string."""
        ts = current_timestamp()

        # Should be parseable as datetime
        assert isinstance(ts, str)
        assert "T" in ts  # ISO format separator

    def test_ends_with_z(self):
        """Should end with Z suffix for UTC."""
        ts = current_timestamp()
        assert ts.endswith("Z")

    def test_does_not_contain_plus_offset(self):
        """Should not contain +00:00 offset."""
        ts = current_timestamp()
        assert "+00:00" not in ts


class TestCalculateDurationMs:
    """Tests for calculate_duration_ms function."""

    def test_calculates_positive_duration(self):
        """Should calculate positive duration in ms."""
        start = datetime.now(UTC) - timedelta(seconds=1)
        duration = calculate_duration_ms(start)

        assert duration >= 1000  # At least 1 second
        assert duration < 2000  # Less than 2 seconds

    def test_returns_integer(self):
        """Should return integer milliseconds."""
        start = datetime.now(UTC)
        duration = calculate_duration_ms(start)

        assert isinstance(duration, int)

    def test_handles_small_durations(self):
        """Should handle very small durations."""
        start = datetime.now(UTC)
        duration = calculate_duration_ms(start)

        # Should be close to 0 but non-negative
        assert duration >= 0
        assert duration < 100  # Less than 100ms
