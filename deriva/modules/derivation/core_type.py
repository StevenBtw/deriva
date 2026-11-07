"""Experimental core types: one step for every ArchiMate 3.2 core type that has no step of its own.

A first, wired implementation, off by default: the step's query selects broad candidates from the graph, one closed
LLM call per batch keeps each candidate as the type or answers none (``params.roles``, its instruction in config), and
a kept candidate becomes an element with the candidate's own name and identity. The relationship rules are the
direct relationships the metamodel draws for the type, handed in by the service layer (the metamodel stays in its
adapter). Narrower candidate structures follow in later releases.
"""

from __future__ import annotations

from collections.abc import Sequence

from deriva.modules.derivation.base import RelationshipRule
from deriva.modules.derivation.element_base import HybridDerivation


class CoreTypeDerivation(HybridDerivation):
    """An experimental core type: candidates from the step's query, kept or rejected by its role call."""

    ELEMENT_TYPE = ""
    MIN_PAGERANK = None  # The query and the role call decide, not a graph cut
    USE_COMMUNITY_ROOTS = False
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []


def core_type_class(element_type: str, outbound: Sequence[RelationshipRule], inbound: Sequence[RelationshipRule]) -> type[CoreTypeDerivation]:
    """The experimental step class of ``element_type`` with the given relationship rules."""
    return type(
        f"{element_type}Derivation",
        (CoreTypeDerivation,),
        {"ELEMENT_TYPE": element_type, "OUTBOUND_RULES": list(outbound), "INBOUND_RULES": list(inbound), "__doc__": f"Experimental {element_type} derivation (off by default)."},
    )
