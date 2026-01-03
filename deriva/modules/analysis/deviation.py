"""
Pure functions for config deviation analysis.

Analyzes which configs produce deviations across benchmark runs,
enabling systematic optimization through config-only changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from .types import ConfigDeviation, DeviationReport

__all__ = [
    "analyze_config_deviations",
    "group_objects_by_config",
    "compute_deviation_stats",
    "extract_node_type",
    "extract_element_type",
    "generate_recommendations",
]


def analyze_config_deviations(
    config_events: list[Any],
    config_type: str,
) -> list[ConfigDeviation]:
    """
    Analyze deviations from config events (ExtractConfig/DeriveConfig).

    Args:
        config_events: List of OCEL events with config_id and objects
        config_type: "extraction" or "derivation"

    Returns:
        List of ConfigDeviation with per-config deviation statistics
    """
    results: list[ConfigDeviation] = []

    # Group events by config_id and run_id
    config_runs = group_objects_by_config(config_events, config_type)

    # Analyze each config
    for config_id, runs_data in config_runs.items():
        if len(runs_data) < 2:
            continue

        deviation = compute_deviation_stats(
            config_id=config_id,
            config_type=config_type,
            objects_by_run=runs_data,
        )
        results.append(deviation)

    return results


def group_objects_by_config(
    events: list[dict[str, Any]],
    config_type: str,
) -> dict[str, dict[str, set[str]]]:
    """
    Group objects by config_id and run_id from OCEL events.

    Args:
        events: List of OCEL event dicts with 'objects' and 'attributes'
        config_type: "extraction" or "derivation"

    Returns:
        Nested dict: {config_id: {run_id: set(object_ids)}}
    """
    config_runs: dict[str, dict[str, set[str]]] = {}
    object_type = "GraphNode" if config_type == "extraction" else "Element"

    for event in events:
        # Handle both OCELEvent objects and dicts
        if hasattr(event, "objects"):
            objects = cast(dict[str, list[str]], event.objects)
        else:
            objects = cast(dict[str, list[str]], event.get("objects", {}))

        config_ids = objects.get("Config", [])
        run_ids = objects.get("BenchmarkRun", [])
        object_ids = objects.get(object_type, [])

        for config_id in config_ids:
            if config_id not in config_runs:
                config_runs[config_id] = {}
            for run_id in run_ids:
                if run_id not in config_runs[config_id]:
                    config_runs[config_id][run_id] = set()
                config_runs[config_id][run_id].update(object_ids)

    return config_runs


def compute_deviation_stats(
    config_id: str,
    config_type: str,
    objects_by_run: dict[str, set[str]],
    max_objects_in_list: int = 50,
) -> ConfigDeviation:
    """
    Compute deviation statistics for a single config.

    Args:
        config_id: The config identifier (node_type or step_name)
        config_type: "extraction" or "derivation"
        objects_by_run: Mapping of run_id -> set of object_ids
        max_objects_in_list: Max objects to include in lists (for JSON size)

    Returns:
        ConfigDeviation with computed statistics
    """
    all_runs = list(objects_by_run.keys())
    all_objects = set.union(*objects_by_run.values()) if objects_by_run else set()

    deviating = []
    stable = []

    for obj_id in all_objects:
        present_in = [r for r, objs in objects_by_run.items() if obj_id in objs]
        if len(present_in) == len(all_runs):
            stable.append(obj_id)
        else:
            deviating.append(obj_id)

    consistency = len(stable) / len(all_objects) if all_objects else 1.0

    return ConfigDeviation(
        config_type=config_type,
        config_id=config_id,
        deviation_count=len(deviating),
        total_objects=len(all_objects),
        consistency_score=consistency,
        deviating_objects=sorted(deviating)[:max_objects_in_list],
        stable_objects=sorted(stable)[:max_objects_in_list],
    )


def analyze_from_object_types(
    objects_by_run: dict[str, set[str]],
    config_type: str,
    type_extractor: Callable[[str], str],
) -> list[ConfigDeviation]:
    """
    Analyze deviations by inferring config from object ID prefixes.

    Fallback when enriched config events aren't available.

    Args:
        objects_by_run: Mapping of run_id -> set of object_ids
        config_type: "extraction" or "derivation"
        type_extractor: Function to extract type from object_id

    Returns:
        List of ConfigDeviation per inferred type
    """
    if len(objects_by_run) < 2:
        return []

    all_objects = set.union(*objects_by_run.values()) if objects_by_run else set()

    # Group by inferred type
    objects_by_type: dict[str, set[str]] = {}
    for obj_id in all_objects:
        obj_type = type_extractor(obj_id)
        if obj_type not in objects_by_type:
            objects_by_type[obj_type] = set()
        objects_by_type[obj_type].add(obj_id)

    results = []
    for obj_type, type_objects in objects_by_type.items():
        # Build per-run data for this type
        type_by_run = {}
        for run_id, run_objects in objects_by_run.items():
            type_by_run[run_id] = run_objects & type_objects

        deviation = compute_deviation_stats(
            config_id=obj_type,
            config_type=config_type,
            objects_by_run=type_by_run,
        )
        results.append(deviation)

    return results


def extract_node_type(node_id: str) -> str:
    """Extract node type from node ID (format: Type_repo_identifier)."""
    parts = node_id.split("_")
    return parts[0] if parts else "Unknown"


def extract_element_type(element_id: str) -> str:
    """Extract element type from element ID."""
    lower_id = element_id.lower()
    if "component" in lower_id or lower_id.startswith("ac_"):
        return "ApplicationComponent"
    if "service" in lower_id or lower_id.startswith("as_"):
        return "ApplicationService"
    if "data" in lower_id or lower_id.startswith("do_"):
        return "DataObject"
    if "artifact" in lower_id or lower_id.startswith("art_"):
        return "Artifact"
    parts = element_id.split("_")
    return parts[0] if parts else "Unknown"


def generate_recommendations(deviations: list[ConfigDeviation]) -> list[str]:
    """
    Generate optimization recommendations based on deviation analysis.

    Args:
        deviations: List of ConfigDeviation to analyze

    Returns:
        List of actionable recommendation strings
    """
    recommendations = []

    for cd in deviations:
        if cd.consistency_score < 0.5:
            recommendations.append(
                f"HIGH PRIORITY: {cd.config_type} config '{cd.config_id}' has only "
                f"{cd.consistency_score:.0%} consistency. Consider refining "
                "instruction/example or increasing specificity."
            )
        elif cd.consistency_score < 0.8:
            recommendations.append(
                f"MEDIUM: {cd.config_type} config '{cd.config_id}' has "
                f"{cd.consistency_score:.0%} consistency. May benefit from "
                "more specific examples or constrained output format."
            )

    if not recommendations:
        recommendations.append(
            "All configs show good consistency (>80%). No immediate action needed."
        )

    return recommendations


def build_deviation_report(
    session_id: str,
    analysis_timestamp: str,
    total_runs: int,
    config_deviations: list[ConfigDeviation],
) -> DeviationReport:
    """
    Build a complete deviation report from analyzed configs.

    Args:
        session_id: Benchmark session ID
        analysis_timestamp: ISO timestamp of analysis
        total_runs: Total number of runs in session
        config_deviations: List of analyzed config deviations

    Returns:
        Complete DeviationReport
    """
    # Sort by deviation count (highest first)
    sorted_deviations = sorted(
        config_deviations, key=lambda x: x.deviation_count, reverse=True
    )

    total_deviations = sum(cd.deviation_count for cd in config_deviations)
    total_objects = sum(cd.total_objects for cd in config_deviations)
    overall_consistency = (
        (total_objects - total_deviations) / total_objects if total_objects > 0 else 1.0
    )

    return DeviationReport(
        session_id=session_id,
        analysis_timestamp=analysis_timestamp,
        total_runs=total_runs,
        total_deviations=total_deviations,
        overall_consistency=overall_consistency,
        config_deviations=sorted_deviations,
    )
