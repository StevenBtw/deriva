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

import json
import logging
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from deriva.adapters.archimate.models import (
    RELATIONSHIP_TYPES,
    Relationship,
    validate_relationship_rule,
)

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.archimate.models import Element
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# Graph edge type → ArchiMate relationship type mapping
# Based on ArchiMate semantics and graph_ideas.md research
#
# NOTE: CONTAINS and DECLARES are excluded. These edges exist between
# File->File, Directory->Directory, and TypeDefinition->TypeDefinition
# (10,000+ edges). Mapping them all to Composition creates an explosion
# of 100+ relationships. Composition between ArchiMate elements is
# handled by the per-element-type relationship rules instead.
EDGE_TO_RELATIONSHIP: dict[str, str] = {
    "IMPLEMENTS": "Realization",  # Interface realization
    "USES": "Serving",  # Uses external dependency
    "CALLS": "Flow",  # Call between behaviors
    "IMPORTS": "Serving",  # Import dependency
    "DEPENDS_ON": "Serving",  # Module dependency
    "INHERITS": "Realization",  # Class inheritance (subclass realizes base)
}

# =============================================================================
# Relationship validation uses RELATIONSHIP_TYPES from models.py
# This ensures consistency with the canonical ArchiMate 3.2 metamodel
# =============================================================================


def get_valid_element_combos(rel_type: str) -> dict[str, set[str] | None]:
    """Get valid source/target element types for a relationship type.

    Uses the canonical RELATIONSHIP_TYPES from models.py to ensure
    ArchiMate 3.2 metamodel compliance.

    Args:
        rel_type: Relationship type (e.g., "Composition", "Flow")

    Returns:
        Dict with "sources" and "targets" sets, or None if any element is allowed
    """
    if rel_type not in RELATIONSHIP_TYPES:
        return {"sources": None, "targets": None}

    rel_def = RELATIONSHIP_TYPES[rel_type]
    return {
        "sources": rel_def.allowed_sources if rel_def.allowed_sources else None,
        "targets": rel_def.allowed_targets if rel_def.allowed_targets else None,
    }


def _graph_edges(
    graph_manager: GraphManager, graph_ns: str, edge_type: str
) -> list[tuple[str, str]]:
    """Distinct (source id, target id) pairs of an edge type between active nodes."""
    rows = graph_manager.query(
        f"MATCH (a)-[:`{graph_ns}:{edge_type}`]->(b) "
        "WHERE a.active = true AND b.active = true "
        "RETURN a.id AS source, b.id AS target"
    )
    return sorted(
        {
            (r["source"], r["target"])
            for r in rows
            if r.get("source") and r.get("target")
        }
    )


def find_relationship_candidates(
    edges: list[tuple[str, str]],
    elements: list[Element],
    existing: set[tuple[str, str, str]],
    rel_type: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Element pairs whose source graph nodes are connected by one of ``edges``.

    Elements are linked to graph nodes by ``properties["source"]``. Pairs that
    already have a relationship of ``rel_type`` are skipped, as are element types
    the metamodel does not allow for ``rel_type``. If no element is linked this
    way, falls back to elements whose properties mention the graph node id and
    skips pairs that already have any relationship.
    """
    valid_combos = get_valid_element_combos(rel_type)
    valid_sources = valid_combos.get("sources")
    valid_targets = valid_combos.get("targets")

    def allowed(src: Element, tgt: Element) -> bool:
        # Each type may be a valid source and target on its own while the pair is
        # not; check the exact pair so rejected pairs never take a slot under limit
        return (
            src.identifier != tgt.identifier
            and (not valid_sources or src.element_type in valid_sources)
            and (not valid_targets or tgt.element_type in valid_targets)
            and (
                rel_type not in RELATIONSHIP_TYPES
                or validate_relationship_rule(
                    src.element_type, rel_type, tgt.element_type
                )[0]
            )
        )

    def row(src: Element, tgt: Element) -> dict[str, Any]:
        return {
            "source_id": src.identifier,
            "source_name": src.name,
            "target_id": tgt.identifier,
            "target_name": tgt.name,
        }

    by_source: dict[str, list[Element]] = defaultdict(list)
    for e in elements:
        if e.properties.get("source"):
            by_source[e.properties["source"]].append(e)

    rows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for graph_source, graph_target in edges:
        for src in by_source.get(graph_source, []):
            for tgt in by_source.get(graph_target, []):
                if (
                    allowed(src, tgt)
                    and (src.identifier, tgt.identifier, rel_type) not in existing
                ):
                    rows[
                        (graph_source, graph_target, src.identifier, tgt.identifier)
                    ] = {
                        **row(src, tgt),
                        "graph_source": graph_source,
                        "graph_target": graph_target,
                    }
    if rows:
        return [rows[k] for k in sorted(rows)][:limit]

    # Fallback: elements whose serialized properties mention the graph node id
    serialized = [(e, json.dumps(e.properties)) for e in elements if e.properties]
    mentions: dict[str, list[Element]] = {}
    for node_id in sorted({n for pair in edges for n in pair}):
        mentions[node_id] = [e for e, text in serialized if node_id in text]
    related = {(source, target) for source, target, _ in existing}
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for graph_source, graph_target in edges:
        for src in mentions[graph_source]:
            for tgt in mentions[graph_target]:
                if (
                    allowed(src, tgt)
                    and (src.identifier, tgt.identifier) not in related
                ):
                    pairs[(src.identifier, tgt.identifier)] = row(src, tgt)
    return [pairs[k] for k in sorted(pairs)][:limit]


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
            graph_ns = graph_manager.namespace
            # Read the model once; candidates are joined in Python (a Cypher join of
            # graph edges x model element pairs does not use indexes and is very slow).
            elements = archimate_manager.get_elements(enabled_only=True)
            existing = {
                (r.source, r.target, r.relationship_type)
                for r in archimate_manager.get_relationships()
            }

            total_created = 0

            for edge_type in edge_types:
                if edge_type not in EDGE_TO_RELATIONSHIP:
                    logger.warning(f"Unknown edge type: {edge_type}, skipping")
                    continue

                rel_type = EDGE_TO_RELATIONSHIP[edge_type]

                # Find graph edges and corresponding model elements
                candidates = find_relationship_candidates(
                    _graph_edges(graph_manager, graph_ns, edge_type),
                    elements,
                    existing,
                    rel_type,
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
                            existing.add(
                                (
                                    candidate["source_id"],
                                    candidate["target_id"],
                                    rel_type,
                                )
                            )
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
