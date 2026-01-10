"""Tests for app.app module - minimal smoke tests for Marimo app."""

from __future__ import annotations


class TestAppModuleImports:
    """Test that app module components can be imported."""

    def test_progress_reporter_imports(self):
        """Should import progress reporter from app module."""
        from deriva.app.progress import MarimoProgressReporter

        assert MarimoProgressReporter is not None

    def test_benchmark_reporter_imports(self):
        """Should import benchmark reporter from app module."""
        from deriva.app.progress import MarimoBenchmarkProgressReporter

        assert MarimoBenchmarkProgressReporter is not None
