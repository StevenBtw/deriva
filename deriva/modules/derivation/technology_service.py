"""
TechnologyService Derivation.

A TechnologyService is the externally visible behaviour a technology realizer offers (ArchiMate 3.2, Figure 82): the
platform node's container hosting, a database's data storage, a managed service's capability. Every realizer (the
environment and its service software) gets one, realized by its technology function, and it serves the application
functions of the units it serves or runs.

Structure only, no LLM: the step's query selects the realizers, and a closed table names the service by the
realizer's kind (``roles.names``: a database "Relational Database", a container platform "Container Hosting"); a
kind the table does not list gets no service. Its relationships come from structure (relationship config).

ArchiMate Layer: Technology Layer
ArchiMate Type: TechnologyService
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
    MIN_PAGERANK = None  # Technology nodes often have low pagerank (external to codebase)
    USE_COMMUNITY_ROOTS = False  # External deps don't have communities
    PATTERN_MATCH_DEFAULT = True  # Accept candidates by default (query filters by techCategory)

    # Its relationships come from structure only (relationship config): no rule-based or LLM tier
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []

    # Uses HybridDerivation.filter_candidates() which handles:
    # - Pattern matching (include/exclude from config)
    # - Graph filtering (PageRank threshold, community roots)
