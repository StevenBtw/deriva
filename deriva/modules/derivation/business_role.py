"""
BusinessRole Derivation.

A BusinessRole is the responsibility for behaviour that an actor can be assigned to (ArchiMate 3.2, Figure 53): a
role the code names as such (a role constant, a permission role), as opposed to an actor, a person or organisation.
The extraction marks each role node with its kind; a node of kind "role" becomes a business role, one of kind
"actor" a business actor (BusinessActor step).

Structure only, no LLM: the step's query selects the role nodes of kind "role", one structural role gives each its
element, named as written. Its relationships come from structure (relationship config); without a link from a role to
an actor in the graph, no actor is assigned to it.

ArchiMate Layer: Business Layer
ArchiMate Type: BusinessRole
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class BusinessRoleDerivation(HybridDerivation):
    """BusinessRole element derivation: one business role per role node of kind "role", from structure."""

    ELEMENT_TYPE = "BusinessRole"
    MIN_PAGERANK = None  # Every selected role node gets its element
    USE_COMMUNITY_ROOTS = False

    # Its relationships come from structure only (relationship config): no rule-based or LLM tier
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []
