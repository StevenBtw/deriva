"""
ApplicationComponent Derivation.

An ApplicationComponent represents a modular, deployable part of a system
that encapsulates its behavior and data.

Graph signals:
- Directory nodes (structural organization)
- Louvain community roots (cohesive modules)
- High PageRank (important/central directories)
- Path patterns: src/, app/, lib/, components/, modules/

Filtering strategy:
1. Query Directory nodes (excluding test/config/docs)
2. Get enrichment data (pagerank, louvain, kcore)
3. Filter to community roots or high-pagerank nodes
4. Limit to top N by PageRank
5. Send to LLM for final decision and naming

ArchiMate Layer: Application Layer
ArchiMate Type: ApplicationComponent

Typical Sources:
    - Directory nodes with src/, app/, lib/ paths
    - Louvain community root nodes (cohesive module boundaries)
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class ApplicationComponentDerivation(HybridDerivation):
    """
    ApplicationComponent element derivation.

    Uses hybrid filtering with emphasis on graph structure:
    - Prioritizes community roots (natural component boundaries)
    - High PageRank nodes (important directories)
    - Optional pattern filtering from config
    """

    ELEMENT_TYPE = "ApplicationComponent"

    # Graph filtering configuration - prioritize community roots
    # Loosened from 0.001/0.6 to capture more components (ref models have 14-21)
    USE_COMMUNITY_ROOTS = True
    COMMUNITY_ROOT_RATIO = 0.3  # 30% community roots, 70% by PageRank
    MIN_PAGERANK = 0.0001

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Composition",
            description="Application components contain other application components",
        ),
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Aggregation",
            description="Application components aggregate related application components",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Assignment",
            description="Application components perform application services",
        ),
        RelationshipRule(
            target_type="DataObject",
            rel_type="Access",
            description="Application components access data objects",
        ),
        RelationshipRule(
            target_type="ApplicationInterface",
            rel_type="Composition",
            description="Application components expose interfaces",
        ),
        RelationshipRule(
            target_type="BusinessFunction",
            rel_type="Realization",
            description="Application components realize business functions",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Realization",
            description="Application components realize business processes",
        ),
        RelationshipRule(
            target_type="ApplicationService",
            rel_type="Realization",
            description="Application components realize application services",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="TechnologyService",
            rel_type="Serving",
            description="Technology services serve application components",
        ),
        RelationshipRule(
            target_type="Node",
            rel_type="Serving",
            description="Nodes serve application components",
        ),
    ]

    # Uses HybridDerivation.filter_candidates() which applies:
    # 1. Pattern matching (if patterns configured)
    # 2. Graph filtering with community roots prioritized (USE_COMMUNITY_ROOTS=True)
    # 3. PageRank threshold filtering (MIN_PAGERANK=0.001)
