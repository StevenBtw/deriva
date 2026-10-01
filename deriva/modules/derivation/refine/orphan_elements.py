"""
Orphan Elements Detection - Refine Step.

Finds ArchiMate elements with no relationships and flags them for review.
Elements without any connections may indicate:
- Incomplete derivation
- Elements that should be related to others
- Legitimate standalone elements

Uses source graph patterns to propose potential relationships.

Refine Step Name: "orphan_elements"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)

logger = logging.getLogger(__name__)


@register_refine_step("orphan_elements")
class OrphanElementsStep:
    """Find ArchiMate elements with no relationships."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute orphan element detection.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Optional manager for source graph (for relationship proposals)
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - disable_orphans: Whether to disable orphan elements (default: False)
                - min_importance: Minimum importance (pagerank) to keep (default: 0)

        Returns:
            RefineResult with details of orphan elements found
        """
        params = params or {}
        disable_orphans = params.get("disable_orphans", False)
        min_importance = params.get("min_importance", 0)

        result = RefineResult(
            success=True,
            step_name="orphan_elements",
        )

        try:
            orphans = archimate_manager.get_orphan_elements()

            if not orphans:
                logger.info("No orphan elements found")
                return result

            logger.info(f"Found {len(orphans)} orphan elements")

            for orphan in orphans:
                identifier = orphan.identifier
                name = orphan.name
                element_type = orphan.element_type

                # Check source graph for potential relationships
                proposed_relationships = []
                if graph_manager:
                    proposed_relationships = self._propose_relationships(graph_manager, orphan.properties.get("source"))

                importance = orphan.properties.get("source_pagerank", 0)

                # Decide action based on importance and params
                if disable_orphans and importance < min_importance:
                    archimate_manager.disable_element(identifier, reason="orphan_no_relationships")
                    result.elements_disabled += 1
                    result.issues_fixed += 1
                    result.details.append(
                        {
                            "action": "disabled",
                            "identifier": identifier,
                            "name": name,
                            "element_type": element_type,
                            "importance": importance,
                            "reason": "orphan_below_threshold",
                        }
                    )
                else:
                    # Flag for review
                    result.issues_found += 1
                    result.details.append(
                        {
                            "action": "flagged",
                            "identifier": identifier,
                            "name": name,
                            "element_type": element_type,
                            "importance": importance,
                            "proposed_relationships": proposed_relationships,
                            "reason": "orphan_no_relationships",
                        }
                    )

            logger.info(f"Orphan detection complete: {result.elements_disabled} disabled, {result.issues_found} flagged")

        except Exception as e:
            logger.exception(f"Error in orphan element detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _propose_relationships(self, graph_manager: GraphManager, source_id: str | None) -> list[dict[str, Any]]:
        """Propose relationships from the relationships of the element's source node in the graph."""
        proposals: list[dict[str, Any]] = []
        if not source_id:
            return proposals

        try:
            graph_rel_query = """
                MATCH (source)-[r]->(target)
                WHERE source.id = $source_id
                  AND 'Graph' IN labels(target)
                RETURN type(r) as rel_type, target.id as target_id, target.name as target_name
                LIMIT 5
            """
            graph_rels = graph_manager.query(graph_rel_query, {"source_id": source_id})

            # Map graph relationships to potential ArchiMate relationships
            # Note: USES maps to Serving (dependency), not Access (data access)
            # Access is specifically for Behavior→Passive element access
            rel_mapping = {
                "CONTAINS": "Composition",
                "CALLS": "Flow",
                "IMPORTS": "Serving",
                "USES": "Serving",  # Dependency usage, not data access
            }

            for rel in graph_rels:
                graph_rel_type = rel["rel_type"].split(":")[-1]
                archimate_rel_type = rel_mapping.get(graph_rel_type, "Association")

                proposals.append(
                    {
                        "source_graph_rel": graph_rel_type,
                        "proposed_archimate_rel": archimate_rel_type,
                        "target_graph_id": rel["target_id"],
                        "target_name": rel["target_name"],
                    }
                )

        except Exception as e:
            logger.warning(f"Error proposing relationships: {e}")

        return proposals
