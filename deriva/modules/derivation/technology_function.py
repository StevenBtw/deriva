"""
TechnologyFunction Derivation.

A TechnologyFunction is the internal behaviour of a technology realizer (ArchiMate 3.2, Figure 82): the platform node
or a system software in the environment is assigned to it, and it realizes the technology service the realizer
offers. Every realizer gets exactly one, named "<realizer> Behaviour".

Structure only, no LLM: the step's query selects the realizers (the environment and its service software), one
structural role gives each its function (by a kind the technology services' closed name table lists), and a name
template names it after its realizer. Its relationships come from structure (relationship config).

ArchiMate Layer: Technology Layer
ArchiMate Type: TechnologyFunction
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class TechnologyFunctionDerivation(HybridDerivation):
    """TechnologyFunction element derivation: one function per technology realizer, from structure."""

    ELEMENT_TYPE = "TechnologyFunction"
    MIN_PAGERANK = None  # Every selected realizer gets its function
    USE_COMMUNITY_ROOTS = False

    # Its relationships come from structure only (relationship config): no rule-based or LLM tier
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []
