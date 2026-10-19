"""Model quality: a verdict on a derived model from its structure.

A report: it reads the model and the graph and changes no result. A model is weak when many elements have no
relationship, when nearly all relationships are Composition or Aggregation (structure without behaviour), when the
Application or Technology layer is empty (the business layer may be empty by design), or when elements have no
artifact behind them: none of their located sources is a file, type or method, and no source file lies under a
folder-like source (a directory, a deployable unit or a build module). Sources without a location (a data domain,
a piece of software) neither count for nor against an element.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from typing import Any

__all__ = ["STRUCTURAL", "model_quality"]

STRUCTURAL = ("Composition", "Aggregation")
# Layers a derived model needs; the business layer may be empty when the repository has no business evidence
REQUIRED_LAYERS = ("Application", "Technology")
LAYERS = ("Business", "Application", "Technology")
# How many element names a reason lists
NAMES = 3


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _names(rows: list[dict[str, Any]]) -> str:
    names = ", ".join(str(r["name"]) for r in rows[:NAMES])
    return names if len(rows) <= NAMES else f"{names} and {len(rows) - NAMES} more"


def model_quality(
    elements: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    located: Mapping[str, str],
    artifacts: Collection[str],
    source_files: Collection[str],
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """The quality verdict of one model.

    Args:
        elements: The enabled elements: ``id``, ``name``, ``type``, ``layer`` and their graph ``sources``
        relationships: ``source``, ``target`` and ``type``
        located: Graph node ids with a location (``path`` or ``filePath``), by id
        artifacts: The located node ids that are files, types or methods
        source_files: The paths of the graph's source files
        thresholds: ``quality_max_orphan_share`` and ``quality_max_structural_share``

    Returns:
        Counts, orphans, relationship types, layers, the elements without an artifact behind them, and
        ``verdict`` ("ok" or "weak") with the ``reasons``
    """
    linked = {r["source"] for r in relationships} | {r["target"] for r in relationships}
    orphans = [{"id": e["id"], "name": e["name"], "type": e["type"]} for e in elements if e["id"] not in linked]
    types = Counter(str(r["type"]) for r in relationships)
    structural = sum(types[t] for t in STRUCTURAL)
    layers = {layer: sum(1 for e in elements if e.get("layer") == layer) for layer in LAYERS}

    files = list(source_files)

    def evidence(node_id: str) -> bool:
        path = located[node_id]
        return node_id in artifacts or any(f == path or f.startswith(path + "/") for f in files)

    unsupported = []
    for e in elements:
        here = [s for s in e.get("sources") or [] if s in located]
        if here and not any(evidence(s) for s in here):
            unsupported.append({"id": e["id"], "name": e["name"], "type": e["type"], "sources": [located[s] for s in here]})

    reasons = []
    if not elements:
        reasons.append("the model has no elements")
    else:
        max_orphans, max_structural = thresholds["quality_max_orphan_share"], thresholds["quality_max_structural_share"]
        if _share(len(orphans), len(elements)) > max_orphans:
            reasons.append(f"{len(orphans)} of {len(elements)} elements ({_share(len(orphans), len(elements)):.0%}) have no relationship (above {max_orphans:.0%})")
        if relationships and _share(structural, len(relationships)) > max_structural:
            counted = (
                f"all {len(relationships)} relationships are"
                if structural == len(relationships)
                else f"{structural} of {len(relationships)} relationships ({_share(structural, len(relationships)):.0%}) are"
            )
            reasons.append(f"{counted} Composition or Aggregation (above {max_structural:.0%})")
        reasons.extend(f"no {layer} element" for layer in REQUIRED_LAYERS if not layers[layer])
        if unsupported:
            counted = f"{len(unsupported)} elements have" if len(unsupported) != 1 else "1 element has"
            whose = "their" if len(unsupported) != 1 else "its"
            reasons.append(f"{counted} no file, type or method behind {whose} sources ({_names(unsupported)})")

    return {
        "elements": len(elements),
        "relationships": len(relationships),
        "orphans": orphans,
        "orphan_share": _share(len(orphans), len(elements)),
        "structural_share": _share(structural, len(relationships)),
        "relationship_types": dict(types.most_common()),
        "layers": layers,
        "unsupported": unsupported,
        "verdict": "weak" if reasons else "ok",
        "reasons": reasons,
    }
