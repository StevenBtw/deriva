"""
Base utilities for refine phase modules.

Provides shared types, utilities, and the refine step registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)


@dataclass
class RefineResult:
    """Result of a refine step execution."""

    success: bool
    step_name: str
    elements_disabled: int = 0
    elements_merged: int = 0
    relationships_deleted: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "success": self.success,
            "step_name": self.step_name,
            "elements_disabled": self.elements_disabled,
            "elements_merged": self.elements_merged,
            "relationships_deleted": self.relationships_deleted,
            "issues_found": self.issues_found,
            "issues_fixed": self.issues_fixed,
            "details": self.details,
            "errors": self.errors,
        }


class RefineStep(Protocol):
    """Protocol for refine step implementations."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute the refine step.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Optional manager for source graph operations
            llm_query_fn: Optional LLM function for semantic operations
            params: Optional step-specific parameters

        Returns:
            RefineResult with execution details
        """
        ...


# Registry of refine step implementations
REFINE_STEPS: dict[str, type] = {}


def register_refine_step(name: str):
    """Decorator to register a refine step implementation."""

    def decorator(cls: type) -> type:
        REFINE_STEPS[name] = cls
        return cls

    return decorator


def run_refine_step(
    step_name: str,
    archimate_manager: ArchimateManager,
    graph_manager: GraphManager | None = None,
    llm_query_fn: Any | None = None,
    params: dict[str, Any] | None = None,
) -> RefineResult:
    """Run a registered refine step by name.

    Args:
        step_name: Name of the refine step to run
        archimate_manager: Manager for ArchiMate model operations
        graph_manager: Optional manager for source graph operations
        llm_query_fn: Optional LLM function for semantic operations
        params: Optional step-specific parameters

    Returns:
        RefineResult with execution details
    """
    if step_name not in REFINE_STEPS:
        return RefineResult(
            success=False,
            step_name=step_name,
            errors=[f"Unknown refine step: {step_name}"],
        )

    step_class = REFINE_STEPS[step_name]
    step_instance = step_class()

    try:
        return step_instance.run(
            archimate_manager=archimate_manager,
            graph_manager=graph_manager,
            llm_query_fn=llm_query_fn,
            params=params,
        )
    except Exception as e:
        logger.exception(f"Error running refine step {step_name}: {e}")
        return RefineResult(
            success=False,
            step_name=step_name,
            errors=[str(e)],
        )


def normalize_name(name: str) -> str:
    """Normalize element name for comparison.

    Converts to lowercase, removes common prefixes/suffixes,
    normalizes whitespace, and applies synonym mappings.
    """
    if not name:
        return ""

    normalized = name.lower().strip()
    # Remove common prefixes
    for prefix in ["the ", "a ", "an "]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    # Normalize whitespace and separators
    normalized = normalized.replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())

    # Apply generic synonym normalization (not repo-specific!)
    # These are common semantic equivalents in software architecture
    synonyms = {
        # Action verbs
        "insert": "create",
        "add": "create",
        "new": "create",
        "remove": "delete",
        "destroy": "delete",
        "modify": "update",
        "edit": "update",
        "change": "update",
        # Document/rendering concepts
        "generation": "rendering",
        "generator": "renderer",
        "generate": "render",
        # Database concepts
        "database": "db",
        "datastore": "db",
        "storage": "db",
        # Process/handling concepts
        "handling": "processing",
        "handler": "processor",
        "handle": "process",
        # Common suffixes
        "details": "detail",
        "items": "item",
    }

    words = normalized.split()
    normalized_words = [synonyms.get(word, word) for word in words]
    return " ".join(normalized_words)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(s1: str, s2: str) -> float:
    """Calculate similarity ratio between two strings (0.0 to 1.0)."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1.0 - (distance / max_len)
