"""
BusinessProcess Derivation.

A BusinessProcess represents a sequence of business behaviors that achieves
a specific outcome such as a defined set of products or business services.

Graph signals:
- Method nodes (functions implementing business logic)
- Nodes with workflow/process naming patterns
- High betweenness centrality (orchestrates other components)
- Route handlers in web applications
- Orchestrator methods (call 3+ other methods)

Filtering strategy:
1. Query Method nodes from source code
2. Exclude utility/helper methods
3. Prioritize methods with business-relevant names
4. Focus on methods that coordinate activities
5. Identify orchestrator methods via CALLS edge count

LLM role:
- Identify which methods represent business processes
- Generate meaningful process names
- Write documentation describing the process purpose

Relationships:
- OUTBOUND: BusinessProcess -> BusinessObject (Access) - processes access business objects
- INBOUND: None defined

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessProcess

Typical Sources:
    - Method nodes with workflow/orchestration logic
    - Functions with names like process_*, handle_*, execute_*
    - Orchestrator methods that coordinate multiple sub-operations
"""

from __future__ import annotations

import logging
from typing import Any

from deriva.modules.derivation.base import (
    Candidate,
    RelationshipRule,
    enrich_candidate,
)
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class BusinessProcessDerivation(HybridDerivation):
    """
    BusinessProcess element derivation.

    Uses hybrid filtering combining patterns and graph analysis to identify
    business processes from Method nodes representing workflow logic.

    Orchestrator detection: Methods that call 3+ other methods are likely
    processes (coordination pattern).
    """

    ELEMENT_TYPE = "BusinessProcess"

    # Graph filtering configuration
    MIN_PAGERANK = 0.0005
    MIN_ORCHESTRATOR_CALLS = 3  # Methods calling 3+ others are likely processes

    OUTBOUND_RULES = [
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Access",
            description="Business processes access business objects",
        ),
        RelationshipRule(
            target_type="DataObject",
            rel_type="Access",
            description="Business processes access data objects",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Serving",
            description="Application services serve business processes",
        ),
    ]

    def filter_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str] | None = None,
        exclude_patterns: set[str] | None = None,
        **kwargs: Any,
    ) -> list[Candidate]:
        """Filter candidates for BusinessProcess derivation.

        Strategy depends on source type:
        - BusinessConcept: Filter by confidence (already semantically identified)
        - Method: Original orchestrator detection and graph filtering
        """
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        for c in candidates:
            enrich_candidate(c, enrichments)

        # Check if candidates are BusinessConcept (have conceptType property)
        is_business_concept = any(
            "BusinessConcept" in c.labels or c.properties.get("conceptType")
            for c in candidates
        )

        if is_business_concept:
            # BusinessConcept source: filter by confidence, skip graph metrics
            return self._filter_business_concepts(candidates, max_candidates)

        # Method source: original orchestrator-based filtering
        return self._filter_method_candidates(
            candidates, enrichments, max_candidates, include_patterns, exclude_patterns
        )

    def _filter_business_concepts(
        self,
        candidates: list[Candidate],
        max_candidates: int,
    ) -> list[Candidate]:
        """Filter BusinessConcept candidates by confidence.

        BusinessConcepts are already semantically identified as processes,
        so we just filter by confidence and limit count.
        """
        # Filter by confidence (property or direct attribute)
        MIN_CONFIDENCE = 0.7

        filtered = []
        for c in candidates:
            confidence = c.properties.get("confidence", 0)
            if confidence >= MIN_CONFIDENCE:
                filtered.append(c)

        # Sort by confidence descending
        filtered.sort(key=lambda c: c.properties.get("confidence", 0), reverse=True)

        self.logger.debug(
            "BusinessProcess filter (BusinessConcept): %d total -> %d passed confidence >= %.1f",
            len(candidates),
            len(filtered),
            MIN_CONFIDENCE,
        )

        return filtered[:max_candidates]

    def _filter_method_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str],
        exclude_patterns: set[str],
    ) -> list[Candidate]:
        """Filter Method candidates using orchestrator detection and graph metrics.

        Original strategy:
        1. Identify orchestrator methods (call 3+ other methods)
        2. Filter by process patterns
        3. Apply graph filtering (PageRank threshold)
        4. Prioritize orchestrators in final selection
        """
        # Pre-filter: exclude dunder methods
        filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

        # Identify orchestrators based on out_degree (CALLS edges)
        orchestrators = []
        non_orchestrators = []
        for c in filtered:
            out_degree = c.properties.get("out_degree", 0)
            if out_degree >= self.MIN_ORCHESTRATOR_CALLS:
                c.properties["is_orchestrator"] = True
                orchestrators.append(c)
            else:
                non_orchestrators.append(c)

        # Apply pattern matching
        likely_processes = [
            c
            for c in non_orchestrators
            if self.matches_patterns(c.name, include_patterns, exclude_patterns)
        ]
        others = [
            c
            for c in non_orchestrators
            if not self.matches_patterns(c.name, include_patterns, exclude_patterns)
        ]

        # Apply graph filtering to each group
        orchestrators = self.apply_graph_filtering(
            orchestrators, enrichments, max_candidates // 3
        )
        likely_processes = self.apply_graph_filtering(
            likely_processes, enrichments, max_candidates // 3
        )

        # Combine: orchestrators first, then pattern-matched, then others
        combined = orchestrators + likely_processes

        remaining_slots = max_candidates - len(combined)
        if remaining_slots > 0 and others:
            others = self.apply_graph_filtering(others, enrichments, remaining_slots)
            combined.extend(others)

        self.logger.debug(
            "BusinessProcess filter (Method): %d total -> %d orchestrators, %d pattern-matched -> %d final",
            len(candidates),
            len(orchestrators),
            len(likely_processes),
            len(combined),
        )

        return combined[:max_candidates]
