"""
Orphan Elements Detection - Refine Step.

Finds ArchiMate elements with no relationships and flags them for review.
Elements without any connections may indicate:
- Incomplete derivation
- Elements that should be related to others
- Legitimate standalone elements

Uses source graph patterns to propose potential relationships.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

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
            # Query for elements with no relationships
            ns = archimate_manager.namespace
            orphan_query = f"""
                MATCH (e)
                WHERE any(lbl IN labels(e) WHERE lbl STARTS WITH '{ns}:')
                  AND e.enabled = true
                WITH e
                WHERE NOT EXISTS {{
                    MATCH (e)-[r]-()
                    WHERE type(r) STARTS WITH '{ns}:'
                }}
                RETURN e.identifier as identifier,
                       e.name as name,
                       [lbl IN labels(e) WHERE lbl STARTS WITH '{ns}:'][0] as label,
                       e.properties_json as properties_json
            """

            orphans = archimate_manager.query(orphan_query)

            if not orphans:
                logger.info("No orphan elements found")
                return result

            logger.info(f"Found {len(orphans)} orphan elements")

            for orphan in orphans:
                identifier = orphan["identifier"]
                name = orphan["name"]
                label = orphan["label"]
                element_type = label.split(":")[-1] if label else "Unknown"

                # Check source graph for potential relationships
                proposed_relationships = []
                if graph_manager:
                    proposed_relationships = self._propose_relationships(
                        graph_manager, archimate_manager, identifier
                    )

                # Calculate importance from properties if available
                importance = 0
                if orphan.get("properties_json"):
                    import json

                    try:
                        props = json.loads(orphan["properties_json"])
                        importance = props.get("source_pagerank", 0)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Decide action based on importance and params
                if disable_orphans and importance < min_importance:
                    archimate_manager.disable_element(
                        identifier, reason="orphan_no_relationships"
                    )
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

            logger.info(
                f"Orphan detection complete: {result.elements_disabled} disabled, "
                f"{result.issues_found} flagged"
            )

        except Exception as e:
            logger.exception(f"Error in orphan element detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _propose_relationships(
        self,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        element_identifier: str,
    ) -> list[dict[str, Any]]:
        """Propose relationships based on source graph patterns.

        Looks up the source node for the element and checks its
        relationships in the graph namespace.
        """
        proposals = []

        try:
            # Find the element's source node
            ns = archimate_manager.namespace
            source_query = f"""
                MATCH (e {{identifier: $identifier}})
                WHERE any(lbl IN labels(e) WHERE lbl STARTS WITH '{ns}:')
                RETURN e.properties_json as properties_json
            """
            result = archimate_manager.query(
                source_query, {"identifier": element_identifier}
            )

            if not result:
                return proposals

            # Extract source from properties
            import json

            props_json = result[0].get("properties_json")
            if not props_json:
                return proposals

            try:
                props = json.loads(props_json)
            except (json.JSONDecodeError, TypeError):
                return proposals

            source_id = props.get("source")
            if not source_id:
                return proposals

            # Query graph for relationships of the source node
            graph_rel_query = """
                MATCH (source)-[r]->(target)
                WHERE source.id = $source_id
                  AND any(lbl IN labels(target) WHERE lbl STARTS WITH 'Graph:')
                RETURN type(r) as rel_type, target.id as target_id, target.name as target_name
                LIMIT 5
            """
            graph_rels = graph_manager.query(graph_rel_query, {"source_id": source_id})

            # Map graph relationships to potential ArchiMate relationships
            rel_mapping = {
                "CONTAINS": "Composition",
                "CALLS": "Flow",
                "IMPORTS": "Serving",
                "USES": "Access",
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
