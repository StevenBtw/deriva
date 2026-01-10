"""
Shared type definitions for pipeline modules.

This module provides TypedDicts and Protocols that ensure consistent interfaces
across extraction, derivation, and validation modules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict, runtime_checkable


# =============================================================================
# Progress Update (for generator-based progress)
# =============================================================================


@dataclass
class ProgressUpdate:
    """
    Progress update yielded by generator-based pipeline functions.

    Used with Marimo's mo.status.progress_bar iterator pattern for real-time updates.

    Attributes:
        phase: Current phase name (e.g., 'extraction', 'derivation')
        step: Current step name (e.g., 'TypeDefinition', 'ApplicationComponent')
        status: Status of this update ('starting', 'processing', 'complete', 'error')
        current: Current step number (1-indexed)
        total: Total number of steps
        message: Optional message (e.g., '15 nodes created')
        stats: Optional statistics dict for completed steps
    """

    phase: str = ""
    step: str = ""
    status: str = "processing"  # starting, processing, complete, error
    current: int = 0
    total: int = 0
    message: str = ""
    stats: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable representation for progress display."""
        if self.status == "complete" and not self.step:
            return f"{self.phase} complete: {self.message}"
        if self.step:
            return f"{self.phase} ({self.current}/{self.total}): {self.step} - {self.status}"
        return f"{self.phase}: {self.status}"


# =============================================================================
# Base Result Types
# =============================================================================


class BaseResult(TypedDict, total=False):
    """
    Base result structure returned by all pipeline module functions.

    All module functions should return this structure for consistency.
    """

    success: bool  # Required: Whether the operation succeeded
    errors: list[str]  # Required: List of error messages
    stats: dict[str, Any]  # Required: Statistics about the operation


class PipelineResult(TypedDict, total=False):
    """
    Unified result structure for all pipeline stages (extraction, derivation, validation).

    This provides a consistent interface across all stages, always including
    both elements and relationships.
    """

    success: bool  # Whether the operation succeeded
    errors: list[str]  # List of error messages
    warnings: list[str]  # List of warning messages
    stats: dict[str, Any]  # Statistics about the operation

    # Core data - always present
    elements: list[dict[str, Any]]  # Created/processed elements
    relationships: list[dict[str, Any]]  # Created/processed relationships

    # Metadata
    stage: str  # Pipeline stage: 'extraction', 'derivation', 'validation'
    timestamp: str  # ISO timestamp when completed
    duration_ms: int  # Duration in milliseconds

    # Optional details
    llm_details: LLMDetails  # LLM call details if used
    issues: list[dict[str, Any]]  # Validation issues (for validation stage)


class LLMDetails(TypedDict, total=False):
    """Details about an LLM call for logging purposes."""

    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    cache_used: bool


# =============================================================================
# Extraction Types
# =============================================================================


class ExtractionData(TypedDict):
    """Data returned by extraction functions."""

    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class ExtractionResult(BaseResult):
    """
    Result structure for extraction module functions.

    Returned by functions like extract_business_concepts, extract_type_definitions, etc.
    """

    data: ExtractionData
    llm_details: LLMDetails


class FileExtractionResult(TypedDict):
    """Per-file extraction result for batch operations."""

    file_path: str
    success: bool
    concepts_extracted: int
    llm_details: LLMDetails
    errors: list[str]


class BatchExtractionResult(ExtractionResult):
    """Result structure for batch extraction operations."""

    file_results: list[FileExtractionResult]


# =============================================================================
# Derivation Types
# =============================================================================


class DerivationData(TypedDict):
    """Data returned by derivation functions."""

    elements_created: list[dict[str, Any]]


class DerivationResult(BaseResult):
    """
    Result structure for derivation module functions.

    Returned by functions like derive_application_components, derive_data_objects, etc.
    """

    data: DerivationData
    llm_details: LLMDetails


class DerivationConfig(TypedDict):
    """Configuration for a derivation step."""

    element_type: str  # Target ArchiMate type
    input_graph_query: str  # Cypher query to get source nodes
    instruction: str  # LLM instruction
    example: str  # Example output JSON


# =============================================================================
# Validation Types
# =============================================================================


class ValidationIssue(TypedDict, total=False):
    """A single validation issue found."""

    type: str  # Issue type (error, warning, info)
    rule: str  # Rule that triggered the issue
    message: str  # Human-readable message
    element_id: str  # ID of element with issue
    severity: str  # Severity level (critical, major, minor)
    suggestion: str  # Optional fix suggestion


class ValidationData(TypedDict):
    """Data returned by validation functions."""

    issues: list[ValidationIssue]
    passed: list[str]  # IDs of elements that passed validation
    failed: list[str]  # IDs of elements that failed validation


class ValidationResult(BaseResult):
    """
    Result structure for validation module functions.

    Returned by functions like validate_relationships, validate_coverage, etc.
    """

    data: ValidationData
    llm_details: LLMDetails | None  # Optional, only if LLM used


class ValidationConfig(TypedDict, total=False):
    """Configuration for a validation step."""

    rule_type: str  # Type of validation rule
    severity: str  # Default severity for violations
    instruction: str  # LLM instruction (if LLM-based)
    cypher_query: str  # Query to get elements to validate


# =============================================================================
# Progress Reporting Protocol
# =============================================================================


class ProgressReporter(Protocol):
    """
    Protocol for progress reporting during pipeline operations.

    Implementations can use different backends (Rich for CLI, Marimo native, etc.)
    while services remain UI-agnostic.
    """

    def start_phase(self, name: str, total_steps: int) -> None:
        """
        Start a new phase (e.g., 'extraction', 'derivation').

        Args:
            name: Phase name
            total_steps: Total number of steps in this phase
        """
        ...

    def start_step(self, name: str, total_items: int | None = None) -> None:
        """
        Start a new step within a phase.

        Args:
            name: Step name (e.g., 'TypeDefinition', 'BusinessObject')
            total_items: Optional total items to process (for progress bar)
        """
        ...

    def update(self, current: int | None = None, message: str = "") -> None:
        """
        Update progress within the current step.

        Args:
            current: Current item number (if known)
            message: Optional status message (e.g., file being processed)
        """
        ...

    def advance(self, amount: int = 1) -> None:
        """
        Advance progress by a given amount.

        Args:
            amount: Number of items to advance
        """
        ...

    def complete_step(self, message: str = "") -> None:
        """
        Mark the current step as complete.

        Args:
            message: Optional completion message
        """
        ...

    def complete_phase(self, message: str = "") -> None:
        """
        Mark the current phase as complete.

        Args:
            message: Optional completion message
        """
        ...

    def log(self, message: str, level: str = "info") -> None:
        """
        Log a message during progress.

        Args:
            message: Message to log
            level: Log level ('info', 'warning', 'error')
        """
        ...


class BenchmarkProgressReporter(Protocol):
    """
    Extended progress reporter for benchmark operations.

    Provides additional context for multi-run benchmark matrices.
    """

    def start_benchmark(
        self,
        session_id: str,
        total_runs: int,
        repositories: list[str],
        models: list[str],
    ) -> None:
        """Start a benchmark session."""
        ...

    def start_run(
        self,
        run_number: int,
        repository: str,
        model: str,
        iteration: int,
    ) -> None:
        """Start a benchmark run."""
        ...

    def complete_run(self, status: str, stats: dict[str, Any] | None = None) -> None:
        """Complete a benchmark run."""
        ...

    def complete_benchmark(
        self,
        runs_completed: int,
        runs_failed: int,
        duration_seconds: float,
    ) -> None:
        """Complete the benchmark session."""
        ...

    # Inherit from ProgressReporter for phase/step tracking
    def start_phase(self, name: str, total_steps: int) -> None:
        """Start a new phase within the current run."""
        ...

    def start_step(self, name: str, total_items: int | None = None) -> None:
        """Start a new step within a phase."""
        ...

    def update(self, current: int | None = None, message: str = "") -> None:
        """Update progress within the current step."""
        ...

    def advance(self, amount: int = 1) -> None:
        """Advance progress by a given amount."""
        ...

    def complete_step(self, message: str = "") -> None:
        """Mark the current step as complete."""
        ...

    def complete_phase(self, message: str = "") -> None:
        """Mark the current phase as complete."""
        ...

    def log(self, message: str, level: str = "info") -> None:
        """Log a message during progress."""
        ...


# =============================================================================
# Utility Protocols
# =============================================================================


class StepContextProtocol(Protocol):
    """Protocol for step context returned by run loggers."""

    items_created: int

    def complete(self) -> None:
        """Mark the step as complete."""
        ...

    def error(self, message: str) -> None:
        """Mark the step as failed with an error message."""
        ...

    def add_edge(self, edge_id: str) -> None:
        """Track a created edge ID for OCEL logging (extraction)."""
        ...

    def add_relationship(self, relationship_id: str) -> None:
        """Track a created relationship ID for OCEL logging (derivation)."""
        ...


class RunLoggerProtocol(Protocol):
    """Protocol for run loggers (supports both RunLogger and OCELRunLogger)."""

    def phase_start(self, phase: str, message: str = "") -> None:
        """Log the start of a phase."""
        ...

    def phase_complete(
        self, phase: str, message: str = "", stats: dict[str, Any] | None = None
    ) -> None:
        """Log the completion of a phase."""
        ...

    def phase_error(self, phase: str, error: str, message: str = "") -> None:
        """Log a phase error."""
        ...

    def step_start(self, step: str, message: str = "") -> StepContextProtocol:
        """Log the start of a step and return a context manager."""
        ...


@runtime_checkable
class HasToDict(Protocol):
    """Protocol for objects that can be converted to a dictionary."""

    def to_dict(self) -> dict[str, Any]:
        """Convert the object to a dictionary representation."""
        ...


# =============================================================================
# Function Protocols
# =============================================================================


class ExtractionFunction(Protocol):
    """Protocol for extraction functions."""

    def __call__(
        self,
        file_path: str,
        file_content: str,
        repo_name: str,
        llm_query_fn: Callable,
        config: dict[str, Any],
    ) -> ExtractionResult:
        """
        Extract nodes/edges from a file.

        Args:
            file_path: Path to the file being analyzed
            file_content: Content of the file
            repo_name: Repository name
            llm_query_fn: Function to call LLM (prompt, schema) -> response
            config: Extraction config with 'instruction' and 'example'

        Returns:
            ExtractionResult with nodes, edges, and metadata
        """
        ...


class BatchExtractionFunction(Protocol):
    """Protocol for batch extraction functions."""

    def __call__(
        self,
        files: list[dict[str, str]],
        repo_name: str,
        llm_query_fn: Callable,
        config: dict[str, Any],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> BatchExtractionResult:
        """
        Extract nodes/edges from multiple files.

        Args:
            files: List of dicts with 'path' and 'content' keys
            repo_name: Repository name
            llm_query_fn: Function to call LLM
            config: Extraction config
            progress_callback: Optional callback(current, total, file_path)

        Returns:
            BatchExtractionResult with aggregated results
        """
        ...


class DerivationFunction(Protocol):
    """Protocol for derivation functions."""

    def __call__(
        self,
        graph_manager: Any,
        archimate_manager: Any,
        llm_query_fn: Callable,
        config: dict[str, Any],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> DerivationResult:
        """
        Derive ArchiMate elements from graph nodes.

        Args:
            graph_manager: Connected GraphManager instance
            archimate_manager: Connected ArchimateManager instance
            llm_query_fn: Function to call LLM (prompt, schema) -> response
            config: Derivation config with query, instruction, example
            progress_callback: Optional callback(current, total, element_name)

        Returns:
            DerivationResult with created elements
        """
        ...


class ValidationFunction(Protocol):
    """Protocol for validation functions."""

    def __call__(
        self,
        archimate_manager: Any,
        config: dict[str, Any],
        llm_query_fn: Callable | None = None,
    ) -> ValidationResult:
        """
        Validate ArchiMate model elements.

        Args:
            archimate_manager: Connected ArchimateManager instance
            config: Validation config
            llm_query_fn: Optional LLM function for complex validation

        Returns:
            ValidationResult with issues and pass/fail lists
        """
        ...


# =============================================================================
# Registry Types
# =============================================================================

ExtractionRegistry = dict[str, ExtractionFunction]
BatchExtractionRegistry = dict[str, BatchExtractionFunction]
DerivationRegistry = dict[str, DerivationFunction]
ValidationRegistry = dict[str, ValidationFunction]


__all__ = [
    # Progress update (generator-based)
    "ProgressUpdate",
    # Base types
    "BaseResult",
    "PipelineResult",
    "LLMDetails",
    # Extraction types
    "ExtractionData",
    "ExtractionResult",
    "FileExtractionResult",
    "BatchExtractionResult",
    # Derivation types
    "DerivationData",
    "DerivationResult",
    "DerivationConfig",
    # Validation types
    "ValidationIssue",
    "ValidationData",
    "ValidationResult",
    "ValidationConfig",
    # Progress protocols
    "ProgressReporter",
    "BenchmarkProgressReporter",
    # Utility protocols
    "HasToDict",
    "StepContextProtocol",
    "RunLoggerProtocol",
    "ExtractionFunction",
    "BatchExtractionFunction",
    "DerivationFunction",
    "ValidationFunction",
    # Registry types
    "ExtractionRegistry",
    "BatchExtractionRegistry",
    "DerivationRegistry",
    "ValidationRegistry",
]
