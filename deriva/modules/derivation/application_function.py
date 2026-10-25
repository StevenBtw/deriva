"""
ApplicationFunction Derivation.

An ApplicationFunction is automated behaviour an application component performs. Every component that is a deployable
unit, a library or a feature package gets exactly one: its main behaviour. A system (an aggregator module) and a unit
split into feature packages are enterprise applications and get none.

Structure only, no LLM: the step's query selects the components' source nodes, one structural role gives each its
function, and a name template names it after its component ("{container} {role}"). The component is assigned to the
function and the function realizes the services the component realizes (relationship config, listed members).

ArchiMate Layer: Application Layer
ArchiMate Type: ApplicationFunction
"""

from __future__ import annotations

import logging

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation

logger = logging.getLogger(__name__)


class ApplicationFunctionDerivation(HybridDerivation):
    """ApplicationFunction element derivation: one function per application component, from structure."""

    ELEMENT_TYPE = "ApplicationFunction"
    MIN_PAGERANK = None  # Every selected component gets its function
    USE_COMMUNITY_ROOTS = False

    # Its relationships come from structure only (relationship config, listed members): no rule-based or LLM tier
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []
