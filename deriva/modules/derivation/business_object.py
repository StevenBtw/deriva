"""
BusinessObject Derivation.

A BusinessObject represents a passive element that has relevance from a
business perspective. It represents things like data entities, domain
concepts, or business documents.

Graph signals:
- TypeDefinition nodes (classes/data models)
- BusinessConcept nodes (from LLM extraction)
- File nodes with model patterns (models.py, entities.py, schema.py)
- High in-degree (many references = important domain concept)

Filtering strategy:
1. Query TypeDefinition and BusinessConcept nodes
2. Exclude utility classes (helpers, mixins, base classes)
3. Prioritize by PageRank (central domain concepts)
4. Focus on nouns that represent business data

LLM role:
- Identify which type definitions are business-relevant
- Generate meaningful business names (not code names)
- Write documentation describing the business meaning

Relationships:
- OUTBOUND: BusinessObject -> BusinessObject (Composition/Aggregation)
- INBOUND: BusinessProcess -> BusinessObject (Access)
- INBOUND: ApplicationService -> BusinessObject (Flow)

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessObject

Typical Sources:
    - TypeDefinition nodes (classes, dataclasses, models)
    - BusinessConcept nodes from LLM extraction
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


class BusinessObjectDerivation(HybridDerivation):
    """
    BusinessObject element derivation.

    Uses hybrid filtering combining:
    - Pattern-based filtering (include/exclude patterns from config)
    - Graph-based filtering (PageRank threshold, community structure)
    """

    ELEMENT_TYPE = "BusinessObject"

    # Graph filtering configuration
    MIN_PAGERANK = 0.001  # Filter out low-importance types

    OUTBOUND_RULES = [
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Composition",
            description="Business objects contain other business objects",
        ),
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Aggregation",
            description="Business objects reference other business objects",
        ),
    ]

    INBOUND_RULES = [
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Access",
            description="Business processes access business objects",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Flow",
            description="Application services flow data to business objects",
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
        """
        Filter candidates for BusinessObject derivation.

        Strategy: Handle mixed BusinessConcept + TypeDefinition sources
        - BusinessConcept: Filter by confidence (already semantically identified)
        - TypeDefinition: Pattern-based and graph filtering
        """
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        # Enrich all candidates with graph metrics
        for c in candidates:
            enrich_candidate(c, enrichments)

        # Separate BusinessConcept from TypeDefinition candidates
        business_concepts = []
        type_definitions = []

        for c in candidates:
            if not c.name:
                continue
            if "BusinessConcept" in c.labels or c.properties.get("conceptType"):
                business_concepts.append(c)
            elif "TypeDefinition" in c.labels:
                type_definitions.append(c)

        # Filter each group appropriately
        filtered_concepts = self._filter_business_concepts(
            business_concepts, max_candidates
        )
        filtered_types = self._filter_typedef_candidates(
            type_definitions, enrichments, max_candidates, include_patterns, exclude_patterns
        )

        # Combine: BusinessConcepts first (higher semantic confidence), then TypeDefinitions
        combined = filtered_concepts + filtered_types

        self.logger.debug(
            "BusinessObject filter: %d total -> %d concepts, %d typedefs -> %d final",
            len(candidates),
            len(filtered_concepts),
            len(filtered_types),
            len(combined),
        )

        return combined[:max_candidates]

    def _filter_business_concepts(
        self,
        candidates: list[Candidate],
        max_candidates: int,
    ) -> list[Candidate]:
        """Filter BusinessConcept candidates by confidence.

        BusinessConcepts are already semantically identified as entities,
        so we just filter by confidence and limit count.
        """
        MIN_CONFIDENCE = 0.7

        filtered = []
        for c in candidates:
            if not c.name:
                continue
            confidence = c.properties.get("confidence", 0)
            if confidence >= MIN_CONFIDENCE:
                filtered.append(c)

        # Sort by confidence descending
        filtered.sort(key=lambda c: c.properties.get("confidence", 0), reverse=True)

        self.logger.debug(
            "BusinessObject filter (BusinessConcept): %d total -> %d passed confidence >= %.1f",
            len(candidates),
            len(filtered),
            MIN_CONFIDENCE,
        )

        return filtered[:max_candidates]

    def _filter_typedef_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str],
        exclude_patterns: set[str],
    ) -> list[Candidate]:
        """Filter TypeDefinition candidates using pattern and graph filtering."""
        # Filter out nulls
        filtered = [c for c in candidates if c.name]

        # Separate likely business objects from others
        likely_business = [
            c
            for c in filtered
            if self._is_likely_business_object(
                c.name, include_patterns, exclude_patterns
            )
        ]
        others = [c for c in filtered if c not in likely_business]

        # Apply graph filtering to likely business objects
        likely_filtered = self.apply_graph_filtering(
            likely_business, enrichments, max_candidates // 2
        )

        # Fill remaining slots with other candidates
        remaining_slots = max_candidates - len(likely_filtered)
        if remaining_slots > 0 and others:
            others_filtered = self.apply_graph_filtering(
                others, enrichments, remaining_slots
            )
            likely_filtered.extend(others_filtered)

        self.logger.debug(
            "BusinessObject filter (TypeDefinition): %d total -> %d after null check -> %d final",
            len(candidates),
            len(filtered),
            len(likely_filtered),
        )

        return likely_filtered[:max_candidates]

    def _is_likely_business_object(
        self, name: str, include_patterns: set[str], exclude_patterns: set[str]
    ) -> bool:
        """Check if a type name suggests a business object."""
        if not name:
            return False

        # Use pattern matching from base class
        if include_patterns or exclude_patterns:
            if self.matches_patterns(name, include_patterns, exclude_patterns):
                return True

        # Default: include if it looks like a noun (starts with capital, no underscores)
        return name[0].isupper() and "_" not in name
