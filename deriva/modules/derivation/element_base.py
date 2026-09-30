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

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from deriva.adapters.archimate.models import Element, Relationship  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
from deriva.common import current_timestamp
from deriva.modules.derivation.base import (
    DERIVATION_SCHEMA,
    NAMING_SCHEMA,
    ROLE_SCHEMA,
    Candidate,
    CandidateDecision,
    ElementPrompt,
    GenerationResult,
    GraphFilter,
    NamingConfig,
    NestedFilter,
    PerCandidateConfig,
    RelationshipLLMConfig,
    RelationshipRule,
    RoleConfig,
    batch_candidates,
    build_derivation_prompt,
    build_element,
    build_naming_prompt,
    build_role_prompt,
    build_single_candidate_prompt,
    choose_name,
    compute_candidate_strength,
    derive_batch_relationships,
    element_identifier,
    extract_response_content,
    get_enrichments_from_graph,
    name_from_source,
    naming_source,
    parse_derivation_response,
    parse_role_answer,
    query_candidates,
    structure_element_name,
)
from deriva.modules.derivation.refine.base import normalize_name, similarity_ratio

if TYPE_CHECKING:
    from deriva.adapters.archimate import ArchimateManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
    from deriva.adapters.graph.cache import EnrichmentCacheManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)


def _display_key(name: str) -> str:
    """Element names within a type compare case- and space-insensitively."""
    return " ".join(name.lower().split())


def _each_word_once(text: str) -> str:
    """The words of ``text`` in order, each once (compared case-insensitively)."""
    seen: set[str] = set()
    words: list[str] = []
    for word in text.split():
        if word.casefold() not in seen:
            seen.add(word.casefold())
            words.append(word)
    return " ".join(words)


def _relative_path(path: str, repo_name: str) -> str:
    """A node path relative to the repository, with forward slashes."""
    path = path.replace("\\", "/").strip("/")
    return path[len(repo_name) + 1 :] if repo_name and path.startswith(repo_name + "/") else path


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
    - Enrichment retrieval from graph
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

    # Confidence gate: elements below this threshold are not created
    MIN_ELEMENT_CONFIDENCE: float = 0.5

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

    def get_filter_kwargs(self, patterns: dict[str, set[str]]) -> dict[str, Any]:
        """
        Get additional kwargs for filter_candidates().

        Pattern-based modules override this to pass their patterns on.
        Graph-based modules can use the default (empty dict).

        Args:
            patterns: The step's include/exclude patterns (loaded by the service)

        Returns:
            Dict of kwargs to pass to filter_candidates()
        """
        return {}

    def _filter_existing_duplicates(
        self,
        candidates: list[Candidate],
        archimate_manager: ArchimateManager,
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
            existing = archimate_manager.get_elements(element_type=self.ELEMENT_TYPE, enabled_only=True)
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

    def _consolidate_near_duplicates(
        self,
        candidates: list[Candidate],
        threshold: float = 0.85,
    ) -> list[Candidate]:
        """Merge near-duplicate candidates before sending to LLM.

        Groups candidates with similar normalized names and keeps only the
        highest-PageRank representative from each group. This prevents the
        LLM from seeing "rollback", "execute_rollback", and "perform_rollback"
        as three separate candidates.

        Uses the same normalize_name() and similarity_ratio() as the existing
        duplicate_elements refine step (270+ synonym mappings built in).

        Args:
            candidates: Filtered candidates (post graph filtering)
            threshold: Similarity threshold for grouping (default 0.85)

        Returns:
            Consolidated candidates with near-duplicates merged
        """
        if len(candidates) <= 1:
            return candidates

        # Normalize all names upfront
        norms = [(c, normalize_name(c.name)) for c in candidates]

        # Union-Find grouping
        parent: dict[int, int] = {i: i for i in range(len(norms))}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(len(norms)):
            for j in range(i + 1, len(norms)):
                if similarity_ratio(norms[i][1], norms[j][1]) >= threshold:
                    union(i, j)

        # Group by root
        groups: dict[int, list[Candidate]] = {}
        for i, (c, _) in enumerate(norms):
            root = find(i)
            groups.setdefault(root, []).append(c)

        # From each group, keep highest pagerank (tiebreaker: alphabetical node_id)
        result = []
        for group in groups.values():
            survivor = max(
                group,
                key=lambda c: (c.pagerank or 0, c.node_id),
            )
            result.append(survivor)
            if len(group) > 1:
                merged_names = [c.name for c in group if c is not survivor]
                self.logger.debug(
                    "Consolidated near-duplicates for %s: kept '%s', merged %s",
                    self.ELEMENT_TYPE,
                    survivor.name,
                    merged_names,
                )

        if len(result) < len(candidates):
            self.logger.info(
                "Near-duplicate consolidation: %d -> %d candidates for %s",
                len(candidates),
                len(result),
                self.ELEMENT_TYPE,
            )

        return result

    def generate(
        self,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
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
        cache_manager: EnrichmentCacheManager | None = None,
        relationship_config: RelationshipLLMConfig | None = None,
        per_candidate: PerCandidateConfig | None = None,
        naming: NamingConfig | None = None,
        patterns: dict[str, set[str]] | None = None,
        roles: RoleConfig | None = None,
        skip_when_directory_is: frozenset[str] | None = None,
        prompt: ElementPrompt | None = None,
        graph_filter: GraphFilter | None = None,
        skip_subtypes: bool = False,
        skip_nested: NestedFilter | None = None,
    ) -> GenerationResult:
        """
        Generate elements of this type.

        This is the common flow shared by all element modules:
        1. Get filter kwargs (patterns for pattern-based modules)
        2. Get enrichments from graph
        3. Query candidates
        4. Filter candidates (module-specific)
        5. Batch candidates
        6. For each batch: LLM call -> parse -> create elements -> derive relationships

        Args:
            graph_manager: GraphManager for querying graph nodes
            archimate_manager: ArchimateManager for creating elements
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
            relationship_config: Relationship config row settings for the LLM
                relationship pass (None skips that pass)
            per_candidate: Per-candidate naming mode from the element config
                (None uses batch mode)
            naming: Isolated naming step from the element config (None keeps the
                structure name)
            patterns: The step's include/exclude patterns from config (None: none)
            roles: Candidates classified into roles from the element config (None: every
                candidate takes the keep and naming path)
            skip_when_directory_is: Element types whose sources take a directory's candidates
                out: one structural source, one element (None: nothing left out this way)
            prompt: The texts of the batch element prompt from the element config (required
                when candidates are derived in batches)
            graph_filter: The step's k-core threshold from the element config (None: no
                k-core threshold)
            skip_subtypes: One element per contract: a candidate type that inherits from
                another candidate type of the repository is left out before any ranking or cut
            skip_nested: One module, one element: a selected directory holding nearly all of its
                nearest selected ancestor's files of a type is left out after the cut (None: none)

        Returns:
            GenerationResult with success status, counts, and any errors
        """
        result = GenerationResult(success=True)

        # Get filter kwargs (patterns for pattern-based modules, the step's graph threshold)
        filter_kwargs = self.get_filter_kwargs(patterns or {})
        if graph_filter is not None:
            filter_kwargs["graph_filter"] = graph_filter

        # Get enrichments and query candidates
        enrichments = get_enrichments_from_graph(
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

        self.logger.info("Found %d candidates for %s", len(candidates), self.ELEMENT_TYPE)

        # One element per contract: a type that inherits from another candidate type of the
        # repository is represented by it and leaves the list before any ranking or cut
        if skip_subtypes:
            subtypes = self._subtypes_of_candidates(candidates, graph_manager)
            for c in candidates:
                if c.node_id in subtypes:
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
            candidates = [c for c in candidates if c.node_id not in subtypes]

        # One structural source, one element: a candidate whose directory already is an element's
        # source is left out before the ranking and cut, so it takes no place (recorded as filtered out)
        eligible = candidates
        if skip_when_directory_is:
            represented = self._represented_by_elements(candidates, skip_when_directory_is, graph_manager, archimate_manager)
            eligible = [c for c in candidates if c.node_id not in represented]

        # Filter candidates (module-specific)
        filtered = self.filter_candidates(eligible, enrichments, max_candidates, **filter_kwargs)

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

        self.logger.info("Filtered to %d candidates for LLM (%s)", len(filtered), self.ELEMENT_TYPE)

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

        # One module, one element: a directory holding nearly all of its nearest selected
        # ancestor's files is represented by it; after the cut, so no place moves to the next candidate
        if skip_nested is not None:
            nested = self._nested_in_ancestors(filtered, skip_nested, graph_manager)
            for c in filtered:
                if c.node_id in nested:
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
stage="nested_removed",
                            became_element=False,
                        )
                    )
            filtered = [c for c in filtered if c.node_id not in nested]

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
            self.logger.info("All candidates matched existing elements for %s", self.ELEMENT_TYPE)
            return result

        # Consolidate near-duplicate candidate names before LLM
        consolidated = self._consolidate_near_duplicates(filtered)
        kept_ids = {c.node_id for c in consolidated}
        for c in filtered:
            if c.node_id not in kept_ids:
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
        filtered = consolidated

        # Names are unique within the type, decided by structure before any LLM call: a
        # candidate whose structure name repeats an earlier candidate's is left out, and an
        # LLM name never takes another candidate's structure name (see _apply_naming)
        repo_name = self._active_repo_name(graph_manager)
        structure_names: dict[str, str] = {}  # candidate id -> key of its structure name
        for c in filtered:
            key = _display_key(structure_element_name(c.node_id, c.name, repo_name))
            if key in structure_names.values():
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
                continue
            structure_names[c.node_id] = key
        filtered = [c for c in filtered if c.node_id in structure_names]

        # Track candidates sent to LLM
        result.candidates_to_llm = len(filtered)

        llm_kwargs: dict[str, Any] = {}
        if temperature is not None:
            llm_kwargs["temperature"] = temperature
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        # Names given so far in this step: role elements first, then kept candidates
        taken: list[str] = []

        # Candidates the step classifies into roles leave the keep and naming path
        if roles is not None:
            role_candidates = [c for c in filtered if roles.labels.intersection(c.labels)]
            filtered = [c for c in filtered if not roles.labels.intersection(c.labels)]
            if role_candidates:
                self._process_roles(
                    role_candidates, roles, llm_query_fn, llm_kwargs, graph_manager, archimate_manager, repo_name, batch_size, result, taken, naming, structure_names
                )

        # Compute abstention strength signal from the filtered set.
        # Shared across batches so the LLM sees one consistent view.
        strength = compute_candidate_strength(filtered)

        # Batch and process
        batches = batch_candidates(filtered, batch_size)

        if per_candidate is not None and len(filtered) >= per_candidate.min_pool:
            self._process_per_candidate(
                filtered=filtered,
                instruction=instruction,
                rules=per_candidate.rules,
                persona=per_candidate.persona,
                llm_query_fn=llm_query_fn,
                llm_kwargs=llm_kwargs,
                archimate_manager=archimate_manager,
                graph_manager=graph_manager,
                existing_elements=existing_elements,
                temperature=temperature,
                max_tokens=max_tokens,
                defer_relationships=defer_relationships,
                result=result,
                repo_name=repo_name,
                structure_names=structure_names,
                taken=taken,
                relationship_config=relationship_config,
                naming=naming,
            )
        elif batches and prompt is None:
            result.success = False
            result.errors.append(f"{self.ELEMENT_TYPE}: params.prompt is missing (the texts of the batch element prompt)")
        else:
            for batch_num, batch in enumerate(batches, 1):
                self._process_batch(
                    batch_num=batch_num,
                    batch=batch,
                    instruction=instruction,
                    example=example,
                    llm_query_fn=llm_query_fn,
                    llm_kwargs=llm_kwargs,
                    strength=strength,
                    archimate_manager=archimate_manager,
                    graph_manager=graph_manager,
                    existing_elements=existing_elements,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    defer_relationships=defer_relationships,
                    result=result,
                    repo_name=repo_name,
                    structure_names=structure_names,
                    taken=taken,
                    element_prompt=cast(ElementPrompt, prompt),
                    relationship_config=relationship_config,
                    naming=naming,
                )

        self.logger.info(
            "Created %d %s elements and %d relationships",
            result.elements_created,
            self.ELEMENT_TYPE,
            result.relationships_created,
        )
        return result

    def _process_roles(
        self,
        candidates: list[Candidate],
        roles: RoleConfig,
        llm_query_fn: Callable[..., Any],
        llm_kwargs: dict[str, Any],
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        repo_name: str,
        batch_size: int,
        result: GenerationResult,
        taken: list[str],
        naming: NamingConfig | None = None,
        structure_names: dict[str, str] | None = None,
    ) -> None:
        """Classify candidates into the configured roles and create one element per chosen role.

        Candidates are asked in batches of ``batch_size`` in id order; a candidate left out of
        an answer is asked again up to ``roles.missing_retries`` times. The element's identity
        and name come from the role; its source is the first member by id (for graph
        grounding) and ``sources`` lists every member. With ``element_per`` "candidate" each
        candidate with a role is its own element, named as written or by ``name_template``.
        """
        ordered = sorted(candidates, key=lambda c: c.node_id)
        role_of: dict[str, str | None] = {}
        for start in range(0, len(ordered), batch_size):
            pending = ordered[start : start + batch_size]
            for _ in range(1 + roles.missing_retries):
                prompt = build_role_prompt(pending, roles.instruction, roles.names, show_path=roles.show_path)
                try:
                    content, error = extract_response_content(llm_query_fn(prompt, ROLE_SCHEMA, **llm_kwargs))
                except Exception as e:
                    content, error = "", str(e)
                if error:
                    self.logger.warning("Role classification failed for %s: %s", self.ELEMENT_TYPE, error)
                    continue
                role_of.update(parse_role_answer(content, {c.node_id for c in pending}, roles.names))
                pending = [c for c in pending if c.node_id not in role_of]
                if not pending:
                    break

        # The elements: (identifier, name, members, role key)
        containers: dict[str, str] = {}
        subjects: dict[str, str] = {}
        duplicates: set[str] = set()
        if roles.element_per == "candidate":
            chosen = [c for c in ordered if role_of.get(c.node_id) is not None]
            if roles.name_template:
                # The name from structure: container + subject + role name, each word once
                containers = self._containers_of(chosen, roles.container_type, graph_manager, archimate_manager, repo_name)
                subjects = {c.node_id: structure_element_name(c.node_id, c.name, repo_name) for c in chosen}
                names = {
                    c.node_id: _each_word_once(roles.name_template.format(container=containers[c.node_id], subject=subjects[c.node_id], role=roles.names[role_of[c.node_id] or ""]))
                    for c in chosen
                }
            else:
                # Named as the candidate is (as written)
                names = {c.node_id: c.name for c in chosen}
            # Names are unique within the type: a candidate whose planned name repeats a name given
            # before (earlier in the step or to an earlier candidate) is left out, as structure names are
            seen = {_display_key(name) for name in taken}
            for c in chosen:
                key = _display_key(names[c.node_id])
                if key in seen:
                    duplicates.add(c.node_id)
                seen.add(key)
            planned = [(element_identifier(self.ELEMENT_TYPE, c.node_id), names[c.node_id], [c], role_of[c.node_id] or "") for c in chosen if c.node_id not in duplicates]
        else:
            members: dict[str, list[Candidate]] = {}
            for c in ordered:
                role = role_of.get(c.node_id)
                if role is not None:
                    members.setdefault(role, []).append(c)
            planned = [(element_identifier(self.ELEMENT_TYPE, f"role::{repo_name}::{key}"), name, members[key], key) for key, name in roles.names.items() if key in members]

        element_of: dict[str, str] = {}  # candidate id -> identifier of its element
        for identifier, name, group, key in planned:
            source = group[0]
            properties: dict[str, Any] = {
                "source": source.node_id,
                "role": key,
                "derived_at": current_timestamp(),
                "source_pagerank": source.pagerank,
                "source_louvain_community": source.louvain_community,
            }
            if roles.element_per == "role":
                properties["sources"] = [c.node_id for c in group]
            element_data: dict[str, Any] = {
                "identifier": identifier,
                "name": name,
                "element_type": self.ELEMENT_TYPE,
                "documentation": roles.documentation.format(
                    members=", ".join(c.name for c in group), role=roles.names[key], container=containers.get(source.node_id, ""), subject=subjects.get(source.node_id, "")
                ),
                "properties": properties,
            }
            # The step's naming call may rename a candidate's element (the usual uniqueness rules apply)
            if roles.naming_call and naming is not None and roles.element_per == "candidate":
                self._apply_naming(element_data, source, naming, llm_query_fn, llm_kwargs, repo_name, taken, structure_names or {})
            try:
                archimate_manager.add_element(
                    Element(
                        name=element_data["name"],
                        element_type=self.ELEMENT_TYPE,
                        identifier=element_data["identifier"],
                        documentation=element_data["documentation"],
                        properties=element_data["properties"],
                    )
                )
            except Exception as e:
                result.errors.append(f"Failed to create {self.ELEMENT_TYPE} element {element_data['identifier']}: {e}")
                continue
            result.elements_created += 1
            result.created_elements.append(element_data)
            taken.append(element_data["name"])
            for c in group:
                element_of[c.node_id] = element_data["identifier"]

        for c in ordered:
            answered = c.node_id in role_of
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
                    stage="created" if c.node_id in element_of else ("duplicate_removed" if c.node_id in duplicates else ("llm_rejected" if answered else "llm_unanswered")),
                    became_element=c.node_id in element_of,
                    element_id=element_of.get(c.node_id),
                )
            )

    def _containers_of(
        self,
        candidates: list[Candidate],
        element_type: str,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        repo_name: str,
    ) -> dict[str, str]:
        """Per candidate id, the name of the ``element_type`` element whose source directory holds it.

        The deepest such directory wins; a candidate that none holds gets its top-level module's
        name from structure ("" without a path). Structure only: directories and paths.
        """
        from deriva.modules.derivation.refine.normalization import strip_repo_prefix

        sources = {e.properties.get("source"): e.name for e in (archimate_manager.get_elements(element_type=element_type) if element_type else []) if e.properties.get("source")}
        rows = graph_manager.query("MATCH (d:Graph:Directory) WHERE d.id IN $ids RETURN d.id AS id, d.path AS path", {"ids": sorted(sources)}) if sources else []
        directories = [(_relative_path(row["path"], repo_name), sources[row["id"]]) for row in rows if row.get("path") and row.get("id") in sources]
        containers: dict[str, str] = {}
        for c in candidates:
            path = _relative_path(c.properties.get("filePath") or c.properties.get("path") or "", repo_name)
            holders = [(len(directory), name) for directory, name in directories if path == directory or path.startswith(directory + "/")]
            if holders:
                containers[c.node_id] = max(holders)[1]
            elif path:
                module = name_from_source(path.split("/")[0])
                containers[c.node_id] = strip_repo_prefix(module, repo_name) if repo_name else module
            else:
                containers[c.node_id] = ""
        return containers

    def _represented_by_elements(
        self,
        candidates: list[Candidate],
        element_types: frozenset[str],
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
    ) -> set[str]:
        """Ids of the candidates a directory represents when that directory is the source of an element of ``element_types``."""
        sources = {e.properties.get("source") for element_type in sorted(element_types) for e in archimate_manager.get_elements(element_type=element_type)}
        if not candidates or not sources:
            return set()
        rows = graph_manager.query(
            "MATCH (d:Graph:Directory)-[r]->(t) WHERE type(r) = 'Graph:REPRESENTS' AND t.id IN $ids RETURN d.id AS dir, t.id AS id",
            {"ids": [c.node_id for c in candidates]},
        )
        return {row["id"] for row in rows if row["dir"] in sources}

    def _subtypes_of_candidates(self, candidates: list[Candidate], graph_manager: GraphManager) -> set[str]:
        """Ids of the candidates that inherit from another candidate type defined in the repository.

        A placeholder for an unresolved or external base type never represents a candidate.
        """
        if len(candidates) < 2:
            return set()
        rows = graph_manager.query(
            "MATCH (a:Graph:TypeDefinition)-[r]->(b) WHERE type(r) = 'Graph:INHERITS' AND a.id IN $ids AND b.id IN $ids "
            "AND b.category <> 'external_reference' RETURN DISTINCT a.id AS id",
            {"ids": [c.node_id for c in candidates]},
        )
        return {row["id"] for row in rows}

    def _nested_in_ancestors(self, candidates: list[Candidate], nested: NestedFilter, graph_manager: GraphManager) -> set[str]:
        """Ids of the directory candidates that hold at least ``nested.min_share`` of their nearest kept ancestor's files.

        Files of ``nested.file_type`` are counted below each directory through containment, over
        any depth. Ancestors are decided top-down, so a left-out directory never represents another.
        """
        if len(candidates) < 2:
            return set()
        ids = [c.node_id for c in candidates]
        pairs = graph_manager.query(
            "MATCH (a:Graph:Directory)-[:`Graph:CONTAINS`*]->(b:Graph:Directory) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS a, b.id AS b",
            {"ids": ids},
        )
        ancestors: dict[str, set[str]] = {}
        for row in pairs:
            ancestors.setdefault(row["b"], set()).add(row["a"])
        if not ancestors:
            return set()
        rows = graph_manager.query(
            "MATCH (d:Graph:Directory)-[:`Graph:CONTAINS`*]->(f:Graph:File) WHERE d.id IN $ids AND f.active = true AND f.fileType = $file_type RETURN d.id AS id, count(f) AS n",
            {"ids": ids, "file_type": nested.file_type},
        )
        files = {row["id"]: row["n"] for row in rows}
        left_out: set[str] = set()
        for node_id in sorted(ancestors, key=lambda d: len(ancestors[d])):
            kept = ancestors[node_id] - left_out
            if not kept:
                continue
            nearest = max(kept, key=lambda a: len(ancestors.get(a, ())))
            if files.get(nearest, 0) and files.get(node_id, 0) / files[nearest] >= nested.min_share:
                left_out.add(node_id)
        return left_out

    def _active_repo_name(self, graph_manager: GraphManager) -> str:
        """The active repository's name ("" when unknown), stripped from element names as a leading token."""
        try:
            rows = graph_manager.query("MATCH (r:Graph:Repository) WHERE r.active = true RETURN r.repository_name as name LIMIT 1")
            if rows and rows[0].get("name"):
                return rows[0]["name"]
        except Exception as e:
            self.logger.debug("Could not read active repository name: %s", e)
        return ""

    def _apply_naming(
        self,
        element_data: dict[str, Any],
        candidate: Candidate,
        naming: NamingConfig,
        llm_query_fn: Callable[..., Any],
        llm_kwargs: dict[str, Any],
        repo_name: str,
        taken: list[str],
        structure_names: dict[str, str],
    ) -> None:
        """Name an element with the isolated naming step, in place.

        The prompt holds only the candidate's structural description, the type
        and the configured convention, so the same source gets the same prompt in
        every run; ``naming.samples`` answers are combined by majority. Without a
        usable answer, when a sibling already has the name, or when the name is
        another candidate's structure name (``structure_names``: candidate id ->
        name key), the structure name stays: which candidates become elements never
        depends on an LLM name.
        """
        from deriva.modules.derivation.refine.normalization import strip_repo_prefix

        prompt = build_naming_prompt(naming_source(candidate), self.ELEMENT_TYPE, naming.instruction)
        answers: list[str | None] = []
        for _ in range(naming.samples):
            try:
                content, error = extract_response_content(llm_query_fn(prompt, NAMING_SCHEMA, **llm_kwargs))
                if error:
                    continue
                text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                answers.append(json.loads(text).get("name"))
            except (ValueError, AttributeError) as e:
                self.logger.debug("Unusable naming answer for %s: %s", candidate.node_id, e)
        name = choose_name(answers)
        # No type-suffix stripping here: the configured convention governs suffixes,
        # and words like "Service" or "API" are often part of the right name
        if name and repo_name:
            name = strip_repo_prefix(name, repo_name)
        blocked = {_display_key(n) for n in taken} | {key for node_id, key in structure_names.items() if node_id != candidate.node_id}
        if name and name != element_data["name"] and _display_key(name) not in blocked:
            element_data["properties"]["structure_name"] = element_data["name"]
            element_data["name"] = name

    def _process_batch(
        self,
        batch_num: int,
        batch: list[Candidate],
        instruction: str,
        example: str,
        llm_query_fn: Callable[..., Any],
        llm_kwargs: dict[str, Any],
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager,
        existing_elements: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        defer_relationships: bool,
        result: GenerationResult,
        repo_name: str,
        structure_names: dict[str, str],
        taken: list[str],
        element_prompt: ElementPrompt,
        strength: dict[str, Any] | None = None,
        relationship_config: RelationshipLLMConfig | None = None,
        naming: NamingConfig | None = None,
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
            relationship_config: Relationship config row settings (None skips the LLM pass)
        """
        # Build prompt
        prompt = build_derivation_prompt(
            candidates=batch,
            instruction=instruction,
            example=example,
            prompt=element_prompt,
            strength=strength,
        )

        # Call LLM
        try:
            response = llm_query_fn(prompt, DERIVATION_SCHEMA, **llm_kwargs)
            response_content, error = extract_response_content(response)
            if error:
                result.errors.append(f"LLM error in batch {batch_num} ({self.ELEMENT_TYPE}): {error}")
                return
        except Exception as e:
            result.errors.append(f"LLM error in batch {batch_num} ({self.ELEMENT_TYPE}): {e}")
            return

        # Parse response
        parse_result = parse_derivation_response(response_content)
        if not parse_result["success"]:
            result.errors.extend([f"{self.ELEMENT_TYPE} batch {batch_num}: {e}" for e in parse_result.get("errors", [])])
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
        created_by_source: dict[str, dict[str, Any]] = {}

        # Element names come from the candidates' own names (structure), not the LLM
        source_names = {c.node_id: c.name for c in batch}
        candidates_by_id = {c.node_id: c for c in batch}
        for derived in parse_result.get("data", []):
            element_result = build_element(
                derived,
                self.ELEMENT_TYPE,
                batch_enrichments,
                repo_name=repo_name,
                source_names=source_names,
            )

            if not element_result["success"]:
                result.errors.extend(element_result.get("errors", []))
                continue

            element_data = element_result["data"]

            # Confidence gate: skip elements the LLM flagged as poor matches
            confidence = element_data.get("properties", {}).get("confidence", 1.0)
            if confidence < self.MIN_ELEMENT_CONFIDENCE:
                self.logger.debug(
                    "Skipping low-confidence element %s (%.2f < %.2f)",
                    element_data.get("name", "?"),
                    confidence,
                    self.MIN_ELEMENT_CONFIDENCE,
                )
                continue

            if naming is not None:
                self._apply_naming(
                    element_data,
                    candidates_by_id[element_data["properties"]["source"]],
                    naming,
                    llm_query_fn,
                    llm_kwargs,
                    repo_name,
                    taken,
                    structure_names,
                )
            taken.append(element_data["name"])

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
                    created_by_source[source_id] = element_data
            except Exception as e:
                result.errors.append(f"Failed to create {self.ELEMENT_TYPE} element {element_data.get('identifier', 'unknown')}: {e}")

        # Track candidate decisions for this batch
        for c in batch:
            created = created_by_source.get(c.node_id)
            if created is not None:
                # The element created from this candidate (its identifier comes from the
                # structure, not from the identifier the LLM proposed)
                element_id = created["identifier"]
                element_confidence = created.get("properties", {}).get("confidence")

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
                relationship_config=relationship_config,
            )

    def _process_per_candidate(
        self,
        filtered: list[Candidate],
        instruction: str,
        rules: str,
        persona: str,
        llm_query_fn: Callable[..., Any],
        llm_kwargs: dict[str, Any],
        archimate_manager: ArchimateManager,
        graph_manager: GraphManager,
        existing_elements: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        defer_relationships: bool,
        result: GenerationResult,
        repo_name: str,
        structure_names: dict[str, str],
        taken: list[str],
        relationship_config: RelationshipLLMConfig | None = None,
        naming: NamingConfig | None = None,
    ) -> None:
        """Derive elements one candidate per LLM call, then batch relationships.

        Each LLM call sees a single candidate and returns zero or one element.
        This isolates keep/name/doc decisions so one candidate cannot perturb
        the naming of another.
        """
        enrichments = {
            c.node_id: {
                "pagerank": c.pagerank,
                "louvain_community": c.louvain_community,
            }
            for c in filtered
        }

        created_elements: list[dict[str, Any]] = []
        created_by_source: dict[str, dict[str, Any]] = {}
        # Names already taken (``taken``) are checked after each call, never put in a prompt
        # (prompts depend on structure only, so one LLM drift cannot cascade)

        for cand in filtered:
            prompt = build_single_candidate_prompt(
                candidate=cand,
                instruction=instruction,
                rules=rules,
                persona=persona,
            )
            try:
                response = llm_query_fn(prompt, DERIVATION_SCHEMA, **llm_kwargs)
                response_content, error = extract_response_content(response)
                if error:
                    result.errors.append(f"LLM error ({self.ELEMENT_TYPE}/{cand.node_id}): {error}")
                    continue
            except Exception as e:
                result.errors.append(f"LLM error ({self.ELEMENT_TYPE}/{cand.node_id}): {e}")
                continue

            parse_result = parse_derivation_response(response_content)
            if not parse_result["success"]:
                result.errors.extend([f"{self.ELEMENT_TYPE}/{cand.node_id}: {e}" for e in parse_result.get("errors", [])])
                continue

            derived_list = parse_result.get("data", [])
            if not derived_list:
                continue

            # The prompt holds this one candidate, so the element is its element
            derived = {**derived_list[0], "source": cand.node_id}
            element_result = build_element(
                derived,
                self.ELEMENT_TYPE,
                enrichments,
                repo_name=repo_name,
                source_names={cand.node_id: cand.name},
            )
            if not element_result["success"]:
                result.errors.extend(element_result.get("errors", []))
                continue

            element_data = element_result["data"]
            confidence = element_data.get("properties", {}).get("confidence", 1.0)
            if confidence < self.MIN_ELEMENT_CONFIDENCE:
                continue

            if naming is not None:
                self._apply_naming(
                    element_data,
                    cand,
                    naming,
                    llm_query_fn,
                    llm_kwargs,
                    repo_name,
                    taken,
                    structure_names,
                )

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
                created_elements.append(element_data)
                created_by_source[cand.node_id] = element_data
                taken.append(element_data["name"])
            except Exception as e:
                result.errors.append(f"Failed to create {self.ELEMENT_TYPE} element {element_data.get('identifier', 'unknown')}: {e}")

        for c in filtered:
            created = created_by_source.get(c.node_id)
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
                    stage="created" if created else "llm_rejected",
                    became_element=created is not None,
                    element_id=created["identifier"] if created else None,
                    element_confidence=created.get("properties", {}).get("confidence") if created else None,
                )
            )

        if created_elements and existing_elements and not defer_relationships:
            self._derive_relationships(
                batch_elements=created_elements,
                existing_elements=existing_elements,
                llm_query_fn=llm_query_fn,
                temperature=temperature,
                max_tokens=max_tokens,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                result=result,
                relationship_config=relationship_config,
            )

    def _derive_relationships(
        self,
        batch_elements: list[dict[str, Any]],
        existing_elements: list[dict[str, Any]],
        llm_query_fn: Callable[..., Any],
        temperature: float | None,
        max_tokens: int | None,
        graph_manager: GraphManager,
        archimate_manager: ArchimateManager,
        result: GenerationResult,
        relationship_config: RelationshipLLMConfig | None = None,
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
            relationship_config: Relationship config row settings (None skips the LLM pass)
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
            llm_config=relationship_config,
        )

        for rel_data in relationships:
            try:
                # Propagate graph properties from source/target elements for stability analysis
                source_props = _get_element_props(batch_elements, existing_elements, rel_data["source"])
                target_props = _get_element_props(batch_elements, existing_elements, rel_data["target"])

                relationship = Relationship(
                    source=rel_data["source"],
                    target=rel_data["target"],
                    relationship_type=rel_data["relationship_type"],
                    properties={
                        "confidence": rel_data.get("confidence", 0.5),
                        "derived_from": rel_data.get("derived_from"),
                        "source_pagerank": source_props.get("source_pagerank"),
                        "source_kcore": source_props.get("source_kcore_level"),
                        "source_community": source_props.get("source_louvain_community"),
                        "target_pagerank": target_props.get("source_pagerank"),
                        "target_kcore": target_props.get("source_kcore_level"),
                        "target_community": target_props.get("source_louvain_community"),
                    },
                )
                archimate_manager.add_relationship(relationship)
                result.relationships_created += 1
                result.created_relationships.append(rel_data)
            except Exception as e:
                result.errors.append(f"Failed to create {self.ELEMENT_TYPE} relationship: {e}")


class PatternBasedDerivation(ElementDerivationBase):
    """
    Mixin for element modules that use pattern-based filtering.

    Most element modules (10 out of 13) use include/exclude patterns
    from the config database (loaded by the service). This mixin provides the
    default implementation of get_filter_kwargs() to pass those patterns on.

    Modules using this base class receive include_patterns and
    exclude_patterns as kwargs to their filter_candidates() method.

    Subclasses can override PATTERN_MATCH_DEFAULT to control the default
    return value when no patterns match (default is False).
    """

    # Override in subclass to change default behavior when no patterns match
    PATTERN_MATCH_DEFAULT: bool = False

    def matches_patterns(self, name: str, include_patterns: set[str], exclude_patterns: set[str]) -> bool:
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

    def get_filter_kwargs(self, patterns: dict[str, set[str]]) -> dict[str, Any]:
        """
        Pass the step's include/exclude patterns to filter_candidates().

        Args:
            patterns: Include/exclude patterns from config (empty when none are configured),
                and under ``labels`` the labels of the candidates they filter, when the step
                limits them (``params.pattern_labels``)

        Returns:
            Dict with include_patterns and exclude_patterns sets (and pattern_labels when set)
        """
        kwargs: dict[str, Any] = {
            "include_patterns": patterns.get("include", set()),
            "exclude_patterns": patterns.get("exclude", set()),
        }
        if "labels" in patterns:
            kwargs["pattern_labels"] = patterns["labels"]
        return kwargs


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
    MIN_PAGERANK_PERCENTILE: float | None = None  # Scale-independent (e.g., 40.0 = top 60%)
    USE_COMMUNITY_ROOTS: bool = False
    USE_ARTICULATION_POINTS: bool = False
    COMMUNITY_ROOT_RATIO: float = 0.5  # 50% community roots when USE_COMMUNITY_ROOTS=True

    def apply_graph_filtering(
        self,
        candidates: list[Candidate],
        enrichments: dict[str, dict[str, Any]],
        max_candidates: int,
        graph_filter: GraphFilter | None = None,
    ) -> list[Candidate]:
        """
        Apply graph-based filtering to candidates.

        Filters by:
        1. Minimum PageRank threshold (if MIN_PAGERANK set)
        2. The step's k-core threshold (``graph_filter``, from its config)
        3. Community roots (if USE_COMMUNITY_ROOTS set)
        4. Articulation points (if USE_ARTICULATION_POINTS set)

        After filtering, ranks by PageRank and returns top N.

        Args:
            candidates: Pre-filtered candidates (e.g., after pattern matching)
            enrichments: Graph enrichment data
            max_candidates: Maximum candidates to return
            graph_filter: The step's k-core threshold and the labels it applies to (None: none)

        Returns:
            Filtered and ranked candidates
        """
        if not candidates:
            return []

        filtered = list(candidates)

        # Filter by minimum PageRank (absolute threshold)
        if self.MIN_PAGERANK is not None:
            filtered = [c for c in filtered if (c.pagerank or 0) >= self.MIN_PAGERANK]

        # Filter by percentile thresholds (scale-independent)
        # Only apply when percentile data is available (None means prep did not compute it)
        if self.MIN_PAGERANK_PERCENTILE is not None:
            filtered = [c for c in filtered if c.pagerank_percentile is None or c.pagerank_percentile >= self.MIN_PAGERANK_PERCENTILE]
        if graph_filter is not None:
            filtered = [
                c
                for c in filtered
                if (graph_filter.labels is not None and not graph_filter.labels.intersection(c.labels))
                or c.kcore_percentile is None
                or c.kcore_percentile >= graph_filter.min_kcore_percentile
            ]

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
            **kwargs: Additional module-specific parameters; ``pattern_labels`` limits the
                patterns to candidates with one of those labels (others pass);
                ``graph_filter`` is the step's k-core threshold

        Returns:
            Filtered candidates, ranked by PageRank
        """
        if not candidates:
            return []

        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()
        pattern_labels: set[str] | None = kwargs.get("pattern_labels")
        graph_filter: GraphFilter | None = kwargs.get("graph_filter")

        # Step 1: Pattern matching (if patterns configured)
        if include_patterns or exclude_patterns:
            pattern_matched = [
                c
                for c in candidates
                if (pattern_labels is not None and not pattern_labels.intersection(c.labels)) or self.matches_patterns(c.name, include_patterns, exclude_patterns)
            ]
        else:
            # No patterns = include all (subject to graph filtering)
            pattern_matched = list(candidates)

        if not pattern_matched:
            return []

        # Step 2: Apply graph filtering
        filtered = self.apply_graph_filtering(pattern_matched, enrichments, max_candidates, graph_filter)

        return filtered


__all__ = [
    "ElementDerivationBase",
    "PatternBasedDerivation",
    "HybridFilteringMixin",
    "HybridDerivation",
]
