"""
Pure functions for stability analysis across benchmark runs.

This module provides:
- Per-type stability breakdown (extraction and derivation phases)
- Pattern identification for stable vs unstable items
- Phase-level stability reports
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .types import AnswerStability, DecisionStability, PhaseStabilityReport, StabilityBreakdown, StepConsistency

__all__ = [
    "compute_type_breakdown",
    "compute_phase_stability",
    "identify_stability_patterns",
    "extract_element_type",
    "extract_node_type",
    "extract_edge_type",
    "extract_relationship_type",
]


def extract_element_type(element_id: str) -> str:
    """
    Extract element type from element identifier.

    Common patterns:
    - "ac_component_name" -> "ApplicationComponent" (ac_ prefix)
    - "bp_process_name" -> "BusinessProcess" (bp_ prefix)
    - "do_data_name" -> "DataObject" (do_ prefix)

    Args:
        element_id: Element identifier string

    Returns:
        Element type name or "Unknown"
    """
    prefix_map = {
        "ac_": "ApplicationComponent",
        "ai_": "ApplicationInterface",
        "as_": "ApplicationService",
        "af_": "ApplicationFunction",
        "ap_": "ApplicationProcess",
        "do_": "DataObject",
        "ba_": "BusinessActor",
        "br_": "BusinessRole",
        "bp_": "BusinessProcess",
        "bf_": "BusinessFunction",
        "bs_": "BusinessService",
        "bo_": "BusinessObject",
        "be_": "BusinessEvent",
        "ts_": "TechnologyService",
        "ti_": "TechnologyInterface",
        "tf_": "TechnologyFunction",
        "nd_": "Node",
        "dv_": "Device",
        "ss_": "SystemSoftware",
        "ar_": "Artifact",
        "techsvc_": "TechnologyService",
        "bus_obj_": "BusinessObject",
        "bus_proc_": "BusinessProcess",
        "app_comp_": "ApplicationComponent",
        "data_obj_": "DataObject",
    }

    element_lower = element_id.lower()
    for prefix, elem_type in prefix_map.items():
        if element_lower.startswith(prefix):
            return elem_type

    # Try to infer from camelCase/PascalCase patterns
    if "_" in element_id:
        parts = element_id.split("_")
        if len(parts) >= 2:
            # Check first two parts for known abbreviations
            abbrev = "_".join(parts[:2]).lower() + "_"
            if abbrev in prefix_map:
                return prefix_map[abbrev]

    return "Unknown"


def extract_node_type(node_id: str) -> str:
    """
    Extract node type from graph node identifier.

    Common patterns:
    - "Graph:BusinessConcept:xyz" -> "BusinessConcept"
    - "Graph:TypeDefinition:xyz" -> "TypeDefinition"
    - "bc_concept_name" -> "BusinessConcept"

    Args:
        node_id: Node identifier string

    Returns:
        Node type name or "Unknown"
    """
    # Check for Graph: prefix pattern
    if node_id.startswith("Graph:"):
        parts = node_id.split(":")
        if len(parts) >= 2:
            return parts[1]

    # Check for abbreviated prefixes
    prefix_map = {
        "bc_": "BusinessConcept",
        "td_": "TypeDefinition",
        "fn_": "Function",
        "md_": "Module",
        "cl_": "Class",
        "mt_": "Method",
        "dep_": "ExternalDependency",
        "dir_": "Directory",
        "file_": "File",
        "repo_": "Repository",
        "tech_": "Technology",
        "test_": "Test",
    }

    node_lower = node_id.lower()
    for prefix, node_type in prefix_map.items():
        if node_lower.startswith(prefix):
            return node_type

    return "Unknown"


def extract_edge_type(edge_id: str) -> str:
    """
    Extract edge type from edge identifier.

    Common patterns:
    - "CONTAINS:source:target" -> "CONTAINS"
    - "DEPENDS_ON:source:target" -> "DEPENDS_ON"

    Args:
        edge_id: Edge identifier string

    Returns:
        Edge type name or "Unknown"
    """
    # Check for TYPE:source:target pattern
    if ":" in edge_id:
        parts = edge_id.split(":")
        edge_type = parts[0].upper()
        if edge_type in (
            "CONTAINS",
            "DEPENDS_ON",
            "IMPORTS",
            "CALLS",
            "INHERITS",
            "IMPLEMENTS",
            "USES",
            "REFERENCES",
            "DEFINES",
            "HAS_METHOD",
            "HAS_ATTRIBUTE",
        ):
            return edge_type

    # Check for edge type as suffix
    edge_types = [
        "CONTAINS",
        "DEPENDS_ON",
        "IMPORTS",
        "CALLS",
        "INHERITS",
        "IMPLEMENTS",
        "USES",
    ]
    for et in edge_types:
        if et in edge_id.upper():
            return et

    return "Unknown"


def extract_relationship_type(rel_id: str) -> str:
    """
    Extract relationship type from relationship identifier.

    Common patterns:
    - "Composition:source:target" -> "Composition"
    - "Serving:source:target" -> "Serving"

    Args:
        rel_id: Relationship identifier string

    Returns:
        Relationship type name or "Unknown"
    """
    rel_types = [
        "Composition",
        "Aggregation",
        "Assignment",
        "Realization",
        "Serving",
        "Access",
        "Flow",
        "Triggering",
        "Specialization",
        "Association",
        "Influence",
    ]

    # Check for TYPE:source:target pattern
    if ":" in rel_id:
        parts = rel_id.split(":")
        rel_type = parts[0]
        # Normalize capitalization
        rel_type_lower = rel_type.lower()
        for rt in rel_types:
            if rt.lower() == rel_type_lower:
                return rt

    # Check for relationship type anywhere in ID
    rel_id_lower = rel_id.lower()
    for rt in rel_types:
        if rt.lower() in rel_id_lower:
            return rt

    return "Unknown"


def compute_type_breakdown(
    objects_by_run: dict[str, set[str]],
    type_extractor: Callable[[str], str],
    phase: str,
) -> list[StabilityBreakdown]:
    """
    Compute stability breakdown by object type.

    Args:
        objects_by_run: Dict mapping run_id -> set of object IDs
        type_extractor: Function to extract type from object ID
        phase: "extraction" or "derivation"

    Returns:
        List of StabilityBreakdown, one per type
    """
    if not objects_by_run:
        return []

    num_runs = len(objects_by_run)

    # Group objects by type and track appearance counts
    type_objects: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for run_id, objects in objects_by_run.items():
        for obj_id in objects:
            obj_type = type_extractor(obj_id)
            type_objects[obj_type][obj_id] += 1

    # Build breakdown for each type
    breakdowns = []

    for obj_type, obj_counts in sorted(type_objects.items()):
        stable_items = []
        unstable_items = {}

        for obj_id, count in obj_counts.items():
            if count == num_runs:
                stable_items.append(obj_id)
            else:
                unstable_items[obj_id] = count

        total_count = len(obj_counts)
        stable_count = len(stable_items)
        unstable_count = len(unstable_items)
        consistency = stable_count / total_count if total_count > 0 else 0.0

        breakdowns.append(
            StabilityBreakdown(
                item_type=obj_type,
                phase=phase,
                total_count=total_count,
                stable_count=stable_count,
                unstable_count=unstable_count,
                consistency_score=consistency,
                stable_items=stable_items,
                unstable_items=unstable_items,
            )
        )

    return breakdowns


def compute_phase_stability(
    nodes_by_run: dict[str, set[str]] | None,
    edges_by_run: dict[str, set[str]] | None,
    elements_by_run: dict[str, set[str]] | None,
    relationships_by_run: dict[str, set[str]] | None,
    repository: str,
    model: str,
) -> dict[str, PhaseStabilityReport]:
    """
    Compute stability reports for extraction and derivation phases.

    Args:
        nodes_by_run: Dict mapping run_id -> set of node IDs (extraction)
        edges_by_run: Dict mapping run_id -> set of edge IDs (extraction)
        elements_by_run: Dict mapping run_id -> set of element IDs (derivation)
        relationships_by_run: Dict mapping run_id -> set of relationship IDs (derivation)
        repository: Repository name
        model: Model name

    Returns:
        Dict with "extraction" and "derivation" phase reports
    """
    reports = {}

    # Extraction phase
    if nodes_by_run or edges_by_run:
        num_runs = len(nodes_by_run or edges_by_run or {})

        node_breakdown = []
        edge_breakdown = []

        if nodes_by_run:
            node_breakdown = compute_type_breakdown(nodes_by_run, extract_node_type, "extraction")

        if edges_by_run:
            edge_breakdown = compute_type_breakdown(edges_by_run, extract_edge_type, "extraction")

        # Calculate overall consistency
        all_breakdowns = node_breakdown + edge_breakdown
        if all_breakdowns:
            overall = sum(b.consistency_score for b in all_breakdowns) / len(all_breakdowns)
        else:
            overall = 0.0

        reports["extraction"] = PhaseStabilityReport(
            phase="extraction",
            repository=repository,
            model=model,
            total_runs=num_runs,
            overall_consistency=overall,
            node_breakdown=node_breakdown,
            edge_breakdown=edge_breakdown,
            element_breakdown=[],
            relationship_breakdown=[],
        )

    # Derivation phase
    if elements_by_run or relationships_by_run:
        num_runs = len(elements_by_run or relationships_by_run or {})

        element_breakdown = []
        relationship_breakdown = []

        if elements_by_run:
            element_breakdown = compute_type_breakdown(elements_by_run, extract_element_type, "derivation")

        if relationships_by_run:
            relationship_breakdown = compute_type_breakdown(relationships_by_run, extract_relationship_type, "derivation")

        # Calculate overall consistency
        all_breakdowns = element_breakdown + relationship_breakdown
        if all_breakdowns:
            overall = sum(b.consistency_score for b in all_breakdowns) / len(all_breakdowns)
        else:
            overall = 0.0

        reports["derivation"] = PhaseStabilityReport(
            phase="derivation",
            repository=repository,
            model=model,
            total_runs=num_runs,
            overall_consistency=overall,
            node_breakdown=[],
            edge_breakdown=[],
            element_breakdown=element_breakdown,
            relationship_breakdown=relationship_breakdown,
        )

    return reports


def identify_stability_patterns(
    breakdowns: list[StabilityBreakdown],
    high_threshold: float = 0.9,
    low_threshold: float = 0.5,
) -> dict[str, list[str]]:
    """
    Identify patterns in stable vs unstable items.

    Analyzes what makes items stable or unstable:
    - Which types have highest/lowest consistency
    - Common naming patterns in stable/unstable items
    - Size/complexity indicators

    Args:
        breakdowns: List of StabilityBreakdown objects
        high_threshold: Threshold for "highly stable" (default 0.9)
        low_threshold: Threshold for "unstable" (default 0.5)

    Returns:
        Dict with pattern categories:
        - "highly_stable_types": Types with consistency >= high_threshold
        - "unstable_types": Types with consistency < low_threshold
        - "stable_patterns": Common patterns in stable item names
        - "unstable_patterns": Common patterns in unstable item names
    """
    highly_stable_types = []
    unstable_types = []
    stable_name_patterns: list[str] = []
    unstable_name_patterns: list[str] = []

    for breakdown in breakdowns:
        if breakdown.consistency_score >= high_threshold:
            highly_stable_types.append(f"{breakdown.item_type} ({breakdown.consistency_score:.0%})")
        elif breakdown.consistency_score < low_threshold:
            unstable_types.append(f"{breakdown.item_type} ({breakdown.consistency_score:.0%})")

        # Analyze naming patterns
        if breakdown.stable_items:
            # Look for common prefixes/patterns
            stable_prefixes = _find_common_patterns(breakdown.stable_items)
            if stable_prefixes:
                stable_name_patterns.extend(stable_prefixes)

        if breakdown.unstable_items:
            unstable_prefixes = _find_common_patterns(list(breakdown.unstable_items.keys()))
            if unstable_prefixes:
                unstable_name_patterns.extend(unstable_prefixes)

    return {
        "highly_stable_types": highly_stable_types,
        "unstable_types": unstable_types,
        "stable_patterns": list(set(stable_name_patterns)),
        "unstable_patterns": list(set(unstable_name_patterns)),
    }


def _find_common_patterns(items: list[str], min_count: int = 2) -> list[str]:
    """
    Find common prefix patterns in a list of item names.

    Args:
        items: List of item names
        min_count: Minimum occurrences to be considered a pattern

    Returns:
        List of common pattern descriptions
    """
    if not items or len(items) < min_count:
        return []

    patterns = []

    # Find common prefixes (first 2-3 segments)
    prefix_counts: dict[str, int] = defaultdict(int)

    for item in items:
        # Split by underscore or camelCase
        if "_" in item:
            parts = item.split("_")
        else:
            # Split camelCase
            parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", item)

        if parts:
            # Count 1-part and 2-part prefixes
            prefix_counts[parts[0].lower()] += 1
            if len(parts) >= 2:
                prefix_counts[f"{parts[0]}_{parts[1]}".lower()] += 1

    # Identify significant patterns
    for prefix, count in prefix_counts.items():
        if count >= min_count and count >= len(items) * 0.3:  # At least 30% of items
            patterns.append(f"'{prefix}' prefix ({count}/{len(items)} items)")

    return patterns


def aggregate_stability_metrics(
    stability_reports: dict[str, dict[str, PhaseStabilityReport]],
) -> dict[str, Any]:
    """
    Aggregate stability metrics across multiple repositories.

    Args:
        stability_reports: Dict mapping repo -> phase -> report

    Returns:
        Aggregated metrics including:
        - avg_extraction_consistency
        - avg_derivation_consistency
        - best_element_types (sorted by consistency)
        - worst_element_types (sorted by consistency)
    """
    extraction_consistencies = []
    derivation_consistencies = []
    element_type_scores: dict[str, list[float]] = defaultdict(list)
    relationship_type_scores: dict[str, list[float]] = defaultdict(list)

    for repo, phases in stability_reports.items():
        if "extraction" in phases:
            extraction_consistencies.append(phases["extraction"].overall_consistency)

        if "derivation" in phases:
            derivation_consistencies.append(phases["derivation"].overall_consistency)

            for breakdown in phases["derivation"].element_breakdown:
                element_type_scores[breakdown.item_type].append(breakdown.consistency_score)

            for breakdown in phases["derivation"].relationship_breakdown:
                relationship_type_scores[breakdown.item_type].append(breakdown.consistency_score)

    # Calculate averages
    avg_extraction = sum(extraction_consistencies) / len(extraction_consistencies) if extraction_consistencies else 0.0
    avg_derivation = sum(derivation_consistencies) / len(derivation_consistencies) if derivation_consistencies else 0.0

    # Calculate per-type averages and sort
    element_type_avgs = [(t, sum(scores) / len(scores)) for t, scores in element_type_scores.items()]
    element_type_avgs.sort(key=lambda x: -x[1])  # Descending

    relationship_type_avgs = [(t, sum(scores) / len(scores)) for t, scores in relationship_type_scores.items()]
    relationship_type_avgs.sort(key=lambda x: -x[1])  # Descending

    return {
        "avg_extraction_consistency": avg_extraction,
        "avg_derivation_consistency": avg_derivation,
        "best_element_types": element_type_avgs[:5],  # Top 5
        "worst_element_types": element_type_avgs[-5:][::-1] if element_type_avgs else [],
        "best_relationship_types": relationship_type_avgs[:5],
        "worst_relationship_types": (relationship_type_avgs[-5:][::-1] if relationship_type_avgs else []),
    }


def compute_answer_stability(answers_by_run: dict[str, dict[tuple[str, str], list[str | None]]]) -> list[AnswerStability]:
    """Per step, how many prompts asked in every run got the same answers in every run.

    Args:
        answers_by_run: run id -> {(step, prompt key): answer hashes}; a prompt asked
            several times in a run (samples, repeated candidates) compares as a multiset

    Returns:
        One AnswerStability per step, sorted by step; empty with fewer than two runs
    """
    if len(answers_by_run) < 2:
        return []
    runs = list(answers_by_run.values())
    shared = set(runs[0]).intersection(*runs[1:])
    counts: dict[str, list[int]] = {}
    for key in shared:
        answers = {tuple(sorted(str(a) for a in run[key])) for run in runs}
        step_counts = counts.setdefault(key[0], [0, 0])
        step_counts[0] += 1
        step_counts[1] += len(answers) == 1
    return [AnswerStability(step=step, prompts=n, identical=same) for step, (n, same) in sorted(counts.items())]


# Answer fields that carry free text or a score, not a decision
FREE_ANSWER_FIELDS = frozenset({"description", "documentation", "confidence"})


def decision_content(content: str) -> str:
    """The decisions in an LLM answer, for comparing answers across runs.

    Free text and scores (``FREE_ANSWER_FIELDS``, at any depth) are left out and the
    rest is serialised with sorted keys, so a reworded description or a different
    confidence is the same decision. Text that is not JSON is returned as is.
    """
    try:
        answer = json.loads(content)
    except ValueError:
        return content

    def decisions(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: decisions(v) for k, v in value.items() if k not in FREE_ANSWER_FIELDS}
        if isinstance(value, list):
            return [decisions(v) for v in value]
        return value

    return json.dumps(decisions(answer), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decision_stability(runs: list[dict[str, Any]]) -> DecisionStability:
    """How many items got the same decision in every run.

    Args:
        runs: Per run, the step's decision per item (``None`` for an item it skipped). An item
            missing from a run's decisions differs from every decision, ``None`` included.
    """
    missing = object()
    items = set().union(*runs) if runs else set()
    stable = sum(1 for item in items if len({repr(run.get(item, missing)) for run in runs}) == 1)
    return DecisionStability(items=len(items), stable=stable)


def compare_step_outputs(runs: list[dict[tuple[str, str], dict[str, Any]]], unscored: frozenset[str] = frozenset()) -> StepConsistency:
    """Compare the outputs of one step repeated on the same input.

    Args:
        runs: Per run, the step's output objects: (group, key) -> properties. The group
            (a node label or edge type) gets its own scores in ``groups``.
        unscored: Properties that are counted in ``property_differences`` but do not make
            an object inexact

    Returns:
        Presence and exact consistency overall and per group, with the properties that differ
    """

    def compare(outputs: list[dict[Any, dict[str, Any]]]) -> StepConsistency:
        keys = [set(output) for output in outputs]
        union = set().union(*keys)
        common = set.intersection(*keys) if keys else set()
        identical = 0
        differences: dict[str, int] = defaultdict(int)
        for key in common:
            values = [output[key] for output in outputs]
            # Missing differs from None; values compare by equality, so dict key order does not count
            differing = {name for name in set().union(*values) if any(name not in v or v[name] != values[0][name] for v in values)}
            identical += not (differing - unscored)
            for name in differing:
                differences[name] += 1
        return StepConsistency(
            runs=len(outputs),
            counts=[len(output) for output in outputs],
            present=len(common),
            total=len(union),
            identical=identical,
            property_differences=dict(sorted(differences.items())),
        )

    result = compare(runs)
    for group in sorted({group for run in runs for group, _ in run}):
        result.groups[group] = compare([{key: props for key, props in run.items() if key[0] == group} for run in runs])
    return result
