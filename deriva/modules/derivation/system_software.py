"""
SystemSoftware Derivation.

A SystemSoftware represents software that provides or contributes to an
environment for storing, executing, and using software or data deployed
within it.

Graph signals:
- Operating system references
- Runtime/platform dependencies
- Container base images
- Middleware and platform services

Filtering strategy:
1. Query ExternalDependency and File nodes
2. Filter for system/platform patterns
3. Exclude application-level libraries
4. Focus on infrastructure software

LLM role:
- Identify which dependencies are system software
- Generate meaningful software names
- Write documentation describing the software's role

ArchiMate Layer: Technology Layer
ArchiMate Type: SystemSoftware

Typical Sources:
    - Runtime/platform dependencies (Python, Node.js, JVM)
    - Container base images (alpine, debian, ubuntu)
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class SystemSoftwareDerivation(HybridDerivation):
    """
    SystemSoftware element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify system
    software from ExternalDependency and platform-related nodes.
    """

    ELEMENT_TYPE = "SystemSoftware"
    MIN_PAGERANK = None  # Technology nodes often have low pagerank (external to codebase)
    USE_COMMUNITY_ROOTS = False  # External deps don't have communities
    PATTERN_MATCH_DEFAULT = True  # Accept candidates by default (query filters by techCategory)

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="TechnologyService",
            rel_type="Realization",
            description="System software realizes technology services",
        ),
        RelationshipRule(
            target_type="DataObject",
            rel_type="Access",
            description="System software accesses data objects",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="Node",
            rel_type="Composition",
            description="Nodes contain system software",
        ),
        RelationshipRule(
            target_type="Device",
            rel_type="Composition",
            description="Devices contain system software",
        ),
    ]

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
