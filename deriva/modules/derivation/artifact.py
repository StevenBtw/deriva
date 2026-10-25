"""
Artifact Derivation.

An Artifact is the deployable form of an application component: its image, package or bundle. Every deployable gets
exactly one: each deployable unit (also one split into feature packages), each library and each static bundle. A
feature package or functional area runs inside its unit's artifact and gets none. A deployment that deploys a unit
is that unit's artifact; a deployment without a unit (a vendor image) is its system software instead.

Structure only, no LLM: the step's query selects the deployables' source nodes, one structural role gives each its
artifact, and a name template names it after its component ("{container} {role}"). The artifact realizes its
component, and the platform node is assigned to the artifacts of the units it deploys (relationship config).

ArchiMate Layer: Technology Layer
ArchiMate Type: Artifact
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class ArtifactDerivation(HybridDerivation):
    """Artifact element derivation: one artifact per deployable (unit, library, static bundle), from structure."""

    ELEMENT_TYPE = "Artifact"
    MIN_PAGERANK = None  # Every selected component gets its artifact
    USE_COMMUNITY_ROOTS = False

    # Its relationships come from structure only (relationship config): no rule-based or LLM tier
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []
