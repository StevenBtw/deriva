"""
BusinessFunction Derivation.

A BusinessFunction represents a collection of business behavior based on a
chosen set of criteria (typically required business resources and/or competencies),
closely aligned to an organization, but not necessarily explicitly governed by
the organization.

Graph signals:
- Module/package structures representing business capabilities
- Groups of related methods/classes
- Service layers and domain modules
- High-level organizational code structures

Filtering strategy:
1. Query Module and Package nodes
2. Filter for business-relevant modules
3. Exclude utility/infrastructure modules
4. Focus on domain-specific capabilities

LLM role:
- Identify which modules represent business functions
- Generate meaningful function names
- Write documentation describing the business capability

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessFunction

Typical Sources:
    - Module/package nodes representing business domains
    - High-level directory structures (e.g., orders/, invoices/)
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class BusinessFunctionDerivation(HybridDerivation):
    """
    BusinessFunction element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify business
    functions from Module and Package nodes representing business capabilities.
    """

    ELEMENT_TYPE = "BusinessFunction"
    MIN_PAGERANK = None  # Query already filters by confidence
    USE_COMMUNITY_ROOTS = True  # Prioritize modules that are community centers
    PATTERN_MATCH_DEFAULT = True  # Accept candidates by default

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="BusinessObject",
            rel_type="Access",
            description="Business functions access business objects",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Composition",
            description="Business functions contain business processes",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="BusinessActor",
            rel_type="Assignment",
            description="Business actors perform business functions",
        ),
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Realization",
            description="Application components realize business functions",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Serving",
            description="Application services serve business functions",
        ),
    ]

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
