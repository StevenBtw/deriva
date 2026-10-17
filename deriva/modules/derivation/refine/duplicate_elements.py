"""
Duplicate Elements Detection - Refine Step.

Finds and handles duplicate ArchiMate elements:
- Tier 1: Exact name + type matches (auto-merge)
- Tier 2: Near-duplicates via fuzzy matching (flag/auto-merge based on threshold)

The step makes no LLM call.

Merge strategy:
- Keep element with higher source pagerank (if available)
- Combine documentation
- Redirect all relationships to survivor
- Disable the duplicate (soft delete)

Refine Step Name: "duplicate_elements"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .base import (
    RefineResult,
    differ_in_a_code,
    normalize_name,
    register_refine_step,
    similarity_ratio,
)
from .normalization import RepoContext, normalize_for_dedup

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see docs/architecture.md)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see docs/architecture.md)

logger = logging.getLogger(__name__)

# Default thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # Similarity ratio for Tier 2


@register_refine_step("duplicate_elements")
class DuplicateElementsStep:
    """Flag elements of one type with equal or similar names (propose-only).

    It never merges: merges are decided only in joint_consistency (the MILP), from structural identity.
    """

    def run(
        self,
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager | None = None,
        llm_query_fn: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> RefineResult:
        """Execute duplicate element detection and handling.

        Args:
            archimate_manager: Manager for ArchiMate model operations
            graph_manager: Optional manager for source graph (for pagerank lookup)
            llm_query_fn: Unused (the step makes no LLM call; part of the refine step interface)
            params: Optional parameters:
                - fuzzy_threshold: Similarity threshold for Tier 2 (default: 0.85)
                - extra_synonyms: Dict of additional synonym mappings {"from": "to"}
                - use_lemmatization: Apply lemmatization before matching (default: False)

        Returns:
            RefineResult with details of duplicates found and handled
        """
        params = params or {}
        fuzzy_threshold = params.get("fuzzy_threshold", FUZZY_MATCH_THRESHOLD)
        extra_synonyms = params.get("extra_synonyms", None)  # Additional synonym mappings
        use_lemmatization = params.get("use_lemmatization", False)  # Apply lemmatization

        result = RefineResult(
            success=True,
            step_name="duplicate_elements",
        )

        try:
            # Get all elements (including disabled for comprehensive check)
            elements = archimate_manager.get_elements(enabled_only=False)

            if not elements:
                logger.info("No elements found for duplicate detection")
                return result

            repo_ctx = _build_repo_context(graph_manager)

            # Group elements by type for comparison
            by_type: dict[str, list] = {}
            for elem in elements:
                if not elem.enabled:
                    continue  # Skip already disabled elements
                elem_type = elem.element_type
                if elem_type not in by_type:
                    by_type[elem_type] = []
                by_type[elem_type].append(elem)

            # Find duplicates within each type
            tier1_duplicates = []  # Exact matches (including after canonicalization)
            tier2_duplicates = []  # Fuzzy matches

            for elem_type, elems in by_type.items():
                if len(elems) < 2:
                    continue

                # Compare each pair
                for i, elem_a in enumerate(elems):
                    for elem_b in elems[i + 1 :]:
                        # Tier 1: Exact name match, or exact match after canonicalization
                        # (strips ArchiMate type suffixes and repo-name prefix).
                        if elem_a.name == elem_b.name:
                            tier1_duplicates.append((elem_a, elem_b))
                            continue
                        canon_a = normalize_for_dedup(elem_a.name, repo_ctx)
                        canon_b = normalize_for_dedup(elem_b.name, repo_ctx)
                        if canon_a and canon_a == canon_b:
                            tier1_duplicates.append((elem_a, elem_b))
                            continue

                        # Tier 2: Fuzzy match on canonical + generic-normalized names.
                        norm_a = normalize_name(canon_a, extra_synonyms, use_lemmatization)
                        norm_b = normalize_name(canon_b, extra_synonyms, use_lemmatization)
                        similarity = similarity_ratio(norm_a, norm_b)

                        # Names that differ in a code (an identifier, an acronym) are different things
                        if similarity >= fuzzy_threshold and not differ_in_a_code(elem_a.name, elem_b.name):
                            tier2_duplicates.append((elem_a, elem_b, similarity))

            # Flag them (propose-only): equal names are tier 1, similar names tier 2; nothing is merged here
            for elem_a, elem_b in tier1_duplicates:
                result.issues_found += 1
                result.details.append(
                    {
                        "tier": 1,
                        "action": "flagged",
                        "element_a": elem_a.identifier,
                        "element_b": elem_b.identifier,
                        "name_a": elem_a.name,
                        "name_b": elem_b.name,
                        "reason": "same_name",
                    }
                )
            for elem_a, elem_b, similarity in tier2_duplicates:
                result.issues_found += 1
                result.details.append(
                    {
                        "tier": 2,
                        "action": "flagged",
                        "element_a": elem_a.identifier,
                        "element_b": elem_b.identifier,
                        "name_a": elem_a.name,
                        "name_b": elem_b.name,
                        "similarity": similarity,
                        "reason": "potential_duplicate",
                    }
                )

            logger.info(f"Duplicate detection complete: {result.issues_found} flagged")

        except Exception as e:
            logger.exception(f"Error in duplicate element detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result


def _build_repo_context(graph_manager: GraphManager | None) -> RepoContext:
    """Build normalization context from runtime graph state.

    The repo name is read from the active Repository node. It is optional; an
    empty context makes the repo-specific rules no-ops.
    """
    repo_name = ""
    if graph_manager is not None:
        try:
            rows = graph_manager.query("MATCH (r:Graph:Repository) WHERE r.active = true RETURN r.repository_name as name LIMIT 1")
            if rows and rows[0].get("name"):
                repo_name = rows[0]["name"]
        except Exception as e:
            logger.debug(f"Could not read active repository name: {e}")

    return RepoContext(repo_name=repo_name)
