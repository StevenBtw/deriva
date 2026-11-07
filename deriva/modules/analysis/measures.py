"""The convention every consistency measure follows for empty input.

Where there is nothing to compare (no object in any run, fewer than two runs), a measure is None: shown as n/a and
left out of every average, so an empty type never raises a score.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["mean_measured", "share_text"]


def mean_measured(values: Iterable[float | None]) -> float | None:
    """The average of the measured values (None ones left out); None when none is measured."""
    measured = [v for v in values if v is not None]
    return sum(measured) / len(measured) if measured else None


def share_text(value: float | None, spec: str = ".1%") -> str:
    """A measure as text in ``spec`` format, "n/a" when it is not measured."""
    return "n/a" if value is None else format(value, spec)
