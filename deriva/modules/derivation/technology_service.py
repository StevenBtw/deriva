"""
TechnologyService Derivation.

A TechnologyService represents an externally visible unit of functionality,
offered by a technology node (e.g., database, message queue, external API).

Graph signals:
- External dependency nodes (imported packages/libraries)
- Nodes with labels like ExternalDependency, Database, API
- High out-degree from application code (many things depend on it)
- Configuration files referencing external services

Filtering strategy:
- Start with ExternalDependency and similar labeled nodes
- Filter to high-importance dependencies (PageRank)
- Exclude standard library and utility packages
- Focus on infrastructure services (databases, queues, APIs)

LLM role:
- Classify which dependencies are technology services vs utilities
- Generate meaningful service names
- Write documentation describing the service's role

Relationships:
- OUTBOUND: TechnologyService -> DataObject (Access) - access databases/files
- OUTBOUND: TechnologyService -> ApplicationService (Serving) - serve app services
- INBOUND: DataObject -> TechnologyService (Realization) - config realizes tech

ArchiMate Layer: Technology Layer
ArchiMate Type: TechnologyService

Typical Sources:
    - ExternalDependency nodes (databases, message queues, APIs)
    - Technology nodes from LLM extraction
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class TechnologyServiceDerivation(HybridDerivation):
    """
    TechnologyService element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify technology
    services from ExternalDependency nodes.
    """

    ELEMENT_TYPE = "TechnologyService"
    MIN_PAGERANK = (
        None  # Technology nodes often have low pagerank (external to codebase)
    )
    USE_COMMUNITY_ROOTS = False  # External deps don't have communities
    PATTERN_MATCH_DEFAULT = (
        True  # Accept candidates by default (query filters by techCategory)
    )

    OUTBOUND_RULES = [
        RelationshipRule(
            target_type="DataObject",
            rel_type="Access",
            description="Technology services access data objects (databases, files)",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Serving",
            description="Technology services serve application services",
        ),
    ]

    INBOUND_RULES = []

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
