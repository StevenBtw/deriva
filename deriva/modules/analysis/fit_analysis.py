"""
Pure functions for fit/underfit/overfit analysis.

This module provides:
- Coverage analysis (how well derived model covers codebase concepts)
- Underfit detection (model too simple, missing elements)
- Overfit detection (spurious elements not grounded in codebase)
"""

from __future__ import annotations

from typing import Any

from .types import FitAnalysis, ReferenceElement, SemanticMatchReport

__all__ = [
    "analyze_coverage",
    "detect_underfit",
    "detect_overfit",
    "create_fit_analysis",
]

# Expected element types per layer for coverage analysis
EXPECTED_ELEMENT_TYPES = {
    "Application": [
        "ApplicationComponent",
        "ApplicationService",
        "ApplicationInterface",
        "DataObject",
    ],
    "Business": [
        "BusinessProcess",
        "BusinessActor",
        "BusinessRole",
        "BusinessObject",
        "BusinessService",
    ],
    "Technology": [
        "TechnologyService",
        "Node",
        "Artifact",
        "SystemSoftware",
    ],
}


def analyze_coverage(
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    semantic_report: SemanticMatchReport | None = None,
) -> tuple[float, list[str], list[str]]:
    """
    Compute coverage score: how well does derived model cover expected concepts.

    Coverage is based on:
    - Presence of expected element types
    - Match rate against reference elements (if available)
    - Layer balance (Application vs Business vs Technology)

    Args:
        derived_elements: List of derived elements
        reference_elements: List of reference elements
        semantic_report: Optional semantic match report for additional context

    Returns:
        Tuple of (coverage_score, concepts_covered, concepts_missing)
    """
    concepts_covered = []
    concepts_missing = []

    # Collect derived element types
    derived_types = set()
    for elem in derived_elements:
        elem_type = elem.get("type", elem.get("element_type", ""))
        if elem_type:
            derived_types.add(elem_type)

    # Check coverage of expected element types
    all_expected = set()
    for layer_types in EXPECTED_ELEMENT_TYPES.values():
        all_expected.update(layer_types)

    for elem_type in all_expected:
        if elem_type in derived_types:
            concepts_covered.append(f"{elem_type} (derived)")
        else:
            concepts_missing.append(f"{elem_type} (not derived)")

    # Check layer balance
    layer_counts = {"Application": 0, "Business": 0, "Technology": 0}
    for elem in derived_elements:
        elem_type = elem.get("type", elem.get("element_type", ""))
        for layer, types in EXPECTED_ELEMENT_TYPES.items():
            if elem_type in types:
                layer_counts[layer] += 1
                break

    # Identify missing layers
    for layer, count in layer_counts.items():
        if count == 0:
            concepts_missing.append(f"{layer} layer (no elements)")
        elif count < 2:
            concepts_missing.append(f"{layer} layer (only {count} element)")

    # If we have semantic report, use precision/recall for coverage
    if semantic_report:
        # Weight coverage by recall (how much of reference is captured)
        match_coverage = semantic_report.element_recall
    else:
        # Fall back to type coverage
        covered_count = sum(1 for t in all_expected if t in derived_types)
        match_coverage = covered_count / len(all_expected) if all_expected else 0.0

    # Compute final coverage score
    # Weight: 60% reference match, 40% type diversity
    type_coverage = len(derived_types) / len(all_expected) if all_expected else 0.0
    coverage_score = 0.6 * match_coverage + 0.4 * min(type_coverage, 1.0)

    return coverage_score, concepts_covered, concepts_missing


def detect_underfit(
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    semantic_report: SemanticMatchReport | None = None,
    extraction_stats: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    """
    Detect underfit: model is too simple, missing expected concepts.

    Underfit indicators:
    - Low element count relative to codebase/reference size
    - Missing entire element types
    - Low relationship-to-element ratio
    - Low recall against reference

    Args:
        derived_elements: List of derived elements
        reference_elements: List of reference elements
        semantic_report: Optional semantic match report
        extraction_stats: Optional extraction statistics (nodes/edges extracted)

    Returns:
        Tuple of (underfit_score, indicators)
    """
    indicators = []
    scores = []

    # 1. Element count relative to reference
    if reference_elements:
        element_ratio = len(derived_elements) / len(reference_elements)
        if element_ratio < 0.3:
            indicators.append(f"Very low element count: {len(derived_elements)} vs {len(reference_elements)} reference ({element_ratio:.0%})")
            scores.append(1.0 - element_ratio)
        elif element_ratio < 0.5:
            indicators.append(f"Low element count: {len(derived_elements)} vs {len(reference_elements)} reference ({element_ratio:.0%})")
            scores.append(0.5 * (1.0 - element_ratio))

    # 2. Missing element types
    reference_types = {e.element_type for e in reference_elements}
    derived_types = {e.get("type", e.get("element_type", "")) for e in derived_elements}

    missing_types = reference_types - derived_types
    if missing_types:
        missing_count = len(missing_types)
        total_types = len(reference_types)
        if missing_count / total_types > 0.5:
            indicators.append(f"Many missing element types: {missing_count}/{total_types} types not derived")
            scores.append(missing_count / total_types)

    # 3. Low recall (from semantic report)
    if semantic_report and semantic_report.element_recall < 0.5:
        indicators.append(f"Low recall against reference: {semantic_report.element_recall:.0%}")
        scores.append(1.0 - semantic_report.element_recall)

    # 4. Extraction to derivation ratio
    if extraction_stats:
        nodes_extracted = extraction_stats.get("nodes_created", 0)
        if nodes_extracted > 0:
            derivation_ratio = len(derived_elements) / nodes_extracted
            if derivation_ratio < 0.1:
                indicators.append(f"Low derivation rate: {len(derived_elements)} elements from {nodes_extracted} nodes ({derivation_ratio:.0%})")
                scores.append(1.0 - derivation_ratio)

    # Calculate overall underfit score
    underfit_score = sum(scores) / len(scores) if scores else 0.0

    return underfit_score, indicators


def detect_overfit(
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    semantic_report: SemanticMatchReport | None = None,
    codebase_stats: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    """
    Detect overfit: model has spurious elements not grounded in codebase.

    Overfit indicators:
    - Many spurious elements (derived but not in reference)
    - Low precision
    - Element count much higher than reference
    - Duplicate/very similar element names

    Args:
        derived_elements: List of derived elements
        reference_elements: List of reference elements
        semantic_report: Optional semantic match report
        codebase_stats: Optional codebase statistics

    Returns:
        Tuple of (overfit_score, indicators)
    """
    indicators = []
    scores = []

    # 1. Spurious element count
    if semantic_report and semantic_report.spurious_elements:
        spurious_count = len(semantic_report.spurious_elements)
        total_derived = len(derived_elements)
        spurious_ratio = spurious_count / total_derived if total_derived > 0 else 0.0

        if spurious_ratio > 0.5:
            indicators.append(f"High spurious element rate: {spurious_count}/{total_derived} ({spurious_ratio:.0%}) not in reference")
            scores.append(spurious_ratio)
        elif spurious_ratio > 0.3:
            indicators.append(f"Moderate spurious element rate: {spurious_count}/{total_derived} ({spurious_ratio:.0%}) not in reference")
            scores.append(0.5 * spurious_ratio)

    # 2. Low precision
    if semantic_report and semantic_report.element_precision < 0.5:
        indicators.append(f"Low precision: {semantic_report.element_precision:.0%} of derived elements match reference")
        scores.append(1.0 - semantic_report.element_precision)

    # 3. Element count much higher than reference
    if reference_elements:
        element_ratio = len(derived_elements) / len(reference_elements)
        if element_ratio > 2.0:
            indicators.append(f"Over-generation: {len(derived_elements)} elements vs {len(reference_elements)} reference ({element_ratio:.1f}x)")
            scores.append(min((element_ratio - 1.0) / 2.0, 1.0))

    # 4. Duplicate/similar element names
    element_names = [e.get("name", "") for e in derived_elements if e.get("name")]
    if element_names:
        duplicates = _find_similar_names(element_names)
        if duplicates:
            indicators.append(f"Potential duplicates: {len(duplicates)} pairs of very similar element names")
            scores.append(min(len(duplicates) / len(element_names), 0.5))

    # Calculate overall overfit score
    overfit_score = sum(scores) / len(scores) if scores else 0.0

    return overfit_score, indicators


def _find_similar_names(names: list[str], threshold: float = 0.9) -> list[tuple[str, str]]:
    """
    Find pairs of very similar element names (potential duplicates).

    Args:
        names: List of element names
        threshold: Similarity threshold (default 0.9)

    Returns:
        List of (name1, name2) tuples that are very similar
    """
    from difflib import SequenceMatcher

    similar_pairs = []
    seen = set()

    for i, name1 in enumerate(names):
        for j, name2 in enumerate(names[i + 1 :], i + 1):
            if (name1, name2) in seen or (name2, name1) in seen:
                continue

            # Skip exact duplicates (handled separately)
            if name1.lower() == name2.lower():
                continue

            similarity = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
            if similarity >= threshold:
                similar_pairs.append((name1, name2))
                seen.add((name1, name2))

    return similar_pairs


def create_fit_analysis(
    repository: str,
    run_id: str,
    derived_elements: list[dict[str, Any]],
    reference_elements: list[ReferenceElement],
    semantic_report: SemanticMatchReport | None = None,
    extraction_stats: dict[str, Any] | None = None,
) -> FitAnalysis:
    """
    Create a complete fit analysis for a benchmark run.

    Args:
        repository: Repository name
        run_id: Run identifier
        derived_elements: List of derived elements
        reference_elements: List of reference elements
        semantic_report: Optional semantic match report
        extraction_stats: Optional extraction statistics

    Returns:
        FitAnalysis with all metrics
    """
    # Analyze coverage
    coverage_score, concepts_covered, concepts_missing = analyze_coverage(derived_elements, reference_elements, semantic_report)

    # Detect underfit
    underfit_score, underfit_indicators = detect_underfit(derived_elements, reference_elements, semantic_report, extraction_stats)

    # Detect overfit
    overfit_score, overfit_indicators = detect_overfit(derived_elements, reference_elements, semantic_report)

    # Generate recommendations
    recommendations = _generate_fit_recommendations(
        coverage_score,
        underfit_score,
        underfit_indicators,
        overfit_score,
        overfit_indicators,
    )

    return FitAnalysis(
        repository=repository,
        run_id=run_id,
        coverage_score=coverage_score,
        concepts_covered=concepts_covered,
        concepts_missing=concepts_missing,
        underfit_score=underfit_score,
        underfit_indicators=underfit_indicators,
        overfit_score=overfit_score,
        overfit_indicators=overfit_indicators,
        recommendations=recommendations,
    )


def _generate_fit_recommendations(
    coverage_score: float,
    underfit_score: float,
    underfit_indicators: list[str],
    overfit_score: float,
    overfit_indicators: list[str],
) -> list[str]:
    """
    Generate actionable recommendations based on fit analysis.

    Args:
        coverage_score: Coverage score (0-1)
        underfit_score: Underfit score (0-1)
        underfit_indicators: List of underfit indicators
        overfit_score: Overfit score (0-1)
        overfit_indicators: List of overfit indicators

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Coverage recommendations
    if coverage_score < 0.5:
        recommendations.append("LOW COVERAGE: Derived model captures less than 50% of expected concepts. Consider reviewing extraction and derivation configs.")
    elif coverage_score < 0.7:
        recommendations.append("MODERATE COVERAGE: Some concepts missing. Review element type configs.")

    # Underfit recommendations
    if underfit_score > 0.5:
        recommendations.append("HIGH UNDERFIT: Model is too simple. Consider adding more derivation configs or improving extraction coverage.")
        if "missing element types" in str(underfit_indicators).lower():
            recommendations.append("Enable derivation configs for missing element types.")
        if "low recall" in str(underfit_indicators).lower():
            recommendations.append("Improve element matching by relaxing derivation criteria.")

    # Overfit recommendations
    if overfit_score > 0.5:
        recommendations.append("HIGH OVERFIT: Model contains many spurious elements. Consider adding stricter filtering in derivation configs.")
        if "low precision" in str(overfit_indicators).lower():
            recommendations.append("Add explicit exclusion rules in derivation prompts.")
        if "duplicates" in str(overfit_indicators).lower():
            recommendations.append("Add deduplication logic or stricter naming rules.")

    # Balance recommendation
    if underfit_score > 0.3 and overfit_score > 0.3:
        recommendations.append("MIXED FIT ISSUES: Both underfit and overfit detected. Focus on precision (reducing false positives) first, then recall.")

    if not recommendations:
        recommendations.append("GOOD FIT: Model appears well-calibrated to the reference.")

    return recommendations
