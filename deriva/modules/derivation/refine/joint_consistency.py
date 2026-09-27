"""Refine step: joint consistency (relationships + duplicate merges, solved exactly).

Refine Step Name: "joint_consistency"
Params: dry_run (default True), fuzzy_threshold (default 0.85), report_path (optional JSON).
The target metamodel is taken from `archimate_manager.metamodel` at runtime.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import RefineResult, normalize_name, register_refine_step, similarity_ratio
from .duplicate_elements import FUZZY_MATCH_THRESHOLD, _build_repo_context
from .joint import JointElement, MergeCandidate, Metamodel, Proposal, origin_tier, solve
from .normalization import RepoContext, normalize_for_dedup

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.archimate.models import Element
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)


def merge_candidates(
    elements: list[Element],
    ctx: RepoContext,
    adjacent: set[frozenset[str]],
    threshold: float,
) -> list[MergeCandidate]:
    """Same-type pairs with deterministic duplicate evidence, tiered."""
    by_type: dict[str, list[Element]] = defaultdict(list)
    for e in elements:
        by_type[e.element_type].append(e)
    out: list[MergeCandidate] = []
    for group in by_type.values():
        group = sorted(group, key=lambda e: e.identifier)
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                src_a, src_b = a.properties.get("source"), b.properties.get("source")
                canon_a, canon_b = (
                    normalize_for_dedup(a.name, ctx),
                    normalize_for_dedup(b.name, ctx),
                )
                if canon_a and canon_a == canon_b:
                    out.append(
                        MergeCandidate(
                            a.identifier, b.identifier, 1, 1.0, "normalized_name"
                        )
                    )
                    continue
                if src_a and src_a == src_b:
                    out.append(
                        MergeCandidate(
                            a.identifier, b.identifier, 1, 1.0, "same_source_node"
                        )
                    )
                    continue
                if not (canon_a and canon_b):
                    continue  # an empty name is no evidence (similarity("", "") is 1.0)
                score = similarity_ratio(
                    normalize_name(canon_a), normalize_name(canon_b)
                )
                if score < threshold:
                    continue
                com_a = a.properties.get("source_louvain_community")
                com_b = b.properties.get("source_louvain_community")
                near = bool(
                    src_a and src_b and frozenset((src_a, src_b)) in adjacent
                ) or (com_a is not None and com_a == com_b)
                tier, evidence = (2, "fuzzy_name+graph") if near else (3, "fuzzy_name")
                out.append(
                    MergeCandidate(a.identifier, b.identifier, tier, score, evidence)
                )
    return out


def _adjacent_sources(
    graph_manager: GraphManager | None, sources: list[str]
) -> set[frozenset[str]]:
    if graph_manager is None or len(sources) < 2:
        return set()
    rows = graph_manager.query(
        "MATCH (a)-[]-(b) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id as a, b.id as b",
        {"ids": sources},
    )
    return {frozenset((r["a"], r["b"])) for r in rows if r.get("a") and r.get("b")}


def _duplicate_disabled_ids(archimate_manager: ArchimateManager) -> set[str]:
    rows = archimate_manager.query(
        f"MATCH (e:`{archimate_manager.namespace}`) WHERE e.enabled = false "
        f"AND e.disabled_reason STARTS WITH 'duplicate_of:' RETURN e.identifier as id"
    )
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
        threshold = params.get("fuzzy_threshold", FUZZY_MATCH_THRESHOLD)
        result = RefineResult(success=True, step_name="joint_consistency")

        try:
            revived = _duplicate_disabled_ids(archimate_manager) if dry_run else set()
            elements = [
                e
                for e in archimate_manager.get_elements(enabled_only=False)
                if e.enabled or e.identifier in revived
            ]
            ids = {e.identifier for e in elements}
            rels = [
                r
                for r in archimate_manager.get_relationships()
                if r.source in ids and r.target in ids
            ]
            ctx = _build_repo_context(graph_manager, archimate_manager)
            sources = sorted({s for e in elements if (s := e.properties.get("source"))})
            candidates = merge_candidates(
                elements, ctx, _adjacent_sources(graph_manager, sources), threshold
            )
            evidence = {(m.first, m.second): m.evidence for m in candidates}

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
                        origin_tier(r.properties.get("derived_from")),
                        float(r.properties.get("confidence") or 0.0),
                    )
                    for r in rels
                ],
                candidates,
                _metamodel(archimate_manager),
            )

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
            result.details += [
                {"action": "drop", "relationship": k, "reason": v}
                for k, v in decision.dropped.items()
            ]
            result.details += [
                {"action": "merge", "duplicate": d, "survivor": s}
                for d, s in decision.merges.items()
            ]
            result.details += [
                {"action": "redirect", "relationship": k, "to": list(v)}
                for k, v in decision.redirects.items()
            ]
            if dry_run:
                return result

            for duplicate, survivor in decision.merges.items():
                tag = evidence.get(
                    (min(duplicate, survivor), max(duplicate, survivor)), "transitive"
                )
                archimate_manager.disable_element(
                    duplicate, reason=f"duplicate_of:{survivor}:joint:{tag}"
                )
                result.elements_merged += 1
                result.elements_disabled += 1
            for rel_id, (source, target) in decision.redirects.items():
                archimate_manager.redirect_relationship(rel_id, source, target)
                result.relationships_created += 1
                result.relationships_deleted += 1
            for rel_id in decision.dropped:
                archimate_manager.delete_relationship(rel_id)
                result.relationships_deleted += 1
            result.issues_fixed = result.issues_found
        except Exception as e:
            logger.exception("joint_consistency failed")
            result.success = False
            result.errors.append(f"joint_consistency failed: {e}")
        return result
