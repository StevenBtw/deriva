"""
Base classes for element derivation modules.

Provides the common generate() flow that all element modules share,
eliminating ~80% code duplication across 13 element modules.

Usage:
    # For pattern-based filtering (most modules):
    class BusinessObjectDerivation(PatternBasedDerivation):
        ELEMENT_TYPE = "BusinessObject"
        OUTBOUND_RULES = [...]
        INBOUND_RULES = [...]

        def filter_candidates(self, candidates, enrichments, max_candidates,
                              include_patterns=None, exclude_patterns=None, **kwargs):
            # Module-specific filtering logic
            ...

    # For graph-based filtering (e.g., ApplicationComponent):
    class ApplicationComponentDerivation(ElementDerivationBase):
        ELEMENT_TYPE = "ApplicationComponent"
        OUTBOUND_RULES = [...]
        INBOUND_RULES = [...]

        def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
            # Uses community roots, PageRank, etc.
            ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable

from deriva.adapters.archimate.models import Element, Relationship
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    Candidate,
    CandidateDecision,
    GenerationResult,
    RelationshipRule,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    derive_batch_relationships,
    extract_response_content,
    get_enrichments_from_neo4j,
    parse_derivation_response,
    query_candidates,
)
from deriva.modules.derivation.refine.base import normalize_name, similarity_ratio

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.graph import GraphManager
    from deriva.adapters.graph.cache import EnrichmentCacheManager


def _get_element_props(
    batch_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    identifier: str,
) -> dict[str, Any]:
    """Get properties for an element by identifier.

    Used to propagate graph properties to relationships for stability analysis.
    """
    for elem in batch_elements + existing_elements:
        if elem.get("identifier") == identifier:
            return elem.get("properties", {})
    return {}


class ElementDerivationBase(ABC):
    """
    Abstract base class for element derivation modules.

    Provides the common generate() flow shared by all element types.
    Subclasses must define:
    - ELEMENT_TYPE: The ArchiMate element type name
    - OUTBOUND_RULES: Relationships FROM this element type
    - INBOUND_RULES: Relationships TO this element type
    - filter_candidates(): Module-specific candidate filtering

    The generate() method handles:
    - Enrichment retrieval from Neo4j
    - Candidate querying
    - Batching
    - LLM calls for element derivation
    - Element creation in ArchimateManager
    - Relationship derivation
    """

    # Subclasses MUST override these
    ELEMENT_TYPE: str
    OUTBOUND_RULES: list[RelationshipRule]
    INBOUND_RULES: list[RelationshipRule]

    def __init__(self) -> None:
        """Initialize the derivation class."""
        self.logger = logging.getLogger(self.__class__.__module__)

    @abstractmethod
    def filter_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        **kwargs: Any,
    ) -> list[Candidate]:
        """
        Filter candidates for this element type.

        Each module implements its own filtering strategy based on:
        - Pattern matching (include/exclude patterns from config)
        - Graph structure (community roots, PageRank)
        - Domain-specific heuristics

        Args:
            candidates: Raw candidates from graph query
            enrichments: Graph enrichment data (pagerank, community, kcore, etc.)
            max_candidates: Maximum candidates to return
            **kwargs: Additional module-specific parameters
                     (e.g., include_patterns, exclude_patterns for pattern-based modules)

        Returns:
            Filtered list of candidates, limited to max_candidates
        """
        ...

    def get_filter_kwargs(self, engine: Any) -> dict[str, Any]:
        """
        Get additional kwargs for filter_candidates().

        Pattern-based modules override this to load patterns from config.
        Graph-based modules can use the default (empty dict).

        Args:
            engine: DuckDB connection for config queries

        Returns:
            Dict of kwargs to pass to filter_candidates()
        """
        return {}

    def _filter_existing_duplicates(
        self,
        candidates: list[Candidate],
        archimate_manager: "ArchimateManager",
        threshold: float = 0.85,
    ) -> list[Candidate]:
        """
        Filter out candidates that already exist as elements.

        This pre-generation duplicate check saves LLM tokens by excluding
        candidates that match existing elements (exact or fuzzy).

        Args:
            candidates: Candidates to filter
            archimate_manager: For querying existing elements
            threshold: Fuzzy match threshold (default: 0.85)

        Returns:
            Filtered candidates with existing matches removed
        """
        try:
            existing = archimate_manager.get_elements(
                element_type=self.ELEMENT_TYPE, enabled_only=True
            )
        except Exception:
            # If we can't get existing elements, skip duplicate check
            return candidates

        if not existing:
            return candidates

        # Build normalized name lookup for existing elements
        existing_names: dict[str, str] = {}
        for elem in existing:
            norm = normalize_name(elem.name)
            existing_names[norm] = elem.identifier

        filtered = []
        for c in candidates:
            if not c.name:
                continue

            norm_name = normalize_name(c.name)

            # Check exact match
            if norm_name in existing_names:
                self.logger.debug(
                    "Skipping candidate %s (exact match with %s)",
                    c.name,
                    existing_names[norm_name],
                )
                continue

            # Check fuzzy match
            is_fuzzy_match = False
            for existing_norm in existing_names:
                if similarity_ratio(norm_name, existing_norm) >= threshold:
                    self.logger.debug(
                        "Skipping candidate %s (fuzzy match with existing)",
                        c.name,
                    )
                    is_fuzzy_match = True
                    break

            if not is_fuzzy_match:
                filtered.append(c)

        if len(candidates) != len(filtered):
            self.logger.info(
                "Pre-generation duplicate check: %d -> %d candidates for %s",
                len(candidates),
                len(filtered),
                self.ELEMENT_TYPE,
            )

        return filtered

    def generate(
        self,
        graph_manager: "GraphManager",
        archimate_manager: "ArchimateManager",
        engine: Any,
        llm_query_fn: Callable[..., Any],
        query: str,
        instruction: str,
        example: str,
        max_candidates: int,
        batch_size: int,
        existing_elements: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        defer_relationships: bool = False,
        cache_manager: "EnrichmentCacheManager | None" = None,
    ) -> GenerationResult:
        """
        Generate elements of this type.

        This is the common flow shared by all element modules:
        1. Get filter kwargs (patterns for pattern-based modules)
        2. Get enrichments from Neo4j
        3. Query candidates
        4. Filter candidates (module-specific)
        5. Batch candidates
        6. For each batch: LLM call -> parse -> create elements -> derive relationships

        Args:
            graph_manager: GraphManager for querying graph nodes
            archimate_manager: ArchimateManager for creating elements
            engine: DuckDB connection for config
            llm_query_fn: Function to call LLM
            query: Cypher query to find candidates
            instruction: LLM instruction for derivation
            example: Example output for LLM
            max_candidates: Maximum candidates to process
            batch_size: Candidates per LLM batch
            existing_elements: Already-created elements for relationship derivation
            temperature: Optional LLM temperature override
            max_tokens: Optional LLM max_tokens override
            defer_relationships: If True, skip relationship derivation
            cache_manager: Optional EnrichmentCacheManager for controlled caching

        Returns:
            GenerationResult with success status, counts, and any errors
        """
        result = GenerationResult(success=True)

        # Get filter kwargs (patterns for pattern-based modules)
        filter_kwargs = self.get_filter_kwargs(engine)

        # Get enrichments and query candidates
        enrichments = get_enrichments_from_neo4j(
            graph_manager,
            cache_manager=cache_manager,
            config_name=self.ELEMENT_TYPE,
        )

        try:
            candidates = query_candidates(graph_manager, query, enrichments)
        except Exception as e:
            return GenerationResult(
                success=False,
                errors=[f"Query failed for {self.ELEMENT_TYPE}: {e}"],
            )

        if not candidates:
            self.logger.info("No candidates found for %s", self.ELEMENT_TYPE)
            return result

        # Track all queried candidates for threshold analysis
        result.candidates_queried = len(candidates)

        self.logger.info(
            "Found %d candidates for %s", len(candidates), self.ELEMENT_TYPE
        )

        # Filter candidates (module-specific)
        filtered = self.filter_candidates(
            candidates, enrichments, max_candidates, **filter_kwargs
        )

        if not filtered:
            self.logger.info("No candidates passed filtering for %s", self.ELEMENT_TYPE)
            # Track rejected candidates
            for c in candidates:
                result.candidate_decisions.append(
                    CandidateDecision(
                        node_id=c.node_id,
                        name=c.name,
                        element_type=self.ELEMENT_TYPE,
                        pagerank=c.pagerank,
                        kcore_level=c.kcore_level,
                        in_degree=c.in_degree,
                        out_degree=c.out_degree,
                        confidence=c.properties.get("confidence"),
                        stage="filtered_out",
                        became_element=False,
                    )
                )
            return result

        result.candidates_filtered = len(filtered)
        filtered_ids = {c.node_id for c in filtered}

        self.logger.info(
            "Filtered to %d candidates for LLM (%s)", len(filtered), self.ELEMENT_TYPE
        )

        # Track candidates filtered out at this stage
        for c in candidates:
            if c.node_id not in filtered_ids:
                result.candidate_decisions.append(
                    CandidateDecision(
                        node_id=c.node_id,
                        name=c.name,
                        element_type=self.ELEMENT_TYPE,
                        pagerank=c.pagerank,
                        kcore_level=c.kcore_level,
                        in_degree=c.in_degree,
                        out_degree=c.out_degree,
                        confidence=c.properties.get("confidence"),
                        stage="filtered_out",
                        became_element=False,
                    )
                )

        # Pre-generation duplicate check - filter out candidates matching existing elements
        pre_dedup_ids = {c.node_id for c in filtered}
        filtered = self._filter_existing_duplicates(filtered, archimate_manager)
        post_dedup_ids = {c.node_id for c in filtered}

        # Track candidates removed by deduplication
        for c in candidates:
            if c.node_id in pre_dedup_ids and c.node_id not in post_dedup_ids:
                result.candidate_decisions.append(
                    CandidateDecision(
                        node_id=c.node_id,
                        name=c.name,
                        element_type=self.ELEMENT_TYPE,
                        pagerank=c.pagerank,
                        kcore_level=c.kcore_level,
                        in_degree=c.in_degree,
                        out_degree=c.out_degree,
                        confidence=c.properties.get("confidence"),
                        stage="duplicate_removed",
                        became_element=False,
                    )
                )

        if not filtered:
            self.logger.info(
                "All candidates matched existing elements for %s", self.ELEMENT_TYPE
            )
            return result

        # Track candidates sent to LLM
        result.candidates_to_llm = len(filtered)

        # Batch and process
        batches = batch_candidates(filtered, batch_size)

        llm_kwargs: dict[str, Any] = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        for batch_num, batch in enumerate(batches, 1):
            self._process_batch(
                batch_num=batch_num,
                batch=batch,
                instruction=instruction,
                example=example,
                llm_query_fn=llm_query_fn,
                llm_kwargs=llm_kwargs,
                archimate_manager=archimate_manager,
                graph_manager=graph_manager,
                existing_elements=existing_elements,
                temperature=temperature,
                max_tokens=max_tokens,
                defer_relationships=defer_relationships,
                result=result,
            )

        self.logger.info(
            "Created %d %s elements and %d relationships",
            result.elements_created,
            self.ELEMENT_TYPE,
            result.relationships_created,
        )
        return result

    def _process_batch(
        self,
        batch_num: int,
        batch: list[Candidate],
        instruction: str,
        example: str,
        llm_query_fn: Callable[..., Any],
        llm_kwargs: dict[str, Any],
        archimate_manager: "ArchimateManager",
        graph_manager: "GraphManager",
        existing_elements: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        defer_relationships: bool,
        result: GenerationResult,
    ) -> None:
        """
        Process a single batch of candidates.

        Handles LLM call, response parsing, element creation, and
        relationship derivation for one batch.

        Args:
            batch_num: Batch number (for error reporting)
            batch: List of candidates in this batch
            instruction: LLM instruction
            example: LLM example
            llm_query_fn: LLM query function
            llm_kwargs: Additional LLM parameters
            archimate_manager: For creating elements
            graph_manager: For relationship derivation
            existing_elements: For relationship derivation
            temperature: LLM temperature
            max_tokens: LLM max tokens
            defer_relationships: Skip relationship derivation if True
            result: GenerationResult to update with counts and errors
        """
        # Build prompt
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=instruction,
            example=example,
            element_type=self.ELEMENT_TYPE,
        )

        # Call LLM
        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **llm_kwargs)
            response_content, error = extract_response_content(response)
            if error:
                result.errors.append(
                    f"LLM error in batch {batch_num} ({self.ELEMENT_TYPE}): {error}"
                )
                return
        except Exception as e:
            result.errors.append(
                f"LLM error in batch {batch_num} ({self.ELEMENT_TYPE}): {e}"
            )
            return

        # Parse response
        parse_result = parse_derivation_response(response_content)
        if not parse_result["success"]:
            result.errors.extend(
                [
                    f"{self.ELEMENT_TYPE} batch {batch_num}: {e}"
                    for e in parse_result.get("errors", [])
                ]
            )
            return

        # Build enrichment lookup for this batch
        batch_enrichments = {
            c.node_id: {
                "pagerank": c.pagerank,
                "louvain_community": c.louvain_community,
            }
            for c in batch
        }

        # Create elements
        batch_elements: list[dict[str, Any]] = []
        created_source_ids: set[str] = set()

        for derived in parse_result.get("data", []):
            element_result = build_element(
                derived, self.ELEMENT_TYPE, batch_enrichments
            )

            if not element_result["success"]:
                result.errors.extend(element_result.get("errors", []))
                continue

            element_data = element_result["data"]

            try:
                element = Element(
                    name=element_data["name"],
                    element_type=element_data["element_type"],
                    identifier=element_data["identifier"],
                    documentation=element_data.get("documentation"),
                    properties=element_data.get("properties", {}),
                )
                archimate_manager.add_element(element)
                result.elements_created += 1
                result.created_elements.append(element_data)
                batch_elements.append(element_data)

                # Track source node that became element
                source_id = derived.get("source")
                if source_id:
                    created_source_ids.add(source_id)
            except Exception as e:
                result.errors.append(
                    f"Failed to create {self.ELEMENT_TYPE} element "
                    f"{element_data.get('identifier', 'unknown')}: {e}"
                )

        # Track candidate decisions for this batch
        for c in batch:
            if c.node_id in created_source_ids:
                # Find the element that was created from this candidate
                element_id = None
                element_confidence = None
                for derived in parse_result.get("data", []):
                    if derived.get("source") == c.node_id:
                        element_id = derived.get("identifier")
                        element_confidence = derived.get("confidence")
                        break

                result.candidate_decisions.append(
                    CandidateDecision(
                        node_id=c.node_id,
                        name=c.name,
                        element_type=self.ELEMENT_TYPE,
                        pagerank=c.pagerank,
                        kcore_level=c.kcore_level,
                        in_degree=c.in_degree,
                        out_degree=c.out_degree,
                        confidence=c.properties.get("confidence"),
                        stage="created",
                        became_element=True,
                        element_id=element_id,
                        element_confidence=element_confidence,
                    )
                )
            else:
                # Candidate was sent to LLM but rejected
                result.candidate_decisions.append(
                    CandidateDecision(
                        node_id=c.node_id,
                        name=c.name,
                        element_type=self.ELEMENT_TYPE,
                        pagerank=c.pagerank,
                        kcore_level=c.kcore_level,
                        in_degree=c.in_degree,
                        out_degree=c.out_degree,
                        confidence=c.properties.get("confidence"),
                        stage="llm_rejected",
                        became_element=False,
                    )
                )

        # Derive relationships
        if batch_elements and existing_elements and not defer_relationships:
            self._derive_relationships(
                batch_elements=batch_elements,
                existing_elements=existing_elements,
                llm_query_fn=llm_query_fn,
                temperature=temperature,
                max_tokens=max_tokens,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                result=result,
            )

    def _derive_relationships(
        self,
        batch_elements: list[dict[str, Any]],
        existing_elements: list[dict[str, Any]],
        llm_query_fn: Callable[..., Any],
        temperature: float | None,
        max_tokens: int | None,
        graph_manager: "GraphManager",
        archimate_manager: "ArchimateManager",
        result: GenerationResult,
    ) -> None:
        """
        Derive relationships for newly created elements.

        Args:
            batch_elements: Elements created in this batch
            existing_elements: All previously created elements
            llm_query_fn: LLM query function
            temperature: LLM temperature
            max_tokens: LLM max tokens
            graph_manager: For graph-based relationship derivation
            archimate_manager: For creating relationships
            result: GenerationResult to update
        """
        relationships = derive_batch_relationships(
            new_elements=batch_elements,
            existing_elements=existing_elements,
            element_type=self.ELEMENT_TYPE,
            outbound_rules=self.OUTBOUND_RULES,
            inbound_rules=self.INBOUND_RULES,
            llm_query_fn=llm_query_fn,
            temperature=temperature,
            max_tokens=max_tokens,
            graph_manager=graph_manager,
        )

        for rel_data in relationships:
            try:
                # Propagate graph properties from source/target elements for stability analysis
                source_props = _get_element_props(
                    batch_elements, existing_elements, rel_data["source"]
                )
                target_props = _get_element_props(
                    batch_elements, existing_elements, rel_data["target"]
                )

                relationship = Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    relationship_type=rel_data["relationship_type"],
                    properties={
                        "confidence": rel_data.get("confidence", 0.5),
                        "source_pagerank": source_props.get("source_pagerank"),
                        "source_kcore": source_props.get("source_kcore_level"),
                        "source_community": source_props.get(
                            "source_louvain_community"
                        ),
                        "target_pagerank": target_props.get("source_pagerank"),
                        "target_kcore": target_props.get("source_kcore_level"),
                        "target_community": target_props.get(
                            "source_louvain_community"
                        ),
                    },
                )
                archimate_manager.add_relationship(relationship)
                result.relationships_created += 1
                result.created_relationships.append(rel_data)
            except Exception as e:
                result.errors.append(
                    f"Failed to create {self.ELEMENT_TYPE} relationship: {e}"
                )


class PatternBasedDerivation(ElementDerivationBase):
    """
    Mixin for element modules that use pattern-based filtering.

    Most element modules (10 out of 13) use include/exclude patterns
    loaded from the config database. This mixin provides the default
    implementation of get_filter_kwargs() to load those patterns.

    Modules using this base class receive include_patterns and
    exclude_patterns as kwargs to their filter_candidates() method.

    Subclasses can override PATTERN_MATCH_DEFAULT to control the default
    return value when no patterns match (default is False).
    """

    # Override in subclass to change default behavior when no patterns match
    PATTERN_MATCH_DEFAULT: bool = False

    def matches_patterns(
        self, name: str, include_patterns: set[str], exclude_patterns: set[str]
    ) -> bool:
        """
        Check if name matches include patterns and not exclude patterns.

        This is a common utility method that consolidates the pattern matching
        logic previously duplicated across all element modules.

        Args:
            name: The name to check
            include_patterns: Patterns that indicate a match
            exclude_patterns: Patterns that indicate exclusion

        Returns:
            True if name matches include patterns and not exclude patterns,
            otherwise returns PATTERN_MATCH_DEFAULT
        """
        if not name:
            return False

        name_lower = name.lower()

        # Check exclusion patterns first
        for pattern in exclude_patterns:
            if pattern in name_lower:
                return False

        # Check for include patterns
        for pattern in include_patterns:
            if pattern in name_lower:
                return True

        return self.PATTERN_MATCH_DEFAULT

    def get_filter_kwargs(self, engine: Any) -> dict[str, Any]:
        """
        Load include/exclude patterns from config database.

        Args:
            engine: DuckDB connection

        Returns:
            Dict with include_patterns and exclude_patterns sets
        """
        from deriva.services import config

        try:
            patterns = config.get_derivation_patterns(engine, self.ELEMENT_TYPE)
            return {
                "include_patterns": patterns.get("include", set()),
                "exclude_patterns": patterns.get("exclude", set()),
            }
        except ValueError:
            # No patterns configured - return empty sets
            self.logger.debug(
                "No derivation patterns found for %s, using empty sets",
                self.ELEMENT_TYPE,
            )
            return {
                "include_patterns": set(),
                "exclude_patterns": set(),
            }


class HybridFilteringMixin:
    """
    Mixin providing graph-based filtering capabilities.

    Adds PageRank filtering, community root detection, and articulation point
    filtering. Use class constants to configure filtering behavior per module.

    Constants (override in subclass):
        MIN_PAGERANK: Minimum PageRank threshold (None = no filtering)
        USE_COMMUNITY_ROOTS: Prioritize community root nodes
        USE_ARTICULATION_POINTS: Include articulation points
        COMMUNITY_ROOT_RATIO: Ratio of candidates that should be community roots (0.0-1.0)
    """

    # Graph filtering constants - override in subclass as needed
    MIN_PAGERANK: float | None = None
    USE_COMMUNITY_ROOTS: bool = False
    USE_ARTICULATION_POINTS: bool = False
    COMMUNITY_ROOT_RATIO: float = (
        0.5  # 50% community roots when USE_COMMUNITY_ROOTS=True
    )

    def apply_graph_filtering(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
    ) -> list[Candidate]:
        """
        Apply graph-based filtering to candidates.

        Filters by:
        1. Minimum PageRank threshold (if MIN_PAGERANK set)
        2. Community roots (if USE_COMMUNITY_ROOTS set)
        3. Articulation points (if USE_ARTICULATION_POINTS set)

        After filtering, ranks by PageRank and returns top N.

        Args:
            candidates: Pre-filtered candidates (e.g., after pattern matching)
            enrichments: Graph enrichment data
            max_candidates: Maximum candidates to return

        Returns:
            Filtered and ranked candidates
        """
        if not candidates:
            return []

        filtered = list(candidates)

        # Filter by minimum PageRank
        if self.MIN_PAGERANK is not None:
            filtered = [c for c in filtered if (c.pagerank or 0) >= self.MIN_PAGERANK]

        if not filtered:
            return []

        # Identify community roots and articulation points
        community_roots = set()
        articulation_points = set()

        if self.USE_COMMUNITY_ROOTS or self.USE_ARTICULATION_POINTS:
            for node_id, data in enrichments.items():
                if data.get("is_community_root"):
                    community_roots.add(node_id)
                if data.get("is_articulation_point"):
                    articulation_points.add(node_id)

        # Split into priority groups
        priority_candidates = []
        regular_candidates = []

        for c in filtered:
            is_priority = False
            if self.USE_COMMUNITY_ROOTS and c.node_id in community_roots:
                is_priority = True
            if self.USE_ARTICULATION_POINTS and c.node_id in articulation_points:
                is_priority = True

            if is_priority:
                priority_candidates.append(c)
            else:
                regular_candidates.append(c)

        # Sort each group by PageRank (descending)
        priority_candidates.sort(key=lambda c: c.pagerank or 0, reverse=True)
        regular_candidates.sort(key=lambda c: c.pagerank or 0, reverse=True)

        # Combine with priority candidates first
        if self.USE_COMMUNITY_ROOTS and priority_candidates:
            # Take up to COMMUNITY_ROOT_RATIO of max_candidates from priority
            priority_limit = int(max_candidates * self.COMMUNITY_ROOT_RATIO)
            result = priority_candidates[:priority_limit]
            remaining = max_candidates - len(result)
            result.extend(regular_candidates[:remaining])
            return result[:max_candidates]

        # Default: combine and take top N by PageRank
        all_sorted = priority_candidates + regular_candidates
        return all_sorted[:max_candidates]


class HybridDerivation(PatternBasedDerivation, HybridFilteringMixin):
    """
    Base class combining pattern-based and graph-based filtering.

    All derivation modules should inherit from this class. It provides:
    - Pattern matching (include/exclude patterns from config)
    - Graph-based filtering (PageRank, community roots)
    - A unified filter_candidates() implementation

    Override class constants to customize filtering behavior:

        class ApplicationComponentDerivation(HybridDerivation):
            ELEMENT_TYPE = "ApplicationComponent"
            USE_COMMUNITY_ROOTS = True  # Prioritize community roots
            MIN_PAGERANK = 0.001  # Filter low-importance nodes
            COMMUNITY_ROOT_RATIO = 0.6  # 60% community roots

    The default filter_candidates() applies:
    1. Pattern matching (if patterns configured)
    2. Graph filtering (PageRank threshold, community roots)
    3. Final ranking by PageRank

    Subclasses can override filter_candidates() for custom logic, or call
    super().filter_candidates() and add additional filtering.
    """

    def filter_candidates(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        include_patterns: set[str] | None = None,
        exclude_patterns: set[str] | None = None,
        **kwargs: Any,
    ) -> list[Candidate]:
        """
        Filter candidates using both patterns and graph metrics.

        1. Apply pattern matching (include/exclude)
        2. Apply graph filtering (PageRank, community roots)
        3. Return top N by PageRank

        Args:
            candidates: Raw candidates from graph query
            enrichments: Graph enrichment data
            max_candidates: Maximum candidates to return
            include_patterns: Patterns that indicate inclusion
            exclude_patterns: Patterns that indicate exclusion
            **kwargs: Additional module-specific parameters

        Returns:
            Filtered candidates, ranked by PageRank
        """
        if not candidates:
            return []

        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        # Step 1: Pattern matching (if patterns configured)
        if include_patterns or exclude_patterns:
            pattern_matched = [
                c
                for c in candidates
                if self.matches_patterns(c.name, include_patterns, exclude_patterns)
            ]
        else:
            # No patterns = include all (subject to graph filtering)
            pattern_matched = list(candidates)

        if not pattern_matched:
            return []

        # Step 2: Apply graph filtering
        filtered = self.apply_graph_filtering(
            pattern_matched, enrichments, max_candidates
        )

        return filtered


__all__ = [
    "ElementDerivationBase",
    "PatternBasedDerivation",
    "HybridFilteringMixin",
    "HybridDerivation",
]
