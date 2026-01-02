"""Tests for common.logging module."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from deriva.common.logging import (
    LogEntry,
    LogLevel,
    LogStatus,
    RunLogger,
    StepContext,
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
            logger.phase_complete(
                phase="extraction",
                message="Extraction complete",
                items_created=10,
                items_failed=2,
                stats={"nodes": 8},
            )

            with open(logger.log_file) as f:
                lines = f.readlines()

            complete_entry = json.loads(lines[-1])
            assert complete_entry["status"] == LogStatus.COMPLETED
            assert complete_entry["items_created"] == 10
            assert complete_entry["items_failed"] == 2
            assert "duration_ms" in complete_entry

    def test_phase_error(self):
        """Should log phase error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.phase_error("extraction", "Connection failed", "Database offline")

            with open(logger.log_file) as f:
                lines = f.readlines()

            error_entry = json.loads(lines[-1])
            assert error_entry["status"] == LogStatus.ERROR
            assert error_entry["message"] == "Connection failed"
            assert error_entry["error"] == "Database offline"

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

    def test_step_sequence_increments(self):
        """Should increment step sequence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_start("Step1")
            logger.step_complete("Step1")
            logger.step_start("Step2")
            logger.step_complete("Step2")

            with open(logger.log_file) as f:
                lines = f.readlines()

            # Check sequences in step entries
            step_entries = [json.loads(l) for l in lines if json.loads(l).get("step")]
            sequences = [e["sequence"] for e in step_entries if e["status"] == "started"]

            assert sequences == [1, 2]

    def test_detail(self):
        """Should log detail level entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.step_start("File")
            logger.detail("Processing file main.py", item_type="file", path="main.py")

            with open(logger.log_file) as f:
                lines = f.readlines()

            detail_entry = json.loads(lines[-1])
            assert detail_entry["level"] == LogLevel.DETAIL
            assert "main.py" in detail_entry["message"]

    def test_multiple_phases(self):
        """Should handle multiple phases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)

            logger.phase_start("extraction")
            logger.phase_complete("extraction")
            logger.phase_start("derivation")
            logger.phase_complete("derivation")

            with open(logger.log_file) as f:
                lines = f.readlines()

            assert len(lines) == 4
            phases = [json.loads(l)["phase"] for l in lines]
            assert phases.count("extraction") == 2
            assert phases.count("derivation") == 2


class TestStepContext:
    """Tests for StepContext context manager."""

    def test_context_logs_start_and_complete(self):
        """Should log step start and complete."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with StepContext(logger, "TypeDefinition"):
                pass  # Simulate work

            with open(logger.log_file) as f:
                lines = f.readlines()

            # Should have: phase_start, step_start, step_complete
            step_entries = [json.loads(l) for l in lines if json.loads(l).get("step")]
            assert len(step_entries) == 2
            assert step_entries[0]["status"] == LogStatus.STARTED
            assert step_entries[1]["status"] == LogStatus.COMPLETED

    def test_context_logs_error_on_exception(self):
        """Should log step error when exception occurs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with pytest.raises(ValueError):
                with StepContext(logger, "TypeDefinition"):
                    raise ValueError("Test error")

            with open(logger.log_file) as f:
                lines = f.readlines()

            step_entries = [json.loads(l) for l in lines if json.loads(l).get("step")]
            error_entry = [e for e in step_entries if e["status"] == LogStatus.ERROR][0]
            assert "Test error" in error_entry["error"]

    def test_context_tracks_items(self):
        """Should track items processed and created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(run_id=1, logs_dir=tmpdir)
            logger.phase_start("extraction")

            with StepContext(logger, "TypeDefinition") as ctx:
                ctx.items_processed = 10
                ctx.items_created = 8
                ctx.items_failed = 2

            with open(logger.log_file) as f:
                lines = f.readlines()

            complete_entry = json.loads(lines[-1])
            assert complete_entry["items_processed"] == 10
            assert complete_entry["items_created"] == 8
            assert complete_entry["items_failed"] == 2
