"""
Rich-based progress reporting for CLI operations.

Provides visual progress bars and status updates for pipeline and benchmark runs.
Uses the Rich library for beautiful terminal output.
"""

from __future__ import annotations

from typing import Any

# Try to import Rich, fall back to quiet mode if not available
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskID,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


# =============================================================================
# QUIET PROGRESS REPORTER (Fallback when Rich not available or disabled)
# =============================================================================


class QuietProgressReporter:
    """
    No-op progress reporter for headless/batch mode.

    Implements the ProgressReporter protocol but does nothing.
    Useful for non-interactive environments or when progress display is disabled.
    """

    def start_phase(self, name: str, total_steps: int) -> None:
        """Start a new phase."""
        pass

    def start_step(self, name: str, total_items: int | None = None) -> None:
        """Start a new step."""
        pass

    def update(self, current: int | None = None, message: str = "") -> None:
        """Update progress."""
        pass

    def advance(self, amount: int = 1) -> None:
        """Advance progress."""
        pass

    def complete_step(self, message: str = "") -> None:
        """Complete current step."""
        pass

    def complete_phase(self, message: str = "") -> None:
        """Complete current phase."""
        pass

    def log(self, message: str, level: str = "info") -> None:
        """Log a message."""
        pass

    def __enter__(self) -> QuietProgressReporter:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class QuietBenchmarkProgressReporter(QuietProgressReporter):
    """No-op benchmark progress reporter."""

    def start_benchmark(
        self,
        session_id: str,
        total_runs: int,
        repositories: list[str],
        models: list[str],
    ) -> None:
        """Start benchmark session."""
        pass

    def start_run(
        self,
        run_number: int,
        repository: str,
        model: str,
        iteration: int,
    ) -> None:
        """Start a benchmark run."""
        pass

    def complete_run(self, status: str, stats: dict[str, Any] | None = None) -> None:
        """Complete a benchmark run."""
        pass

    def complete_benchmark(
        self,
        runs_completed: int,
        runs_failed: int,
        duration_seconds: float,
    ) -> None:
        """Complete the benchmark session."""
        pass


# =============================================================================
# RICH PROGRESS REPORTER (Pipeline operations)
# =============================================================================

if RICH_AVAILABLE:

    class RichProgressReporter:
        """
        Rich-based progress reporter for pipeline operations.

        Provides beautiful progress bars with ETA, spinners for indeterminate
        operations, and structured output for multi-step pipelines.
        """

        def __init__(self, console: Console | None = None):
            """
            Initialize the Rich progress reporter.

            Args:
                console: Optional Rich console (creates one if not provided)
            """
            self.console = console or Console()
            self._progress: Progress | None = None
            self._live: Live | None = None

            # Task tracking
            self._phase_task: TaskID | None = None
            self._step_task: TaskID | None = None
            self._current_phase: str = ""
            self._current_step: str = ""

        def __enter__(self) -> RichProgressReporter:
            """Start the progress display."""
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=40),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
                expand=False,
            )
            self._live = Live(self._progress, console=self.console, refresh_per_second=10)
            self._live.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            """Stop the progress display."""
            if self._live:
                self._live.__exit__(*args)
            self._progress = None
            self._live = None

        def start_phase(self, name: str, total_steps: int) -> None:
            """Start a new phase with a progress bar."""
            if not self._progress:
                return

            self._current_phase = name
            # Remove old phase task if exists
            if self._phase_task is not None:
                self._progress.remove_task(self._phase_task)

            self._phase_task = self._progress.add_task(
                f"[bold cyan]{name.upper()}",
                total=total_steps,
            )

        def start_step(self, name: str, total_items: int | None = None) -> None:
            """Start a new step within the current phase."""
            if not self._progress:
                return

            self._current_step = name

            # Remove old step task if exists
            if self._step_task is not None:
                self._progress.remove_task(self._step_task)

            if total_items is not None and total_items > 0:
                self._step_task = self._progress.add_task(
                    f"  {name}",
                    total=total_items,
                )
            else:
                # Indeterminate progress (spinner only)
                self._step_task = self._progress.add_task(
                    f"  {name}",
                    total=None,
                )

        def update(self, current: int | None = None, message: str = "") -> None:
            """Update progress with optional message."""
            if not self._progress or self._step_task is None:
                return

            description = f"  {self._current_step}"
            if message:
                # Truncate long messages
                if len(message) > 40:
                    message = message[:37] + "..."
                description = f"  {self._current_step}: {message}"

            self._progress.update(
                self._step_task,
                description=description,
                completed=current,
            )

        def advance(self, amount: int = 1) -> None:
            """Advance progress by given amount."""
            if not self._progress or self._step_task is None:
                return
            self._progress.advance(self._step_task, amount)

        def complete_step(self, message: str = "") -> None:
            """Mark current step as complete and advance phase."""
            if not self._progress:
                return

            # Mark step as complete
            if self._step_task is not None:
                task = self._progress.tasks[self._step_task]
                if task.total is not None:
                    self._progress.update(self._step_task, completed=task.total)
                self._progress.remove_task(self._step_task)
                self._step_task = None

            # Advance phase
            if self._phase_task is not None:
                self._progress.advance(self._phase_task, 1)

        def complete_phase(self, message: str = "") -> None:
            """Mark current phase as complete."""
            if not self._progress:
                return

            if self._phase_task is not None:
                task = self._progress.tasks[self._phase_task]
                if task.total is not None:
                    self._progress.update(self._phase_task, completed=task.total)

            if message:
                self.console.print(f"[green]{message}[/green]")

        def log(self, message: str, level: str = "info") -> None:
            """Log a message with appropriate styling."""
            if level == "error":
                self.console.print(f"[red]{message}[/red]")
            elif level == "warning":
                self.console.print(f"[yellow]{message}[/yellow]")
            else:
                self.console.print(f"[dim]{message}[/dim]")

    # =============================================================================
    # RICH BENCHMARK PROGRESS REPORTER
    # =============================================================================

    class RichBenchmarkProgressReporter:
        """
        Rich-based progress reporter for benchmark operations.

        Provides a structured display showing:
        - Overall benchmark progress
        - Current run details (repository, model, iteration)
        - Per-run phase/step progress
        """

        def __init__(self, console: Console | None = None):
            """
            Initialize the benchmark progress reporter.

            Args:
                console: Optional Rich console
            """
            self.console = console or Console()
            self._live: Live | None = None
            self._progress: Progress | None = None

            # Benchmark context
            self._session_id: str = ""
            self._total_runs: int = 0
            self._repositories: list[str] = []
            self._models: list[str] = []

            # Current run context
            self._current_run: int = 0
            self._current_repo: str = ""
            self._current_model: str = ""
            self._current_iteration: int = 0

            # Task tracking
            self._benchmark_task: TaskID | None = None
            self._phase_task: TaskID | None = None
            self._step_task: TaskID | None = None
            self._current_phase: str = ""
            self._current_step: str = ""

        def __enter__(self) -> RichBenchmarkProgressReporter:
            """Start the progress display."""
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(bar_width=30),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self.console,
                expand=False,
            )
            self._live = Live(
                self._create_display(),
                console=self.console,
                refresh_per_second=10,
            )
            self._live.__enter__()
            return self

        def __exit__(self, *args: Any) -> None:
            """Stop the progress display."""
            if self._live:
                self._live.__exit__(*args)
            self._progress = None
            self._live = None

        def _create_display(self) -> Panel:
            """Create the benchmark display panel."""
            if not self._progress:
                return Panel("")

            # Create info table
            info = Table.grid(padding=(0, 2))
            info.add_column(style="cyan", justify="right")
            info.add_column()

            if self._session_id:
                info.add_row("Session:", self._session_id)
            if self._current_repo:
                info.add_row("Repository:", self._current_repo)
            if self._current_model:
                info.add_row("Model:", self._current_model)
            if self._current_iteration > 0:
                info.add_row("Iteration:", str(self._current_iteration))

            # Combine with progress
            from rich.console import Group

            content = Group(info, "", self._progress)

            title = f"BENCHMARK: {self._session_id}" if self._session_id else "BENCHMARK"
            return Panel(
                content,
                title=f"[bold blue]{title}[/bold blue]",
                border_style="blue",
            )

        def _refresh_display(self) -> None:
            """Refresh the live display."""
            if self._live:
                self._live.update(self._create_display())

        def start_benchmark(
            self,
            session_id: str,
            total_runs: int,
            repositories: list[str],
            models: list[str],
        ) -> None:
            """Start a benchmark session."""
            self._session_id = session_id
            self._total_runs = total_runs
            self._repositories = repositories
            self._models = models

            if self._progress:
                self._benchmark_task = self._progress.add_task(
                    "[bold green]Overall Progress",
                    total=total_runs,
                )
            self._refresh_display()

        def start_run(
            self,
            run_number: int,
            repository: str,
            model: str,
            iteration: int,
        ) -> None:
            """Start a benchmark run."""
            self._current_run = run_number
            self._current_repo = repository
            self._current_model = model
            self._current_iteration = iteration
            self._refresh_display()

        def complete_run(self, status: str, stats: dict[str, Any] | None = None) -> None:
            """Complete a benchmark run."""
            if self._progress and self._benchmark_task is not None:
                self._progress.advance(self._benchmark_task, 1)

            # Clear phase/step tasks
            if self._phase_task is not None:
                self._progress.remove_task(self._phase_task)
                self._phase_task = None
            if self._step_task is not None:
                self._progress.remove_task(self._step_task)
                self._step_task = None

            self._refresh_display()

        def complete_benchmark(
            self,
            runs_completed: int,
            runs_failed: int,
            duration_seconds: float,
        ) -> None:
            """Complete the benchmark session."""
            self._refresh_display()
            status = "SUCCESS" if runs_failed == 0 else "COMPLETED WITH FAILURES"
            color = "green" if runs_failed == 0 else "yellow"
            self.console.print(
                f"\n[bold {color}]{status}[/bold {color}]: "
                f"{runs_completed} completed, {runs_failed} failed "
                f"in {duration_seconds:.1f}s"
            )

        def start_phase(self, name: str, total_steps: int) -> None:
            """Start a new phase within the current run."""
            if not self._progress:
                return

            self._current_phase = name

            if self._phase_task is not None:
                self._progress.remove_task(self._phase_task)

            self._phase_task = self._progress.add_task(
                f"[cyan]{name.capitalize()}",
                total=total_steps,
            )
            self._refresh_display()

        def start_step(self, name: str, total_items: int | None = None) -> None:
            """Start a new step within a phase."""
            if not self._progress:
                return

            self._current_step = name

            if self._step_task is not None:
                self._progress.remove_task(self._step_task)

            if total_items is not None and total_items > 0:
                self._step_task = self._progress.add_task(
                    f"  {name}",
                    total=total_items,
                )
            else:
                self._step_task = self._progress.add_task(
                    f"  {name}",
                    total=None,
                )
            self._refresh_display()

        def update(self, current: int | None = None, message: str = "") -> None:
            """Update progress within the current step."""
            if not self._progress or self._step_task is None:
                return

            description = f"  {self._current_step}"
            if message:
                if len(message) > 30:
                    message = message[:27] + "..."
                description = f"  {self._current_step}: {message}"

            self._progress.update(
                self._step_task,
                description=description,
                completed=current,
            )
            self._refresh_display()

        def advance(self, amount: int = 1) -> None:
            """Advance progress by given amount."""
            if not self._progress or self._step_task is None:
                return
            self._progress.advance(self._step_task, amount)
            self._refresh_display()

        def complete_step(self, message: str = "") -> None:
            """Mark current step as complete."""
            if not self._progress:
                return

            if self._step_task is not None:
                self._progress.remove_task(self._step_task)
                self._step_task = None

            if self._phase_task is not None:
                self._progress.advance(self._phase_task, 1)

            self._refresh_display()

        def complete_phase(self, message: str = "") -> None:
            """Mark current phase as complete."""
            if not self._progress:
                return

            if self._phase_task is not None:
                task = self._progress.tasks[self._phase_task]
                if task.total is not None:
                    self._progress.update(self._phase_task, completed=task.total)

            self._refresh_display()

        def log(self, message: str, level: str = "info") -> None:
            """Log a message."""
            if level == "error":
                self.console.print(f"[red]{message}[/red]")
            elif level == "warning":
                self.console.print(f"[yellow]{message}[/yellow]")
            else:
                self.console.print(f"[dim]{message}[/dim]")


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================


def create_progress_reporter(
    quiet: bool = False,
    console: Any | None = None,
) -> QuietProgressReporter | Any:
    """
    Create a progress reporter for pipeline operations.

    Args:
        quiet: If True, return a no-op reporter
        console: Optional Rich console (only used if Rich is available)

    Returns:
        ProgressReporter implementation
    """
    if quiet or not RICH_AVAILABLE:
        return QuietProgressReporter()
    return RichProgressReporter(console)


def create_benchmark_progress_reporter(
    quiet: bool = False,
    console: Any | None = None,
) -> QuietBenchmarkProgressReporter | Any:
    """
    Create a progress reporter for benchmark operations.

    Args:
        quiet: If True, return a no-op reporter
        console: Optional Rich console

    Returns:
        BenchmarkProgressReporter implementation
    """
    if quiet or not RICH_AVAILABLE:
        return QuietBenchmarkProgressReporter()
    return RichBenchmarkProgressReporter(console)


__all__ = [
    "RICH_AVAILABLE",
    "QuietProgressReporter",
    "QuietBenchmarkProgressReporter",
    "create_progress_reporter",
    "create_benchmark_progress_reporter",
]

# Only export Rich reporters if available
if RICH_AVAILABLE:
    __all__.extend([
        "RichProgressReporter",
        "RichBenchmarkProgressReporter",
    ])
