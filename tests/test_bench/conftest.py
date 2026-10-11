"""Fixtures for the benchmark tests."""

from __future__ import annotations

import pytest

from tests.test_studio.conftest import make_client  # noqa: F401  (the benchmark API tests use the studio client)


@pytest.fixture(autouse=True)
def _benchmark_folders_in_a_temporary_home(monkeypatch, tmp_path):
    """Benchmark sessions, models and event logs go to a temporary home, never into the checkout's workspace."""
    monkeypatch.setenv("DERIVA_HOME", str(tmp_path / "home"))
