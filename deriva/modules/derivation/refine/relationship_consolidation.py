"""
Relationship Consolidation - Refine Step.

Consolidates and improves relationship quality by:
1. Boosting confidence when multiple derivation signals agree
2. Pruning low-confidence relationships with no corroboration
3. Merging equivalent relationships from different derivation sources

This step runs after initial derivation to improve model quality.

Confidence boosting rules:
- Same source/target with multiple relationship types: +0.05 per additional signal
- Edge-based + community-based derivation agree: +0.10
- Edge-based + name-based derivation agree: +0.10
- All three signals agree: +0.15 (total)

Pruning rules:
- Confidence < min_confidence (default 0.5): pruned
- Single-signal derivation with confidence < require_corroboration_threshold: pruned

Refine Step Name: "relationship_consolidation"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import RefineResult, register_refine_step

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# Derivation source signals that can corroborate each other
DERIVATION_SIGNALS = {
    "edge_calls": "edge",
    "edge_imports": "edge",
    "edge_uses": "edge",
    "community": "community",
    "neighbor": "community",
    "name_match": "name",
    "llm": "llm",
}

# Confidence boost amounts
BOOST_AMOUNTS = {
    "two_signals": 0.05,  # Two different signal categories agree
    "edge_community": 0.10,  # Edge + community agree
    "edge_name": 0.10,  # Edge + name agree
    "all_three": 0.15,  # Edge + community + name all agree (replaces individual boosts)
}


@register_refine_step("relationship_consolidation")
class RelationshipConsolidationStep:
    """Consolidate and improve relationship quality through confidence analysis."""

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute relationship consolidation.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Not used for this step
            llm_query_fn: Not used for this step
            params: Optional parameters:
                - min_confidence: Minimum confidence to keep (default: 0.5)
                - require_corroboration: Require multiple signals for low-confidence (default: True)
                - corroboration_threshold: Below this confidence, require corroboration (default: 0.7)
                - auto_prune: Actually delete low-confidence relationships (default: False)

        Returns:
            RefineResult with consolidation details
        """
        params = params or {}
        min_confidence = params.get("min_confidence", 0.5)
        require_corroboration = params.get("require_corroboration", True)
        corroboration_threshold = params.get("corroboration_threshold", 0.7)
        auto_prune = params.get("auto_prune", False)

        result = RefineResult(
            success=True,
            step_name="relationship_consolidation",
        )

        try:
            # Step 1: Get all relationships with their properties
            ns = archimate_manager.namespace
            rel_query = f"""
                MATCH (source:{ns})-[r]->(target:{ns})
                WHERE type(r) STARTS WITH '{ns}:'
                  AND source.enabled = true AND target.enabled = true
                RETURN r.identifier as identifier,
                       source.identifier as source_id,
                       source.name as source_name,
                       target.identifier as target_id,
                       target.name as target_name,
                       type(r) as rel_type,
                       r.confidence as confidence,
                       r.derived_from as derived_from,
                       r.name as rel_name
            """

            relationships = archimate_manager.query(rel_query)

            if not relationships:
                logger.info("No relationships found to consolidate")
                return result

            logger.info(
                f"Analyzing {len(relationships)} relationships for consolidation"
            )

            # Step 2: Group relationships by source-target pair
            rel_groups: dict[tuple[str, str], list[dict]] = {}
            for rel in relationships:
                key = (rel["source_id"], rel["target_id"])
                if key not in rel_groups:
                    rel_groups[key] = []
                rel_groups[key].append(rel)

            # Step 3: Process each group
            relationships_to_boost: list[
                tuple[str, float, str]
            ] = []  # (id, new_confidence, reason)
            relationships_to_prune: list[tuple[str, str]] = []  # (id, reason)

            for (source_id, target_id), rels in rel_groups.items():
                # Collect all derivation signals for this source-target pair
                signals = self._collect_signals(rels)

                # Calculate confidence boost
                boost, boost_reason = self._calculate_boost(signals)

                # Apply boost to all relationships in the group
                for rel in rels:
                    current_conf = rel.get("confidence") or 0.8  # Default confidence
                    new_conf = min(1.0, current_conf + boost)

                    if boost > 0:
                        relationships_to_boost.append(
                            (rel["identifier"], new_conf, boost_reason)
                        )
                        result.details.append(
                            {
                                "action": "boosted",
                                "relationship_id": rel["identifier"],
                                "source": rel["source_name"],
                                "target": rel["target_name"],
                                "rel_type": rel["rel_type"].split(":")[-1],
                                "old_confidence": current_conf,
                                "new_confidence": new_conf,
                                "reason": boost_reason,
                            }
                        )

                    # Check for pruning
                    should_prune, prune_reason = self._should_prune(
                        rel,
                        signals,
                        min_confidence,
                        require_corroboration,
                        corroboration_threshold,
                    )

                    if should_prune:
                        relationships_to_prune.append((rel["identifier"], prune_reason))
                        result.issues_found += 1
                        result.details.append(
                            {
                                "action": "flagged_for_prune"
                                if not auto_prune
                                else "pruned",
                                "relationship_id": rel["identifier"],
                                "source": rel["source_name"],
                                "target": rel["target_name"],
                                "rel_type": rel["rel_type"].split(":")[-1],
                                "confidence": rel.get("confidence"),
                                "reason": prune_reason,
                            }
                        )

            # Step 4: Apply confidence boosts
            for rel_id, new_conf, _ in relationships_to_boost:
                update_query = """
                    MATCH ()-[r]->()
                    WHERE r.identifier = $identifier
                    SET r.confidence = $confidence, r.consolidated = true
                """
                archimate_manager.query(
                    update_query, {"identifier": rel_id, "confidence": new_conf}
                )

            # Step 5: Prune low-confidence relationships (if auto_prune enabled)
            if auto_prune and relationships_to_prune:
                prune_ids = [rel_id for rel_id, _ in relationships_to_prune]
                deleted = archimate_manager.delete_relationships(prune_ids)
                result.relationships_deleted = deleted
                result.issues_fixed = deleted
                logger.info(f"Pruned {deleted} low-confidence relationships")
            elif relationships_to_prune:
                logger.info(
                    f"Found {len(relationships_to_prune)} relationships below confidence threshold "
                    f"(set auto_prune=true to remove)"
                )

            logger.info(
                f"Relationship consolidation complete: "
                f"{len(relationships_to_boost)} boosted, "
                f"{len(relationships_to_prune)} flagged for pruning"
            )

        except Exception as e:
            logger.exception(f"Error in relationship consolidation: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _collect_signals(self, relationships: list[dict]) -> set[str]:
        """Collect unique derivation signal categories from relationships.

        Args:
            relationships: List of relationship records

        Returns:
            Set of signal categories (edge, community, name, llm)
        """
        signals = set()
        for rel in relationships:
            derived_from = rel.get("derived_from") or ""
            # Map specific sources to categories
            for source_key, category in DERIVATION_SIGNALS.items():
                if source_key in derived_from.lower():
                    signals.add(category)
        return signals

    def _calculate_boost(self, signals: set[str]) -> tuple[float, str]:
        """Calculate confidence boost based on corroborating signals.

        Args:
            signals: Set of signal categories

        Returns:
            Tuple of (boost_amount, reason_string)
        """
        if not signals or len(signals) < 2:
            return 0.0, ""

        has_edge = "edge" in signals
        has_community = "community" in signals
        has_name = "name" in signals

        # Check for all three agreeing
        if has_edge and has_community and has_name:
            return BOOST_AMOUNTS["all_three"], "edge+community+name agreement"

        # Check for specific pair combinations
        boost = 0.0
        reasons = []

        if has_edge and has_community:
            boost += BOOST_AMOUNTS["edge_community"]
            reasons.append("edge+community")

        if has_edge and has_name:
            boost += BOOST_AMOUNTS["edge_name"]
            reasons.append("edge+name")

        # Generic two-signal boost if no specific pairs matched
        if boost == 0.0 and len(signals) >= 2:
            boost = BOOST_AMOUNTS["two_signals"]
            reasons.append(f"{len(signals)} signals agree")

        return boost, " + ".join(reasons) if reasons else ""

    def _should_prune(
        self,
        rel: dict,
        signals: set[str],
        min_confidence: float,
        require_corroboration: bool,
        corroboration_threshold: float,
    ) -> tuple[bool, str]:
        """Determine if a relationship should be pruned.

        Args:
            rel: Relationship record
            signals: Set of signal categories for this source-target pair
            min_confidence: Minimum confidence to keep
            require_corroboration: Whether to require multiple signals for low confidence
            corroboration_threshold: Confidence level below which corroboration is required

        Returns:
            Tuple of (should_prune, reason)
        """
        confidence = rel.get("confidence") or 0.8

        # Below minimum confidence is always pruned
        if confidence < min_confidence:
            return True, f"confidence {confidence:.2f} below minimum {min_confidence}"

        # Check for corroboration requirement
        if require_corroboration and confidence < corroboration_threshold:
            if len(signals) < 2:
                return True, (
                    f"confidence {confidence:.2f} below {corroboration_threshold} "
                    f"with only {len(signals)} signal(s)"
                )

        return False, ""
