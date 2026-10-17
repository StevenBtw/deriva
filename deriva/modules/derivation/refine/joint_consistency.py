"""Refine step: joint consistency (relationships + duplicate merges, solved exactly).

Refine Step Name: "joint_consistency"
Params: dry_run (default True), origin_tiers (the evidence tier per relationship origin; default
DEFAULT_ORIGIN_TIERS), report_path (optional JSON).
The target metamodel is taken from `archimate_manager.metamodel` at runtime.

Duplicate merges come only from structural identity (the same type, source node and role); a name is no evidence.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step
from .joint import DEFAULT_ORIGIN_TIERS, JointElement, MergeCandidate, Metamodel, Proposal, origin_tier, solve

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see docs/architecture.md)
    from deriva.adapters.archimate.models import Element  # noqa: TID251 - known layer exception (see docs/architecture.md)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see docs/architecture.md)

logger = logging.getLogger(__name__)


def merge_candidates(elements: list[Element]) -> list[MergeCandidate]:
    """Same-type pairs made from the same source node in the same role (an interface per channel shares its unit's
    source but not its role): tier 1. Names are no evidence."""
    groups: dict[tuple[str, str, str], list[Element]] = defaultdict(list)
    for e in elements:
        source = e.properties.get("source")
        if source:
            groups[(e.element_type, str(source), str(e.properties.get("role") or ""))].append(e)
    out: list[MergeCandidate] = []
    for group in groups.values():
        group = sorted(group, key=lambda e: e.identifier)
        out += [MergeCandidate(a.identifier, b.identifier, 1, 1.0, "same_source_node") for i, a in enumerate(group) for b in group[i + 1 :]]
    return out


def origin_tiers(params: dict[str, Any]) -> dict[str, int]:
    """The evidence tier per relationship origin (``params.origin_tiers``, versioned config), else the default table."""
    table = params.get("origin_tiers", DEFAULT_ORIGIN_TIERS)
    if not isinstance(table, dict) or not all(isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v in (1, 2, 3) for k, v in table.items()):
        raise ValueError(f"joint_consistency params.origin_tiers maps origins to tier 1, 2 or 3, got {table!r}")
    return dict(table)


def _duplicate_disabled_ids(archimate_manager: ArchimateManager) -> set[str]:
    rows = archimate_manager.query(f"MATCH (e:`{archimate_manager.namespace}`) WHERE e.enabled = false AND e.disabled_reason STARTS WITH 'duplicate_of:' RETURN e.identifier as id")
    return {r["id"] for r in rows if r.get("id")}


def _metamodel(archimate_manager: ArchimateManager) -> Metamodel:
    mm = archimate_manager.metamodel
    return Metamodel(
        is_valid=lambda s, r, t: mm.can_relate(s, r, t)[0],
        single_parent_types=mm.single_parent_relationship_types,
        acyclic_types=mm.acyclic_relationship_types,
    )


@register_refine_step("joint_consistency")
class JointConsistencyStep:
    """Select relationships and duplicate merges jointly (see refine/joint.py)."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        params = params or {}
        dry_run = params.get("dry_run", True)
        tiers = origin_tiers(params)
        result = RefineResult(success=True, step_name="joint_consistency")

        try:
            # Earlier duplicate merges are re-decided here, in dry run and apply alike,
            # so the report describes exactly what an apply run does
            revived = _duplicate_disabled_ids(archimate_manager)
            elements = [e for e in archimate_manager.get_elements(enabled_only=False) if e.enabled or e.identifier in revived]
            ids = {e.identifier for e in elements}
            rels = [r for r in archimate_manager.get_relationships() if r.source in ids and r.target in ids]
            candidates = merge_candidates(elements)
            evidence = {(m.first, m.second): m.evidence for m in candidates}

            started = time.perf_counter()
            decision = solve(
                [
                    JointElement(
                        e.identifier,
                        e.element_type,
                        float(e.properties.get("source_pagerank") or 0.0),
                        len(e.documentation or ""),
                    )
                    for e in elements
                ],
                [
                    Proposal(
                        r.identifier,
                        r.source,
                        r.target,
                        r.relationship_type,
                        origin_tier(r.properties.get("derived_from"), tiers),
                    )
                    for r in rels
                ],
                candidates,
                _metamodel(archimate_manager),
            )
            result.report = {"status": decision.status, "seconds": round(time.perf_counter() - started, 3), **decision.stats}

            if params.get("report_path"):
                Path(params["report_path"]).write_text(
                    json.dumps(
                        {
                            "status": decision.status,
                            "kept": decision.kept,
                            "dropped": decision.dropped,
                            "merges": decision.merges,
                            "redirects": decision.redirects,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            if not decision.ok:
                result.success = False
                result.errors.append(f"joint solve failed: {decision.status}")
                return result

            result.issues_found = len(decision.dropped) + len(decision.merges)
            result.details += [{"action": "drop", "relationship": k, "reason": v} for k, v in decision.dropped.items()]
            result.details += [{"action": "merge", "duplicate": d, "survivor": s} for d, s in decision.merges.items()]
            result.details += [{"action": "redirect", "relationship": k, "to": list(v)} for k, v in decision.redirects.items()]
            if dry_run:
                return result

            for duplicate, survivor in decision.merges.items():
                tag = evidence.get((min(duplicate, survivor), max(duplicate, survivor)), "transitive")
                archimate_manager.disable_element(duplicate, reason=f"duplicate_of:{survivor}:joint:{tag}")
                result.elements_merged += 1
                result.elements_disabled += 1
            for rel_id, (source, target) in decision.redirects.items():
                archimate_manager.redirect_relationship(rel_id, source, target)
                result.relationships_created += 1
                result.relationships_deleted += 1
            for rel_id in decision.dropped:
                archimate_manager.delete_relationship(rel_id)
                result.relationships_deleted += 1
            for identifier in sorted(revived - set(decision.merges)):
                archimate_manager.enable_element(identifier)
            result.issues_fixed = result.issues_found
        except Exception as e:
            logger.exception("joint_consistency failed")
            result.success = False
            result.errors.append(f"joint_consistency failed: {e}")
        return result
