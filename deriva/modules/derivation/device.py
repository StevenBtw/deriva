"""
Device Derivation.

A Device represents a physical IT resource upon which system software and
artifacts may be stored or deployed for execution.

Graph signals:
- Hardware configuration references
- Docker/container host definitions
- Physical server references in deployment configs
- Infrastructure-as-code resources (Terraform, CloudFormation)

Filtering strategy:
1. Query File nodes with infrastructure patterns
2. Filter for device/hardware patterns
3. Exclude software-only definitions
4. Focus on physical/virtual machine definitions

LLM role:
- Identify which configs represent devices
- Generate meaningful device names
- Write documentation describing the device purpose

ArchiMate Layer: Technology Layer
ArchiMate Type: Device

Typical Sources:
    - Infrastructure-as-code (Terraform, CloudFormation)
    - Docker/Kubernetes deployment configurations
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class DeviceDerivation(HybridDerivation):
    """
    Device element derivation.

    Uses hybrid filtering (patterns + graph metrics) to identify devices
    from infrastructure configuration files.
    """

    ELEMENT_TYPE = "Device"
    MIN_PAGERANK = 0.0005  # Config files often have low pagerank
    USE_COMMUNITY_ROOTS = False

    OUTBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="SystemSoftware",
            rel_type="Composition",
            description="Devices contain system software",
        ),
    ]

    INBOUND_RULES: list[RelationshipRule] = [
        RelationshipRule(
            target_type="Node",
            rel_type="Composition",
            description="Nodes contain devices",
        ),
    ]

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
