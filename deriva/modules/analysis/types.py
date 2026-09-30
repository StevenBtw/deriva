"""
Type definitions for analysis module.

Pure dataclasses for representing analysis results. No behavior, no I/O.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "StepConsistency",
    "ConfigDeviation",
    "DeviationReport",
    "InconsistencyInfo",
    "IntraModelMetrics",
    "InterModelMetrics",
    # Comprehensive analysis types
    "StabilityBreakdown",
    "PhaseStabilityReport",
    "ReferenceElement",
    "ReferenceRelationship",
    "SemanticMatch",
    "SemanticMatchReport",
    "FitAnalysis",
    "CrossRepoComparison",
    "BenchmarkReport",
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
    edge_type_breakdown: dict[str, float] = field(default_factory=dict)  # CONTAINS: 95%, etc.

    # Relationship consistency (derivation phase)
    relationship_counts: list[int] = field(default_factory=list)
    relationship_count_variance: float = 0.0
    relationship_consistency: float = 100.0  # % of relationships in ALL runs
    stable_relationships: list[str] = field(default_factory=list)
    unstable_relationships: dict[str, int] = field(default_factory=dict)
    relationship_type_breakdown: dict[str, float] = field(default_factory=dict)  # Serving: 90%, etc.

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
    relationship_overlap: list[str] = field(default_factory=list)  # Relationships in ALL models
    relationship_unique_by_model: dict[str, list[str]] = field(default_factory=dict)
    relationship_jaccard: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# Comprehensive Benchmark Analysis Types
# ============================================================================


@dataclass
class AnswerStability:
    """Raw LLM answer stability of one step: the same prompt answered identically in every run.

    Reported next to output consistency, so that voting or deterministic
    post-processing cannot hide the variance of the LLM itself.
    """

    step: str
    prompts: int  # prompts asked in every run
    identical: int  # of those, answered identically in every run

    @property
    def score(self) -> float:
        return self.identical / self.prompts if self.prompts else 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {"step": self.step, "prompts": self.prompts, "identical": self.identical, "score": self.score}


@dataclass
class DecisionStability:
    """Per-item decisions of a classification step (one label per term): decided alike in every run.

    Finer than ``AnswerStability`` for batched prompts, where one changed label makes a
    whole batch answer differ. A skipped item (no decision) counts as a decision of its own.
    """

    items: int  # items decided in any run
    stable: int  # of those, with the same decision in every run

    @property
    def score(self) -> float:
        return self.stable / self.items if self.items else 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {"items": self.items, "stable": self.stable, "score": self.score}


@dataclass
class StepConsistency:
    """One step repeated on a fixed input: how often its outputs agree across runs.

    Presence compares which objects the runs produced; exact also requires the same
    properties. ``property_differences`` names the properties that differ, per object
    present in every run.
    """

    runs: int
    counts: list[int]  # objects produced per run
    present: int  # objects produced in every run
    total: int  # objects produced in any run
    identical: int  # of those in every run, with the same properties in every run
    property_differences: dict[str, int] = field(default_factory=dict)
    groups: dict[str, StepConsistency] = field(default_factory=dict)

    @property
    def presence_score(self) -> float:
        return self.present / self.total if self.total else 1.0

    @property
    def exact_score(self) -> float:
        return self.identical / self.total if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "runs": self.runs,
            "counts": self.counts,
            "present": self.present,
            "total": self.total,
            "identical": self.identical,
            "presence_score": self.presence_score,
            "exact_score": self.exact_score,
            "property_differences": self.property_differences,
            "groups": {name: group.to_dict() for name, group in self.groups.items()},
        }


@dataclass
class StabilityBreakdown:
    """Stability metrics breakdown by item type."""

    item_type: str  # e.g., "ApplicationComponent", "Serving", "CONTAINS"
    phase: str  # "extraction" or "derivation"
    total_count: int  # Total unique items across all runs
    stable_count: int  # Items appearing in ALL runs
    unstable_count: int  # Items appearing in SOME runs
    consistency_score: float  # stable_count / total_count (0.0 to 1.0)
    stable_items: list[str] = field(default_factory=list)
    unstable_items: dict[str, int] = field(default_factory=dict)  # item -> run_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PhaseStabilityReport:
    """Stability report for extraction or derivation phase."""

    phase: str  # "extraction" or "derivation"
    repository: str
    model: str
    total_runs: int
    overall_consistency: float  # Average consistency across all types

    # For extraction phase
    node_breakdown: list[StabilityBreakdown] = field(default_factory=list)
    edge_breakdown: list[StabilityBreakdown] = field(default_factory=list)

    # For derivation phase
    element_breakdown: list[StabilityBreakdown] = field(default_factory=list)
    relationship_breakdown: list[StabilityBreakdown] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "phase": self.phase,
            "repository": self.repository,
            "model": self.model,
            "total_runs": self.total_runs,
            "overall_consistency": self.overall_consistency,
            "node_breakdown": [b.to_dict() for b in self.node_breakdown],
            "edge_breakdown": [b.to_dict() for b in self.edge_breakdown],
            "element_breakdown": [b.to_dict() for b in self.element_breakdown],
            "relationship_breakdown": [b.to_dict() for b in self.relationship_breakdown],
        }


@dataclass
class ReferenceElement:
    """Element from a reference ArchiMate model."""

    identifier: str
    name: str
    element_type: str  # e.g., "ApplicationComponent", "BusinessProcess"
    layer: str = ""  # "Business", "Application", "Technology"
    documentation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ReferenceRelationship:
    """Relationship from a reference ArchiMate model."""

    identifier: str
    source: str  # Source element identifier
    target: str  # Target element identifier
    relationship_type: str  # e.g., "Composition", "Serving"
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class SemanticMatch:
    """Match result between a derived element and reference element."""

    derived_id: str
    derived_name: str
    derived_type: str
    reference_id: str | None  # None if no match found
    reference_name: str | None
    reference_type: str | None
    match_type: str  # "exact", "fuzzy_name", "type_only", "no_match"
    similarity_score: float  # 0.0 to 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class SemanticMatchReport:
    """Semantic comparison results between derived and reference models."""

    repository: str
    reference_model_path: str
    derived_run: str

    # Element matching
    total_derived_elements: int
    total_reference_elements: int
    correctly_derived: list[SemanticMatch] = field(default_factory=list)
    missing_elements: list[ReferenceElement] = field(default_factory=list)
    spurious_elements: list[str] = field(default_factory=list)

    # Relationship matching
    total_derived_relationships: int = 0
    total_reference_relationships: int = 0
    correctly_derived_relationships: list[SemanticMatch] = field(default_factory=list)
    missing_relationships: list[ReferenceRelationship] = field(default_factory=list)
    spurious_relationships: list[str] = field(default_factory=list)

    # Aggregate metrics
    element_precision: float = 0.0  # correctly_derived / total_derived
    element_recall: float = 0.0  # correctly_derived / total_reference
    element_f1: float = 0.0
    relationship_precision: float = 0.0
    relationship_recall: float = 0.0
    relationship_f1: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "repository": self.repository,
            "reference_model_path": self.reference_model_path,
            "derived_run": self.derived_run,
            "total_derived_elements": self.total_derived_elements,
            "total_reference_elements": self.total_reference_elements,
            "correctly_derived": [m.to_dict() for m in self.correctly_derived],
            "missing_elements": [e.to_dict() for e in self.missing_elements],
            "spurious_elements": self.spurious_elements,
            "total_derived_relationships": self.total_derived_relationships,
            "total_reference_relationships": self.total_reference_relationships,
            "correctly_derived_relationships": [m.to_dict() for m in self.correctly_derived_relationships],
            "missing_relationships": [r.to_dict() for r in self.missing_relationships],
            "spurious_relationships": self.spurious_relationships,
            "element_precision": self.element_precision,
            "element_recall": self.element_recall,
            "element_f1": self.element_f1,
            "relationship_precision": self.relationship_precision,
            "relationship_recall": self.relationship_recall,
            "relationship_f1": self.relationship_f1,
        }


@dataclass
class FitAnalysis:
    """Analysis of how well a derived model fits the codebase."""

    repository: str
    run_id: str

    # Coverage metrics
    coverage_score: float  # 0.0 to 1.0 - how well codebase concepts are captured
    concepts_covered: list[str] = field(default_factory=list)
    concepts_missing: list[str] = field(default_factory=list)

    # Underfit detection (model too simple)
    underfit_score: float = 0.0  # Higher = more underfit
    underfit_indicators: list[str] = field(default_factory=list)

    # Overfit detection (model has spurious elements)
    overfit_score: float = 0.0  # Higher = more overfit
    overfit_indicators: list[str] = field(default_factory=list)

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class CrossRepoComparison:
    """Comparison of benchmark results across multiple repositories."""

    repositories: list[str]
    model: str

    # Per-repo metrics
    consistency_by_repo: dict[str, float] = field(default_factory=dict)
    element_count_by_repo: dict[str, int] = field(default_factory=dict)
    precision_by_repo: dict[str, float] = field(default_factory=dict)
    recall_by_repo: dict[str, float] = field(default_factory=dict)

    # Best/worst performers (sorted by consistency)
    best_element_types: list[tuple[str, float]] = field(default_factory=list)
    worst_element_types: list[tuple[str, float]] = field(default_factory=list)
    best_relationship_types: list[tuple[str, float]] = field(default_factory=list)
    worst_relationship_types: list[tuple[str, float]] = field(default_factory=list)

    # Generalization analysis
    generalizable_patterns: list[str] = field(default_factory=list)
    repo_specific_issues: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class BenchmarkReport:
    """Full comprehensive benchmark analysis report."""

    session_ids: list[str]
    repositories: list[str]
    models: list[str]
    generated_at: str

    # 1. Stability Analysis
    stability_reports: dict[str, dict[str, PhaseStabilityReport]] = field(default_factory=dict)  # repo -> phase -> report
    # Raw LLM answer stability, so voting or post-processing cannot hide LLM variance
    answer_stability: dict[str, list[AnswerStability]] = field(default_factory=dict)  # repo -> per step

    # 2. Semantic Match Analysis
    semantic_reports: dict[str, SemanticMatchReport] = field(default_factory=dict)  # repo -> report

    # 3. Fit Analysis
    fit_analyses: dict[str, FitAnalysis] = field(default_factory=dict)  # repo -> analysis

    # 4. Cross-Repository Comparison
    cross_repo: CrossRepoComparison | None = None

    # Summary metrics
    overall_consistency: float = 0.0
    overall_precision: float = 0.0
    overall_recall: float = 0.0

    # Recommendations
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "meta": {
                "session_ids": self.session_ids,
                "repositories": self.repositories,
                "models": self.models,
                "generated_at": self.generated_at,
            },
            "stability": {repo: {phase: report.to_dict() for phase, report in phases.items()} for repo, phases in self.stability_reports.items()},
            "answer_stability": {repo: [s.to_dict() for s in steps] for repo, steps in self.answer_stability.items()},
            "semantic_match": {repo: report.to_dict() for repo, report in self.semantic_reports.items()},
            "fit_analysis": {repo: analysis.to_dict() for repo, analysis in self.fit_analyses.items()},
            "cross_repo": self.cross_repo.to_dict() if self.cross_repo else None,
            "summary": {
                "overall_consistency": self.overall_consistency,
                "overall_precision": self.overall_precision,
                "overall_recall": self.overall_recall,
            },
            "recommendations": self.recommendations,
        }

    def to_markdown(self) -> str:
        """Generate human-readable markdown summary."""
        lines = [
            "# Comprehensive Benchmark Analysis Report",
            "",
            f"**Generated:** {self.generated_at}",
            f"**Sessions:** {', '.join(self.session_ids)}",
            f"**Repositories:** {', '.join(self.repositories)}",
            f"**Models:** {', '.join(self.models)}",
            "",
            "## Executive Summary",
            "",
            "| Repository | Consistency | Precision | Recall | F1 |",
            "|------------|-------------|-----------|--------|-----|",
        ]

        for repo in self.repositories:
            consistency = self.stability_reports.get(repo, {}).get("derivation", PhaseStabilityReport("", repo, "", 0, 0.0)).overall_consistency
            semantic = self.semantic_reports.get(repo)
            precision = semantic.element_precision if semantic else 0.0
            recall = semantic.element_recall if semantic else 0.0
            f1 = semantic.element_f1 if semantic else 0.0
            lines.append(f"| {repo} | {consistency:.1%} | {precision:.1%} | {recall:.1%} | {f1:.2f} |")

        lines.extend(
            [
                "",
                "## 1. Stability Analysis",
                "",
            ]
        )

        for repo, phases in self.stability_reports.items():
            lines.append(f"### {repo}")
            for phase, report in phases.items():
                lines.append(f"**{phase.title()} Phase:** {report.overall_consistency:.1%} consistency")
                if report.element_breakdown:
                    lines.append("| Element Type | Consistency | Stable | Unstable |")
                    lines.append("|--------------|-------------|--------|----------|")
                    for b in sorted(report.element_breakdown, key=lambda x: -x.consistency_score):
                        lines.append(f"| {b.item_type} | {b.consistency_score:.1%} | {b.stable_count} | {b.unstable_count} |")
            lines.append("")

        if self.answer_stability:
            lines.extend(["### LLM Answer Stability", "", "The same prompt given the same decisions in every run (raw LLM output; free text and confidence left out).", ""])
            for repo, steps in self.answer_stability.items():
                lines.extend([f"**{repo}**", "", "| Step | Prompts | Identical | Score |", "|------|---------|-----------|-------|"])
                lines.extend(f"| {s.step} | {s.prompts} | {s.identical} | {s.score:.1%} |" for s in steps)
                lines.append("")

        if self.semantic_reports:
            lines.extend(
                [
                    "## 2. Semantic Match with Reference Models",
                    "",
                ]
            )
            for repo, report in self.semantic_reports.items():
                lines.extend(
                    [
                        f"### {repo}",
                        f"- **Reference:** {report.reference_model_path}",
                        f"- **Precision:** {report.element_precision:.1%}",
                        f"- **Recall:** {report.element_recall:.1%}",
                        f"- **F1 Score:** {report.element_f1:.2f}",
                        f"- **Correctly Derived:** {len(report.correctly_derived)}",
                        f"- **Missing Elements:** {len(report.missing_elements)}",
                        f"- **Spurious Elements:** {len(report.spurious_elements)}",
                        "",
                    ]
                )

        if self.cross_repo:
            lines.extend(
                [
                    "## 3. Best/Worst Performing",
                    "",
                    "### Best Element Types",
                    "| Type | Avg Consistency |",
                    "|------|-----------------|",
                ]
            )
            for t, score in self.cross_repo.best_element_types[:5]:
                lines.append(f"| {t} | {score:.1%} |")

            lines.extend(
                [
                    "",
                    "### Worst Element Types",
                    "| Type | Avg Consistency |",
                    "|------|-----------------|",
                ]
            )
            for t, score in self.cross_repo.worst_element_types[:5]:
                lines.append(f"| {t} | {score:.1%} |")
            lines.append("")

        if self.recommendations:
            lines.extend(
                [
                    "## 4. Recommendations",
                    "",
                ]
            )
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")

        return "\n".join(lines)
