"""Tests for common.logging module."""

from __future__ import annotations

import json
import logging
import tempfile

import pytest

from deriva.common.logging import (
    LogEntry,
    LogLevel,
    LogStatus,
    RunLogger,
    RunLoggerHandler,
    get_logger_for_active_run,
    read_run_logs,
    setup_logging_bridge,
    teardown_logging_bridge,
)


class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_phase_is_level_1(self):
        """Phase should be level 1."""
        assert LogLevel.PHASE == 1

    def test_step_is_level_2(self):
        """Step should be level 2."""
        assert LogLevel.STEP == 2

    def test_detail_is_level_3(self):
        """Detail should be level 3."""
        assert LogLevel.DETAIL == 3

    def test_levels_are_ordered(self):
        """Levels should be in increasing order."""
        assert LogLevel.PHASE < LogLevel.STEP < LogLevel.DETAIL


class TestLogStatus:
    """Tests for LogStatus enum."""

    def test_status_values(self):
        """Should have expected status values."""
        assert LogStatus.STARTED == "started"
        assert LogStatus.COMPLETED == "completed"
        assert LogStatus.ERROR == "error"
        assert LogStatus.SKIPPED == "skipped"


class TestLogEntry:
    """Tests for LogEntry dataclass."""

    def test_basic_entry(self):
        """Should create basic log entry."""
        entry = LogEntry(
            level=1,
            phase="extraction",
            status="started",
            timestamp="2024-01-15T10:30:00",
            message="Starting extraction",
        )

        assert entry.level == 1
        assert entry.phase == "extraction"
        assert entry.status == "started"
        assert entry.message == "Starting extraction"

    def test_entry_with_optional_fields(self):
        """Should create entry with optional fields."""
        entry = LogEntry(
            level=2,
            phase="extraction",
            status="completed",
            timestamp="2024-01-15T10:30:00",
            message="Step completed",
            step="TypeDefinition",
            sequence=1,
            duration_ms=500,
            items_processed=10,
            items_created=8,
            items_failed=2,
            stats={"total": 10},
        )

        assert entry.step == "TypeDefinition"
        assert entry.sequence == 1
        assert entry.duration_ms == 500
        assert entry.items_processed == 10
        assert entry.items_created == 8
        assert entry.items_failed == 2
        assert entry.stats == {"total": 10}

    def test_entry_with_error(self):
        """Should create entry with error field."""
        entry = LogEntry(
            level=2,
            phase="extraction",
            status="error",
            timestamp="2024-01-15T10:30:00",
            message="Step failed",
            error="Connection refused",
        )

        assert entry.error == "Connection refused"

    def test_to_dict_excludes_none(self):
        """Should exclude None values from dictionary."""
        entry = LogEntry(
            level=1,
            phase="extraction",
            status="started",
            timestamp="2024-01-15T10:30:00",
            message="Test",
        )

        d = entry.to_dict()

        assert "step" not in d
        assert "sequence" not in d
        assert "error" not in d
        assert d["level"] == 1
        assert d["phase"] == "extraction"

    def test_to_json(self):
        """Should convert to valid JSON string."""
        entry = LogEntry(
            level=1,
            phase="extraction",
            status="started",
            timestamp="2024-01-15T10:30:00",
            message="Test",
        )

        json_str = entry.to_json()
        parsed = json.loads(json_str)

        assert parsed["level"] == 1
        assert parsed["phase"] == "extraction"


class TestRunLogger:
    """Tests for RunLogger class."""

    def test_creates_log_directory(self):
        """Should create log directory for run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=123, logs_dir=tmpdir)

            assert logger.run_dir.exists()
            assert logger.run_dir.name == "run_123"

    def test_creates_log_file(self):
        """Should create log file with timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            # Log file is created on first write
            logger.phase_start("extraction", "Starting extraction")

            assert logger.log_file.exists()
            assert logger.log_file.suffix == ".jsonl"
            assert "log_" in logger.log_file.name

    def test_phase_start(self):
        """Should log phase start."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction", "Starting extraction")

            with open(logger.log_file) as f:
                entry = json.loads(f.readline())

            assert entry["level"] == LogLevel.PHASE
            assert entry["phase"] == "extraction"
            assert entry["status"] == LogStatus.STARTED
            assert entry["message"] == "Starting extraction"

    def test_phase_complete(self):
        """Should log phase completion with duration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.phase_complete("extraction", "Done", stats={"nodes": 10})

            with open(logger.log_file) as f:
                lines = f.readlines()

            complete_entry = json.loads(lines[-1])
            assert complete_entry["status"] == LogStatus.COMPLETED
            assert complete_entry["phase"] == "extraction"
            assert complete_entry["stats"]["nodes"] == 10
            assert "duration_ms" in complete_entry

    def test_phase_error(self):
        """Should log phase error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.phase_error("extraction", "Connection failed", "Extraction failed")

            with open(logger.log_file) as f:
                lines = f.readlines()

            error_entry = json.loads(lines[-1])
            assert error_entry["status"] == LogStatus.ERROR
            assert error_entry["error"] == "Connection failed"

    def test_step_start(self):
        """Should log step start within phase."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_start("TypeDefinition", "Extracting types")

            with open(logger.log_file) as f:
                lines = f.readlines()

            step_entry = json.loads(lines[-1])
            assert step_entry["level"] == LogLevel.STEP
            assert step_entry["step"] == "TypeDefinition"
            assert step_entry["status"] == LogStatus.STARTED

    def test_step_complete(self):
        """Should log step completion with stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_complete(
                step="TypeDefinition",
                sequence=1,
                message="Done",
                items_processed=100,
                items_created=50,
                items_failed=2,
                duration_ms=1500,
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            step_entry = json.loads(lines[-1])
            assert step_entry["status"] == LogStatus.COMPLETED
            assert step_entry["items_processed"] == 100
            assert step_entry["items_created"] == 50
            assert step_entry["items_failed"] == 2
            assert step_entry["duration_ms"] == 1500

    def test_step_error(self):
        """Should log step error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_error("TypeDefinition", 1, "Parse error", "Failed to parse")

            with open(logger.log_file) as f:
                lines = f.readlines()

            step_entry = json.loads(lines[-1])
            assert step_entry["status"] == LogStatus.ERROR
            assert step_entry["error"] == "Parse error"

    def test_step_skipped(self):
        """Should log skipped step."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_skipped("TypeDefinition", "No matching files")

            with open(logger.log_file) as f:
                lines = f.readlines()

            step_entry = json.loads(lines[-1])
            assert step_entry["status"] == LogStatus.SKIPPED
            assert "No matching files" in step_entry["message"]

    def test_detail_file_classified(self):
        """Should log file classification detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("classification")
            logger.detail_file_classified(
                file_path="src/main.py",
                file_type="source",
                subtype="python",
                extension=".py",
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["level"] == LogLevel.DETAIL
            assert detail_entry["stats"]["file_path"] == "src/main.py"
            assert detail_entry["stats"]["file_type"] == "source"

    def test_detail_file_unclassified(self):
        """Should log unclassified file detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("classification")
            logger.detail_file_unclassified("file.xyz", ".xyz")

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["status"] == LogStatus.SKIPPED
            assert detail_entry["stats"]["extension"] == ".xyz"

    def test_detail_extraction(self):
        """Should log extraction detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.detail_extraction(
                file_path="src/main.py",
                node_type="BusinessConcept",
                prompt="Extract concepts",
                response='{"concepts": []}',
                tokens_in=100,
                tokens_out=50,
                cache_used=True,
                concepts_extracted=3,
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["tokens_in"] == 100
            assert detail_entry["stats"]["cache_used"] is True

    def test_detail_node_created(self):
        """Should log node creation detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.detail_node_created(
                node_id="node-123",
                node_type="BusinessConcept",
                source_file="src/main.py",
                properties={"name": "MyService"},
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["node_id"] == "node-123"
            assert detail_entry["stats"]["properties"]["name"] == "MyService"

    def test_detail_edge_created(self):
        """Should log edge creation detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.detail_edge_created(
                edge_id="edge-1",
                relationship_type="CONTAINS",
                from_node="node-1",
                to_node="node-2",
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["relationship_type"] == "CONTAINS"
            assert detail_entry["stats"]["from_node"] == "node-1"

    def test_detail_node_deactivated(self):
        """Should log node deactivation detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("derivation")
            logger.detail_node_deactivated(
                node_id="node-123",
                node_type="Directory",
                reason="Low connectivity",
                algorithm="k-core",
                properties={"k_value": 2},
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["action"] == "deactivated"
            assert detail_entry["stats"]["algorithm"] == "k-core"

    def test_detail_edge_deactivated(self):
        """Should log edge deactivation detail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("derivation")
            logger.detail_edge_deactivated(
                edge_id="edge-1",
                relationship_type="CONTAINS",
                from_node="node-1",
                to_node="node-2",
                reason="Redundant edge",
                algorithm="redundant_edges",
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["action"] == "deactivated"

    def test_detail_element_created(self):
        """Should log ArchiMate element creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("derivation")
            logger.detail_element_created(
                element_id="elem-1",
                element_type="ApplicationComponent",
                name="Auth Service",
                source_node="node-123",
                confidence=0.95,
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["element_type"] == "ApplicationComponent"
            assert detail_entry["stats"]["confidence"] == 0.95

    def test_detail_relationship_created(self):
        """Should log ArchiMate relationship creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("derivation")
            logger.detail_relationship_created(
                relationship_id="rel-1",
                relationship_type="Composition",
                source_element="elem-1",
                target_element="elem-2",
                confidence=0.85,
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["stats"]["relationship_type"] == "Composition"

    def test_get_log_path(self):
        """Should return log file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            path = logger.get_log_path()

            assert path == logger.log_file

    def test_read_logs(self):
        """Should read all log entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_start("TypeDefinition")
            logger.phase_complete("extraction")

            entries = logger.read_logs()

            assert len(entries) == 3

    def test_read_logs_with_level_filter(self):
        """Should filter logs by level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_start("TypeDefinition")
            logger.phase_complete("extraction")

            phase_entries = logger.read_logs(level=LogLevel.PHASE)
            step_entries = logger.read_logs(level=LogLevel.STEP)

            assert len(phase_entries) == 2  # start + complete
            assert len(step_entries) == 1  # just the step start

    def test_read_logs_empty_file(self):
        """Should return empty list for non-existent log file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            entries = logger.read_logs()

            assert entries == []

    def test_multiple_phases(self):
        """Should handle multiple phases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.phase_start("derivation")

            with open(logger.log_file) as f:
                lines = f.readlines()

            assert len(lines) == 2
            phases = [json.loads(line)["phase"] for line in lines]
            assert "extraction" in phases
            assert "derivation" in phases


class TestStepContext:
    """Tests for StepContext context manager."""

    def test_context_manager_basic(self):
        """Should work as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with logger.step_start("TypeDefinition") as step:
                step.items_processed = 10
                step.items_created = 5

            entries = logger.read_logs()
            # phase start + step start + step complete
            assert len(entries) == 3

    def test_context_manager_auto_complete(self):
        """Should auto-complete step on exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with logger.step_start("TypeDefinition") as step:
                step.items_created = 5

            entries = logger.read_logs(level=LogLevel.STEP)
            completed = [e for e in entries if e["status"] == LogStatus.COMPLETED]
            assert len(completed) == 1
            assert completed[0]["items_created"] == 5

    def test_context_manager_error(self):
        """Should handle exception and log error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with pytest.raises(ValueError):
                with logger.step_start("TypeDefinition"):
                    raise ValueError("Test error")

            entries = logger.read_logs(level=LogLevel.STEP)
            error_entries = [e for e in entries if e["status"] == LogStatus.ERROR]
            assert len(error_entries) == 1
            assert "Test error" in error_entries[0]["error"]

    def test_context_manager_manual_complete(self):
        """Should allow manual completion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with logger.step_start("TypeDefinition") as step:
                step.complete("Manually completed")

            entries = logger.read_logs(level=LogLevel.STEP)
            completed = [e for e in entries if e["status"] == LogStatus.COMPLETED]
            assert len(completed) == 1

    def test_context_manager_manual_error(self):
        """Should allow manual error reporting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with logger.step_start("TypeDefinition") as step:
                step.error("Manual error")

            entries = logger.read_logs(level=LogLevel.STEP)
            error_entries = [e for e in entries if e["status"] == LogStatus.ERROR]
            assert len(error_entries) == 1


class TestRunLoggerHandler:
    """Tests for RunLoggerHandler logging bridge."""

    def test_handler_creation(self):
        """Should create handler with RunLogger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(run_id=1, logs_dir=tmpdir)
            handler = RunLoggerHandler(run_logger)

            assert handler.run_logger == run_logger

    def test_handler_forwards_warning(self):
        """Should forward warning logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(run_id=1, logs_dir=tmpdir)
            run_logger.phase_start("test")
            handler = RunLoggerHandler(run_logger, min_level=logging.WARNING)

            test_logger = logging.getLogger("test_handler")
            test_logger.addHandler(handler)
            test_logger.setLevel(logging.WARNING)

            test_logger.warning("Test warning message")

            test_logger.removeHandler(handler)

            entries = run_logger.read_logs(level=LogLevel.DETAIL)
            assert len(entries) >= 1
            assert any("Test warning message" in e.get("message", "") for e in entries)

    def test_handler_forwards_error(self):
        """Should forward error logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(run_id=1, logs_dir=tmpdir)
            run_logger.phase_start("test")
            handler = RunLoggerHandler(run_logger, min_level=logging.WARNING)

            test_logger = logging.getLogger("test_handler_error")
            test_logger.addHandler(handler)
            test_logger.setLevel(logging.ERROR)

            test_logger.error("Test error message")

            test_logger.removeHandler(handler)

            entries = run_logger.read_logs(level=LogLevel.DETAIL)
            error_entries = [e for e in entries if e.get("status") == LogStatus.ERROR]
            assert len(error_entries) >= 1


class TestLoggingBridge:
    """Tests for setup_logging_bridge and teardown_logging_bridge."""

    def test_setup_and_teardown(self):
        """Should setup and teardown logging bridge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(run_id=1, logs_dir=tmpdir)
            run_logger.phase_start("test")

            handler = setup_logging_bridge(run_logger)

            assert handler is not None
            assert isinstance(handler, RunLoggerHandler)

            teardown_logging_bridge(handler)

    def test_bridge_with_specific_loggers(self):
        """Should setup bridge for specific loggers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(run_id=1, logs_dir=tmpdir)
            run_logger.phase_start("test")

            handler = setup_logging_bridge(
                run_logger,
                logger_names=["my_specific_logger"],
            )

            teardown_logging_bridge(handler, logger_names=["my_specific_logger"])


class TestReadRunLogs:
    """Tests for read_run_logs function."""

    def test_reads_existing_logs(self):
        """Should read logs from existing run directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a run and write some logs
            logger = RunLogger(run_id=99, logs_dir=tmpdir)
            logger.phase_start("test")
            logger.phase_complete("test")

            # Read logs using the function
            entries = read_run_logs(run_id=99, logs_dir=tmpdir)

            assert len(entries) == 2

    def test_returns_empty_for_missing_run(self):
        """Should return empty list for non-existent run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = read_run_logs(run_id=999, logs_dir=tmpdir)

            assert entries == []

    def test_filters_by_level(self):
        """Should filter entries by level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=88, logs_dir=tmpdir)
            logger.phase_start("extraction")
            logger.step_start("TypeDefinition")
            logger.phase_complete("extraction")

            phase_entries = read_run_logs(run_id=88, logs_dir=tmpdir, level=LogLevel.PHASE)

            assert len(phase_entries) == 2  # start + complete


class TestGetLoggerForActiveRun:
    """Tests for get_logger_for_active_run function."""

    def test_returns_none_without_active_run(self):
        """Should return None when no active run."""
        from unittest.mock import MagicMock

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        result = get_logger_for_active_run(engine)

        assert result is None

    def test_returns_logger_for_active_run(self):
        """Should return logger when active run exists."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = MagicMock()
            engine.execute.return_value.fetchone.return_value = (42,)

            result = get_logger_for_active_run(engine, logs_dir=tmpdir)

            assert result is not None
            assert isinstance(result, RunLogger)
            assert result.run_id == 42
