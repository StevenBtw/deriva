"""
Node Derivation.

A Node represents a computational or physical resource that hosts, manipulates,
or interacts with other computational or physical resources.

Graph signals:
- Server/container definitions
- Kubernetes deployments and services
- Cloud resource definitions (EC2, VMs)
- Docker Compose service definitions

Filtering strategy:
1. Query File nodes with deployment/infrastructure patterns
2. Filter for node/server patterns
3. Exclude application-level definitions
4. Focus on infrastructure nodes

LLM role:
- Identify which configs represent nodes
- Generate meaningful node names
- Write documentation describing the node's role

ArchiMate Layer: Technology Layer
ArchiMate Type: Node

Typical Sources:
    - Kubernetes deployment/service definitions
    - Docker Compose service configurations
    - Infrastructure-as-code server definitions
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class NodeDerivation(HybridDerivation):
    """
    Node element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify
    infrastructure nodes from deployment and configuration files.
    """

    ELEMENT_TYPE = "Node"
    MIN_PAGERANK = None  # Infrastructure files have low pagerank but are important
    USE_COMMUNITY_ROOTS = False

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="SystemSoftware",
            rel_type="Composition",
            description="Nodes contain system software",
        ),
        RelationshipRule(
            target_type="Device",
            rel_type="Composition",
            description="Nodes contain devices",
        ),
        RelationshipRule(
            target_type="ApplicationComponent",
            rel_type="Serving",
            description="Nodes serve application components",
        ),
        RelationshipRule(
            target_type="BusinessProcess",
            rel_type="Realization",
            description="Technology nodes realize business processes",
        ),
        RelationshipRule(
            target_type="SystemSoftware",
            rel_type="Aggregation",
            description="Nodes aggregate system software",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = []

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
