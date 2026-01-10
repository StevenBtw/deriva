"""Tests for cli.progress module."""

from __future__ import annotations

from deriva.cli.progress import (
    QuietBenchmarkProgressReporter,
    QuietProgressReporter,
    create_benchmark_progress_reporter,
    create_progress_reporter,
)


class TestQuietProgressReporter:
    """Tests for QuietProgressReporter - no-op implementation."""

    def test_start_phase_does_nothing(self):
        """Methods should be no-ops."""
        reporter = QuietProgressReporter()
        reporter.start_phase("test", 5)  # Should not raise

    def test_start_step_does_nothing(self):
        """Should accept parameters without error."""
        reporter = QuietProgressReporter()
        reporter.start_step("test", 100)

    def test_update_does_nothing(self):
        """Should accept update parameters."""
        reporter = QuietProgressReporter()
        reporter.update(current=50, message="test")

    def test_advance_does_nothing(self):
        """Should accept advance amount."""
        reporter = QuietProgressReporter()
        reporter.advance(5)

    def test_complete_step_does_nothing(self):
        """Should accept completion."""
        reporter = QuietProgressReporter()
        reporter.complete_step("done")

    def test_context_manager_returns_self(self):
        """Should work as context manager."""
        reporter = QuietProgressReporter()
        with reporter as r:
            assert r is reporter


class TestQuietBenchmarkProgressReporter:
    """Tests for QuietBenchmarkProgressReporter."""

    def test_inherits_from_quiet_reporter(self):
        """Should inherit from QuietProgressReporter."""
        reporter = QuietBenchmarkProgressReporter()
        assert isinstance(reporter, QuietProgressReporter)

    def test_start_benchmark_does_nothing(self):
        """Benchmark methods should be no-ops."""
        reporter = QuietBenchmarkProgressReporter()
        reporter.start_benchmark("session-1", 10, ["repo1"], ["model1"])

    def test_start_run_does_nothing(self):
        """Should accept run parameters."""
        reporter = QuietBenchmarkProgressReporter()
        reporter.start_run(1, "repo", "model", 1)

    def test_complete_run_does_nothing(self):
        """Should accept completion."""
        reporter = QuietBenchmarkProgressReporter()
        reporter.complete_run("success", {"time": 10})

    def test_complete_benchmark_does_nothing(self):
        """Should accept benchmark completion."""
        reporter = QuietBenchmarkProgressReporter()
        reporter.complete_benchmark(10, 0, 100.0)


class TestQuietProgressReporterAdditional:
    """Additional tests for QuietProgressReporter."""

    def test_complete_phase_does_nothing(self):
        """Should accept phase completion."""
        reporter = QuietProgressReporter()
        reporter.complete_phase("phase done")

    def test_log_does_nothing(self):
        """Should accept log messages at all levels."""
        reporter = QuietProgressReporter()
        reporter.log("info message", level="info")
        reporter.log("error message", level="error")
        reporter.log("warning message", level="warning")


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_progress_reporter_quiet_mode(self):
        """Should return QuietProgressReporter when quiet=True."""
        reporter = create_progress_reporter(quiet=True)
        assert isinstance(reporter, QuietProgressReporter)

    def test_create_benchmark_progress_reporter_quiet_mode(self):
        """Should return QuietBenchmarkProgressReporter when quiet=True."""
        reporter = create_benchmark_progress_reporter(quiet=True)
        assert isinstance(reporter, QuietBenchmarkProgressReporter)

    def test_create_progress_reporter_returns_reporter(self):
        """Should return a progress reporter instance."""
        reporter = create_progress_reporter()
        # Should have the progress reporter interface
        assert hasattr(reporter, "start_phase")
        assert hasattr(reporter, "start_step")
        assert hasattr(reporter, "update")

    def test_create_benchmark_reporter_returns_reporter(self):
        """Should return a benchmark reporter instance."""
        reporter = create_benchmark_progress_reporter()
        # Should have the benchmark reporter interface
        assert hasattr(reporter, "start_benchmark")
        assert hasattr(reporter, "start_run")
        assert hasattr(reporter, "complete_run")


# Test Rich reporters when available
from deriva.cli.progress import RICH_AVAILABLE

if RICH_AVAILABLE:
    from deriva.cli.progress import (
        RichBenchmarkProgressReporter,
        RichProgressReporter,
    )

    class TestRichProgressReporter:
        """Tests for RichProgressReporter class."""

        def test_context_manager_starts_and_stops(self):
            """Should start and stop progress display."""
            reporter = RichProgressReporter()
            with reporter:
                assert reporter._progress is not None
                assert reporter._live is not None
            assert reporter._progress is None
            assert reporter._live is None

        def test_start_phase_without_context_does_nothing(self):
            """Should not raise when called outside context."""
            reporter = RichProgressReporter()
            reporter.start_phase("test", 10)  # Should not raise

        def test_start_phase_creates_task(self):
            """Should create phase task."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("extraction", 5)
                assert reporter._phase_task is not None
                assert reporter._current_phase == "extraction"

        def test_start_step_creates_task(self):
            """Should create step task."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("processing files", 100)
                assert reporter._step_task is not None
                assert reporter._current_step == "processing files"

        def test_start_step_indeterminate(self):
            """Should handle indeterminate progress (None total)."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("connecting", None)
                assert reporter._step_task is not None

        def test_start_step_zero_items(self):
            """Should handle zero items (indeterminate)."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("waiting", 0)
                assert reporter._step_task is not None

        def test_update_modifies_task(self):
            """Should update progress."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("processing", 100)
                reporter.update(50, "half done")

        def test_update_truncates_long_message(self):
            """Should truncate long messages."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("processing", 100)
                long_msg = "a" * 100
                reporter.update(50, long_msg)

        def test_update_without_step_task(self):
            """Should not raise when no step task."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.update(50, "no task")

        def test_advance_increments_progress(self):
            """Should advance progress."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("processing", 100)
                reporter.advance(10)

        def test_advance_without_step_task(self):
            """Should not raise when no step task."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.advance(5)

        def test_complete_step_removes_task(self):
            """Should remove step task on completion."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("phase", 1)
                reporter.start_step("step", 10)
                reporter.complete_step()
                assert reporter._step_task is None

        def test_complete_step_advances_phase(self):
            """Should advance phase task on step completion."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("phase", 2)
                reporter.start_step("step1", 10)
                reporter.complete_step()

        def test_complete_phase(self):
            """Should complete phase."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("phase", 1)
                reporter.complete_phase("done")

        def test_complete_phase_with_message(self, capsys):
            """Should print completion message."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("phase", 1)
                reporter.complete_phase("Phase completed successfully")

        def test_log_info(self):
            """Should log info message."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.log("info message", level="info")

        def test_log_error(self):
            """Should log error message."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.log("error message", level="error")

        def test_log_warning(self):
            """Should log warning message."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.log("warning message", level="warning")

        def test_replace_old_phase_task(self):
            """Should replace old phase task when starting new phase."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_phase("phase1", 2)
                old_task = reporter._phase_task
                reporter.start_phase("phase2", 3)
                assert reporter._phase_task != old_task

        def test_replace_old_step_task(self):
            """Should replace old step task when starting new step."""
            reporter = RichProgressReporter()
            with reporter:
                reporter.start_step("step1", 10)
                old_task = reporter._step_task
                reporter.start_step("step2", 20)
                assert reporter._step_task != old_task

    class TestRichBenchmarkProgressReporter:
        """Tests for RichBenchmarkProgressReporter class."""

        def test_context_manager_starts_and_stops(self):
            """Should start and stop display."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                assert reporter._progress is not None
                assert reporter._live is not None
            assert reporter._progress is None
            assert reporter._live is None

        def test_start_benchmark_sets_context(self):
            """Should set benchmark context."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark(
                    session_id="bench_123",
                    total_runs=10,
                    repositories=["repo1", "repo2"],
                    models=["gpt4", "claude"],
                )
                assert reporter._session_id == "bench_123"
                assert reporter._total_runs == 10
                assert reporter._repositories == ["repo1", "repo2"]
                assert reporter._models == ["gpt4", "claude"]
                assert reporter._benchmark_task is not None

        def test_start_run_sets_context(self):
            """Should set run context."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_run(
                    run_number=1,
                    repository="repo1",
                    model="gpt4",
                    iteration=1,
                )
                assert reporter._current_run == 1
                assert reporter._current_repo == "repo1"
                assert reporter._current_model == "gpt4"
                assert reporter._current_iteration == 1

        def test_complete_run_advances_benchmark_task(self):
            """Should advance benchmark progress."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.complete_run("success")

        def test_complete_run_clears_tasks(self):
            """Should clear phase and step tasks on run completion."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_phase("extraction", 2)
                reporter.start_step("step1", 10)
                reporter.complete_run("success")
                assert reporter._phase_task is None
                assert reporter._step_task is None

        def test_complete_benchmark_prints_success(self, capsys):
            """Should print success message."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.complete_benchmark(
                    runs_completed=2,
                    runs_failed=0,
                    duration_seconds=60.0,
                )

        def test_complete_benchmark_prints_failures(self, capsys):
            """Should print failure summary."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.complete_benchmark(
                    runs_completed=1,
                    runs_failed=1,
                    duration_seconds=60.0,
                )

        def test_start_phase_in_benchmark(self):
            """Should create phase task within benchmark."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_phase("extraction", 3)
                assert reporter._phase_task is not None
                assert reporter._current_phase == "extraction"

        def test_start_step_in_benchmark(self):
            """Should create step task within benchmark."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_step("processing", 10)
                assert reporter._step_task is not None

        def test_start_step_indeterminate_in_benchmark(self):
            """Should handle indeterminate step."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_step("connecting", None)
                assert reporter._step_task is not None

        def test_update_in_benchmark(self):
            """Should update step progress."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_step("processing", 10)
                reporter.update(5, "halfway")

        def test_update_truncates_long_message(self):
            """Should truncate long messages in update."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_step("processing", 10)
                reporter.update(5, "a" * 50)

        def test_advance_in_benchmark(self):
            """Should advance step progress."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_step("processing", 10)
                reporter.advance(2)

        def test_complete_step_in_benchmark(self):
            """Should complete step and advance phase."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_phase("extraction", 2)
                reporter.start_step("step1", 5)
                reporter.complete_step()
                assert reporter._step_task is None

        def test_complete_phase_in_benchmark(self):
            """Should complete phase."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("s1", 2, ["r"], ["m"])
                reporter.start_phase("extraction", 2)
                reporter.complete_phase()

        def test_log_in_benchmark(self):
            """Should log messages at all levels."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.log("info", level="info")
                reporter.log("error", level="error")
                reporter.log("warning", level="warning")

        def test_create_display_without_context(self):
            """Should handle display creation without context."""
            reporter = RichBenchmarkProgressReporter()
            # _create_display is called during __enter__
            with reporter:
                pass

        def test_create_display_with_all_context(self):
            """Should create display with full context."""
            reporter = RichBenchmarkProgressReporter()
            with reporter:
                reporter.start_benchmark("session_123", 10, ["repo1"], ["model1"])
                reporter.start_run(1, "repo1", "model1", 1)
