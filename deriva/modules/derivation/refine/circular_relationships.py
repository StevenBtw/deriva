"""
Circular Relationships Detection - Refine Step.

Detects and breaks circular Composition relationships in the ArchiMate model:
- Bidirectional pairs: A→B AND B→A (both Composition)
- Longer cycles: A→B→C→A (all Composition)

Circular containment is invalid in ArchiMate - a component cannot both
contain and be contained by another component.

Refine Step Name: "circular_relationships"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)

logger = logging.getLogger(__name__)


@register_refine_step("circular_relationships")
class CircularRelationshipsStep:
    """Detect and break circular Composition relationships.

    ArchiMate Composition represents structural containment (parent-child).
    Circular compositions violate this semantics - a component cannot be
    both the container and the contained.

    This step:
    1. Finds bidirectional Composition pairs (A→B AND B→A)
    2. Finds longer cycles (A→B→C→A) using graph traversal
    3. Breaks cycles by deleting the lower-confidence relationship
    """

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute circular relationship detection and removal.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Not used for this step
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - max_cycle_length: Maximum cycle length to detect (default: 5)
                - delete_cycles: If True, delete relationships to break cycles (default: True)

        Returns:
            RefineResult with details of circular relationships handled
        """
        params = params or {}
        max_cycle_length = params.get("max_cycle_length", 5)
        delete_cycles = params.get("delete_cycles", True)

        result = RefineResult(
            success=True,
            step_name="circular_relationships",
        )

        try:
            ns = archimate_manager.namespace

            # Step 1: Find and handle bidirectional Composition pairs
            self._handle_bidirectional_compositions(archimate_manager, ns, result, delete_cycles)

            # Step 2: Find longer cycles (optional, more expensive)
            if max_cycle_length > 2:
                self._handle_longer_cycles(archimate_manager, ns, result, max_cycle_length, delete_cycles)

            logger.info(f"Circular relationship detection complete: {result.issues_found} found, {result.relationships_deleted} deleted")

        except Exception as e:
            logger.exception(f"Error in circular relationship detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _handle_bidirectional_compositions(
        self,
        archimate_manager: ArchimateManager,
        ns: str,
        result: RefineResult,
        delete_cycles: bool,
    ) -> None:
        """Find and handle bidirectional Composition pairs (A→B AND B→A).

        For each pair, we keep the relationship with higher confidence
        (or the first one if confidence is equal).
        """
        # Query for bidirectional Composition relationships
        bidirectional_query = f"""
            MATCH (a)-[r1:`{ns}:Composition`]->(b)-[r2:`{ns}:Composition`]->(a)
            WHERE a.enabled = true AND b.enabled = true
              AND a.identifier < b.identifier  // Avoid duplicates (A,B) and (B,A)
            RETURN
                a.identifier AS a_id,
                a.name AS a_name,
                b.identifier AS b_id,
                b.name AS b_name,
                r1.identifier AS r1_id,
                r1.confidence AS r1_confidence,
                r2.identifier AS r2_id,
                r2.confidence AS r2_confidence
        """

        pairs = archimate_manager.query(bidirectional_query)

        if not pairs:
            logger.debug("No bidirectional Composition pairs found")
            return

        logger.info(f"Found {len(pairs)} bidirectional Composition pairs")

        to_delete = []
        for pair in pairs:
            result.issues_found += 1

            # Determine which relationship to keep (higher confidence)
            r1_conf = pair.get("r1_confidence") or 0.5
            r2_conf = pair.get("r2_confidence") or 0.5

            if r1_conf >= r2_conf:
                keep_id, delete_id = pair["r1_id"], pair["r2_id"]
                keep_dir = f"{pair['a_name']} → {pair['b_name']}"
            else:
                keep_id, delete_id = pair["r2_id"], pair["r1_id"]
                keep_dir = f"{pair['b_name']} → {pair['a_name']}"

            result.details.append(
                {
                    "action": "deleted" if delete_cycles else "flagged",
                    "reason": "bidirectional_composition",
                    "element_a": pair["a_id"],
                    "element_a_name": pair["a_name"],
                    "element_b": pair["b_id"],
                    "element_b_name": pair["b_name"],
                    "kept": keep_id,
                    "kept_direction": keep_dir,
                    "deleted": delete_id,
                    "r1_confidence": r1_conf,
                    "r2_confidence": r2_conf,
                }
            )

            if delete_cycles:
                to_delete.append(delete_id)

        # Delete the relationships
        if to_delete:
            deleted_count = archimate_manager.delete_relationships(to_delete)
            result.relationships_deleted += deleted_count
            result.issues_fixed += deleted_count
            logger.info(f"Deleted {deleted_count} bidirectional Composition relationships")

    def _handle_longer_cycles(
        self,
        archimate_manager: ArchimateManager,
        ns: str,
        result: RefineResult,
        max_length: int,
        delete_cycles: bool,
    ) -> None:
        """Find and handle longer Composition cycles (A→B→C→A).

        Uses variable-length path matching to find cycles of length 3+.
        """
        # Query for cycles of length 3 to max_length
        # Note: This can be expensive for large graphs
        cycle_query = f"""
            MATCH path = (start)-[:`{ns}:Composition`*3..{max_length}]->(start)
            WHERE start.enabled = true
            WITH start, path,
                 [r IN relationships(path) | r.identifier] AS rel_ids,
                 [r IN relationships(path) | coalesce(r.confidence, 0.5)] AS confidences,
                 [n IN nodes(path) | n.name] AS node_names
            // Get minimum confidence relationship in cycle
            WITH start, rel_ids, confidences, node_names,
                 reduce(minIdx = 0, i IN range(0, size(confidences)-1) |
                     CASE WHEN confidences[i] < confidences[minIdx] THEN i ELSE minIdx END
                 ) AS weakest_idx
            RETURN DISTINCT
                start.identifier AS start_id,
                start.name AS start_name,
                rel_ids,
                confidences,
                node_names,
                weakest_idx,
                rel_ids[weakest_idx] AS weakest_rel_id,
                confidences[weakest_idx] AS weakest_confidence
            LIMIT 100  // Safety limit
        """

        try:
            cycles = archimate_manager.query(cycle_query)
        except Exception as e:
            logger.warning(f"Cycle detection query failed: {e}")
            return

        if not cycles:
            logger.debug("No longer Composition cycles found")
            return

        logger.info(f"Found {len(cycles)} longer Composition cycles")

        # Track which relationships we've already marked for deletion
        already_deleted = set()
        to_delete = []

        for cycle in cycles:
            # Skip if we've already handled this cycle via another relationship
            weakest_rel = cycle["weakest_rel_id"]
            if weakest_rel in already_deleted:
                continue

            result.issues_found += 1
            cycle_path = " → ".join(cycle["node_names"])

            result.details.append(
                {
                    "action": "deleted" if delete_cycles else "flagged",
                    "reason": "composition_cycle",
                    "cycle_path": cycle_path,
                    "cycle_length": len(cycle["rel_ids"]),
                    "weakest_rel_id": weakest_rel,
                    "weakest_confidence": cycle["weakest_confidence"],
                    "all_rel_ids": cycle["rel_ids"],
                }
            )

            if delete_cycles:
                to_delete.append(weakest_rel)
                already_deleted.add(weakest_rel)

        # Delete the weakest links
        if to_delete:
            deleted_count = archimate_manager.delete_relationships(to_delete)
            result.relationships_deleted += deleted_count
            result.issues_fixed += deleted_count
            logger.info(f"Deleted {deleted_count} relationships to break cycles")
