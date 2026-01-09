"""
Marimo-based progress reporting for pipeline operations.

Provides progress tracking that integrates with Marimo's reactive UI model.
Collects progress events during execution and provides summary data for display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ProgressEvent:
    """A single progress event."""

    timestamp: datetime
    event_type: str  # phase_start, phase_end, step_start, step_end, update, log
    name: str
    message: str = ""
    current: int | None = None
    total: int | None = None
    level: str = "info"


@dataclass
class ProgressState:
    """Current progress state for display."""

    phase: str = ""
    step: str = ""
    current: int = 0
    total: int | None = None
    message: str = ""
    status: str = "idle"  # idle, running, complete, error
    events: list[ProgressEvent] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        if not self.start_time:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()

    @property
    def phase_count(self) -> int:
        """Count completed phases."""
        return sum(1 for e in self.events if e.event_type == "phase_end")

    @property
    def step_count(self) -> int:
        """Count completed steps."""
        return sum(1 for e in self.events if e.event_type == "step_end")


class MarimoProgressReporter:
    """
    Progress reporter for Marimo pipeline operations.

    Collects progress events during execution and provides state for display.
    Since Marimo cells are synchronous, this reporter collects events that
    can be displayed after the operation completes.

    Usage in Marimo:
        progress = MarimoProgressReporter()
        result = session.run_pipeline(progress=progress)

        # Display results using progress.state
        mo.md(f"Completed {progress.state.phase_count} phases in {progress.state.elapsed_seconds:.1f}s")
    """

    def __init__(self) -> None:
        """Initialize the progress reporter."""
        self.state = ProgressState()

    def start_phase(self, name: str, total_steps: int) -> None:
        """Start a new phase."""
        self.state.phase = name
        self.state.step = ""
        self.state.total = total_steps
        self.state.current = 0
        self.state.status = "running"

        if not self.state.start_time:
            self.state.start_time = datetime.now()

        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="phase_start",
                name=name,
                total=total_steps,
            )
        )

    def start_step(self, name: str, total_items: int | None = None) -> None:
        """Start a new step within the current phase."""
        self.state.step = name
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="step_start",
                name=name,
                total=total_items,
            )
        )

    def update(self, current: int | None = None, message: str = "") -> None:
        """Update progress with optional message."""
        if current is not None:
            self.state.current = current
        if message:
            self.state.message = message

    def advance(self, amount: int = 1) -> None:
        """Advance progress by given amount."""
        self.state.current += amount

    def complete_step(self, message: str = "") -> None:
        """Mark current step as complete."""
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="step_end",
                name=self.state.step,
                message=message,
            )
        )
        self.state.step = ""

    def complete_phase(self, message: str = "") -> None:
        """Mark current phase as complete."""
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="phase_end",
                name=self.state.phase,
                message=message,
            )
        )
        self.state.phase = ""
        self.state.status = "complete"
        self.state.end_time = datetime.now()

    def log(self, message: str, level: str = "info") -> None:
        """Log a message."""
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="log",
                name="",
                message=message,
                level=level,
            )
        )

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the progress for display."""
        phases = [e for e in self.state.events if e.event_type == "phase_start"]
        steps = [e for e in self.state.events if e.event_type == "step_end"]
        logs = [e for e in self.state.events if e.event_type == "log"]
        errors = [e for e in logs if e.level == "error"]

        return {
            "status": self.state.status,
            "elapsed_seconds": self.state.elapsed_seconds,
            "phases_completed": len([e for e in self.state.events if e.event_type == "phase_end"]),
            "phases_total": len(phases),
            "steps_completed": len(steps),
            "phase_names": [e.name for e in phases],
            "step_details": [
                {"name": e.name, "message": e.message}
                for e in steps
            ],
            "errors": [e.message for e in errors],
            "log_count": len(logs),
        }

    def __enter__(self) -> MarimoProgressReporter:
        """Context manager entry."""
        self.state = ProgressState()
        self.state.start_time = datetime.now()
        self.state.status = "running"
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        if self.state.status == "running":
            self.state.status = "complete"
        self.state.end_time = datetime.now()


class MarimoBenchmarkProgressReporter(MarimoProgressReporter):
    """
    Progress reporter for Marimo benchmark operations.

    Extends MarimoProgressReporter with benchmark-specific tracking.
    """

    def __init__(self) -> None:
        """Initialize the benchmark progress reporter."""
        super().__init__()
        self.session_id: str = ""
        self.total_runs: int = 0
        self.runs_completed: int = 0
        self.runs_failed: int = 0
        self.current_run: int = 0
        self.current_repo: str = ""
        self.current_model: str = ""
        self.current_iteration: int = 0
        self.run_results: list[dict[str, Any]] = []

    def start_benchmark(
        self,
        session_id: str,
        total_runs: int,
        repositories: list[str],
        models: list[str],
    ) -> None:
        """Start a benchmark session."""
        self.session_id = session_id
        self.total_runs = total_runs
        self.state.start_time = datetime.now()
        self.state.status = "running"
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="benchmark_start",
                name=session_id,
                message=f"Repos: {', '.join(repositories)}, Models: {', '.join(models)}",
                total=total_runs,
            )
        )

    def start_run(
        self,
        run_number: int,
        repository: str,
        model: str,
        iteration: int,
    ) -> None:
        """Start a benchmark run."""
        self.current_run = run_number
        self.current_repo = repository
        self.current_model = model
        self.current_iteration = iteration
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="run_start",
                name=f"Run {run_number}",
                message=f"{repository} / {model} (iter {iteration})",
            )
        )

    def complete_run(self, status: str, stats: dict[str, Any] | None = None) -> None:
        """Complete a benchmark run."""
        if status == "success":
            self.runs_completed += 1
        else:
            self.runs_failed += 1

        self.run_results.append({
            "run_number": self.current_run,
            "repository": self.current_repo,
            "model": self.current_model,
            "iteration": self.current_iteration,
            "status": status,
            "stats": stats,
        })

        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="run_end",
                name=f"Run {self.current_run}",
                message=status,
            )
        )

    def complete_benchmark(
        self,
        runs_completed: int,
        runs_failed: int,
        duration_seconds: float,
    ) -> None:
        """Complete the benchmark session."""
        self.state.status = "complete"
        self.state.end_time = datetime.now()
        self.state.events.append(
            ProgressEvent(
                timestamp=datetime.now(),
                event_type="benchmark_end",
                name=self.session_id,
                message=f"Completed: {runs_completed}, Failed: {runs_failed}",
            )
        )

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the benchmark progress."""
        base = super().get_summary()
        base.update({
            "session_id": self.session_id,
            "total_runs": self.total_runs,
            "runs_completed": self.runs_completed,
            "runs_failed": self.runs_failed,
            "run_results": self.run_results,
        })
        return base


def create_marimo_progress_reporter() -> MarimoProgressReporter:
    """Create a progress reporter for Marimo pipeline operations."""
    return MarimoProgressReporter()


def create_marimo_benchmark_progress_reporter() -> MarimoBenchmarkProgressReporter:
    """Create a progress reporter for Marimo benchmark operations."""
    return MarimoBenchmarkProgressReporter()


__all__ = [
    "ProgressEvent",
    "ProgressState",
    "MarimoProgressReporter",
    "MarimoBenchmarkProgressReporter",
    "create_marimo_progress_reporter",
    "create_marimo_benchmark_progress_reporter",
]
