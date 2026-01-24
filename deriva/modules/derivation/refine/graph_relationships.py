"""
Graph-based deterministic relationship derivation - Refine Step.

Creates ArchiMate relationships from source graph edge patterns.
Runs before structural_consistency which validates the results.

This step addresses the relationship consistency problem (10-22%) by deriving
relationships deterministically from graph structure rather than LLM inference.

Graph Edge → ArchiMate Relationship Mapping:
- CONTAINS → Composition (structural containment)
- DECLARES → Composition (type declares method)
- IMPLEMENTS → Realization (interface implementation)
- USES → Serving (external dependency usage)
- CALLS → Flow (method invocation)
- IMPORTS → Serving (module import)
- DEPENDS_ON → Serving (module dependency)

Refine Step Name: "graph_relationships"
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate.models import Relationship

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# Graph edge type → ArchiMate relationship type mapping
# Based on ArchiMate semantics and graph_ideas.md research
EDGE_TO_RELATIONSHIP: dict[str, str] = {
    "CONTAINS": "Composition",  # Structural containment
    "DECLARES": "Composition",  # Type declares member
    "IMPLEMENTS": "Realization",  # Interface realization
    "USES": "Serving",  # Uses external dependency
    "CALLS": "Flow",  # Call between behaviors
    "IMPORTS": "Serving",  # Import dependency
    "DEPENDS_ON": "Serving",  # Module dependency
    "INHERITS": "Realization",  # Class inheritance (subclass realizes base)
}

# Valid source/target element type combinations per ArchiMate relationship type
# Based on ArchiMate 3.2 metamodel constraints
VALID_ELEMENT_COMBOS: dict[str, dict[str, set[str] | None]] = {
    "Composition": {
        # Composition: parent contains child (structural elements)
        "sources": {
            "ApplicationComponent",
            "Node",
            "Device",
            "SystemSoftware",
            "BusinessFunction",
        },
        "targets": {
            "ApplicationComponent",
            "ApplicationService",
            "ApplicationInterface",
            "DataObject",
            "Node",
            "Device",
            "SystemSoftware",
            "TechnologyService",
        },
    },
    "Realization": {
        # Realization: internal behavior realizes external behavior
        # Also used for class inheritance (INHERITS edges)
        "sources": {
            "ApplicationComponent",
            "ApplicationService",
            "SystemSoftware",
            "Node",
            "Device",
        },
        "targets": {
            "ApplicationComponent",  # For class inheritance
            "ApplicationService",
            "ApplicationInterface",
            "TechnologyService",
            "BusinessService",
            "BusinessProcess",
        },
    },
    "Serving": {
        # Serving: element provides functionality to another
        "sources": None,  # Any element can serve
        "targets": None,  # Any element can be served
    },
    "Flow": {
        # Flow: transfer of data/information between behaviors
        "sources": {
            "ApplicationService",
            "ApplicationInterface",
            "BusinessProcess",
            "BusinessFunction",
            "BusinessEvent",
            "TechnologyService",
        },
        "targets": {
            "ApplicationService",
            "ApplicationInterface",
            "BusinessProcess",
            "BusinessFunction",
            "BusinessEvent",
            "DataObject",
            "BusinessObject",
            "TechnologyService",
        },
    },
    "Access": {
        # Access: behavior accesses data
        "sources": {
            "ApplicationService",
            "ApplicationInterface",
            "BusinessProcess",
            "BusinessFunction",
        },
        "targets": {
            "DataObject",
            "BusinessObject",
        },
    },
}


@register_refine_step("graph_relationships")
class GraphRelationshipsStep:
    """Derive ArchiMate relationships from source graph edges.

    This step queries the Graph namespace for structural edges and creates
    corresponding ArchiMate relationships in the Model namespace where:
    1. Both source and target graph nodes have corresponding Model elements
    2. No relationship already exists between those elements
    3. The element types are valid for the relationship type

    This enables deterministic relationship derivation (~90%+ consistency)
    versus LLM-based inference (10-22% consistency).
    """

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute graph-based relationship derivation.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Manager for source graph operations (required)
            llm_query_fn: Not used (deterministic derivation)
            params: Optional parameters:
                - edge_types: List of graph edge types to process
                  (default: all in EDGE_TO_RELATIONSHIP)
                - max_relationships: Max relationships to create (default: 500)
                - dry_run: If True, only report what would be created

        Returns:
            RefineResult with relationships_created count
        """
        params = params or {}
        edge_types = params.get("edge_types", list(EDGE_TO_RELATIONSHIP.keys()))
        max_relationships = params.get("max_relationships", 500)
        dry_run = params.get("dry_run", False)

        result = RefineResult(
            success=True,
            step_name="graph_relationships",
        )

        if graph_manager is None:
            logger.warning(
                "Graph manager not provided, skipping graph relationship derivation"
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
            graph_ns = graph_manager.namespace

            total_created = 0

            for edge_type in edge_types:
                if edge_type not in EDGE_TO_RELATIONSHIP:
                    logger.warning(f"Unknown edge type: {edge_type}, skipping")
                    continue

                rel_type = EDGE_TO_RELATIONSHIP[edge_type]

                # Find graph edges and corresponding model elements
                candidates = self._find_relationship_candidates(
                    archimate_manager,
                    graph_manager,
                    edge_type,
                    rel_type,
                    model_ns,
                    graph_ns,
                    max_relationships - total_created,
                )

                if not candidates:
                    continue

                logger.info(
                    f"Found {len(candidates)} {edge_type} edges for {rel_type} relationships"
                )

                # Create relationships
                for candidate in candidates:
                    if total_created >= max_relationships:
                        logger.warning(
                            f"Reached max_relationships limit ({max_relationships})"
                        )
                        break

                    if dry_run:
                        result.details.append(
                            {
                                "action": "would_create",
                                "source": candidate["source_id"],
                                "target": candidate["target_id"],
                                "relationship_type": rel_type,
                                "graph_edge": edge_type,
                            }
                        )
                        result.relationships_created += 1
                        total_created += 1
                    else:
                        created = self._create_relationship(
                            archimate_manager,
                            candidate["source_id"],
                            candidate["target_id"],
                            rel_type,
                            edge_type,
                        )
                        if created:
                            result.relationships_created += 1
                            total_created += 1
                            result.details.append(
                                {
                                    "action": "created",
                                    "source": candidate["source_id"],
                                    "source_name": candidate.get("source_name"),
                                    "target": candidate["target_id"],
                                    "target_name": candidate.get("target_name"),
                                    "relationship_type": rel_type,
                                    "graph_edge": edge_type,
                                }
                            )

            logger.info(
                f"Graph relationship derivation complete: "
                f"{result.relationships_created} relationships "
                f"{'would be ' if dry_run else ''}created"
            )

        except Exception as e:
            logger.exception(f"Error in graph relationship derivation: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _find_relationship_candidates(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager,
        edge_type: str,
        rel_type: str,
        model_ns: str,
        graph_ns: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Find graph edges that should become ArchiMate relationships.

        Queries for graph edges where:
        1. Both source and target nodes have a corresponding Model element
           (tracked via source_identifier property)
        2. No relationship of this type already exists between the elements
        3. Element types are valid for the relationship type

        Args:
            archimate_manager: ArchiMate manager
            graph_manager: Graph manager
            edge_type: Graph edge type (e.g., "CONTAINS")
            rel_type: ArchiMate relationship type (e.g., "Composition")
            model_ns: Model namespace
            graph_ns: Graph namespace
            limit: Maximum candidates to return

        Returns:
            List of candidate dicts with source_id, target_id, names
        """
        # Build element type filter if needed
        valid_combos = VALID_ELEMENT_COMBOS.get(rel_type, {})
        valid_sources = valid_combos.get("sources")
        valid_targets = valid_combos.get("targets")

        source_filter = ""
        target_filter = ""
        circular_filter = ""

        if valid_sources:
            source_types = ", ".join(f"'{model_ns}:{t}'" for t in valid_sources)
            source_filter = f"""
                AND any(lbl IN labels(model_src) WHERE lbl IN [{source_types}])
            """

        if valid_targets:
            target_types = ", ".join(f"'{model_ns}:{t}'" for t in valid_targets)
            target_filter = f"""
                AND any(lbl IN labels(model_tgt) WHERE lbl IN [{target_types}])
            """

        # For Composition relationships, prevent circular containment (A→B AND B→A)
        if rel_type == "Composition":
            circular_filter = f"""
              // Prevent circular Composition: skip if reverse relationship exists
              AND NOT EXISTS {{
                  (model_tgt)-[reverse:`{model_ns}:Composition`]->(model_src)
              }}
            """

        # Query: find graph edges → model elements without existing relationships
        # Uses source_identifier property to link graph nodes to model elements
        query = f"""
            // Find graph edges of the specified type
            MATCH (graph_src)-[edge:`{graph_ns}:{edge_type}`]->(graph_tgt)
            WHERE graph_src.active = true AND graph_tgt.active = true

            // Find model elements that were derived from these graph nodes
            // Elements store their source graph node ID in source_identifier
            MATCH (model_src), (model_tgt)
            WHERE any(lbl IN labels(model_src) WHERE lbl STARTS WITH '{model_ns}:')
              AND any(lbl IN labels(model_tgt) WHERE lbl STARTS WITH '{model_ns}:')
              AND model_src.enabled = true AND model_tgt.enabled = true
              AND model_src.source_identifier = graph_src.id
              AND model_tgt.source_identifier = graph_tgt.id
              AND model_src.identifier <> model_tgt.identifier  // Prevent self-loops
              {source_filter}
              {target_filter}
              // Exclude if relationship already exists
              AND NOT EXISTS {{
                  (model_src)-[existing]->(model_tgt)
                  WHERE type(existing) = '{model_ns}:{rel_type}'
              }}
              {circular_filter}

            RETURN DISTINCT
                model_src.identifier AS source_id,
                model_src.name AS source_name,
                model_tgt.identifier AS target_id,
                model_tgt.name AS target_name,
                graph_src.id AS graph_source,
                graph_tgt.id AS graph_target
            LIMIT {limit}
        """

        try:
            results = archimate_manager.query(query)
            if results:
                return results
            # Primary query returned no results, try fallback
            logger.debug(
                "Primary query for %s returned no results, trying fallback",
                edge_type,
            )
            return self._find_candidates_fallback(
                archimate_manager,
                graph_manager,
                edge_type,
                rel_type,
                model_ns,
                graph_ns,
                limit,
            )
        except Exception as e:
            logger.warning("Query for %s edges failed: %s", edge_type, e)
            # Try fallback query using properties_json CONTAINS
            return self._find_candidates_fallback(
                archimate_manager,
                graph_manager,
                edge_type,
                rel_type,
                model_ns,
                graph_ns,
                limit,
            )

    def _find_candidates_fallback(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager,
        edge_type: str,
        rel_type: str,
        model_ns: str,
        graph_ns: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fallback candidate finding using properties_json.

        Used when source_identifier property is not available.
        Searches for graph node IDs in the properties_json field.
        """
        # Build element type filters (same as primary query)
        valid_combos = VALID_ELEMENT_COMBOS.get(rel_type, {})
        valid_sources = valid_combos.get("sources")
        valid_targets = valid_combos.get("targets")

        source_filter = ""
        target_filter = ""
        circular_filter = ""

        if valid_sources:
            source_types = ", ".join(f"'{model_ns}:{t}'" for t in valid_sources)
            source_filter = f"""
                AND any(lbl IN labels(model_src) WHERE lbl IN [{source_types}])
            """

        if valid_targets:
            target_types = ", ".join(f"'{model_ns}:{t}'" for t in valid_targets)
            target_filter = f"""
                AND any(lbl IN labels(model_tgt) WHERE lbl IN [{target_types}])
            """

        # Prevent circular Composition relationships
        if rel_type == "Composition":
            circular_filter = f"""
              AND NOT EXISTS {{
                  (model_tgt)-[reverse:`{model_ns}:Composition`]->(model_src)
              }}
            """

        query = f"""
            // Find graph edges of the specified type
            MATCH (graph_src)-[edge:`{graph_ns}:{edge_type}`]->(graph_tgt)
            WHERE graph_src.active = true AND graph_tgt.active = true

            WITH graph_src.id as src_id, graph_tgt.id as tgt_id

            // Find model elements that reference these graph nodes in properties
            MATCH (model_src), (model_tgt)
            WHERE any(lbl IN labels(model_src) WHERE lbl STARTS WITH '{model_ns}:')
              AND any(lbl IN labels(model_tgt) WHERE lbl STARTS WITH '{model_ns}:')
              AND model_src.enabled = true AND model_tgt.enabled = true
              AND model_src.properties_json CONTAINS src_id
              AND model_tgt.properties_json CONTAINS tgt_id
              AND model_src.identifier <> model_tgt.identifier  // Prevent self-loops
              {source_filter}
              {target_filter}
              // Exclude if relationship already exists
              AND NOT EXISTS {{
                  (model_src)-[existing]->(model_tgt)
                  WHERE type(existing) STARTS WITH '{model_ns}:'
              }}
              {circular_filter}

            RETURN DISTINCT
                model_src.identifier AS source_id,
                model_src.name AS source_name,
                model_tgt.identifier AS target_id,
                model_tgt.name AS target_name
            LIMIT {limit}
        """

        try:
            results = archimate_manager.query(query)
            return results if results else []
        except Exception as e:
            logger.warning(f"Fallback query for {edge_type} edges also failed: {e}")
            return []

    def _create_relationship(
        self,
        archimate_manager: ArchimateManager,
        source_id: str,
        target_id: str,
        rel_type: str,
        graph_edge: str,
    ) -> bool:
        """Create an ArchiMate relationship.

        Args:
            archimate_manager: ArchiMate manager
            source_id: Source element identifier
            target_id: Target element identifier
            rel_type: Relationship type (e.g., "Composition")
            graph_edge: Originating graph edge type (for documentation)

        Returns:
            True if created successfully, False otherwise
        """
        # Safety check: prevent self-referential relationships
        if source_id == target_id:
            logger.warning(
                f"Skipping self-referential relationship: {source_id} -> {target_id}"
            )
            return False

        try:
            relationship = Relationship(
                source=source_id,
                target=target_id,
                relationship_type=rel_type,
                identifier=f"rel-{uuid.uuid4().hex[:12]}",
                documentation=f"Derived from Graph:{graph_edge} edge",
                properties={"derived_from": f"Graph:{graph_edge}"},
            )

            archimate_manager.add_relationship(relationship, validate=True)
            logger.debug(
                f"Created {rel_type}: {source_id} -> {target_id} (from {graph_edge})"
            )
            return True

        except Exception as e:
            logger.warning(
                f"Failed to create {rel_type} relationship "
                f"{source_id} -> {target_id}: {e}"
            )
            return False
