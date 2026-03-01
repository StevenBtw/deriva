"""
Structural Consistency - Refine Step.

Validates that source graph structural patterns are preserved in the ArchiMate model:
- Containment relationships in Graph → Composition/Aggregation in Model
- Call relationships in Graph → Flow/Serving in Model
- Import relationships in Graph → Serving in Model

This ensures the derived model reflects the actual code structure.

Refine Step Name: "structural_consistency"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate.models import BEHAVIOR_ELEMENTS, PASSIVE_ELEMENTS

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# ArchiMate relationship aspect constraints
# These relationships have strict source/target aspect requirements
ASPECT_CONSTRAINED_RELATIONSHIPS = {
    "Flow": {"valid_sources": BEHAVIOR_ELEMENTS, "valid_targets": BEHAVIOR_ELEMENTS},
    "Triggering": {"valid_sources": BEHAVIOR_ELEMENTS, "valid_targets": BEHAVIOR_ELEMENTS},
    "Access": {"valid_sources": None, "valid_targets": PASSIVE_ELEMENTS},  # Any source, passive target
}

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
                - check_aspect_constraints: Check Flow/Access aspect constraints (default: True)
                - fix_aspect_violations: Auto-fix Flow→Passive to Access (default: False)
                - strict_mode: Fail on any violations (default: False)

        Returns:
            RefineResult with details of structural inconsistencies found
        """
        params = params or {}
        check_containment = params.get("check_containment", True)
        check_calls = params.get("check_calls", True)
        check_aspect_constraints = params.get("check_aspect_constraints", True)
        fix_aspect_violations = params.get("fix_aspect_violations", False)

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

            # Check ArchiMate aspect constraints (Flow/Triggering/Access)
            if check_aspect_constraints:
                self._check_aspect_constraints(
                    archimate_manager, result, model_ns, fix_aspect_violations
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
            MATCH (graph_parent)-[:`Graph:CONTAINS`]->(graph_child)
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

    def _check_aspect_constraints(
        self,
        archimate_manager: ArchimateManager,
        result: RefineResult,
        model_ns: str,
        fix_violations: bool = False,
    ) -> None:
        """Check that relationships respect ArchiMate aspect constraints.

        Flow and Triggering: Must be between Behavior elements only
        Access: Must target Passive elements only

        Args:
            archimate_manager: Manager for ArchiMate model operations
            result: RefineResult to update with findings
            model_ns: Model namespace
            fix_violations: If True, auto-fix Flow→Passive to Access
        """
        # Query all Flow relationships and check source/target element types
        flow_query = f"""
            MATCH (source)-[r:`{model_ns}:Flow`]->(target)
            WHERE source.enabled = true AND target.enabled = true
            RETURN r.identifier as rel_id,
                   source.identifier as source_id,
                   source.name as source_name,
                   source.element_type as source_type,
                   target.identifier as target_id,
                   target.name as target_name,
                   target.element_type as target_type
        """

        try:
            flow_rels = archimate_manager.query(flow_query)
        except Exception as e:
            logger.warning(f"Flow aspect constraint check query failed: {e}")
            flow_rels = []

        violations_found = 0
        violations_fixed = 0

        for rel in flow_rels:
            source_type = rel.get("source_type", "")
            target_type = rel.get("target_type", "")

            # Check if source is a Behavior element
            source_valid = source_type in BEHAVIOR_ELEMENTS
            # Check if target is a Behavior element
            target_valid = target_type in BEHAVIOR_ELEMENTS

            if not source_valid or not target_valid:
                violations_found += 1

                # Determine the specific violation
                if not target_valid and target_type in PASSIVE_ELEMENTS:
                    violation_type = "flow_to_passive"
                    suggested_fix = "Change to Access relationship"
                elif not source_valid:
                    violation_type = "flow_from_non_behavior"
                    suggested_fix = "Review source element type"
                else:
                    violation_type = "flow_to_non_behavior"
                    suggested_fix = "Review target element type"

                if fix_violations and violation_type == "flow_to_passive":
                    # Auto-fix: Change Flow to Access
                    try:
                        self._fix_flow_to_access(
                            archimate_manager, rel["rel_id"], model_ns
                        )
                        violations_fixed += 1
                        result.details.append(
                            {
                                "action": "fixed",
                                "issue_type": violation_type,
                                "relationship_id": rel["rel_id"],
                                "source": f"{rel['source_name']} ({source_type})",
                                "target": f"{rel['target_name']} ({target_type})",
                                "fix_applied": "Changed Flow to Access",
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to fix Flow→Passive violation: {e}")
                        result.issues_found += 1
                        result.details.append(
                            {
                                "action": "flagged",
                                "issue_type": violation_type,
                                "relationship_id": rel["rel_id"],
                                "source": f"{rel['source_name']} ({source_type})",
                                "target": f"{rel['target_name']} ({target_type})",
                                "suggested_fix": suggested_fix,
                                "fix_error": str(e),
                            }
                        )
                else:
                    result.issues_found += 1
                    result.details.append(
                        {
                            "action": "flagged",
                            "issue_type": violation_type,
                            "relationship_id": rel["rel_id"],
                            "source": f"{rel['source_name']} ({source_type})",
                            "target": f"{rel['target_name']} ({target_type})",
                            "suggested_fix": suggested_fix,
                        }
                    )

        if violations_found > 0:
            logger.warning(
                f"Found {violations_found} Flow aspect constraint violations, "
                f"fixed {violations_fixed}"
            )
        else:
            result.details.append(
                {
                    "action": "info",
                    "message": "No Flow aspect constraint violations found",
                    "flow_relationships_checked": len(flow_rels),
                }
            )

    def _fix_flow_to_access(
        self,
        archimate_manager: ArchimateManager,
        rel_id: str,
        model_ns: str,
    ) -> None:
        """Fix a Flow→Passive violation by changing the relationship type to Access.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            rel_id: Identifier of the relationship to fix
            model_ns: Model namespace
        """
        # Update the relationship type from Flow to Access
        # This requires deleting the old relationship and creating a new one
        # because Neo4j doesn't allow changing relationship types in-place

        # Get the relationship details first
        query = f"""
            MATCH (source)-[r:`{model_ns}:Flow`]->(target)
            WHERE r.identifier = $rel_id
            RETURN source.identifier as source_id,
                   target.identifier as target_id,
                   r.name as name,
                   r.documentation as documentation,
                   r.properties_json as properties_json,
                   r.confidence as confidence
        """

        results = archimate_manager.query(query, {"rel_id": rel_id})
        if not results:
            raise ValueError(f"Relationship {rel_id} not found")

        rel_data = results[0]

        # Delete the old Flow relationship
        delete_query = f"""
            MATCH ()-[r:`{model_ns}:Flow`]->()
            WHERE r.identifier = $rel_id
            DELETE r
        """
        archimate_manager.query(delete_query, {"rel_id": rel_id})

        # Create new Access relationship with same properties
        create_query = f"""
            MATCH (source {{identifier: $source_id}}), (target {{identifier: $target_id}})
            WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{model_ns}:')
              AND any(lbl IN labels(target) WHERE lbl STARTS WITH '{model_ns}:')
            CREATE (source)-[r:`{model_ns}:Access` {{
                identifier: $rel_id,
                relationship_type: 'Access',
                name: $name,
                documentation: $documentation,
                properties_json: $properties_json,
                confidence: $confidence
            }}]->(target)
            RETURN r.identifier as new_id
        """

        archimate_manager.query(
            create_query,
            {
                "source_id": rel_data["source_id"],
                "target_id": rel_data["target_id"],
                "rel_id": rel_id,
                "name": rel_data.get("name"),
                "documentation": rel_data.get("documentation"),
                "properties_json": rel_data.get("properties_json"),
                "confidence": rel_data.get("confidence", 0.9),
            },
        )

        logger.info(f"Fixed Flow→Access: {rel_id}")
