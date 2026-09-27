"""
ApplicationInterface Derivation.

An ApplicationInterface represents a point of access where application services
are made available to a user, another application component, or a node.

Graph signals:
- API endpoint definitions (REST, GraphQL, gRPC)
- Public methods/functions exposed to external callers
- Route handlers in web frameworks
- Interface/protocol definitions

Filtering strategy:
1. Query Method nodes that represent endpoints/handlers
2. Filter for API/interface patterns
3. Exclude internal/private methods
4. Focus on externally accessible entry points

LLM role:
- Identify which methods represent interfaces
- Generate meaningful interface names
- Write documentation describing the interface purpose

ArchiMate Layer: Application Layer
ArchiMate Type: ApplicationInterface

Typical Sources:
    - API endpoint definitions (REST, GraphQL, gRPC)
    - Public interface/protocol method definitions
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


class ApplicationInterfaceDerivation(HybridDerivation):
    """
    ApplicationInterface element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify application
    interfaces from API endpoints and public method definitions.
    """

    ELEMENT_TYPE = "ApplicationInterface"
    MIN_PAGERANK = None  # Query filters by pattern, no need for pagerank filter
    USE_COMMUNITY_ROOTS = False  # Interfaces are endpoints, not hubs
    PATTERN_MATCH_DEFAULT = True  # Accept candidates by default

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Serving",
            description="Application interfaces expose application services",
        ),
        RelationshipRule(
            target_type="BusinessActor",
            rel_type="Serving",
            description="Application interfaces serve business actors",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Composition",
            description="Application components contain interfaces",
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
        Filter candidates for ApplicationInterface derivation.

        Pre-filters to exclude private methods (starting with _),
        then delegates to HybridDerivation for pattern + graph filtering.
        """
        # Enrich all candidates first
        for c in candidates:
            enrich_candidate(c, enrichments)

        # Pre-filter: exclude private methods (starting with _)
        filtered = [c for c in candidates if c.name and not c.name.startswith("_")]

        # Delegate to base class for pattern + graph filtering
        return super().filter_candidates(
            filtered, enrichments, max_candidates, include_patterns, exclude_patterns
        )
