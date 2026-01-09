"""
Type definitions for analysis module.

Pure dataclasses for representing analysis results. No behavior, no I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "ConfigDeviation",
    "DeviationReport",
    "InconsistencyInfo",
    "IntraModelMetrics",
    "InterModelMetrics",
]


@dataclass
class ConfigDeviation:
    """Deviation statistics for a single config."""

    config_type: str  # "extraction" or "derivation"
    config_id: str  # node_type or step_name
    deviation_count: int  # Number of objects that deviate
    total_objects: int  # Total objects produced by this config
    consistency_score: float  # 0.0 to 1.0 (1.0 = fully consistent)
    deviating_objects: list[str] = field(default_factory=list)
    stable_objects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class DeviationReport:
    """Complete deviation report for a benchmark session."""

    session_id: str
    analysis_timestamp: str
    total_runs: int
    total_deviations: int
    overall_consistency: float
    config_deviations: list[ConfigDeviation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "analysis_timestamp": self.analysis_timestamp,
            "total_runs": self.total_runs,
            "total_deviations": self.total_deviations,
            "overall_consistency": self.overall_consistency,
            "config_deviations": [cd.to_dict() for cd in self.config_deviations],
        }


@dataclass
class InconsistencyInfo:
    """Information about an inconsistent object across runs."""

    object_id: str
    object_type: str
    present_in: list[str]  # Run IDs where object appears
    missing_from: list[str]  # Run IDs where object is missing
    total_runs: int

    @property
    def consistency_score(self) -> float:
        """Fraction of runs where object appears (0.0 to 1.0)."""
        return len(self.present_in) / self.total_runs if self.total_runs > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            **asdict(self),
            "consistency_score": self.consistency_score,
        }


@dataclass
class IntraModelMetrics:
    """Consistency metrics for a single model across runs on the same repo."""

    model: str
    repository: str
    runs: int
    element_counts: list[int]
    count_variance: float
    name_consistency: float  # % of element names in ALL runs
    stable_elements: list[str] = field(default_factory=list)
    unstable_elements: dict[str, int] = field(default_factory=dict)

    # Edge consistency (extraction phase)
    edge_counts: list[int] = field(default_factory=list)
    edge_count_variance: float = 0.0
    edge_consistency: float = 100.0  # % of edges in ALL runs
    stable_edges: list[str] = field(default_factory=list)
    unstable_edges: dict[str, int] = field(default_factory=dict)
    edge_type_breakdown: dict[str, float] = field(
        default_factory=dict
    )  # CONTAINS: 95%, etc.

    # Relationship consistency (derivation phase)
    relationship_counts: list[int] = field(default_factory=list)
    relationship_count_variance: float = 0.0
    relationship_consistency: float = 100.0  # % of relationships in ALL runs
    stable_relationships: list[str] = field(default_factory=list)
    unstable_relationships: dict[str, int] = field(default_factory=dict)
    relationship_type_breakdown: dict[str, float] = field(
        default_factory=dict
    )  # Serving: 90%, etc.

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class InterModelMetrics:
    """Comparison metrics across models for the same repository."""

    repository: str
    models: list[str]
    elements_by_model: dict[str, list[str]]
    overlap: list[str]  # Elements in ALL models
    unique_by_model: dict[str, list[str]]  # Elements unique to each model
    jaccard_similarity: float

    # Edge comparison (extraction phase)
    edges_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_overlap: list[str] = field(default_factory=list)  # Edges in ALL models
    edge_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    edge_jaccard: float = 1.0

    # Relationship comparison (derivation phase)
    relationships_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_overlap: list[str] = field(
        default_factory=list
    )  # Relationships in ALL models
    relationship_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_jaccard: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
