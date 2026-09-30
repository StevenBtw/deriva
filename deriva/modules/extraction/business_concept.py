"""
Business concept identity and merging, shared by the steps that create BusinessConcept nodes.

DirectoryClassification (concepts a directory represents) and BusinessConcept (classified
candidate terms from the documentation, see concept_candidates) can yield the same concept;
both use one id per canonical name and merge their occurrences independent of order.
"""

from __future__ import annotations

from typing import Any

from deriva.common.naming import name_key


def merge_concept_properties(existing: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """Combine two occurrences of the same concept, independent of file order.

    Files can classify one concept differently (a README calls "User" an
    entity, a requirements document an actor). Every type is kept in
    ``conceptTypes`` and every document wording in ``sourceTerms`` (sorted
    unions), and ``confidence`` is the highest seen.
    The single-valued fields (``conceptType``, description, origin) come from
    the strongest occurrence: highest confidence, ties broken by origin path,
    type and description, so any processing order gives the same node.
    """

    def types(props: dict[str, Any]) -> set[str]:
        return set(props.get("conceptTypes") or [props.get("conceptType", "other")])

    def strength(props: dict[str, Any]) -> tuple[float, str, str, str]:
        return (
            -float(props.get("confidence", 0.0)),
            str(props.get("originSource", "")),
            str(props.get("conceptType", "")),
            str(props.get("description", "")),
        )

    occurrences = [new] if existing is None else [existing, new]
    best = min(occurrences, key=strength)
    return {
        **best,
        "conceptTypes": sorted(set().union(*(types(o) for o in occurrences))),
        "sourceTerms": sorted(set().union(*(o.get("sourceTerms") or [] for o in occurrences))),
        "confidence": max(float(o.get("confidence", 0.0)) for o in occurrences),
    }


def concept_node_id(repo_name: str, concept_name: str) -> str:
    """Graph id of a business concept: one id for every spelling of its name (canonical name key)."""
    return f"concept::{repo_name}::{name_key(concept_name)}"
