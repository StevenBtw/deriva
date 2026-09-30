"""Structural quality of a derived ArchiMate model.

Consistency says whether runs agree; these measures say something about whether the
model is usable: how many elements take part in no relationship, how dense the lines
are, whether composition stays exclusive (a part belongs to one whole), whether pairs
carry several relationship types, and how far the cross-layer chains a reader follows
are present (a business process served by an application service, a data object
realizing a business object, a component served by a node).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .types import ReferenceElement, ReferenceRelationship

# Cross-layer and structural chains: (element type, the type it should be linked to)
CHAINS: list[tuple[str, str]] = [
    ("BusinessProcess", "ApplicationService"),
    ("BusinessActor", "BusinessProcess"),
    ("ApplicationService", "ApplicationComponent"),
    ("ApplicationInterface", "ApplicationComponent"),
    ("DataObject", "BusinessObject"),
    ("DataObject", "ApplicationComponent"),
    ("ApplicationComponent", "Node"),
    ("ApplicationComponent", "SystemSoftware"),
    ("SystemSoftware", "TechnologyService"),
]


@dataclass
class ModelQuality:
    """Structural measures of one model."""

    elements: int
    relationships: int
    relationships_per_element: float
    orphans: int
    orphan_share: float
    composition_violations: int  # parts composed into more than one whole
    duplicate_pairs: int  # source and target linked by more than one relationship type
    chains: dict[str, tuple[int, int]] = field(default_factory=dict)  # "A-B": (A linked to a B, all A)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def compute_model_quality(elements: list[ReferenceElement], relationships: list[ReferenceRelationship]) -> ModelQuality:
    """Structural measures of a model; relationships to elements outside it are left out."""
    types = {e.identifier: e.element_type for e in elements}
    rels = [r for r in relationships if r.source in types and r.target in types]

    linked: set[str] = set()
    neighbour_types: dict[str, set[str]] = defaultdict(set)
    wholes: dict[str, set[str]] = defaultdict(set)
    pair_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rels:
        linked.update((r.source, r.target))
        neighbour_types[r.source].add(types[r.target])
        neighbour_types[r.target].add(types[r.source])
        pair_types[(r.source, r.target)].add(r.relationship_type)
        if r.relationship_type == "Composition":
            wholes[r.target].add(r.source)

    chains: dict[str, tuple[int, int]] = {}
    for own, other in CHAINS:
        members = [e.identifier for e in elements if e.element_type == own]
        if members:
            chains[f"{own}-{other}"] = (sum(other in neighbour_types[m] for m in members), len(members))

    orphans = sum(e.identifier not in linked for e in elements)
    return ModelQuality(
        elements=len(elements),
        relationships=len(rels),
        relationships_per_element=round(len(rels) / len(elements), 2) if elements else 0.0,
        orphans=orphans,
        orphan_share=round(orphans / len(elements), 3) if elements else 0.0,
        composition_violations=sum(len(sources) > 1 for sources in wholes.values()),
        duplicate_pairs=sum(len(kinds) > 1 for kinds in pair_types.values()),
        chains=chains,
    )
