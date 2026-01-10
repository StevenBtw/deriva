"""
Duplicate Relationships Detection - Refine Step.

Finds and removes duplicate relationships in the ArchiMate model:
- Exact duplicates: Same source, target, and type
- Redundant relationships: Same source and target with semantically equivalent types

Only hard-deletes relationships (unlike elements which are soft-deleted).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)


@register_refine_step("duplicate_relationships")
class DuplicateRelationshipsStep:
    """Find and remove duplicate ArchiMate relationships."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute duplicate relationship detection and removal.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Not used for this step
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - check_redundant: Also check for redundant relationships (default: True)

        Returns:
            RefineResult with details of duplicate relationships handled
        """
        params = params or {}
        check_redundant = params.get("check_redundant", True)

        result = RefineResult(
            success=True,
            step_name="duplicate_relationships",
        )

        try:
            # Find exact duplicates: same source, target, type
            ns = archimate_manager.namespace
            duplicate_query = f"""
                MATCH (a)-[r1]->(b), (a)-[r2]->(b)
                WHERE any(lbl IN labels(a) WHERE lbl STARTS WITH '{ns}:')
                  AND any(lbl IN labels(b) WHERE lbl STARTS WITH '{ns}:')
                  AND type(r1) = type(r2)
                  AND type(r1) STARTS WITH '{ns}:'
                  AND id(r1) < id(r2)
                  AND a.enabled = true AND b.enabled = true
                RETURN r1.identifier as r1_id,
                       r2.identifier as r2_id,
                       a.identifier as source,
                       b.identifier as target,
                       type(r1) as rel_type
            """

            duplicates = archimate_manager.query(duplicate_query)

            if duplicates:
                logger.info(f"Found {len(duplicates)} exact duplicate relationships")

                # Collect IDs to delete (keep r1, delete r2)
                to_delete = []
                for dup in duplicates:
                    to_delete.append(dup["r2_id"])
                    result.details.append(
                        {
                            "action": "deleted",
                            "kept": dup["r1_id"],
                            "deleted": dup["r2_id"],
                            "source": dup["source"],
                            "target": dup["target"],
                            "rel_type": dup["rel_type"].split(":")[-1],
                            "reason": "exact_duplicate",
                        }
                    )

                # Delete duplicates
                if to_delete:
                    deleted_count = archimate_manager.delete_relationships(to_delete)
                    result.relationships_deleted += deleted_count
                    result.issues_fixed += deleted_count

            # Check for redundant relationships (same source/target, different types)
            if check_redundant:
                self._check_redundant_relationships(archimate_manager, result)

            logger.info(
                f"Duplicate relationship detection complete: "
                f"{result.relationships_deleted} deleted"
            )

        except Exception as e:
            logger.exception(f"Error in duplicate relationship detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _check_redundant_relationships(
        self,
        archimate_manager: ArchimateManager,
        result: RefineResult,
    ) -> None:
        """Check for redundant relationships between same source/target.

        Some relationship type pairs are redundant:
        - Serving + Flow between same elements (usually Serving suffices)
        - Multiple Composition relationships (should be only one)
        """
        ns = archimate_manager.namespace

        # Find elements with multiple relationships to the same target
        multi_rel_query = f"""
            MATCH (a)-[r]->(b)
            WHERE any(lbl IN labels(a) WHERE lbl STARTS WITH '{ns}:')
              AND any(lbl IN labels(b) WHERE lbl STARTS WITH '{ns}:')
              AND type(r) STARTS WITH '{ns}:'
              AND a.enabled = true AND b.enabled = true
            WITH a, b, collect({{id: r.identifier, type: type(r)}}) as rels
            WHERE size(rels) > 1
            RETURN a.identifier as source,
                   a.name as source_name,
                   b.identifier as target,
                   b.name as target_name,
                   rels
        """

        multi_rels = archimate_manager.query(multi_rel_query)

        if not multi_rels:
            return

        logger.info(
            f"Found {len(multi_rels)} element pairs with multiple relationships"
        )

        # Redundancy rules: which relationship types are redundant together
        redundant_pairs = {
            ("Serving", "Flow"): "Serving",  # Keep Serving
            ("Access", "Flow"): "Access",  # Keep Access
            ("Realization", "Serving"): "Realization",  # Keep Realization
        }

        for item in multi_rels:
            rels = item["rels"]
            rel_types = [r["type"].split(":")[-1] for r in rels]
            rel_ids = {r["type"].split(":")[-1]: r["id"] for r in rels}

            # Check for redundant pairs
            types_set = set(rel_types)
            for (type_a, type_b), keep_type in redundant_pairs.items():
                if type_a in types_set and type_b in types_set:
                    delete_type = type_b if keep_type == type_a else type_a
                    delete_id = rel_ids.get(delete_type)

                    if delete_id:
                        # Flag for now (could auto-delete with param)
                        result.issues_found += 1
                        result.details.append(
                            {
                                "action": "flagged",
                                "source": item["source"],
                                "source_name": item["source_name"],
                                "target": item["target"],
                                "target_name": item["target_name"],
                                "relationship_types": rel_types,
                                "recommended_keep": keep_type,
                                "recommended_delete": delete_type,
                                "reason": "redundant_relationship_pair",
                            }
                        )
