"""
Shared type definitions for pipeline modules.

This module provides TypedDicts and Protocols that ensure consistent interfaces
across extraction, derivation, and validation modules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypedDict, runtime_checkable

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
# Utility Protocols
# =============================================================================


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
    # Protocols
    "HasToDict",
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
