"""
Logging module - Structured logging for pipeline runs using structlog.

Logging Levels:
- Level 1: High-level phases (classification, extraction, derivation, validation)
- Level 2: Steps within phases (Repository, Directory, File, BusinessConcept, etc.)
- Level 3: Detailed item-level logging (each file, node, edge)

Log files are stored in: workspace/logs/run_{id}/log_{datetime}.jsonl
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import IO, Any

import structlog

__all__ = [
    "LogLevel",
    "LogStatus",
    "LogEntry",
    "RunLogger",
    "StepContext",
    "RunLoggerHandler",
    "get_logger_for_active_run",
    "read_run_logs",
    "setup_logging_bridge",
    "teardown_logging_bridge",
]


class LogLevel(int, Enum):
    """Log levels for filtering."""

    PHASE = 1  # High-level: classification, extraction, derivation, validation
    STEP = 2  # Steps within phases: Repository, Directory, File, etc.
    DETAIL = 3  # Item-level: each file, node, edge


class LogStatus(str, Enum):  # noqa: UP042 - StrEnum would change str() of members, which callers compare
    """Status values for log entries."""

    STARTED = "started"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"


class LogEntry:
    """A single log entry - compatibility wrapper for structlog output."""

    def __init__(
        self,
        level: int,
        phase: str,
        status: str,
        timestamp: str,
        message: str,
        step: str | None = None,
        sequence: int | None = None,
        duration_ms: int | None = None,
        items_processed: int | None = None,
        items_created: int | None = None,
        items_failed: int | None = None,
        stats: dict[str, Any] | None = None,
        error: str | None = None,
    ):
        self.level = level
        self.phase = phase
        self.status = status
        self.timestamp = timestamp
        self.message = message
        self.step = step
        self.sequence = sequence
        self.duration_ms = duration_ms
        self.items_processed = items_processed
        self.items_created = items_created
        self.items_failed = items_failed
        self.stats = stats
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {
            "level": self.level,
            "phase": self.phase,
            "status": self.status,
            "timestamp": self.timestamp,
            "message": self.message,
        }
        if self.step is not None:
            result["step"] = self.step
        if self.sequence is not None:
            result["sequence"] = self.sequence
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        if self.items_processed is not None:
            result["items_processed"] = self.items_processed
        if self.items_created is not None:
            result["items_created"] = self.items_created
        if self.items_failed is not None:
            result["items_failed"] = self.items_failed
        if self.stats is not None:
            result["stats"] = self.stats
        if self.error is not None:
            result["error"] = self.error
        return result

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


def _jsonl_renderer(
    logger: structlog.types.WrappedLogger,
    method_name: str,
    event_dict: structlog.types.EventDict,
) -> str:
    """Custom renderer that outputs JSONL format compatible with existing logs."""
    return json.dumps(event_dict, default=str)


def _create_structlog_logger(file_handle: IO[str]) -> structlog.stdlib.BoundLogger:
    """Create a structlog logger configured for JSONL file output."""

    def file_writer(
        logger: structlog.types.WrappedLogger,
        method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> str:
        """Write to file and return the JSON string."""
        json_str = json.dumps(event_dict, default=str)
        file_handle.write(json_str + "\n")
        file_handle.flush()
        return json_str

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            file_writer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

    return structlog.get_logger()


class RunLogger:
    """
    Logger for a single pipeline run using structlog.

    Creates and appends to a JSONL file in workspace/logs/run_{id}/.
    """

    def __init__(self, run_id: int, logs_dir: str = "workspace/logs"):
        """
        Initialize logger for a run.

        Args:
            run_id: The run ID from the runs table
            logs_dir: Base directory for logs (default: "workspace/logs" in project root)
        """
        self.run_id = run_id

        # Resolve logs_dir relative to project root
        logs_path = Path(logs_dir)
        if not logs_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            logs_path = project_root / logs_path

        self.logs_dir = logs_path
        self.run_dir = self.logs_dir / f"run_{run_id}"

        # Create run directory
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Create log file with datetime
        self.start_time = datetime.now()
        datetime_str = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_file = self.run_dir / f"log_{datetime_str}.jsonl"

        # Open file handle for structlog
        self._file_handle: IO[str] | None = None

        # Track current phase for step logging
        self._current_phase: str | None = None
        self._phase_start: datetime | None = None
        self._step_sequence: int = 0

        # Bound logger with run context
        self._logger: structlog.stdlib.BoundLogger | None = None

    def _ensure_logger(self) -> structlog.stdlib.BoundLogger:
        """Ensure the structlog logger is initialized."""
        if self._logger is None:
            self._file_handle = open(self.log_file, "a", encoding="utf-8")
            self._logger = _create_structlog_logger(self._file_handle)
            self._logger = self._logger.bind(run_id=self.run_id)
        return self._logger

    def _write_entry(self, entry: LogEntry) -> None:
        """Write a log entry to the JSONL file."""
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

    def _now(self) -> str:
        """Get current timestamp as ISO string."""
        return datetime.now().isoformat()

    def _elapsed_ms(self, start: datetime) -> int:
        """Calculate elapsed milliseconds since start."""
        return int((datetime.now() - start).total_seconds() * 1000)

    def close(self) -> None:
        """Close the file handle."""
        if hasattr(self, "_file_handle") and self._file_handle:
            self._file_handle.close()
            self._file_handle = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()

    # ==================== Level 1: Phase Logging ====================

    def phase_start(self, phase: str, message: str = "") -> None:
        """
        Log the start of a phase (Level 1).

        Args:
            phase: Phase name (classification, extraction, derivation, validation)
            message: Optional message
        """
        self._current_phase = phase
        self._phase_start = datetime.now()
        self._step_sequence = 0

        entry = LogEntry(
            level=LogLevel.PHASE,
            phase=phase,
            status=LogStatus.STARTED,
            timestamp=self._now(),
            message=message or f"Starting {phase}",
        )
        self._write_entry(entry)

    def phase_complete(self, phase: str, message: str = "", stats: dict[str, Any] | None = None) -> None:
        """
        Log the completion of a phase (Level 1).

        Args:
            phase: Phase name
            message: Optional message
            stats: Optional summary statistics
        """
        duration = None
        if self._phase_start and self._current_phase == phase:
            duration = self._elapsed_ms(self._phase_start)

        entry = LogEntry(
            level=LogLevel.PHASE,
            phase=phase,
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=message or f"Completed {phase}",
            duration_ms=duration,
            stats=stats,
        )
        self._write_entry(entry)
        self._current_phase = None
        self._phase_start = None

    def phase_error(self, phase: str, error: str, message: str = "") -> None:
        """
        Log a phase error (Level 1).

        Args:
            phase: Phase name
            error: Error message/details
            message: Optional message
        """
        duration = None
        if self._phase_start and self._current_phase == phase:
            duration = self._elapsed_ms(self._phase_start)

        entry = LogEntry(
            level=LogLevel.PHASE,
            phase=phase,
            status=LogStatus.ERROR,
            timestamp=self._now(),
            message=message or f"Error in {phase}",
            duration_ms=duration,
            error=error,
        )
        self._write_entry(entry)
        self._current_phase = None
        self._phase_start = None

    # ==================== Level 2: Step Logging ====================

    def step_start(self, step: str, message: str = "") -> StepContext:
        """
        Log the start of a step within a phase (Level 2).

        Args:
            step: Step name (Repository, Directory, File, BusinessConcept, etc.)
            message: Optional message

        Returns:
            StepContext for tracking step completion
        """
        self._step_sequence += 1

        entry = LogEntry(
            level=LogLevel.STEP,
            phase=self._current_phase or "unknown",
            step=step,
            sequence=self._step_sequence,
            status=LogStatus.STARTED,
            timestamp=self._now(),
            message=message or f"Starting {step}",
        )
        self._write_entry(entry)

        return StepContext(self, step, self._step_sequence)

    def step_complete(
        self,
        step: str,
        sequence: int,
        message: str = "",
        items_processed: int = 0,
        items_created: int = 0,
        items_failed: int = 0,
        duration_ms: int | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        """
        Log the completion of a step (Level 2).

        Args:
            step: Step name
            sequence: Step sequence number
            message: Optional message
            items_processed: Number of items processed
            items_created: Number of items created (nodes/edges)
            items_failed: Number of items that failed
            duration_ms: Duration in milliseconds
            stats: Optional detailed statistics
        """
        entry = LogEntry(
            level=LogLevel.STEP,
            phase=self._current_phase or "unknown",
            step=step,
            sequence=sequence,
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=message or f"Completed {step}",
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_created=items_created,
            items_failed=items_failed,
            stats=stats,
        )
        self._write_entry(entry)

    def step_error(
        self,
        step: str,
        sequence: int,
        error: str,
        message: str = "",
        duration_ms: int | None = None,
    ) -> None:
        """
        Log a step error (Level 2).

        Args:
            step: Step name
            sequence: Step sequence number
            error: Error message/details
            message: Optional message
            duration_ms: Duration in milliseconds
        """
        entry = LogEntry(
            level=LogLevel.STEP,
            phase=self._current_phase or "unknown",
            step=step,
            sequence=sequence,
            status=LogStatus.ERROR,
            timestamp=self._now(),
            message=message or f"Error in {step}",
            duration_ms=duration_ms,
            error=error,
        )
        self._write_entry(entry)

    def step_skipped(self, step: str, message: str = "") -> None:
        """
        Log a skipped step (Level 2).

        Args:
            step: Step name
            message: Reason for skipping
        """
        self._step_sequence += 1

        entry = LogEntry(
            level=LogLevel.STEP,
            phase=self._current_phase or "unknown",
            step=step,
            sequence=self._step_sequence,
            status=LogStatus.SKIPPED,
            timestamp=self._now(),
            message=message or f"Skipped {step}",
        )
        self._write_entry(entry)

    # ==================== Level 2: Step Context Manager ====================

    @contextmanager
    def step(self, step_name: str, message: str = ""):
        """
        Context manager for step logging with automatic timing.

        Args:
            step_name: Name of the step
            message: Optional start message

        Yields:
            StepContext for tracking items processed/created

        Example:
            with logger.step("Repository") as ctx:
                # do work
                ctx.items_processed = 10
                ctx.items_created = 5
        """
        ctx = self.step_start(step_name, message)
        try:
            yield ctx
        except Exception as e:
            ctx.error(str(e))
            raise
        else:
            if not ctx._completed:
                ctx.complete()

    # ==================== Level 3: Detail Logging ====================

    def detail_file_classified(self, file_path: str, file_type: str, subtype: str, extension: str) -> None:
        """Log a successfully classified file (Level 3)."""
        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "classification",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Classified: {file_path}",
            stats={
                "file_path": file_path,
                "file_type": file_type,
                "subtype": subtype,
                "extension": extension,
            },
        )
        self._write_entry(entry)

    def detail_file_unclassified(self, file_path: str, extension: str) -> None:
        """Log an unclassified file (Level 3)."""
        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "classification",
            status=LogStatus.SKIPPED,
            timestamp=self._now(),
            message=f"Unclassified: {file_path}",
            stats={
                "file_path": file_path,
                "extension": extension,
                "reason": "unknown_extension",
            },
        )
        self._write_entry(entry)

    def detail_extraction(
        self,
        file_path: str,
        node_type: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        cache_used: bool,
        retries: int = 0,
        concepts_extracted: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Log an LLM extraction detail (Level 3)."""
        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "extraction",
            status=LogStatus.COMPLETED if success else LogStatus.ERROR,
            timestamp=self._now(),
            message=f"Extraction from {file_path}: {concepts_extracted} {node_type}(s)",
            error=error,
            stats={
                "file_path": file_path,
                "node_type": node_type,
                "prompt": prompt,
                "response": response,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cache_used": cache_used,
                "retries": retries,
                "concepts_extracted": concepts_extracted,
            },
        )
        self._write_entry(entry)

    def detail_node_created(
        self,
        node_id: str,
        node_type: str,
        source_file: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Log a node creation detail (Level 3)."""
        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "extraction",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Created {node_type}: {node_id}",
            stats={
                "node_id": node_id,
                "node_type": node_type,
                "source_file": source_file,
                "properties": properties,
            },
        )
        self._write_entry(entry)

    def detail_edge_created(self, edge_id: str, relationship_type: str, from_node: str, to_node: str) -> None:
        """Log an edge creation detail (Level 3)."""
        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "extraction",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Created {relationship_type}: {from_node} -> {to_node}",
            stats={
                "edge_id": edge_id,
                "relationship_type": relationship_type,
                "from_node": from_node,
                "to_node": to_node,
            },
        )
        self._write_entry(entry)

    def detail_node_deactivated(
        self,
        node_id: str,
        node_type: str,
        reason: str,
        algorithm: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Log a node deactivation detail (Level 3)."""
        stats = {
            "node_id": node_id,
            "node_type": node_type,
            "reason": reason,
            "action": "deactivated",
        }
        if algorithm:
            stats["algorithm"] = algorithm
        if properties:
            stats.update(properties)

        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "derivation",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Deactivated {node_type}: {node_id} ({reason})",
            stats=stats,
        )
        self._write_entry(entry)

    def detail_edge_deactivated(
        self,
        edge_id: str,
        relationship_type: str,
        from_node: str,
        to_node: str,
        reason: str,
        algorithm: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Log an edge deactivation detail (Level 3)."""
        stats = {
            "edge_id": edge_id,
            "relationship_type": relationship_type,
            "from_node": from_node,
            "to_node": to_node,
            "reason": reason,
            "action": "deactivated",
        }
        if algorithm:
            stats["algorithm"] = algorithm
        if properties:
            stats.update(properties)

        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "derivation",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Deactivated {relationship_type}: {from_node} -> {to_node} ({reason})",
            stats=stats,
        )
        self._write_entry(entry)

    def detail_element_created(
        self,
        element_id: str,
        element_type: str,
        name: str,
        source_node: str | None = None,
        confidence: float | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Log an ArchiMate element creation detail (Level 3)."""
        stats: dict[str, Any] = {
            "element_id": element_id,
            "element_type": element_type,
            "name": name,
        }
        if source_node:
            stats["source_node"] = source_node
        if confidence is not None:
            stats["confidence"] = confidence
        if properties:
            stats.update(properties)

        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "derivation",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Created {element_type}: {name}",
            stats=stats,
        )
        self._write_entry(entry)

    def detail_relationship_created(
        self,
        relationship_id: str,
        relationship_type: str,
        source_element: str,
        target_element: str,
        confidence: float | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Log an ArchiMate relationship creation detail (Level 3)."""
        stats: dict[str, Any] = {
            "relationship_id": relationship_id,
            "relationship_type": relationship_type,
            "source_element": source_element,
            "target_element": target_element,
        }
        if confidence is not None:
            stats["confidence"] = confidence
        if properties:
            stats.update(properties)

        entry = LogEntry(
            level=LogLevel.DETAIL,
            phase=self._current_phase or "derivation",
            status=LogStatus.COMPLETED,
            timestamp=self._now(),
            message=f"Created {relationship_type}: {source_element} -> {target_element}",
            stats=stats,
        )
        self._write_entry(entry)

    # ==================== Utility Methods ====================

    def get_log_path(self) -> Path:
        """Get the path to the current log file."""
        return self.log_file

    def read_logs(self, level: int | None = None) -> list[dict[str, Any]]:
        """
        Read all log entries from the file.

        Args:
            level: Optional level filter (1, 2, or 3)

        Returns:
            List of log entry dictionaries
        """
        if not self.log_file.exists():
            return []

        entries = []
        with open(self.log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if level is None or entry.get("level") == level:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        pass
        return entries


class StepContext:
    """
    Context manager for tracking step duration and completion.

    Usage:
        with logger.step_start("Repository") as step:
            # do work
            step.items_processed = 10
            step.items_created = 5
    """

    def __init__(self, logger: RunLogger, step: str, sequence: int):
        self.logger = logger
        self.step = step
        self.sequence = sequence
        self.start_time = datetime.now()
        self.items_processed = 0
        self.items_created = 0
        self.items_failed = 0
        self.stats: dict[str, Any] | None = None
        self._completed = False
        self._edge_ids: list[str] = []

    def __enter__(self) -> StepContext:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            # Exception occurred
            self.error(str(exc_val))
        elif not self._completed:
            # Normal completion
            self.complete()

    def _elapsed_ms(self) -> int:
        return int((datetime.now() - self.start_time).total_seconds() * 1000)

    def complete(self, message: str = "") -> None:
        """Mark step as completed."""
        self._completed = True
        self.logger.step_complete(
            step=self.step,
            sequence=self.sequence,
            message=message,
            items_processed=self.items_processed,
            items_created=self.items_created,
            items_failed=self.items_failed,
            duration_ms=self._elapsed_ms(),
            stats=self.stats,
        )

    def error(self, error: str, message: str = "") -> None:
        """Mark step as errored."""
        self._completed = True
        self.logger.step_error(
            step=self.step,
            sequence=self.sequence,
            error=error,
            message=message,
            duration_ms=self._elapsed_ms(),
        )

    def add_edge(self, edge_id: str) -> None:
        """Track a created edge ID for OCEL logging (extraction)."""
        self._edge_ids.append(edge_id)


def get_logger_for_active_run(engine, logs_dir: str = "workspace/logs") -> RunLogger | None:
    """
    Get a logger for the currently active run.

    Args:
        engine: DuckDB engine connection
        logs_dir: Base directory for logs (default: "workspace/logs" in project root)

    Returns:
        RunLogger if there's an active run, None otherwise
    """
    result = engine.execute("SELECT run_id FROM runs WHERE is_active = TRUE").fetchone()
    if result:
        return RunLogger(run_id=result[0], logs_dir=logs_dir)
    return None


def read_run_logs(run_id: int, logs_dir: str = "workspace/logs", level: int | None = None) -> list[dict[str, Any]]:
    """
    Read logs for a specific run.

    Args:
        run_id: The run ID
        logs_dir: Base directory for logs (default: "workspace/logs" in project root)
        level: Optional level filter

    Returns:
        List of log entries, or empty list if no logs found
    """
    logs_path = Path(logs_dir)
    if not logs_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        logs_path = project_root / logs_path

    run_dir = logs_path / f"run_{run_id}"
    if not run_dir.exists():
        return []

    # Find the most recent log file
    log_files = sorted(run_dir.glob("log_*.jsonl"), reverse=True)
    if not log_files:
        return []

    entries = []
    with open(log_files[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    if level is None or entry.get("level") == level:
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass
    return entries


# =============================================================================
# Standard Logging Bridge (integrates Python logging with structlog)
# =============================================================================


class RunLoggerHandler(logging.Handler):
    """
    A logging.Handler that forwards standard Python logging to RunLogger.

    This bridges the standard logging module with the structured RunLogger,
    allowing warnings/errors from adapters to appear in pipeline logs.
    """

    def __init__(self, run_logger: RunLogger, min_level: int = logging.WARNING):
        """
        Initialize the handler.

        Args:
            run_logger: The RunLogger instance to forward messages to
            min_level: Minimum Python logging level to forward (default: WARNING)
        """
        super().__init__(level=min_level)
        self.run_logger = run_logger

    def emit(self, record: logging.LogRecord) -> None:
        """Forward a log record to RunLogger as a detail entry."""
        try:
            # Map Python log levels to status
            if record.levelno >= logging.ERROR:
                status = LogStatus.ERROR
            elif record.levelno >= logging.WARNING:
                status = LogStatus.ERROR  # Treat warnings as errors in structured log
            else:
                status = LogStatus.COMPLETED

            # Format the message
            message = self.format(record)

            # Create a detail entry
            entry = LogEntry(
                level=LogLevel.DETAIL,
                phase=self.run_logger._current_phase or "system",
                status=status,
                timestamp=datetime.now().isoformat(),
                message=message,
                error=message if status == LogStatus.ERROR else None,
                stats={
                    "logger": record.name,
                    "level": record.levelname,
                    "module": record.module,
                    "funcName": record.funcName,
                    "lineno": record.lineno,
                },
            )
            self.run_logger._write_entry(entry)
        except Exception:
            # Don't let logging errors break the application
            self.handleError(record)


def setup_logging_bridge(
    run_logger: RunLogger,
    min_level: int = logging.WARNING,
    logger_names: list[str] | None = None,
) -> RunLoggerHandler:
    """
    Set up a bridge from standard Python logging to RunLogger.

    Args:
        run_logger: The RunLogger to forward messages to
        min_level: Minimum level to forward (default: WARNING)
        logger_names: Specific logger names to bridge (default: all via root)

    Returns:
        The handler (for later removal if needed)
    """
    handler = RunLoggerHandler(run_logger, min_level)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    if logger_names:
        for name in logger_names:
            logging.getLogger(name).addHandler(handler)
    else:
        logging.getLogger().addHandler(handler)

    return handler


def teardown_logging_bridge(handler: RunLoggerHandler, logger_names: list[str] | None = None) -> None:
    """
    Remove a previously set up logging bridge.

    Args:
        handler: The handler returned by setup_logging_bridge
        logger_names: Same logger names used in setup (or None for root)
    """
    if logger_names:
        for name in logger_names:
            logging.getLogger(name).removeHandler(handler)
    else:
        logging.getLogger().removeHandler(handler)
