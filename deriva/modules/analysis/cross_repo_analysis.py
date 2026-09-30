"""
Pure functions for cross-repository comparison analysis.

This module provides:
- Comparison of benchmark results across multiple repositories
- Identification of generalizable patterns
- Detection of repository-specific issues
"""

from __future__ import annotations

from collections import defaultdict

from .types import (
    CrossRepoComparison,
    FitAnalysis,
    PhaseStabilityReport,
    SemanticMatchReport,
)

__all__ = [
    "compare_across_repos",
    "identify_generalizable_patterns",
    "identify_repo_specific_issues",
    "rank_element_types",
    "rank_relationship_types",
]


def compare_across_repos(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
    semantic_reports: dict[str, SemanticMatchReport],
    fit_analyses: dict[str, FitAnalysis],
    model: str,
) -> CrossRepoComparison:
    """
    Compare benchmark results across multiple repositories.

    Args:
        stability_reports: Dict mapping repo -> phase -> report
        semantic_reports: Dict mapping repo -> semantic match report
        fit_analyses: Dict mapping repo -> fit analysis
        model: Model name used in benchmarks

    Returns:
        CrossRepoComparison with aggregated metrics
    """
    repositories = list(set(stability_reports.keys()) | set(semantic_reports.keys()) | set(fit_analyses.keys()))

    # Collect per-repo metrics
    consistency_by_repo = {}
    element_count_by_repo = {}
    precision_by_repo = {}
    recall_by_repo = {}

    for repo in repositories:
        # Consistency from derivation phase
        if repo in stability_reports and "derivation" in stability_reports[repo]:
            consistency_by_repo[repo] = stability_reports[repo]["derivation"].overall_consistency
        else:
            consistency_by_repo[repo] = 0.0

        # Precision and recall from semantic reports
        if repo in semantic_reports:
            sr = semantic_reports[repo]
            precision_by_repo[repo] = sr.element_precision
            recall_by_repo[repo] = sr.element_recall
            element_count_by_repo[repo] = sr.total_derived_elements
        else:
            precision_by_repo[repo] = 0.0
            recall_by_repo[repo] = 0.0
            element_count_by_repo[repo] = 0

    # Rank element types by consistency across repos
    best_element_types, worst_element_types = rank_element_types(stability_reports)

    # Rank relationship types
    best_relationship_types, worst_relationship_types = rank_relationship_types(stability_reports)

    # Identify patterns
    generalizable_patterns = identify_generalizable_patterns(stability_reports, threshold=0.8)
    repo_specific_issues = identify_repo_specific_issues(stability_reports, semantic_reports)

    return CrossRepoComparison(
        repositories=repositories,
        model=model,
        consistency_by_repo=consistency_by_repo,
        element_count_by_repo=element_count_by_repo,
        precision_by_repo=precision_by_repo,
        recall_by_repo=recall_by_repo,
        best_element_types=best_element_types,
        worst_element_types=worst_element_types,
        best_relationship_types=best_relationship_types,
        worst_relationship_types=worst_relationship_types,
        generalizable_patterns=generalizable_patterns,
        repo_specific_issues=repo_specific_issues,
    )


def rank_element_types(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """
    Rank element types by average consistency across repositories.

    Args:
        stability_reports: Dict mapping repo -> phase -> report

    Returns:
        Tuple of (best_types, worst_types) as lists of (type, avg_consistency)
    """
    type_scores: dict[str, list[float]] = defaultdict(list)

    for repo, phases in stability_reports.items():
        if "derivation" in phases:
            for breakdown in phases["derivation"].element_breakdown:
                type_scores[breakdown.item_type].append(breakdown.consistency_score)

    # Calculate averages
    type_avgs = [(t, sum(scores) / len(scores)) for t, scores in type_scores.items() if scores]
    type_avgs.sort(key=lambda x: -x[1])  # Descending

    # Top 5 and bottom 5
    best_types = type_avgs[:5]
    worst_types = type_avgs[-5:][::-1] if len(type_avgs) > 5 else type_avgs[::-1]

    return best_types, worst_types


def rank_relationship_types(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """
    Rank relationship types by average consistency across repositories.

    Args:
        stability_reports: Dict mapping repo -> phase -> report

    Returns:
        Tuple of (best_types, worst_types) as lists of (type, avg_consistency)
    """
    type_scores: dict[str, list[float]] = defaultdict(list)

    for repo, phases in stability_reports.items():
        if "derivation" in phases:
            for breakdown in phases["derivation"].relationship_breakdown:
                type_scores[breakdown.item_type].append(breakdown.consistency_score)

    # Calculate averages
    type_avgs = [(t, sum(scores) / len(scores)) for t, scores in type_scores.items() if scores]
    type_avgs.sort(key=lambda x: -x[1])  # Descending

    # Top 5 and bottom 5
    best_types = type_avgs[:5]
    worst_types = type_avgs[-5:][::-1] if len(type_avgs) > 5 else type_avgs[::-1]

    return best_types, worst_types


def identify_generalizable_patterns(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
    threshold: float = 0.8,
) -> list[str]:
    """
    Find patterns that work well across all repositories.

    A pattern is generalizable if:
    - It appears in all repositories
    - It has consistency >= threshold in all repositories

    Args:
        stability_reports: Dict mapping repo -> phase -> report
        threshold: Minimum consistency to be considered "working well"

    Returns:
        List of pattern descriptions
    """
    patterns = []
    repos = list(stability_reports.keys())

    if not repos:
        return patterns

    # Collect element type consistency across repos
    element_consistency: dict[str, dict[str, float]] = defaultdict(dict)
    relationship_consistency: dict[str, dict[str, float]] = defaultdict(dict)

    for repo, phases in stability_reports.items():
        if "derivation" in phases:
            for breakdown in phases["derivation"].element_breakdown:
                element_consistency[breakdown.item_type][repo] = breakdown.consistency_score

            for breakdown in phases["derivation"].relationship_breakdown:
                relationship_consistency[breakdown.item_type][repo] = breakdown.consistency_score

    # Find element types that work well everywhere
    for elem_type, repo_scores in element_consistency.items():
        if len(repo_scores) == len(repos):  # Present in all repos
            min_score = min(repo_scores.values())
            if min_score >= threshold:
                avg_score = sum(repo_scores.values()) / len(repo_scores)
                patterns.append(f"Element type '{elem_type}' is stable across all repos (avg: {avg_score:.0%}, min: {min_score:.0%})")

    # Find relationship types that work well everywhere
    for rel_type, repo_scores in relationship_consistency.items():
        if len(repo_scores) == len(repos):
            min_score = min(repo_scores.values())
            if min_score >= threshold:
                avg_score = sum(repo_scores.values()) / len(repo_scores)
                patterns.append(f"Relationship type '{rel_type}' is stable across all repos (avg: {avg_score:.0%}, min: {min_score:.0%})")

    # Check for consistent extraction patterns
    for repo, phases in stability_reports.items():
        if "extraction" in phases:
            extraction = phases["extraction"]
            if extraction.overall_consistency >= threshold:
                patterns.append(f"Extraction phase is stable on {repo} ({extraction.overall_consistency:.0%})")

    return patterns


def identify_repo_specific_issues(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
    semantic_reports: dict[str, SemanticMatchReport],
    low_consistency_threshold: float = 0.5,
    low_precision_threshold: float = 0.5,
) -> dict[str, list[str]]:
    """
    Find patterns that only fail on specific repositories.

    Args:
        stability_reports: Dict mapping repo -> phase -> report
        semantic_reports: Dict mapping repo -> semantic match report
        low_consistency_threshold: Below this is considered an issue
        low_precision_threshold: Below this is considered an issue

    Returns:
        Dict mapping repo -> list of issues specific to that repo
    """
    issues: dict[str, list[str]] = defaultdict(list)
    repos = list(stability_reports.keys()) + list(semantic_reports.keys())
    repos = list(set(repos))

    # Collect per-type consistency across repos
    element_consistency: dict[str, dict[str, float]] = defaultdict(dict)

    for repo, phases in stability_reports.items():
        if "derivation" in phases:
            for breakdown in phases["derivation"].element_breakdown:
                element_consistency[breakdown.item_type][repo] = breakdown.consistency_score

    # Find element types that fail on specific repos
    for elem_type, repo_scores in element_consistency.items():
        if len(repo_scores) < 2:
            continue

        avg_score = sum(repo_scores.values()) / len(repo_scores)

        for repo, score in repo_scores.items():
            # Check if this repo is significantly worse than average
            if score < low_consistency_threshold and score < avg_score * 0.7:
                issues[repo].append(f"Element type '{elem_type}' underperforms: {score:.0%} vs {avg_score:.0%} avg")

    # Check semantic report issues
    if semantic_reports:
        avg_precision = sum(s.element_precision for s in semantic_reports.values()) / len(semantic_reports)
        avg_recall = sum(s.element_recall for s in semantic_reports.values()) / len(semantic_reports)

        for repo, sr in semantic_reports.items():
            if sr.element_precision < low_precision_threshold:
                if sr.element_precision < avg_precision * 0.7:
                    issues[repo].append(f"Low precision: {sr.element_precision:.0%} vs {avg_precision:.0%} avg")

            if sr.element_recall < low_precision_threshold:
                if sr.element_recall < avg_recall * 0.7:
                    issues[repo].append(f"Low recall: {sr.element_recall:.0%} vs {avg_recall:.0%} avg")

            if sr.spurious_elements and len(sr.spurious_elements) > 10:
                issues[repo].append(f"High spurious count: {len(sr.spurious_elements)} unmatched elements")

    # Check derivation consistency issues
    for repo, phases in stability_reports.items():
        if "derivation" in phases:
            derivation = phases["derivation"]
            if derivation.overall_consistency < low_consistency_threshold:
                issues[repo].append(f"Overall derivation consistency low: {derivation.overall_consistency:.0%}")

            # Check for problematic element types
            for breakdown in derivation.element_breakdown:
                if breakdown.consistency_score < 0.3 and breakdown.total_count > 2:
                    issues[repo].append(f"Very unstable: {breakdown.item_type} at {breakdown.consistency_score:.0%}")

    return dict(issues)


def generate_cross_repo_recommendations(
    comparison: CrossRepoComparison,
) -> list[str]:
    """
    Generate recommendations based on cross-repository comparison.

    Args:
        comparison: CrossRepoComparison object

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Check for consistently good/bad patterns
    if comparison.best_element_types:
        best_type, best_score = comparison.best_element_types[0]
        if best_score >= 0.9:
            recommendations.append(f"STRONG: '{best_type}' derivation is highly stable ({best_score:.0%}). Use its config as a template for other element types.")

    if comparison.worst_element_types:
        worst_type, worst_score = comparison.worst_element_types[0]
        if worst_score < 0.5:
            recommendations.append(f"WEAK: '{worst_type}' derivation needs improvement ({worst_score:.0%}). Review the derivation prompt and add stricter naming rules.")

    # Check for repo-specific issues
    if comparison.repo_specific_issues:
        for repo, issues in comparison.repo_specific_issues.items():
            if len(issues) > 3:
                recommendations.append(f"INVESTIGATE: {repo} has multiple issues ({len(issues)}). May indicate configs don't generalize to this codebase type.")

    # Check for generalizable patterns
    if comparison.generalizable_patterns:
        recommendations.append(f"GOOD NEWS: {len(comparison.generalizable_patterns)} patterns work across all repos. These configs are production-ready.")

    # Check precision/recall balance
    if comparison.precision_by_repo and comparison.recall_by_repo:
        avg_precision = sum(comparison.precision_by_repo.values()) / len(comparison.precision_by_repo)
        avg_recall = sum(comparison.recall_by_repo.values()) / len(comparison.recall_by_repo)

        if avg_precision > avg_recall * 1.5:
            recommendations.append(
                f"BALANCE: Precision ({avg_precision:.0%}) much higher than recall ({avg_recall:.0%}). Consider adding more derivation rules to capture missing concepts."
            )
        elif avg_recall > avg_precision * 1.5:
            recommendations.append(f"BALANCE: Recall ({avg_recall:.0%}) much higher than precision ({avg_precision:.0%}). Consider adding filtering to reduce false positives.")

    return recommendations
