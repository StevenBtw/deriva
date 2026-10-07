"""
Pure functions for computing consistency metrics.

All functions are pure - they take data as input and return results.
No I/O, no side effects, no external dependencies beyond common.
"""

from __future__ import annotations

from typing import Any

from .types import InconsistencyInfo

__all__ = [
    "compute_consistency_score",
    "find_inconsistencies",
    "compare_object_sets",
    "jaccard_similarity",
]


def compute_consistency_score(objects_by_run: dict[str, set[str]]) -> float:
    """
    Compute overall consistency score for objects across runs.

    Args:
        objects_by_run: Mapping of run_id -> set of object_ids

    Returns:
        Float between 0.0 and 1.0, where 1.0 means all objects
        appear in all runs.
    """
    if len(objects_by_run) < 2:
        return 1.0

    all_objects = set.union(*objects_by_run.values()) if objects_by_run else set()
    if not all_objects:
        return 1.0

    # Count objects that appear in ALL runs
    consistent_count = sum(1 for obj in all_objects if all(obj in objs for objs in objects_by_run.values()))

    return consistent_count / len(all_objects)


def find_inconsistencies(
    objects_by_run: dict[str, set[str]],
    object_type: str = "Object",
) -> dict[str, InconsistencyInfo]:
    """
    Find objects that appear in some runs but not others.

    Args:
        objects_by_run: Mapping of run_id -> set of object_ids
        object_type: Type label for the objects (e.g., "Element", "GraphNode")

    Returns:
        Dict mapping object_id -> InconsistencyInfo for inconsistent objects
    """
    if len(objects_by_run) < 2:
        return {}

    all_runs = list(objects_by_run.keys())
    all_objects = set.union(*objects_by_run.values()) if objects_by_run else set()
    inconsistent: dict[str, InconsistencyInfo] = {}

    for obj_id in all_objects:
        present_in = [run for run, objs in objects_by_run.items() if obj_id in objs]
        missing_from = [run for run in all_runs if run not in present_in]

        # Object is inconsistent if not in all runs
        if len(present_in) != len(all_runs):
            inconsistent[obj_id] = InconsistencyInfo(
                object_id=obj_id,
                object_type=object_type,
                present_in=present_in,
                missing_from=missing_from,
                total_runs=len(all_runs),
            )

    return inconsistent


def compare_object_sets(
    set_1: set[str],
    set_2: set[str],
    label_1: str = "set_1",
    label_2: str = "set_2",
) -> dict[str, Any]:
    """
    Compare two sets of objects.

    Args:
        set_1: First set of object IDs
        set_2: Second set of object IDs
        label_1: Label for first set
        label_2: Label for second set

    Returns:
        Dict with overlap, unique items, and similarity metrics
    """
    overlap = set_1 & set_2
    only_in_1 = set_1 - set_2
    only_in_2 = set_2 - set_1
    union = set_1 | set_2

    return {
        label_1: sorted(set_1),
        label_2: sorted(set_2),
        "overlap": sorted(overlap),
        f"only_in_{label_1}": sorted(only_in_1),
        f"only_in_{label_2}": sorted(only_in_2),
        "jaccard_similarity": jaccard_similarity(set_1, set_2),
        f"count_{label_1}": len(set_1),
        f"count_{label_2}": len(set_2),
        "overlap_count": len(overlap),
        "union_count": len(union),
    }


def jaccard_similarity(set_1: set[str], set_2: set[str]) -> float:
    """
    Compute Jaccard similarity between two sets.

    Args:
        set_1: First set
        set_2: Second set

    Returns:
        Float between 0.0 and 1.0 (1.0 = identical sets)
    """
    if not set_1 and not set_2:
        return 1.0

    intersection = set_1 & set_2
    union = set_1 | set_2

    return len(intersection) / len(union) if union else 1.0
