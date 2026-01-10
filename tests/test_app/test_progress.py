"""Tests for app.progress module."""

from __future__ import annotations

from datetime import datetime, timedelta

from deriva.app.progress import (
    MarimoBenchmarkProgressReporter,
    MarimoProgressReporter,
    ProgressEvent,
    ProgressState,
    create_marimo_benchmark_progress_reporter,
    create_marimo_progress_reporter,
)


class TestProgressState:
    """Tests for ProgressState dataclass."""

    def test_elapsed_seconds_zero_when_no_start(self):
        """Should return 0 when no start time."""
        state = ProgressState()
        assert state.elapsed_seconds == 0.0

    def test_elapsed_seconds_calculates_duration(self):
        """Should calculate elapsed time from start."""
        state = ProgressState()
        state.start_time = datetime.now() - timedelta(seconds=5)
        assert 4.5 < state.elapsed_seconds < 6.0

    def test_elapsed_seconds_uses_end_time_if_set(self):
        """Should use end_time if available."""
        state = ProgressState()
        state.start_time = datetime(2024, 1, 1, 12, 0, 0)
        state.end_time = datetime(2024, 1, 1, 12, 0, 10)
        assert state.elapsed_seconds == 10.0

    def test_phase_count_counts_phase_end_events(self):
        """Should count phase_end events."""
        state = ProgressState()
        state.events = [
            ProgressEvent(datetime.now(), "phase_start", "p1"),
            ProgressEvent(datetime.now(), "phase_end", "p1"),
            ProgressEvent(datetime.now(), "phase_start", "p2"),
            ProgressEvent(datetime.now(), "phase_end", "p2"),
        ]
        assert state.phase_count == 2

    def test_step_count_counts_step_end_events(self):
        """Should count step_end events."""
        state = ProgressState()
        state.events = [
            ProgressEvent(datetime.now(), "step_start", "s1"),
            ProgressEvent(datetime.now(), "step_end", "s1"),
            ProgressEvent(datetime.now(), "step_end", "s2"),
        ]
        assert state.step_count == 2


class TestMarimoProgressReporter:
    """Tests for MarimoProgressReporter class."""

    def test_start_phase_sets_state(self):
        """Should set phase name and status."""
        reporter = MarimoProgressReporter()
        reporter.start_phase("extraction", 5)

        assert reporter.state.phase == "extraction"
        assert reporter.state.total == 5
        assert reporter.state.current == 0
        assert reporter.state.status == "running"
        assert reporter.state.start_time is not None

    def test_start_step_records_step(self):
        """Should record step in events."""
        reporter = MarimoProgressReporter()
        reporter.start_step("process_files", 100)

        assert reporter.state.step == "process_files"
        assert len(reporter.state.events) == 1
        assert reporter.state.events[0].event_type == "step_start"

    def test_update_sets_current_and_message(self):
        """Should update current progress and message."""
        reporter = MarimoProgressReporter()
        reporter.update(current=50, message="Processing...")

        assert reporter.state.current == 50
        assert reporter.state.message == "Processing..."

    def test_advance_increments_current(self):
        """Should increment current by amount."""
        reporter = MarimoProgressReporter()
        reporter.state.current = 5
        reporter.advance(3)

        assert reporter.state.current == 8

    def test_complete_step_records_event(self):
        """Should record step completion."""
        reporter = MarimoProgressReporter()
        reporter.start_step("test_step")
        reporter.complete_step("Done")

        assert reporter.state.step == ""
        events = [e for e in reporter.state.events if e.event_type == "step_end"]
        assert len(events) == 1
        assert events[0].message == "Done"

    def test_complete_phase_sets_complete_status(self):
        """Should mark phase complete and set end time."""
        reporter = MarimoProgressReporter()
        reporter.start_phase("test", 1)
        reporter.complete_phase()

        assert reporter.state.status == "complete"
        assert reporter.state.end_time is not None
        assert reporter.state.phase == ""

    def test_log_records_message(self):
        """Should record log message with level."""
        reporter = MarimoProgressReporter()
        reporter.log("Error occurred", level="error")

        logs = [e for e in reporter.state.events if e.event_type == "log"]
        assert len(logs) == 1
        assert logs[0].message == "Error occurred"
        assert logs[0].level == "error"

    def test_get_summary_returns_stats(self):
        """Should return comprehensive summary."""
        reporter = MarimoProgressReporter()
        reporter.start_phase("phase1", 2)
        reporter.start_step("step1")
        reporter.complete_step("done")
        reporter.complete_phase()

        summary = reporter.get_summary()

        assert summary["status"] == "complete"
        assert summary["phases_completed"] == 1
        assert summary["steps_completed"] == 1
        assert "elapsed_seconds" in summary

    def test_context_manager_sets_times(self):
        """Should set start and end times when used as context manager."""
        with MarimoProgressReporter() as reporter:
            assert reporter.state.status == "running"
            assert reporter.state.start_time is not None

        assert reporter.state.status == "complete"
        assert reporter.state.end_time is not None


class TestMarimoBenchmarkProgressReporter:
    """Tests for MarimoBenchmarkProgressReporter class."""

    def test_start_benchmark_initializes_session(self):
        """Should initialize benchmark session."""
        reporter = MarimoBenchmarkProgressReporter()
        reporter.start_benchmark(
            session_id="bench-1",
            total_runs=10,
            repositories=["repo1"],
            models=["model1"],
        )

        assert reporter.session_id == "bench-1"
        assert reporter.total_runs == 10
        assert reporter.state.status == "running"

    def test_complete_run_tracks_success(self):
        """Should track successful runs."""
        reporter = MarimoBenchmarkProgressReporter()
        reporter.start_run(1, "repo", "model", 1)
        reporter.complete_run("success", {"time": 10})

        assert reporter.runs_completed == 1
        assert reporter.runs_failed == 0
        assert len(reporter.run_results) == 1

    def test_complete_run_tracks_failure(self):
        """Should track failed runs."""
        reporter = MarimoBenchmarkProgressReporter()
        reporter.start_run(1, "repo", "model", 1)
        reporter.complete_run("failed")

        assert reporter.runs_completed == 0
        assert reporter.runs_failed == 1

    def test_get_summary_includes_benchmark_data(self):
        """Should include benchmark-specific data in summary."""
        reporter = MarimoBenchmarkProgressReporter()
        reporter.session_id = "test-session"
        reporter.total_runs = 5

        summary = reporter.get_summary()

        assert summary["session_id"] == "test-session"
        assert summary["total_runs"] == 5


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_marimo_progress_reporter(self):
        """Should create MarimoProgressReporter instance."""
        reporter = create_marimo_progress_reporter()
        assert isinstance(reporter, MarimoProgressReporter)

    def test_create_marimo_benchmark_progress_reporter(self):
        """Should create MarimoBenchmarkProgressReporter instance."""
        reporter = create_marimo_benchmark_progress_reporter()
        assert isinstance(reporter, MarimoBenchmarkProgressReporter)
