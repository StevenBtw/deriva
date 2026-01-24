"""
ApplicationService Derivation.

An ApplicationService represents an explicitly defined exposed application
behavior. This includes API endpoints, web routes, and service interfaces.

Graph signals:
- Method nodes with route/endpoint patterns
- Functions decorated with @app.route, @api.get, etc.
- Controller/handler methods
- Methods in files named routes.py, api.py, views.py

Filtering strategy:
1. Query Method nodes
2. Filter for route/endpoint patterns
3. Look for HTTP method indicators (get, post, put, delete)
4. Focus on externally exposed interfaces

LLM role:
- Identify which methods are application services
- Generate meaningful service names
- Write documentation describing the service's purpose

Relationships:
- OUTBOUND: ApplicationService -> BusinessObject (Flow) - services transfer data
- INBOUND: TechnologyService -> ApplicationService (Serving) - tech serves app services

ArchiMate Layer: Application Layer
ArchiMate Type: ApplicationService

Typical Sources:
    - Method nodes with @route, @api decorators
    - Methods in routes.py, api.py, views.py, controllers.py
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
    MIN_PAGERANK = None  # Query already filters by out_degree, no need for pagerank filter
    USE_COMMUNITY_ROOTS = True  # Prioritize service hubs

    OUTBOUND_RULES = [
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Flow",
            description="Application services transfer/process business data",
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
    ]

    INBOUND_RULES = [
        RelationshipRule(
            target_type="TechnologyService",
            rel_type="Serving",
            description="Technology services serve application services",
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
        """Filter candidates for ApplicationService derivation."""
        # Pre-filter: exclude dunder methods
        for c in candidates:
            enrich_candidate(c, enrichments)

        filtered = [c for c in candidates if c.name and not c.name.startswith("__")]

        # Use parent's hybrid filtering
        return super().filter_candidates(
            filtered, enrichments, max_candidates, include_patterns, exclude_patterns
        )
