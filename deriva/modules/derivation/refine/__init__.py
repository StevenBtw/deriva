"""
Refine phase modules for Deriva derivation pipeline.

The refine phase performs post-generation model refinement using
cross-graph logic to improve ArchiMate model quality:

1. duplicate_elements: Find and merge/disable duplicate elements
2. orphan_elements: Find elements with no relationships
3. duplicate_relationships: Find and remove duplicate relationships
4. circular_relationships: Detect and break circular Composition chains
5. cross_layer: Validate cross-layer coherence
6. structural_consistency: Validate source graph patterns are preserved
7. graph_relationships: Derive relationships from graph structure

All refine steps work on the Model namespace (ArchiMate elements)
and may reference the Graph namespace (source code representation).

Usage:
    from deriva.modules.derivation.refine import run_refine_step, REFINE_STEPS

    # Run a specific refine step
    result = run_refine_step(
        "duplicate_elements",
        archimate_manager=am,
        graph_manager=gm,
    )

    # List available steps
    for step_name in REFINE_STEPS:
        print(f"Available: {step_name}")
"""

# Import modules to trigger registration
from . import (
    circular_relationships,
    cross_layer,
    duplicate_elements,
    duplicate_relationships,
    graph_relationships,
    joint_consistency,
    orphan_elements,
    relationship_consolidation,
    structural_consistency,
)
from .base import (
    REFINE_STEPS,
    RefineResult,
    RefineStep,
    run_refine_step,
)

__all__ = [
    "REFINE_STEPS",
    "RefineResult",
    "RefineStep",
    "run_refine_step",
    # Modules imported for side-effect registration
    "circular_relationships",
    "cross_layer",
    "duplicate_elements",
    "duplicate_relationships",
    "graph_relationships",
    "joint_consistency",
    "orphan_elements",
    "relationship_consolidation",
    "structural_consistency",
]
