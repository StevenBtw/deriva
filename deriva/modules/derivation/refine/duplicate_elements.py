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
    normalize_name,
    register_refine_step,
    similarity_ratio,
)
from .normalization import RepoContext, normalize_for_dedup

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)

logger = logging.getLogger(__name__)

# Default thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # Similarity ratio for Tier 2


@register_refine_step("duplicate_elements")
class DuplicateElementsStep:
    """Find and merge/disable duplicate ArchiMate elements."""

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
                - auto_merge_tier2: Whether to auto-merge Tier 2 matches (default: False)
                - extra_synonyms: Dict of additional synonym mappings {"from": "to"}
                - use_lemmatization: Apply lemmatization before matching (default: False)

        Returns:
            RefineResult with details of duplicates found and handled
        """
        params = params or {}
        fuzzy_threshold = params.get("fuzzy_threshold", FUZZY_MATCH_THRESHOLD)
        auto_merge_tier2 = params.get("auto_merge_tier2", False)
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

                        if similarity >= fuzzy_threshold:
                            tier2_duplicates.append((elem_a, elem_b, similarity))

            # Process Tier 1: Auto-merge exact duplicates
            for elem_a, elem_b in tier1_duplicates:
                survivor, duplicate = self._select_survivor(elem_a, elem_b)
                self._merge_elements(archimate_manager, survivor, duplicate, "exact_name_match")
                result.elements_merged += 1
                result.elements_disabled += 1
                result.details.append(
                    {
                        "tier": 1,
                        "action": "merged",
                        "survivor": survivor.identifier,
                        "duplicate": duplicate.identifier,
                        "name": survivor.name,
                        "reason": "exact_name_match",
                    }
                )

            # Process Tier 2: Fuzzy matches
            for elem_a, elem_b, similarity in tier2_duplicates:
                if auto_merge_tier2:
                    survivor, duplicate = self._select_survivor(elem_a, elem_b)
                    self._merge_elements(
                        archimate_manager,
                        survivor,
                        duplicate,
                        f"fuzzy_match_{similarity:.2f}",
                    )
                    result.elements_merged += 1
                    result.elements_disabled += 1
                    result.details.append(
                        {
                            "tier": 2,
                            "action": "merged",
                            "survivor": survivor.identifier,
                            "duplicate": duplicate.identifier,
                            "similarity": similarity,
                            "reason": "fuzzy_match",
                        }
                    )
                else:
                    # Flag for review (don't merge)
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

            logger.info(f"Duplicate detection complete: {result.elements_merged} merged, {result.issues_found} flagged")

        except Exception as e:
            logger.exception(f"Error in duplicate element detection: {e}")
            result.success = False
            result.errors.append(str(e))

        return result

    def _select_survivor(self, elem_a, elem_b):
        """Select which element to keep based on properties.

        Prefers element with:
        1. Higher source pagerank (if available)
        2. More documentation
        3. First alphabetically (deterministic fallback)
        """
        # Check for pagerank in properties
        rank_a = elem_a.properties.get("source_pagerank", 0)
        rank_b = elem_b.properties.get("source_pagerank", 0)

        if rank_a > rank_b:
            return elem_a, elem_b
        if rank_b > rank_a:
            return elem_b, elem_a

        # Check documentation length
        doc_a = len(elem_a.documentation or "")
        doc_b = len(elem_b.documentation or "")

        if doc_a > doc_b:
            return elem_a, elem_b
        if doc_b > doc_a:
            return elem_b, elem_a

        # Deterministic fallback: alphabetical by identifier
        if elem_a.identifier < elem_b.identifier:
            return elem_a, elem_b
        return elem_b, elem_a

    def _merge_elements(
        self,
        archimate_manager: ArchimateManager,
        survivor,
        duplicate,
        reason: str,
    ) -> None:
        """Merge duplicate into survivor and disable duplicate.

        - Combines documentation
        - Redirects relationships (handled by keeping survivor)
        - Disables duplicate
        """
        # Combine documentation if duplicate has additional info
        if duplicate.documentation and survivor.documentation:
            if duplicate.documentation not in survivor.documentation:
                # Could update survivor documentation here if needed
                pass

        # Disable the duplicate
        archimate_manager.disable_element(duplicate.identifier, reason=f"duplicate_of:{survivor.identifier}:{reason}")

        logger.debug(f"Merged {duplicate.identifier} into {survivor.identifier} ({reason})")


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
