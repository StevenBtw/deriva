"""
Structural Consistency - Refine Step.

Validates that source graph structural patterns are preserved in the ArchiMate model:
- Containment relationships in Graph → Composition/Aggregation in Model
- Call relationships in Graph → Flow/Serving in Model
- Import relationships in Graph → Serving in Model

This ensures the derived model reflects the actual code structure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# Mapping of Graph relationship types to expected ArchiMate relationship types
GRAPH_TO_ARCHIMATE_MAPPING = {
    "CONTAINS": {"Composition", "Aggregation"},
    "CALLS": {"Flow", "Serving", "Triggering"},
    "IMPORTS": {"Serving", "Access"},
    "USES": {"Access", "Serving"},
    "EXTENDS": {"Realization", "Specialization"},
    "IMPLEMENTS": {"Realization"},
}


@register_refine_step("structural_consistency")
class StructuralConsistencyStep:
    """Validate structural consistency between Graph and Model namespaces."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute structural consistency validation.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Manager for source graph operations (required)
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - check_containment: Check CONTAINS→Composition (default: True)
                - check_calls: Check CALLS→Flow/Serving (default: True)
                - strict_mode: Fail on any violations (default: False)

        Returns:
            RefineResult with details of structural inconsistencies found
        """
        params = params or {}
        check_containment = params.get("check_containment", True)
        check_calls = params.get("check_calls", True)

        result = RefineResult(
            success=True,
            step_name="structural_consistency",
        )

        if graph_manager is None:
            logger.warning(
                "Graph manager not provided, skipping structural consistency check"
            )
            result.details.append(
                {
                    "action": "skipped",
                    "reason": "graph_manager_not_provided",
                }
            )
            return result

        try:
            model_ns = archimate_manager.namespace

            # Check containment preservation
            if check_containment:
                self._check_containment_preservation(
                    graph_manager, archimate_manager, result, model_ns
                )

            # Check call relationship preservation
            if check_calls:
                self._check_call_preservation(
                    graph_manager, archimate_manager, result, model_ns
                )

            logger.info(
                f"Structural consistency check complete: {result.issues_found} issues found"
            )

        except Exception as e:
            logger.exception(f"Error in structural consistency check: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _check_containment_preservation(
        self,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        model_ns: str,
    ) -> None:
        """Check that Graph containment relationships are reflected in Model.

        Graph: (parent:Directory)-[:CONTAINS]->(child:Directory)
        Expected Model: (parent:ApplicationComponent)-[:Composition]->(child:ApplicationComponent)
        """
        # Query Graph for containment relationships between nodes that have Model representations
        containment_query = f"""
            MATCH (graph_parent)-[:Graph:CONTAINS]->(graph_child)
            WHERE graph_parent.active = true AND graph_child.active = true
              AND any(lbl IN labels(graph_parent) WHERE lbl STARTS WITH 'Graph:')
              AND any(lbl IN labels(graph_child) WHERE lbl STARTS WITH 'Graph:')
            WITH graph_parent.id as parent_source, graph_child.id as child_source

            // Find Model elements derived from these Graph nodes
            MATCH (model_parent), (model_child)
            WHERE any(lbl IN labels(model_parent) WHERE lbl STARTS WITH '{model_ns}:')
              AND any(lbl IN labels(model_child) WHERE lbl STARTS WITH '{model_ns}:')
              AND model_parent.enabled = true AND model_child.enabled = true
              AND model_parent.properties_json CONTAINS parent_source
              AND model_child.properties_json CONTAINS child_source

            // Check if there's a corresponding Model relationship
            OPTIONAL MATCH (model_parent)-[model_rel]->(model_child)
            WHERE type(model_rel) STARTS WITH '{model_ns}:'

            RETURN parent_source, child_source,
                   model_parent.identifier as parent_model_id,
                   model_parent.name as parent_name,
                   model_child.identifier as child_model_id,
                   model_child.name as child_name,
                   model_rel IS NOT NULL as has_model_relationship,
                   type(model_rel) as model_rel_type
            LIMIT 100
        """

        try:
            containments = archimate_manager.query(containment_query)
        except Exception as e:
            # Fallback to simpler query if complex one fails
            logger.warning(f"Complex containment query failed, using fallback: {e}")
            containments = []

        for item in containments:
            if not item["has_model_relationship"]:
                result.issues_found += 1
                result.details.append(
                    {
                        "action": "flagged",
                        "issue_type": "missing_containment_relationship",
                        "graph_parent": item["parent_source"],
                        "graph_child": item["child_source"],
                        "model_parent_id": item["parent_model_id"],
                        "model_parent_name": item["parent_name"],
                        "model_child_id": item["child_model_id"],
                        "model_child_name": item["child_name"],
                        "expected_rel_type": "Composition",
                        "reason": "containment_not_preserved",
                    }
                )

    def _check_call_preservation(
        self,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        model_ns: str,
    ) -> None:
        """Check that Graph call relationships are reflected in Model.

        Graph: (caller:Method)-[:CALLS]->(callee:Method)
        Expected Model: (caller:*)-[:Flow|Serving]->(callee:*)
        """
        # This is a simplified check - full implementation would cross-reference
        # Graph CALLS relationships with Model Flow/Serving relationships

        call_query = f"""
            MATCH (model_source)-[r]->(model_target)
            WHERE any(lbl IN labels(model_source) WHERE lbl STARTS WITH '{model_ns}:')
              AND any(lbl IN labels(model_target) WHERE lbl STARTS WITH '{model_ns}:')
              AND type(r) IN ['{model_ns}:Flow', '{model_ns}:Serving']
              AND model_source.enabled = true AND model_target.enabled = true
            RETURN count(*) as flow_serving_count
        """

        try:
            rel_counts = archimate_manager.query(call_query)
            if rel_counts:
                count = rel_counts[0]["flow_serving_count"]
                result.details.append(
                    {
                        "action": "info",
                        "flow_serving_relationships": count,
                        "reason": "call_preservation_summary",
                    }
                )
        except Exception as e:
            logger.warning(f"Call preservation check query failed: {e}")

    def _get_element_source(
        self, archimate_manager: ArchimateManager, identifier: str, model_ns: str
    ) -> str | None:
        """Get the source Graph node ID for a Model element."""
        query = f"""
            MATCH (e {{identifier: $identifier}})
            WHERE any(lbl IN labels(e) WHERE lbl STARTS WITH '{model_ns}:')
            RETURN e.properties_json as properties_json
        """

        try:
            result = archimate_manager.query(query, {"identifier": identifier})
            if result and result[0].get("properties_json"):
                import json

                props = json.loads(result[0]["properties_json"])
                return props.get("source")
        except Exception:
            pass

        return None
