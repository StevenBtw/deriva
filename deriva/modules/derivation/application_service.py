"""
ApplicationService Derivation.

An ApplicationService represents an explicitly defined exposed application
behavior. This includes API endpoints, web routes, and service interfaces.

Graph signals:
- BusinessConcept nodes with conceptType 'service' or 'capability'
- TypeDefinition nodes with *Service* naming pattern
- Method nodes with route/endpoint patterns (legacy)

Filtering strategy:
1. Query BusinessConcept and TypeDefinition nodes
2. For BusinessConcept: filter by confidence (already semantically identified)
3. For TypeDefinition: filter by name patterns and graph metrics
4. Focus on externally exposed interfaces

LLM role:
- Identify which types represent application services
- Generate meaningful service names
- Write documentation describing the service's purpose

Relationships:
- OUTBOUND: ApplicationService -> BusinessObject (Flow) - services transfer data
- INBOUND: TechnologyService -> ApplicationService (Serving) - tech serves app services

ArchiMate Layer: Application Layer
ArchiMate Type: ApplicationService

Typical Sources:
    - BusinessConcept nodes (service, capability conceptTypes)
    - TypeDefinition nodes with *Service* naming pattern
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


class ApplicationServiceDerivation(HybridDerivation):
    """
    ApplicationService element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify API endpoints
    and service methods from Method nodes.
    """

    ELEMENT_TYPE = "ApplicationService"
    MIN_PAGERANK = (
        None  # Query already filters by out_degree, no need for pagerank filter
    )
    USE_COMMUNITY_ROOTS = True  # Prioritize service hubs

    OUTBOUND_RULES = [
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Access",
            description="Application services access business data",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Serving",
            description="Application services serve business processes",
        ),
        RelationshipRule(
            target_type="BusinessFunction",
            rel_type="Serving",
            description="Application services serve business functions",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Flow",
            description="Data flow between application services",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Aggregation",
            description="Application services aggregate sub-services",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Triggering",
            description="Application services trigger business processes",
        ),
    ]

    INBOUND_RULES = [
        RelationshipRule(
            target_type="TechnologyService",
            rel_type="Serving",
            description="Technology services serve application services",
        ),
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Realization",
            description="Application components realize application services",
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
        """Filter candidates for ApplicationService derivation.

        Strategy depends on source type:
        - BusinessConcept: Filter by confidence (already semantically identified)
        - TypeDefinition: Filter by name patterns and graph metrics
        """
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

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

        # Filter each group appropriately (don't pre-limit, combine then limit)
        filtered_concepts = self._filter_business_concepts(
            business_concepts, max_candidates
        )
        filtered_types = self._filter_typedef_candidates(
            type_definitions,
            enrichments,
            max_candidates,
            include_patterns,
            exclude_patterns,
        )

        # Combine: TypeDefinitions first (deterministic pattern match), then BusinessConcepts
        combined = filtered_types + filtered_concepts

        self.logger.debug(
            "ApplicationService filter: %d total -> %d concepts, %d typedefs -> %d final",
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

        BusinessConcepts are already semantically identified as services,
        so we just filter by confidence and limit count.
        """
        MIN_CONFIDENCE = 0.85  # ROC analysis: AUC=0.972 at threshold 0.85

        filtered = []
        for c in candidates:
            confidence = c.properties.get("confidence", 0)
            if confidence >= MIN_CONFIDENCE:
                filtered.append(c)

        # Sort by confidence descending
        filtered.sort(key=lambda c: c.properties.get("confidence", 0), reverse=True)

        self.logger.debug(
            "ApplicationService filter (BusinessConcept): %d total -> %d passed confidence >= %.1f",
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
        """Filter TypeDefinition candidates using name patterns.

        Strategy:
        1. Filter by *Service* name pattern (already done in query)
        2. Skip strict graph filtering - name pattern is strong signal
        3. Sort by confidence if available, then by pagerank
        """
        # Pre-filter: exclude dunder names
        filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

        # Skip include_patterns for TypeDefinitions - they already match *Service* in query
        # Only apply exclude_patterns if provided
        if exclude_patterns:
            filtered = [
                c
                for c in filtered
                if not any(
                    pattern.lower() in c.name.lower() for pattern in exclude_patterns
                )
            ]

        # Sort by confidence (if available) then pagerank
        # TypeDefinitions matching *Service* pattern are already strong candidates
        filtered.sort(
            key=lambda c: (
                c.properties.get("confidence", 0),
                c.properties.get("pagerank", 0),
            ),
            reverse=True,
        )

        self.logger.debug(
            "ApplicationService filter (TypeDefinition): %d total -> %d final",
            len(candidates),
            len(filtered),
        )

        return filtered[:max_candidates]
