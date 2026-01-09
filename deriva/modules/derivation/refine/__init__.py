"""
Refine phase modules for Deriva derivation pipeline.

The refine phase performs post-generation model refinement using
cross-graph logic to improve ArchiMate model quality:

1. duplicate_elements: Find and merge/disable duplicate elements
2. orphan_elements: Find elements with no relationships
3. duplicate_relationships: Find and remove duplicate relationships
4. cross_layer: Validate cross-layer coherence
5. structural_consistency: Validate source graph patterns are preserved

All refine steps work on the Model namespace (ArchiMate elements)
and may reference the Graph namespace (source code representation).
"""

from .base import (
    REFINE_STEPS,
    RefineResult,
    RefineStep,
    run_refine_step,
)

# Import modules to trigger registration
from . import (
    cross_layer,
    duplicate_elements,
    duplicate_relationships,
    orphan_elements,
    structural_consistency,
)

__all__ = [
    "REFINE_STEPS",
    "RefineResult",
    "RefineStep",
    "run_refine_step",
]
