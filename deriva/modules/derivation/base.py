"""
Base utilities for hybrid derivation.

Provides shared functionality for per-element derivation files:
- Graph filtering and enrichment access
- LLM schemas for structured output
- Prompt building for elements and relationships
- Response parsing
- Element and relationship creation helpers
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from deriva.adapters.archimate.models import validate_relationship_rule  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
from deriva.adapters.llm import FailedResponse, ResponseType  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)
from deriva.common import current_timestamp, parse_json_array
from deriva.common.naming import name_key
from deriva.common.types import PipelineResult

if TYPE_CHECKING:
    from deriva.adapters.graph import GraphManager  # noqa: TID251 - known layer exception (see ARCHITECTURE.MD)


def extract_response_content(response: Any) -> tuple[str, str | None]:
    """
    Extract content from an LLM response, handling all response types.

    Args:
        response: LLM response object (LiveResponse, CachedResponse, FailedResponse, or other)

    Returns:
        Tuple of (content, error) where error is None if successful
    """
    # Check for FailedResponse first
    if isinstance(response, FailedResponse):
        return "", f"LLM call failed: {response.error}"

    # Check for response_type attribute (dataclass-based responses)
    if hasattr(response, "response_type"):
        if response.response_type == ResponseType.FAILED:
            error = getattr(response, "error", "Unknown error")
            return "", f"LLM call failed: {error}"

    # Extract content from response
    if hasattr(response, "content"):
        content = response.content
        if not content or not content.strip():
            return "", "LLM returned empty content"
        return content, None

    # Fallback to string representation (shouldn't happen with proper response types)
    content = str(response)
    if not content or not content.strip():
        return "", "LLM returned empty content"
    return content, None


logger = logging.getLogger(__name__)

# Essential properties to include in LLM prompts (reduces token usage).
# These properties provide critical identity/context signals for LLM-based
# derivation decisions. Including only these reduces prompt size by ~60%
# while retaining the most semantically useful information.
#
# Used by Candidate.to_dict(include_props=ESSENTIAL_PROPS)
ESSENTIAL_PROPS: set[str] = {
    "name",
    "description",
    "typeName",
    "filePath",
    "conceptType",
    "conceptName",
    "techName",
    "dependencyName",
    "methodName",
    "className",
    "docstring",
}

# Properties to exclude from cache key computation (cause cache misses if included).
# Note: Currently unused because strip_for_relationship_prompt() is more thorough,
# removing ALL properties except {identifier, name, element_type}.
# Kept for potential future use with partial stripping.
EXCLUDED_FROM_CACHE: set[str] = {"derived_at"}

# Essential fields for relationship derivation (reduces tokens by ~50%)
RELATIONSHIP_ESSENTIAL_FIELDS: set[str] = {"identifier", "name", "element_type"}


def strip_for_relationship_prompt(
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Strip elements to essential fields for relationship derivation.

    For relationship inference, we only need identifier, name, and element_type.
    Documentation and other properties are not needed and add tokens.

    Args:
        elements: List of element dictionaries

    Returns:
        List with only essential fields per element
    """
    return [{k: v for k, v in elem.items() if k in RELATIONSHIP_ESSENTIAL_FIELDS} for elem in elements]


def strip_cache_breaking_props(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Strip properties that would invalidate cache from elements.

    The derived_at timestamp changes every run, causing cache misses
    even when the actual content is identical.

    Note: Currently unused in production. All relationship prompt builders now use
    strip_for_relationship_prompt() which is more thorough (strips to just
    {identifier, name, element_type}). This function is kept for potential future
    use where partial stripping is preferred over complete stripping.

    Args:
        elements: List of element dictionaries

    Returns:
        Copy of elements with cache-breaking properties removed
    """
    result = []
    for elem in elements:
        clean = dict(elem)
        if "properties" in clean and isinstance(clean["properties"], dict):
            clean["properties"] = {k: v for k, v in clean["properties"].items() if k not in EXCLUDED_FROM_CACHE}
        result.append(clean)
    return result


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class Candidate:
    """A candidate node for element derivation with enrichment data."""

    node_id: str
    name: str
    labels: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

    # Graph enrichment data (populated from DuckDB)
    pagerank: float = 0.0
    pagerank_percentile: float | None = None  # None: not computed (0.0 is the bottom rank)
    louvain_community: str | None = None
    kcore_level: int = 0
    kcore_percentile: float | None = None
    is_articulation_point: bool = False
    in_degree: int = 0
    out_degree: int = 0

    def to_dict(self, include_props: set[str] | None = None) -> dict[str, Any]:
        """Convert to dict for JSON serialization in LLM prompts.

        Args:
            include_props: Optional set of property keys to include.
                          If None, includes all properties.
                          Use ESSENTIAL_PROPS for minimal token usage.
        """
        # Filter properties if whitelist provided
        props = self.properties
        if include_props is not None:
            props = {k: v for k, v in self.properties.items() if k in include_props}

        return {
            "id": self.node_id,
            "name": self.name,
            "labels": self.labels,
            "properties": props,
            "pagerank": round(self.pagerank, 4),
            "in_degree": self.in_degree,
            "out_degree": self.out_degree,
        }


@dataclass
class RelationshipRule:
    """A rule defining valid relationships for an element type."""

    target_type: str  # For outbound: target element type. For inbound: source element type
    rel_type: str  # ArchiMate relationship type (Serving, Access, etc.)
    description: str = ""  # Human-readable description


@dataclass(frozen=True)
class ContainmentRule:
    """Ownership decided by containment (relationship config ``params.containment``).

    The nearest element of the container type whose source directory holds the source
    of an element of the contained type is related to it with ``relationship``.
    """

    container: str  # e.g. ApplicationComponent
    contained: str  # e.g. ApplicationInterface
    relationship: str  # e.g. Composition


@dataclass(frozen=True)
class MembershipRule:
    """Relationships from role membership (relationship config ``params.membership``).

    An element of the group type lists its member technologies (``sources``); it is
    related to each element of the member type whose source is one of them, from the
    group to the member when ``from_group``, else from the member to the group.
    """

    group: str  # e.g. Node
    member: str  # e.g. SystemSoftware
    relationship: str  # e.g. Composition
    from_group: bool = True


@dataclass(frozen=True)
class ConfigurationRule:
    """Relationships from configuration files (relationship config ``params.configuration``).

    A provider element serves the consumer element whose directory holds (nearest
    enclosing) a file that configures one of the provider's technologies.
    """

    provider: str  # e.g. TechnologyService
    consumer: str  # e.g. ApplicationComponent
    relationship: str  # e.g. Serving


@dataclass(frozen=True)
class SameNameRule:
    """Relationships between elements whose structural sources carry the same name (``params.same_name``).

    The name of a source is the last part of its node id (a type's name, a concept's key), compared
    by canonical name key after removing any of ``strip_suffixes`` (an implementation suffix).
    """

    source: str  # e.g. DataObject
    target: str  # e.g. BusinessObject
    relationship: str  # e.g. Realization
    strip_suffixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyRule:
    """Dependencies from file imports (relationship config ``params.dependency``).

    The provider serves the consumer when a file of the consumer imports a file of the
    provider, drawn between the two elements just below the deepest element that holds
    both (siblings).
    """

    provider: str  # e.g. ApplicationComponent
    consumer: str  # e.g. ApplicationComponent
    relationship: str  # e.g. Serving


@dataclass(frozen=True)
class RelationshipLLMConfig:
    """Versioned settings for the LLM relationship pass (the relationship phase config row).

    The rules and conventions the LLM follows are config, not code, so a run is
    fully described by its config versions.
    """

    instruction: str  # Conventions and rules inserted into the relationship prompt
    min_confidence: float  # LLM relationships below this confidence are dropped
    persona: str  # Opening line of the relationship prompt; {element_type} is the type just created
    temperature: float | None = None  # Temperature of the consolidated relationship pass (row column)


@dataclass(frozen=True)
class PerCandidateConfig:
    """Per-candidate naming mode for an element type (element config ``params.per_candidate``).

    Each filtered candidate gets its own LLM call that names it, so one
    candidate's name cannot perturb another's and the graph filter alone
    decides inclusion. Small pools fall back to batch mode: their candidates
    are often semantically similar, and batch competition keeps names distinct.
    """

    min_pool: int  # Per-candidate mode engages only for pools at least this large
    rules: str  # Rules text for the single-candidate naming prompt
    persona: str  # Opening line of the single-candidate naming prompt
    # Only candidates carrying an annotation that fully matches this pattern are named per
    # candidate (their annotation decides, whatever the pool size); the others take the batch path
    decorators: str | None = None


@dataclass
class CandidateDecision:
    """Tracks a candidate's journey through derivation for threshold analysis."""

    node_id: str
    name: str
    element_type: str  # e.g., "BusinessProcess", "ApplicationService"

    # Graph metrics at decision time
    pagerank: float = 0.0
    kcore_level: int = 0
    in_degree: int = 0
    out_degree: int = 0
    confidence: float | None = None  # From BusinessConcept if applicable

    # Decision outcome
    stage: str = "queried"  # queried → filtered → sent_to_llm → created | rejected
    became_element: bool = False
    element_id: str | None = None  # If became element
    element_confidence: float | None = None  # LLM confidence if created

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON export."""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "element_type": self.element_type,
            "pagerank": round(self.pagerank, 4),
            "kcore_level": self.kcore_level,
            "in_degree": self.in_degree,
            "out_degree": self.out_degree,
            "confidence": self.confidence,
            "stage": self.stage,
            "became_element": self.became_element,
            "element_id": self.element_id,
            "element_confidence": self.element_confidence,
        }


@dataclass
class GenerationResult:
    """Result from element generation (includes relationships)."""

    success: bool
    elements_created: int = 0
    relationships_created: int = 0
    created_elements: list[dict[str, Any]] = field(default_factory=list)
    created_relationships: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Candidate tracking for threshold optimization
    candidates_queried: int = 0
    candidates_filtered: int = 0
    candidates_to_llm: int = 0
    candidate_decisions: list[CandidateDecision] = field(default_factory=list)


@dataclass
class DerivationResult:
    """Result from element + relationship derivation (mirrors extraction pattern)."""

    success: bool
    elements: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


# =============================================================================
# Graph Enrichment Access
# =============================================================================


def get_enrichments_from_graph(graph_manager: GraphManager) -> dict[str, dict[str, Any]]:
    """
    Get all graph enrichment data from graph node properties.

    The prep phase stores enrichments (PageRank, Louvain, k-core, etc.)
    as properties on graph nodes. This function reads them back, from the
    graph every time: the derivation service reads them once per run and
    passes them to the element steps.

    Args:
        graph_manager: Connected GraphManager instance

    Returns:
        Dict mapping node_id to enrichment data
    """
    # Query the graph
    # Note: Labels are stored as separate items (e.g., ['Graph', 'Directory']),
    # not as concatenated strings (e.g., 'Graph:Directory').
    query = """
        MATCH (n)
        WHERE 'Graph' IN labels(n)
          AND n.active = true
        RETURN n.id as node_id,
               n.pagerank as pagerank,
               n.pagerank_percentile as pagerank_percentile,
               n.louvain_community as louvain_community,
               n.kcore_level as kcore_level,
               n.kcore_percentile as kcore_percentile,
               n.is_articulation_point as is_articulation_point,
               n.in_degree as in_degree,
               n.out_degree as out_degree
    """
    try:
        rows = graph_manager.query(query)
        enrichments = {
            row["node_id"]: {
                "pagerank": row.get("pagerank") or 0.0,
                "pagerank_percentile": row.get("pagerank_percentile"),
                "louvain_community": row.get("louvain_community"),
                "kcore_level": row.get("kcore_level") or 0,
                "kcore_percentile": row.get("kcore_percentile"),
                "is_articulation_point": row.get("is_articulation_point") or False,
                "in_degree": row.get("in_degree") or 0,
                "out_degree": row.get("out_degree") or 0,
            }
            for row in rows
            if row.get("node_id")
        }
        return enrichments
    except Exception as e:
        logger.warning("Failed to get enrichments from graph: %s", e)
        return {}


# Backward compatibility alias (deprecated)
def get_enrichments(engine: Any) -> dict[str, dict[str, Any]]:
    """Deprecated: Use get_enrichments_from_graph() instead."""
    logger.warning("get_enrichments(engine) is deprecated - enrichments should be read from the graph")
    return {}


def enrich_candidate(candidate: Candidate, enrichments: dict[str, dict[str, Any]]) -> None:
    """Add enrichment data to a candidate in-place."""
    data = enrichments.get(candidate.node_id, {})
    candidate.pagerank = data.get("pagerank", 0.0)
    candidate.pagerank_percentile = data.get("pagerank_percentile")
    candidate.louvain_community = data.get("louvain_community")
    candidate.kcore_level = data.get("kcore_level", 0)
    candidate.kcore_percentile = data.get("kcore_percentile")
    candidate.is_articulation_point = data.get("is_articulation_point", False)
    candidate.in_degree = data.get("in_degree", 0)
    candidate.out_degree = data.get("out_degree", 0)


# =============================================================================
# Graph Filtering
# =============================================================================


def filter_by_pagerank(
    candidates: list[Candidate],
    top_n: int | None = None,
    percentile: float | None = None,
    min_pagerank: float | None = None,
) -> list[Candidate]:
    """
    Filter candidates by PageRank score.

    Args:
        candidates: List of candidates with pagerank populated
        top_n: Keep top N candidates
        percentile: Keep top X percentile (0-100)
        min_pagerank: Minimum absolute PageRank score to include (applied first)

    Returns:
        Filtered and sorted candidates (highest pagerank first)
    """
    # Apply minimum threshold first (removes low-importance nodes)
    if min_pagerank is not None:
        candidates = [c for c in candidates if c.pagerank >= min_pagerank]

    sorted_candidates = sorted(candidates, key=lambda c: -c.pagerank)

    if top_n is not None:
        return sorted_candidates[:top_n]

    if percentile is not None:
        cutoff_idx = max(1, int(len(sorted_candidates) * (100 - percentile) / 100))
        return sorted_candidates[:cutoff_idx]

    return sorted_candidates


def filter_by_labels(
    candidates: list[Candidate],
    include_labels: list[str] | None = None,
    exclude_labels: list[str] | None = None,
) -> list[Candidate]:
    """
    Filter candidates by node labels.

    Args:
        candidates: List of candidates
        include_labels: Only keep candidates with ANY of these labels
        exclude_labels: Remove candidates with ANY of these labels
    """
    result = candidates

    if include_labels:
        result = [c for c in result if any(lbl in c.labels for lbl in include_labels)]

    if exclude_labels:
        result = [c for c in result if not any(lbl in c.labels for lbl in exclude_labels)]

    return result


def filter_by_community(
    candidates: list[Candidate],
    community_ids: set[str] | None = None,
    only_roots: bool = False,
) -> list[Candidate]:
    """
    Filter candidates by Louvain community.

    Args:
        candidates: List of candidates
        community_ids: Only keep candidates in these communities
        only_roots: Only keep community root nodes (node_id == louvain_community)
    """
    result = candidates

    if community_ids is not None:
        result = [c for c in result if c.louvain_community in community_ids]

    if only_roots:
        result = [c for c in result if c.node_id == c.louvain_community]

    return result


def get_community_roots(candidates: list[Candidate]) -> list[Candidate]:
    """Get candidates that are Louvain community roots."""
    return [c for c in candidates if c.node_id == c.louvain_community]


def get_articulation_points(candidates: list[Candidate]) -> list[Candidate]:
    """Get candidates that are articulation points (bridge nodes)."""
    return [c for c in candidates if c.is_articulation_point]


# =============================================================================
# Token Estimation & Context Limiting (Phase 4)
# =============================================================================

# Default model context limits (tokens) - conservative estimates.
# Used by get_model_context_limit() to determine maximum prompt size
# and by check_prompt_size() to warn when approaching limits.
#
# Values are intentionally conservative to leave room for response tokens.
# Actual model limits may be higher, but staying within these ensures reliability.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1-mini": 128000,
    "gpt-4.1-nano": 128000,
    "claude-3": 200000,
    "claude-haiku": 200000,
    "claude-sonnet": 200000,
    "claude-opus": 200000,
    "devstral": 32000,
    "mistral": 32000,
    "default": 16000,  # Conservative default
}


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a text string.

    Uses a simple heuristic: ~4 characters per token for English text.
    This is accurate within ~10% for most LLM tokenizers.

    Args:
        text: Text to estimate tokens for

    Returns:
        Estimated token count
    """
    return len(text) // 4


def get_model_context_limit(model_name: str) -> int:
    """
    Get the context limit for a model.

    Args:
        model_name: Model identifier (e.g., "gpt-4o-mini", "claude-sonnet")

    Returns:
        Context limit in tokens
    """
    model_lower = model_name.lower()
    for key, limit in MODEL_CONTEXT_LIMITS.items():
        if key in model_lower:
            return limit
    return MODEL_CONTEXT_LIMITS["default"]


def limit_existing_elements(
    elements: list[dict[str, Any]],
    max_elements: int = 50,
    sort_by_confidence: bool = True,
) -> list[dict[str, Any]]:
    """
    Limit existing elements to top-N by importance.

    When deriving relationships, we don't need ALL existing elements -
    just the most important ones. This reduces tokens by up to 80%.

    Args:
        elements: List of element dictionaries
        max_elements: Maximum number of elements to keep (default 50)
        sort_by_confidence: If True, sort by confidence descending (default True)

    Returns:
        Filtered list of elements
    """
    if len(elements) <= max_elements:
        return elements

    if sort_by_confidence:
        # Sort by confidence (from properties), highest first
        sorted_elements = sorted(
            elements,
            key=lambda e: e.get("properties", {}).get("confidence", 0.5),
            reverse=True,
        )
        return sorted_elements[:max_elements]

    # Simple truncation if not sorting
    return elements[:max_elements]


def stratified_sample_elements(
    elements: list[dict[str, Any]],
    max_per_type: int = 10,
    relevant_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Sample elements with stratification by element type.

    Ensures representation from each relevant element type while
    limiting total count. Improves relationship diversity.

    Args:
        elements: List of element dictionaries
        max_per_type: Maximum elements per type (default 10)
        relevant_types: Only include these types (None = all types)

    Returns:
        Stratified sample of elements
    """
    if not elements:
        return []

    # Group by element_type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for elem in elements:
        etype = elem.get("element_type", "Unknown")
        if relevant_types is None or etype in relevant_types:
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append(elem)

    # Take the top max_per_type of each type by graph importance (the pagerank of the source
    # node, stored by build_element as source_pagerank), then identifier: structure only,
    # never the LLM-written confidence
    sampled = []
    for etype in sorted(by_type):
        sorted_type = sorted(
            by_type[etype],
            key=lambda e: (-(e.get("properties", {}).get("source_pagerank") or 0.0), e.get("identifier", "")),
        )
        sampled.extend(sorted_type[:max_per_type])

    return sampled


def normalize_name_for_matching(name: str) -> set[str]:
    """
    Normalize an element name into a set of meaningful words for matching.

    Handles various naming conventions:
    - CamelCase: "InvoiceManagement" -> {"invoice", "management"}
    - snake_case: "invoice_management" -> {"invoice", "management"}
    - Spaces: "Invoice Management" -> {"invoice", "management"}

    Returns:
        Set of lowercase words (excluding common stop words)
    """
    import re

    # Common stop words to exclude
    stop_words = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "on",
        "by",
        "with",
        "is",
        "be",
        "data",
        "object",
        "service",
        "process",
        "function",
        "actor",
        "component",
        "interface",
    }

    if not name:
        return set()

    # Split CamelCase
    words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    # Replace underscores and hyphens with spaces
    words = re.sub(r"[_\-]", " ", words)
    # Split on spaces and lowercase
    word_list = [w.lower().strip() for w in words.split() if w.strip()]
    # Filter short words and stop words
    return {w for w in word_list if len(w) > 2 and w not in stop_words}


def names_match_for_relationship(source_name: str, target_name: str, threshold: float = 0.3) -> bool:
    """
    Determine if two element names are semantically related.

    Uses word overlap to determine if elements should be related.
    This is a deterministic function - same inputs always produce same output.

    Args:
        source_name: Name of source element
        target_name: Name of target element
        threshold: Minimum overlap ratio (default 0.3 = 30% word overlap)

    Returns:
        True if names are related enough to warrant a relationship
    """
    source_words = normalize_name_for_matching(source_name)
    target_words = normalize_name_for_matching(target_name)

    if not source_words or not target_words:
        return False

    # Calculate overlap
    overlap = source_words & target_words
    if not overlap:
        return False

    # Use Jaccard-like similarity (overlap / smaller set)
    min_size = min(len(source_words), len(target_words))
    similarity = len(overlap) / min_size

    return similarity >= threshold


def extract_file_path_from_source(source_id: str | None) -> str | None:
    """
    Extract the file path from a source node ID.

    Source IDs have formats like:
    - method_flask_invoice_generator_models.py_Positions_delete
    - file_flask_invoice_generator_.flaskenv
    - typedef_flask_invoice_generator_forms.py_InvoiceForm

    Returns:
        The file name (e.g., "models.py", ".flaskenv") or None
    """
    if not source_id:
        return None

    # Common patterns: look for file extensions
    import re

    # Match .py, .js, .ts, .json, .yaml, .yml, .md, .txt, .env, etc.
    match = re.search(r"_([^_]+\.[a-zA-Z0-9]+)(?:_|$)", source_id)
    if match:
        return match.group(1)

    # Handle dotfiles like .flaskenv, .gitignore
    match = re.search(r"_(\.[a-zA-Z0-9]+)(?:_|$)", source_id)
    if match:
        return match.group(1)

    return None


def elements_share_source_file(elem1: dict[str, Any], elem2: dict[str, Any]) -> bool:
    """
    Check if two elements are derived from the same source file.

    This provides a strong signal for relationship derivation since
    elements from the same file are likely related.

    Args:
        elem1: First element dict
        elem2: Second element dict

    Returns:
        True if both elements have the same source file
    """
    source1 = elem1.get("properties", {}).get("source")
    source2 = elem2.get("properties", {}).get("source")

    if not source1 or not source2:
        return False

    file1 = extract_file_path_from_source(source1)
    file2 = extract_file_path_from_source(source2)

    if not file1 or not file2:
        return False

    return file1 == file2


def get_community_from_element(element: dict[str, Any]) -> str | None:
    """
    Extract the Louvain community ID from an element's properties.

    The community is stored during element creation from the source node's
    louvain_community property.

    Args:
        element: Element dictionary with properties

    Returns:
        Community ID string or None if not available
    """
    props = element.get("properties", {})
    return props.get("source_community")


# Sharing a community shows that elements belong together, not that data flows
# between them, that one triggers the other, or that one aggregates the other
_NOT_FROM_CO_MEMBERSHIP = frozenset({"Flow", "Triggering", "Aggregation"})


def derive_community_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
) -> list[dict[str, Any]]:
    """
    Create relationships between elements in the same Louvain community.

    Elements from the same community are structurally related in the source
    code - they should be architecturally related in ArchiMate.

    This is Tier 1a of the graph-first relationship derivation approach.

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type

    Returns:
        List of community-based relationship dicts with confidence 0.95
    """
    relationships = []
    created_pairs: set[tuple[str, str, str]] = set()

    for new_elem in new_elements:
        new_id = new_elem.get("identifier", "")
        new_community = get_community_from_element(new_elem)

        if not new_id or not new_community:
            continue

        # Find existing elements in SAME community
        same_community = [e for e in existing_elements if get_community_from_element(e) == new_community]

        if not same_community:
            continue

        # Process OUTBOUND rules (FROM new TO existing in same community)
        new_type = new_elem.get("element_type", "")
        for rule in outbound_rules:
            if rule.rel_type in _NOT_FROM_CO_MEMBERSHIP:
                continue
            # Validate rule against ArchiMate metamodel
            is_valid, msg = validate_relationship_rule(new_type, rule.rel_type, rule.target_type)
            if not is_valid:
                logger.warning(
                    "Skipping invalid OUTBOUND rule: %s -[%s]-> %s: %s",
                    new_type,
                    rule.rel_type,
                    rule.target_type,
                    msg,
                )
                continue

            targets = [e for e in same_community if e.get("element_type") == rule.target_type]

            for target in targets:
                target_id = target.get("identifier", "")
                if not target_id:
                    continue

                pair_key = (new_id, target_id, rule.rel_type)
                if pair_key not in created_pairs:
                    # For Composition, check if reverse relationship would create a cycle
                    if rule.rel_type == "Composition":
                        reverse_key = (target_id, new_id, "Composition")
                        if reverse_key in created_pairs:
                            # Skip: creating this would form a bidirectional cycle
                            continue

                    created_pairs.add(pair_key)
                    relationships.append(
                        {
                            "source": new_id,
                            "target": target_id,
                            "relationship_type": rule.rel_type,
                            "confidence": 0.95,
                            "derived_from": "community",
                        }
                    )

        # Process INBOUND rules (FROM existing in same community TO new)
        for rule in inbound_rules:
            if rule.rel_type in _NOT_FROM_CO_MEMBERSHIP:
                continue
            # Validate rule against ArchiMate metamodel
            # For INBOUND: source=rule.target_type, target=new_type
            is_valid, msg = validate_relationship_rule(rule.target_type, rule.rel_type, new_type)
            if not is_valid:
                logger.warning(
                    "Skipping invalid INBOUND rule: %s -[%s]-> %s: %s",
                    rule.target_type,
                    rule.rel_type,
                    new_type,
                    msg,
                )
                continue

            sources = [e for e in same_community if e.get("element_type") == rule.target_type]

            for source in sources:
                source_id = source.get("identifier", "")
                if not source_id:
                    continue

                pair_key = (source_id, new_id, rule.rel_type)
                if pair_key not in created_pairs:
                    # For Composition, check if reverse relationship would create a cycle
                    if rule.rel_type == "Composition":
                        reverse_key = (new_id, source_id, "Composition")
                        if reverse_key in created_pairs:
                            # Skip: creating this would form a bidirectional cycle
                            continue

                    created_pairs.add(pair_key)
                    relationships.append(
                        {
                            "source": source_id,
                            "target": new_id,
                            "relationship_type": rule.rel_type,
                            "confidence": 0.95,
                            "derived_from": "community",
                        }
                    )

    logger.debug("Community-based derivation: %d relationships", len(relationships))
    return relationships


def derive_neighbor_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    graph_manager: GraphManager,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
) -> list[dict[str, Any]]:
    """
    Create relationships between elements whose source nodes are direct
    neighbors in the graph (1-hop).

    This is Tier 1b of the graph-first relationship derivation approach.

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        graph_manager: GraphManager for querying graph structure
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type

    Returns:
        List of neighbor-based relationship dicts with confidence 0.90
    """
    relationships = []
    created_pairs: set[tuple[str, str, str]] = set()

    # Build lookup: source_id -> element for existing elements
    existing_by_source: dict[str, dict[str, Any]] = {}
    for elem in existing_elements:
        source_id = elem.get("properties", {}).get("source")
        if source_id:
            existing_by_source[source_id] = elem

    for new_elem in new_elements:
        new_id = new_elem.get("identifier", "")
        source_id = new_elem.get("properties", {}).get("source")

        if not new_id or not source_id:
            continue

        try:
            # Query graph for direct neighbors (both directions)
            neighbors = graph_manager.query(
                """
                MATCH (src)-[]-(neighbor)
                WHERE src.id = $source_id
                RETURN DISTINCT neighbor.id as neighbor_id
                """,
                {"source_id": source_id},
            )

            neighbor_ids = {n["neighbor_id"] for n in neighbors if n.get("neighbor_id")}

            # Find existing elements with source in neighbor set
            for neighbor_source_id in neighbor_ids:
                existing = existing_by_source.get(neighbor_source_id)
                if not existing:
                    continue

                existing_id = existing.get("identifier", "")
                existing_type = existing.get("element_type", "")
                new_type = new_elem.get("element_type", "")

                # Check OUTBOUND rules
                for rule in outbound_rules:
                    if existing_type == rule.target_type:
                        # Validate rule against ArchiMate metamodel
                        is_valid, _ = validate_relationship_rule(new_type, rule.rel_type, rule.target_type)
                        if not is_valid:
                            continue

                        pair_key = (new_id, existing_id, rule.rel_type)
                        if pair_key not in created_pairs:
                            created_pairs.add(pair_key)
                            relationships.append(
                                {
                                    "source": new_id,
                                    "target": existing_id,
                                    "relationship_type": rule.rel_type,
                                    "confidence": 0.90,
                                    "derived_from": "graph_neighbor",
                                }
                            )

                # Check INBOUND rules
                for rule in inbound_rules:
                    if existing_type == rule.target_type:
                        # Validate rule against ArchiMate metamodel
                        is_valid, _ = validate_relationship_rule(rule.target_type, rule.rel_type, new_type)
                        if not is_valid:
                            continue

                        pair_key = (existing_id, new_id, rule.rel_type)
                        if pair_key not in created_pairs:
                            created_pairs.add(pair_key)
                            relationships.append(
                                {
                                    "source": existing_id,
                                    "target": new_id,
                                    "relationship_type": rule.rel_type,
                                    "confidence": 0.90,
                                    "derived_from": "graph_neighbor",
                                }
                            )

        except Exception as e:
            logger.warning("Error querying graph neighbors for %s: %s", source_id, e)
            continue

    logger.debug("Graph neighbor derivation: %d relationships", len(relationships))
    return relationships


# =============================================================================
# Edge-type to ArchiMate relationship mapping
# =============================================================================
# Uses ArchiMate 3.2 metamodel constraints from models.py:
# - Flow: Behavior → Behavior only
# - Access: Behavior/Structure → Passive only (DataObject, BusinessObject)
# - Serving: general dependency between elements
EDGE_RELATIONSHIP_MAP: dict[str, dict[str, tuple[str, float]]] = {
    # Graph edge type -> {target element type -> (ArchiMate relationship, confidence)}
    "CALLS": {
        "ApplicationService": ("Serving", 0.92),  # Service dependency
        "ApplicationInterface": (
            "Serving",
            0.90,
        ),  # Interface is Structure, not Behavior
        "ApplicationComponent": ("Serving", 0.88),
    },
    "IMPORTS": {
        "DataObject": ("Access", 0.90),  # Access is valid for Passive targets
        "BusinessObject": ("Access", 0.88),  # Access is valid for Passive targets
        "ApplicationComponent": ("Serving", 0.85),  # Serving for non-Passive
        "TechnologyService": ("Serving", 0.83),  # Serving for non-Passive
    },
    "USES": {
        "TechnologyService": ("Serving", 0.93),
        "SystemSoftware": ("Serving", 0.91),
        "Node": ("Serving", 0.88),
    },
}


def derive_edge_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    graph_manager: GraphManager,
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
) -> list[dict[str, Any]]:
    """
    Derive relationships by walking specific edge types (CALLS, IMPORTS, USES).

    This is Tier 1.5 of the graph-first relationship derivation approach.
    It provides higher confidence than generic neighbor relationships because
    it uses explicit code dependency information.

    Edge type mapping (per ArchiMate 3.2 metamodel):
    - CALLS edges -> Serving relationships (service/component dependencies)
    - IMPORTS edges -> Access (for Passive targets) or Serving (for others)
    - USES edges -> Serving relationships (technology dependencies)

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        graph_manager: GraphManager for querying graph structure
        element_type: The ArchiMate element type just created
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type

    Returns:
        List of edge-based relationship dicts with confidence 0.85-0.95
    """
    relationships = []
    created_pairs: set[tuple[str, str, str]] = set()

    # Build lookup: source_id -> element for existing elements
    existing_by_source: dict[str, dict[str, Any]] = {}
    for elem in existing_elements:
        source_id = elem.get("properties", {}).get("source")
        if source_id:
            existing_by_source[source_id] = elem

    # Determine which edge types to query based on element type
    edge_types_to_query: list[str] = []
    if element_type in (
        "ApplicationService",
        "ApplicationInterface",
        "ApplicationComponent",
    ):
        edge_types_to_query.append("CALLS")
    if element_type in ("DataObject", "ApplicationComponent"):
        edge_types_to_query.append("IMPORTS")
    if element_type in ("TechnologyService", "SystemSoftware", "Node"):
        edge_types_to_query.append("USES")

    if not edge_types_to_query:
        return relationships

    for new_elem in new_elements:
        new_id = new_elem.get("identifier", "")
        source_id = new_elem.get("properties", {}).get("source")

        if not new_id or not source_id:
            continue

        for edge_type in edge_types_to_query:
            try:
                # Query graph for nodes connected via specific edge type
                # Check both directions: source->target and target->source
                connected_nodes = graph_manager.query(
                    f"""
                    MATCH (src)-[r:`Graph:{edge_type}`]->(target)
                    WHERE src.id = $source_id AND target.active = true
                    RETURN DISTINCT target.id as connected_id, 'outbound' as direction
                    UNION
                    MATCH (src)<-[r:`Graph:{edge_type}`]-(source_node)
                    WHERE src.id = $source_id AND source_node.active = true
                    RETURN DISTINCT source_node.id as connected_id, 'inbound' as direction
                    """,
                    {"source_id": source_id},
                )

                for conn in connected_nodes:
                    connected_id = conn.get("connected_id")
                    direction = conn.get("direction")

                    if not connected_id:
                        continue

                    existing = existing_by_source.get(connected_id)
                    if not existing:
                        continue

                    existing_elem_id = existing.get("identifier", "")
                    existing_type = existing.get("element_type", "")

                    # Look up relationship mapping for this edge type and target type
                    edge_mapping = EDGE_RELATIONSHIP_MAP.get(edge_type, {})
                    if existing_type not in edge_mapping:
                        continue

                    rel_type, confidence = edge_mapping[existing_type]

                    # Verify this relationship type is allowed by the rules
                    valid_outbound = any(r.target_type == existing_type and r.rel_type == rel_type for r in outbound_rules)
                    valid_inbound = any(r.target_type == existing_type and r.rel_type == rel_type for r in inbound_rules)

                    if direction == "outbound" and valid_outbound:
                        pair_key = (new_id, existing_elem_id, rel_type)
                        if pair_key not in created_pairs:
                            created_pairs.add(pair_key)
                            relationships.append(
                                {
                                    "source": new_id,
                                    "target": existing_elem_id,
                                    "relationship_type": rel_type,
                                    "confidence": confidence,
                                    "derived_from": f"{edge_type.lower()}_edge",
                                }
                            )
                    elif direction == "inbound" and valid_inbound:
                        pair_key = (existing_elem_id, new_id, rel_type)
                        if pair_key not in created_pairs:
                            created_pairs.add(pair_key)
                            relationships.append(
                                {
                                    "source": existing_elem_id,
                                    "target": new_id,
                                    "relationship_type": rel_type,
                                    "confidence": confidence,
                                    "derived_from": f"{edge_type.lower()}_edge",
                                }
                            )

            except Exception as e:
                logger.warning("Error querying %s edges for %s: %s", edge_type, source_id, e)
                continue

    logger.debug(
        "Edge-type derivation (%s): %d relationships",
        ", ".join(edge_types_to_query),
        len(relationships),
    )
    return relationships


def derive_deterministic_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
) -> list[dict[str, Any]]:
    """
    Derive relationships deterministically from rules without LLM.

    Uses two matching strategies:
    1. Name matching - elements with overlapping semantic words
    2. File proximity - elements derived from the same source file

    This runs BEFORE LLM derivation to ensure core relationships are stable.

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        element_type: The ArchiMate element type just created
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type

    Returns:
        List of deterministically derived relationship dicts
    """
    relationships = []
    created_pairs: set[tuple[str, str, str]] = set()  # (source, target, type)

    # Relationship types that benefit from lower threshold (more connections)
    # Flow relationships are about data/control flow, not ownership
    loose_match_types = {"Flow", "Triggering", "Access"}

    for new_elem in new_elements:
        new_id = new_elem.get("identifier", "")
        new_name = new_elem.get("name", "")

        if not new_id or not new_name:
            continue

        # Process OUTBOUND rules (FROM new TO existing)
        for rule in outbound_rules:
            # Validate rule against ArchiMate metamodel
            is_valid, msg = validate_relationship_rule(element_type, rule.rel_type, rule.target_type)
            if not is_valid:
                logger.warning(
                    "Skipping invalid OUTBOUND rule: %s -[%s]-> %s: %s",
                    element_type,
                    rule.rel_type,
                    rule.target_type,
                    msg,
                )
                continue

            targets = [e for e in existing_elements if e.get("element_type") == rule.target_type]

            # Use lower threshold for Flow-like relationships
            threshold = 0.15 if rule.rel_type in loose_match_types else 0.3

            for target in targets:
                target_id = target.get("identifier", "")
                target_name = target.get("name", "")

                if not target_id or not target_name:
                    continue

                # Strategy 1: Name matching (with relationship-specific threshold)
                name_match = names_match_for_relationship(new_name, target_name, threshold=threshold)

                # Strategy 2: File proximity (elements from same source file)
                file_match = elements_share_source_file(new_elem, target)

                if name_match or file_match:
                    pair_key = (new_id, target_id, rule.rel_type)
                    if pair_key not in created_pairs:
                        created_pairs.add(pair_key)
                        # Higher confidence for name match, slightly lower for file match only
                        confidence = 0.95 if name_match else 0.85
                        relationships.append(
                            {
                                "source": new_id,
                                "target": target_id,
                                "relationship_type": rule.rel_type,
                                "confidence": confidence,
                                "derived_from": "rule",
                            }
                        )

        # Process INBOUND rules (FROM existing TO new)
        for rule in inbound_rules:
            # Validate rule against ArchiMate metamodel
            # For INBOUND: source=rule.target_type, target=element_type
            is_valid, msg = validate_relationship_rule(rule.target_type, rule.rel_type, element_type)
            if not is_valid:
                logger.warning(
                    "Skipping invalid INBOUND rule: %s -[%s]-> %s: %s",
                    rule.target_type,
                    rule.rel_type,
                    element_type,
                    msg,
                )
                continue

            sources = [e for e in existing_elements if e.get("element_type") == rule.target_type]

            # Use lower threshold for Flow-like relationships
            threshold = 0.15 if rule.rel_type in loose_match_types else 0.3

            for source in sources:
                source_id = source.get("identifier", "")
                source_name = source.get("name", "")

                if not source_id or not source_name:
                    continue

                # Strategy 1: Name matching
                name_match = names_match_for_relationship(source_name, new_name, threshold=threshold)

                # Strategy 2: File proximity
                file_match = elements_share_source_file(source, new_elem)

                if name_match or file_match:
                    pair_key = (source_id, new_id, rule.rel_type)
                    if pair_key not in created_pairs:
                        created_pairs.add(pair_key)
                        confidence = 0.95 if name_match else 0.85
                        relationships.append(
                            {
                                "source": source_id,
                                "target": new_id,
                                "relationship_type": rule.rel_type,
                                "confidence": confidence,
                                "derived_from": "rule",
                            }
                        )

    logger.debug(
        "Deterministic derivation: %d relationships for %s",
        len(relationships),
        element_type,
    )
    return relationships


def get_connected_source_ids(
    graph_manager: GraphManager,
    source_ids: list[str],
    max_hops: int = 2,
) -> set[str]:
    """
    Get graph node IDs connected to the given source nodes.

    Queries the graph for nodes within max_hops of the source nodes.
    This enables graph-aware filtering of existing elements.

    Args:
        graph_manager: GraphManager instance for querying
        source_ids: List of source node IDs to find connections for
        max_hops: Maximum path length to consider (default 2)

    Returns:
        Set of connected node IDs (includes source_ids)
    """
    if not source_ids or not graph_manager:
        return set(source_ids) if source_ids else set()

    # Build Cypher query for neighbors within max_hops
    # Using variable-length path pattern for efficiency
    query = f"""
        MATCH (n)
        WHERE n.id IN $source_ids
        MATCH (n)-[*1..{int(max_hops)}]-(neighbor)
        WHERE neighbor.active = true OR neighbor.active IS NULL
        RETURN DISTINCT neighbor.id as id
    """

    try:
        results = graph_manager.query(query, {"source_ids": source_ids})
        connected = {row["id"] for row in results if row.get("id")}
        # Include original source IDs
        connected.update(source_ids)
        return connected
    except Exception as e:
        logger.warning("Graph query for connected nodes failed: %s", e)
        # Fall back to just the source IDs
        return set(source_ids)


def filter_by_graph_proximity(
    elements: list[dict[str, Any]],
    connected_ids: set[str],
) -> list[dict[str, Any]]:
    """
    Filter elements to only those with source nodes in the connected set.

    This implements graph-aware pre-filtering: only include elements
    that are graph neighbors of the new elements being processed.

    Args:
        elements: List of element dictionaries with properties.source
        connected_ids: Set of connected graph node IDs

    Returns:
        Filtered list of elements with graph proximity
    """
    if not connected_ids:
        return elements

    filtered = []
    for elem in elements:
        source = elem.get("properties", {}).get("source")
        if source and source in connected_ids:
            filtered.append(elem)

    return filtered


def check_prompt_size(
    prompt: str,
    model_name: str = "default",
    warn_threshold: float = 0.8,
) -> tuple[int, bool]:
    """
    Check if prompt size is within model limits.

    Args:
        prompt: The prompt string to check
        model_name: Model name for context limit lookup
        warn_threshold: Fraction of limit to warn at (default 0.8 = 80%)

    Returns:
        Tuple of (estimated_tokens, is_over_threshold)
    """
    estimated = estimate_tokens(prompt)
    limit = get_model_context_limit(model_name)
    threshold = int(limit * warn_threshold)

    if estimated > threshold:
        logger.warning(
            "Prompt size %d tokens exceeds %d%% of %s limit (%d)",
            estimated,
            int(warn_threshold * 100),
            model_name,
            limit,
        )
        return estimated, True

    return estimated, False


# =============================================================================
# Batching
# =============================================================================


def calculate_dynamic_batch_size(
    num_candidates: int,
    min_batch: int = 10,
    max_batch: int = 25,
) -> int:
    """
    Calculate optimal batch size based on candidate count.

    For small candidate sets, use larger batches to reduce LLM calls.
    For large sets, use moderate batches to balance context and calls.

    Args:
        num_candidates: Total number of candidates
        min_batch: Minimum batch size (default 10)
        max_batch: Maximum batch size (default 25)

    Returns:
        Calculated batch size
    """
    if num_candidates <= min_batch:
        return num_candidates  # Single batch for small sets
    # Use ~3-4 batches for most datasets
    dynamic = max(min_batch, num_candidates // 3)
    return min(max_batch, dynamic)


def adjust_batch_for_tokens(
    current_batch_size: int,
    estimated_tokens: int,
    model_name: str = "default",
    target_utilization: float = 0.7,
    min_batch: int = 5,
) -> int:
    """
    Adjust batch size based on estimated token count.

    If the estimated tokens exceed target utilization of model limit,
    reduce batch size proportionally to fit within limits.

    Args:
        current_batch_size: Current batch size
        estimated_tokens: Estimated tokens for current batch
        model_name: Model name for context limit lookup
        target_utilization: Target fraction of context limit (default 0.7 = 70%)
        min_batch: Minimum batch size (default 5)

    Returns:
        Adjusted batch size
    """
    limit = get_model_context_limit(model_name)
    target = int(limit * target_utilization)

    if estimated_tokens <= target:
        return current_batch_size

    # Scale down proportionally
    scale_factor = target / estimated_tokens
    adjusted = int(current_batch_size * scale_factor)

    # Clamp to minimum
    adjusted = max(min_batch, adjusted)

    if adjusted < current_batch_size:
        logger.info(
            "Reducing batch size %d -> %d due to token limit (est: %d, target: %d)",
            current_batch_size,
            adjusted,
            estimated_tokens,
            target,
        )

    return adjusted


def batch_candidates(
    candidates: list[Candidate],
    batch_size: int | None = None,
    group_by_community: bool = True,
) -> list[list[Candidate]]:
    """
    Split candidates into batches for LLM processing.

    Args:
        candidates: List of candidates to batch
        batch_size: Maximum items per batch. If None, uses dynamic sizing
                   based on candidate count (recommended).
        group_by_community: If True, group candidates by Louvain community first,
                           keeping related nodes together (default True)

    Returns:
        List of batches
    """
    if not candidates:
        return []

    # Use dynamic batch sizing if not specified
    if batch_size is None:
        batch_size = calculate_dynamic_batch_size(len(candidates))

    if not group_by_community:
        # Simple sequential batching
        batches = []
        for i in range(0, len(candidates), batch_size):
            batches.append(candidates[i : i + batch_size])
        return batches

    # Group by Louvain community first for coherent batches
    by_community: dict[str | None, list[Candidate]] = {}
    for c in candidates:
        comm = c.louvain_community
        if comm not in by_community:
            by_community[comm] = []
        by_community[comm].append(c)

    # Build batches keeping communities together when possible
    batches: list[list[Candidate]] = []
    current_batch: list[Candidate] = []

    for community_candidates in by_community.values():
        for c in community_candidates:
            current_batch.append(c)
            if len(current_batch) >= batch_size:
                batches.append(current_batch)
                current_batch = []

    if current_batch:
        batches.append(current_batch)

    return batches


# =============================================================================
# Query Helpers
# =============================================================================


def query_candidates(
    graph_manager: GraphManager,
    cypher_query: str,
    enrichments: dict[str, dict[str, Any]] | None = None,
) -> list[Candidate]:
    """
    Execute a Cypher query and return enriched candidates.

    The query should return: id, name, labels, properties
    """
    results = graph_manager.query(cypher_query)
    candidates = []

    for row in results:
        candidate = Candidate(
            node_id=row.get("id", ""),
            name=row.get("name", ""),
            labels=row.get("labels", []),
            properties=row.get("properties", {}),
        )
        if enrichments:
            enrich_candidate(candidate, enrichments)
        candidates.append(candidate)

    # The graph's result order is unspecified: every later step sees the candidates in node id order
    candidates.sort(key=lambda c: c.node_id)
    return candidates


def compute_candidate_strength(candidates: list[Candidate]) -> dict[str, Any]:
    """Compute graph-derived strength signals for a candidate set.

    Used by the abstention mechanism to inform the LLM whether the candidate
    evidence is strong enough to warrant creating elements. All signals come
    from the graph (count, pagerank percentile, kcore percentile) — no
    repo-specific inputs.

    Returns a dict with:
        count: number of candidates
        avg_pagerank_percentile: mean pagerank percentile (0-100)
        avg_kcore_percentile: mean kcore percentile (0-100)
        strength_label: 'strong', 'moderate', 'weak', or 'minimal'
    """
    if not candidates:
        return {
            "count": 0,
            "avg_pagerank_percentile": 0.0,
            "avg_kcore_percentile": 0.0,
            "strength_label": "minimal",
        }

    n = len(candidates)
    avg_pr_pct = sum(c.pagerank_percentile or 0.0 for c in candidates) / n
    avg_kcore_pct = sum(c.kcore_percentile or 0.0 for c in candidates) / n

    # Label buckets. Thresholds tuned to the observed cross-repo baseline:
    # - "minimal": so few or so weak that abstention should be strongly considered
    # - "weak": below-median signals; low confidence in most candidates
    # - "moderate": middling signals
    # - "strong": many candidates with high graph importance
    combined = (avg_pr_pct + avg_kcore_pct) / 2.0
    if n <= 2 or combined < 20:
        label = "minimal"
    elif combined < 40:
        label = "weak"
    elif combined < 70:
        label = "moderate"
    else:
        label = "strong"

    return {
        "count": n,
        "avg_pagerank_percentile": round(avg_pr_pct, 1),
        "avg_kcore_percentile": round(avg_kcore_pct, 1),
        "strength_label": label,
    }


# =============================================================================
# LLM Schemas
# =============================================================================

DERIVATION_SCHEMA: dict[str, Any] = {
    "name": "derivation_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "identifier": {"type": "string"},
                        "name": {"type": "string"},
                        "documentation": {"type": "string"},
                        "source": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "identifier",
                        "name",
                        "documentation",
                        "source",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["elements"],
        "additionalProperties": False,
    },
}

RELATIONSHIP_SCHEMA: dict[str, Any] = {
    "name": "relationship_output",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "relationship_type": {"type": "string"},
                        "name": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": [
                        "source",
                        "target",
                        "relationship_type",
                        "name",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["relationships"],
        "additionalProperties": False,
    },
}


# =============================================================================
# Prompt Building - Elements
# =============================================================================


@dataclass(frozen=True)
class ElementPrompt:
    """The texts of the batch element prompt (element config ``params.prompt``).

    ``rules`` holds an ``{abstention}`` slot for ``abstention``, which is filled in only when the
    candidate evidence is minimal (so the model may answer with an empty list).
    """

    persona: str
    candidates: str  # What the candidate list is
    rules: str
    abstention: str


def build_derivation_prompt(
    candidates: list[Candidate] | list[dict[str, Any]],
    instruction: str,
    example: str,
    prompt: ElementPrompt,
    strength: dict[str, Any] | None = None,
) -> str:
    """
    Build LLM prompt for element derivation.

    Args:
        candidates: Pre-filtered candidate nodes (Candidate objects or dicts)
        instruction: Element-specific derivation instructions
        example: Example output format
        prompt: The step's prompt texts (persona, candidate note, rules, abstention rule)
        strength: Candidate evidence strength; ``minimal`` fills the abstention slot
    """
    # Convert Candidate objects to dicts with minimal properties (reduces tokens)
    if candidates and isinstance(candidates[0], Candidate):
        candidate_list = cast(list[Candidate], candidates)
        data = [c.to_dict(include_props=ESSENTIAL_PROPS) for c in candidate_list]
    else:
        data = candidates

    # Use compact JSON (no indentation) to reduce token usage by ~20-30%
    data_json = json.dumps(data, separators=(",", ":"), default=str)

    # Abstention signal — inform the LLM about candidate evidence strength.
    # The strength label bucketing is done upstream from graph signals only.
    # "Zero is valid" guidance is only surfaced when strength is 'minimal' to
    # avoid triggering over-abstention on repos with many noisy candidates.
    strength_section = ""
    abstention = ""
    if strength:
        label = strength.get("strength_label", "unknown")
        strength_section = f"""
## Candidate Evidence Strength
- Candidate count: {strength.get("count", 0)}
- Avg pagerank percentile: {strength.get("avg_pagerank_percentile", 0.0)}
- Avg kcore percentile: {strength.get("avg_kcore_percentile", 0.0)}
- Overall strength: {label}
"""
        if label == "minimal":
            abstention = prompt.abstention

    return f"""{prompt.persona}

## Instructions
{instruction}

## Candidate Nodes
{prompt.candidates}

```json
{data_json}
```
{strength_section}
## Example Output
{example}

## Rules
{prompt.rules.replace("{abstention}", abstention)}

Return a JSON object with an "elements" array.
"""


def build_single_candidate_prompt(
    candidate: Candidate | dict[str, Any],
    instruction: str,
    *,
    rules: str,
    persona: str,
) -> str:
    """Build a focused prompt asking the LLM to judge ONE candidate.

    Isolating the decision per candidate prevents cross-candidate correlations
    in the output (one name influencing a sibling's name, or the batch-level
    abstention trigger dropping legitimate middles). The LLM returns either
    zero or one element. The persona and rules texts come from the element config
    (``params.per_candidate``).
    """
    if isinstance(candidate, Candidate):
        cand_dict = candidate.to_dict(include_props=ESSENTIAL_PROPS)
    else:
        cand_dict = candidate
    cand_json = json.dumps(cand_dict, separators=(",", ":"), default=str)

    return f"""{persona}

## Instructions
{instruction}

## Candidate
```json
{cand_json}
```

## Rules
{rules}

Return a JSON object with an "elements" array of exactly one element.
"""


# =============================================================================
# Prompt Building - Relationships
# =============================================================================


# =============================================================================
# Response Parsing
# =============================================================================


def parse_derivation_response(response: str) -> dict[str, Any]:
    """Parse LLM response for elements."""
    return parse_json_array(response, "elements").to_dict()


def parse_relationship_response(response: str) -> dict[str, Any]:
    """Parse LLM response for relationships."""
    return parse_json_array(response, "relationships").to_dict()


# =============================================================================
# Element Building
# =============================================================================


def sanitize_identifier(identifier: str) -> str:
    """
    Sanitize identifier to be valid XML NCName.

    - Lowercase everything
    - Replace spaces, hyphens, colons with underscores
    - Remove non-alphanumeric characters (except underscore)
    - Ensure starts with letter/underscore
    """
    sanitized = identifier.lower().replace(" ", "_").replace("-", "_").replace(":", "_")
    sanitized = "".join(c for c in sanitized if c.isalnum() or c == "_")
    if sanitized and not (sanitized[0].isalpha() or sanitized[0] == "_"):
        sanitized = f"id_{sanitized}"
    return sanitized


def clamp_confidence(value: Any, default: float = 0.5) -> float:
    """Clamp confidence score to valid [0.0, 1.0] range."""
    try:
        conf = float(value) if value is not None else default
        return max(0.0, min(1.0, conf))
    except TypeError, ValueError:
        return default


_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+[A-Za-z]*")


def name_from_source(source_name: str, strip_extension: bool = False) -> str:
    """Human-readable element name derived from a source node's own name.

    Names come from structure, not from the LLM, so the same source node always
    yields the same element name. Splits snake_case, kebab-case and camelCase,
    keeps acronyms, title-cases words and, for file sources, drops the extension
    (``data_unit_schema.avsc`` -> ``Data Unit Schema``). Names that already
    contain spaces or dots in a product name (``Node.js``) are kept as written.
    """
    base = source_name.strip().replace("\\", "/").rstrip("/").split("/")[-1]
    if strip_extension:
        stem, dot, ext = base.rpartition(".")
        if dot and stem and ext.isalnum():
            base = stem
    if " " in base or ("." in base and not strip_extension):
        return " ".join(base.split())
    words = []
    for chunk in re.split(r"[_\-.]+", base.lstrip(".")):
        for part in _WORD.findall(chunk):
            words.append(part if len(part) > 1 and part.isupper() else part[:1].upper() + part[1:])
    return " ".join(words)


def structure_element_name(source_id: str, source_name: str, repo_name: str = "") -> str:
    """The name an element gets from its source node: ``name_from_source`` without an
    ArchiMate type suffix and, when ``repo_name`` is given, without a leading repository token.
    """
    from deriva.modules.derivation.refine.normalization import (
        strip_archimate_suffix,
        strip_repo_prefix,
    )

    name = strip_archimate_suffix(name_from_source(source_name, strip_extension=source_id.startswith("file::")))
    return strip_repo_prefix(name, repo_name) if repo_name else name


@dataclass(frozen=True)
class NamingConfig:
    """Isolated naming step for an element type (element config ``params.naming``).

    The name is asked in a prompt that depends only on the element's source node,
    its ArchiMate type and this instruction, so the same source gets the same
    prompt in every run. ``samples`` answers are combined by majority.
    """

    instruction: str  # Naming convention for the element type
    samples: int = 1  # Answers per element; above 1 they are combined by majority (voting, reported per session)


# Structural source fields that are the same in every run (no LLM-written text)
_NAMING_FIELDS = (
    ("path", "path"),
    ("filePath", "path"),
    ("typeName", "type"),
    ("category", "category"),
    ("conceptTypes", "concept_types"),
)

NAMING_SCHEMA: dict[str, Any] = {
    "name": "element_naming",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
}


def naming_source(candidate: Candidate) -> dict[str, Any]:
    """The stable, structural description of a candidate used for naming."""
    kind = next((label for label in candidate.labels if label != "Graph"), "Node")
    source: dict[str, Any] = {"kind": kind, "name": candidate.name}
    for prop, key in _NAMING_FIELDS:
        value = candidate.properties.get(prop)
        if value not in (None, "", [], "None") and key not in source:
            source[key] = value
    return source


def build_naming_prompt(source: dict[str, Any], element_type: str, instruction: str) -> str:
    """Prompt for naming one element; depends only on its source, type and instruction."""
    source_json = json.dumps(source, sort_keys=True, separators=(",", ":"), default=str)
    return f"""{instruction}

## ArchiMate {element_type} derived from this source
```json
{source_json}
```

Return {{"name": "..."}}."""


@dataclass(frozen=True)
class GraphFilter:
    """A step's k-core threshold for its candidates (element config ``params.graph_filter``).

    The percentile is computed over the whole graph, so it only fits candidates that were
    chosen as graph neighbours; ``labels`` limits the threshold to candidates with one of
    those graph labels (others, chosen by the query on structure, pass).
    """

    min_kcore_percentile: float
    labels: frozenset[str] | None = None  # None: the threshold applies to every candidate


@dataclass(frozen=True)
class NestedFilter:
    """One module, one element (element config ``params.skip_nested``).

    A selected directory that holds at least ``min_share`` of the files of ``file_type``
    below its nearest selected ancestor directory is represented by that ancestor.
    """

    file_type: str
    min_share: float


@dataclass(frozen=True)
class UnitFilter:
    """Components at the deployable-unit level (element config ``params.deployable_units``).

    A unit is a directory candidate that directly holds a file named in ``file_names`` (a
    build, dependency or container file). With at least ``min_units`` outermost units, those
    units are the candidates; a repository with fewer keeps its candidates.
    """

    file_names: frozenset[str]  # Lower-case file names
    min_units: int


@dataclass(frozen=True)
class RoleConfig:
    """Candidates classified into a closed list of roles (element config ``params.roles``).

    Candidates with one of ``labels`` leave the keep and naming path: one call per batch
    chooses a role key (or none) for each, and every chosen role becomes one element whose
    identity and name come from the role.
    """

    labels: frozenset[str]  # Graph labels of the candidates classified into roles
    instruction: str  # What each role means (config text)
    names: dict[str, str]  # Role key -> role name, in the order the elements are created
    documentation: str = ""  # Element documentation; {members} lists the candidates' names, {role} the role name
    missing_retries: int = 0  # Times a candidate left out of an answer is asked again
    # "role": one element per chosen role, named after it; "candidate": one element per
    # candidate with a role, with the candidate's identity and name and the role stored
    element_per: str = "role"
    # element_per "candidate" only: the element name from structure, a template with {container}
    # (the element of container_type whose source directory holds the candidate, else its
    # top-level module), {subject} (the candidate's structure name) and {role} (the role name),
    # each word once; empty keeps the candidate's own name as written
    name_template: str = ""
    container_type: str = ""  # Element type whose source directory holds a candidate ({container})
    show_path: bool = False  # Show each candidate's path in the classification prompt
    # element_per "candidate" only: the step's naming call (params.naming) may rename each element,
    # starting from its template name, under the usual uniqueness rules
    naming_call: bool = False


ROLE_SCHEMA: dict[str, Any] = {
    "name": "role_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "role": {"type": "string"}},
                    "required": ["id", "role"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}


def build_role_prompt(candidates: list[Candidate], instruction: str, names: dict[str, str], show_path: bool = False) -> str:
    """Prompt for choosing a role per candidate from a closed list; depends only on structure."""
    roles = "\n".join(f"- {key}: {name}" for key, name in names.items())
    items = []
    for c in candidates:
        item: dict[str, Any] = {"id": c.node_id, "name": c.name}
        if c.properties.get("techCategory"):
            item["category"] = c.properties["techCategory"]
        path = c.properties.get("filePath") or c.properties.get("path")
        if show_path and path:
            item["path"] = path
        items.append(item)
    items_json = json.dumps(items, separators=(",", ":"), default=str)
    return f"""{instruction}

## Roles
{roles}
- none

## Candidates
```json
{items_json}
```

Return {{"items": [{{"id": "...", "role": "..."}}]}} with one item per candidate: its id and a role key from the list, or none."""


def parse_role_answer(content: str, ids: set[str], roles: dict[str, str]) -> dict[str, str | None]:
    """The role per candidate id in a role classification answer: a role key, or None for none.

    Items with an unknown id or role are left out, so their candidates count as not answered.
    """
    decided: dict[str, str | None] = {}
    for item in parse_json_array(content, "items").data:
        if not isinstance(item, dict):
            continue
        candidate_id, role = item.get("id"), item.get("role")
        if candidate_id in ids and (role == "none" or role in roles):
            decided[candidate_id] = None if role == "none" else role
    return decided


def canonical_name(name: str) -> str:
    """Formatting-independent form of an LLM name: quotes trimmed, camel humps split, spacing normalized.

    Splits only at a lowercase-to-uppercase boundary ("EntityProcessor" ->
    "Entity Processor"), so acronyms and forms like "OAuth" or "REST API" stay.
    """
    name = name.strip().strip("\"'`").strip()
    return " ".join(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", word) for word in name.split())


def choose_name(samples: list[str | None]) -> str | None:
    """Majority name over canonicalized samples, ties broken deterministically.

    Votes group case- and spacing-insensitively ("HTTPServer" and "HTTP Server" are one
    name); the most frequent written form of the winning group is returned.
    """
    names = [canonical_name(s) for s in samples if s and s.strip()]
    names = [n for n in names if n]
    if not names:
        return None
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(n.lower().replace(" ", ""), []).append(n)
    best = min(groups, key=lambda k: (-len(groups[k]), k))
    forms = groups[best]
    return min(forms, key=lambda f: (-forms.count(f), f))


def source_casing(name: str, source_name: str) -> str:
    """``name`` with each word spelled as the source spells it, when the source writes that word with capitals (a
    type name in camel case: "CrudTypeImpl" makes "CRUD Type" read "Crud Type"); a lowercase source (a directory
    name) carries no casing, so its words keep the name's spelling."""
    spelled: dict[str, str] = {}
    for chunk in re.split(r"[_\-.\s]+", source_name or ""):
        for word in _WORD.findall(chunk):
            if not word.islower():
                spelled.setdefault(word.lower(), word)
    return " ".join(spelled.get(word.lower(), word) for word in name.split(" "))


def element_identifier(element_type: str, source_id: str) -> str:
    """Stable element identifier from its type and source node (``ac_big_data_kafka``)."""
    prefix = "".join(c for c in element_type if c.isupper()).lower()
    parts = source_id.split("::")
    tail = "::".join(parts[2:]) if len(parts) >= 3 else source_id
    return sanitize_identifier(f"{prefix}_{tail}")


def build_element(
    derived: dict[str, Any],
    element_type: str,
    candidate_enrichments: dict[str, dict[str, Any]] | None = None,
    repo_name: str = "",
    *,
    source_names: dict[str, str],
) -> dict[str, Any]:
    """Build ArchiMate element dict from LLM output.

    Structure decides the element: its name and identifier come from the source
    node (a candidate), the LLM contributes the keep decision, confidence and
    documentation. An element whose source is not a candidate is rejected.

    Args:
        derived: LLM-derived element data with source, documentation, confidence
        element_type: The ArchiMate element type
        candidate_enrichments: Optional mapping of node_id -> enrichment data
            (pagerank, louvain_community, etc.) to add to properties
        repo_name: Active repo name. When non-empty, the leading repo token
            is stripped from the element name (e.g., "<Repo> Client" -> "Client").
        source_names: Candidate node id -> the node's own name

    Returns:
        Dict with success flag and element data
    """
    source_id = derived.get("source")
    if not source_id or source_id not in source_names:
        return {
            "success": False,
            "errors": [f"Element source {source_id!r} is not a candidate"],
        }

    name = structure_element_name(source_id, source_names[source_id], repo_name)
    if not name:
        return {"success": False, "errors": [f"Empty name for source {source_id!r}"]}

    identifier = element_identifier(element_type, source_id)
    # Clamp confidence to [0.0, 1.0] range (LLM may return out-of-range values)
    confidence = clamp_confidence(derived.get("confidence"))

    properties: dict[str, Any] = {
        "source": source_id,
        "confidence": confidence,
        "derived_at": current_timestamp(),
        "llm_name": derived.get("name"),
    }

    # Add enrichment data if available (for graph-aware relationship derivation and stability analysis)
    if candidate_enrichments:
        enrichment = candidate_enrichments.get(source_id, {})
        for key in [
            "pagerank",
            "louvain_community",
            "kcore_level",
            "is_articulation_point",
            "in_degree",
            "out_degree",
        ]:
            if key in enrichment:
                properties[f"source_{key}"] = enrichment[key]

    return {
        "success": True,
        "data": {
            "identifier": identifier,
            "name": name,
            "element_type": element_type,
            "documentation": derived.get("documentation", ""),
            "properties": properties,
        },
    }


# =============================================================================
# Per-Element Relationship Derivation
# =============================================================================


def build_unified_relationship_prompt(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
    instruction: str,
    persona: str,
) -> str:
    """
    Build LLM prompt for unified relationship derivation (both directions).

    This is used after creating a batch of elements to derive:
    - OUTBOUND: relationships FROM new_elements TO existing_elements
    - INBOUND: relationships FROM existing_elements TO new_elements

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        element_type: The ArchiMate element type just created
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type (from other types)
        instruction: Conventions and rules from the relationship config row
        persona: Opening line from the relationship config row ({element_type}: the type just created)

    Returns:
        Prompt string for LLM
    """
    if not new_elements:
        return ""

    # Strip to essential fields for relationship derivation (reduces tokens ~50%)
    clean_new = strip_for_relationship_prompt(new_elements)
    clean_existing = strip_for_relationship_prompt(existing_elements)

    # Use compact JSON to reduce token usage
    new_json = json.dumps(clean_new, separators=(",", ":"), default=str)
    existing_json = json.dumps(clean_existing, separators=(",", ":"), default=str)

    # Build outbound rules text
    outbound_text = ""
    if outbound_rules:
        outbound_lines = []
        for rule in outbound_rules:
            targets_of_type = [e for e in existing_elements if e.get("element_type") == rule.target_type]
            if targets_of_type:
                outbound_lines.append(f"- {element_type} --[{rule.rel_type}]--> {rule.target_type}: {rule.description}")
        if outbound_lines:
            outbound_text = "OUTBOUND (FROM new elements TO existing):\n" + "\n".join(outbound_lines)

    # Build inbound rules text
    inbound_text = ""
    if inbound_rules:
        inbound_lines = []
        for rule in inbound_rules:
            sources_of_type = [e for e in existing_elements if e.get("element_type") == rule.target_type]
            if sources_of_type:
                inbound_lines.append(f"- {rule.target_type} --[{rule.rel_type}]--> {element_type}: {rule.description}")
        if inbound_lines:
            inbound_text = "INBOUND (FROM existing elements TO new):\n" + "\n".join(inbound_lines)

    # Note: identifier lists and valid_rel_types removed - they're in the JSON/rules (saves tokens)
    prompt = f"""{persona.replace("{element_type}", element_type)}

## New {element_type} Elements (just created)
```json
{new_json}
```

## Existing Elements (from previous steps)
```json
{existing_json}
```

## Relationship Rules
{outbound_text}

{inbound_text}

{instruction}

Return {{"relationships": []}} with source, target, relationship_type, confidence for each.
"""
    return prompt


# Whole-part relationships: at most one per ordered pair (Composition and
# Aggregation between the same two elements contradict each other)
_WHOLE_PART_TYPES = frozenset({"Composition", "Aggregation"})


def dedupe_relationships(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates and all but the first whole-part relationship per pair, keeping order."""
    seen: set[tuple[str, str, str]] = set()
    whole_part: set[tuple[str, str]] = set()
    kept = []
    for rel in relationships:
        key = (rel["source"], rel["target"], rel["relationship_type"])
        if key in seen:
            continue
        if rel["relationship_type"] in _WHOLE_PART_TYPES:
            if (rel["source"], rel["target"]) in whole_part:
                continue
            whole_part.add((rel["source"], rel["target"]))
        seen.add(key)
        kept.append(rel)
    return kept


# ArchiMate's structural relationships: a part or a realized element has one owner
OWNERSHIP_RELATIONSHIPS = frozenset({"Composition", "Aggregation", "Assignment", "Realization"})


def _left_to_containment(
    relationship: dict[str, Any],
    type_of: dict[str, str],
    decided: dict[tuple[str, str], tuple[str, str, set[str], set[str] | None]],
    owner_pairs: set[frozenset[str]],
    owner_pair_only: bool = False,
) -> bool:
    """Whether structure already decided this relationship, so another tier may not add it.

    Two elements that structure related get no other relationship. Unless
    ``owner_pair_only``, for a type pair that structure decides (containment,
    membership, configuration): a member that structure placed gets no further
    ownership relationship of that pair nor another of the rule's type, and a member
    it could not place gets only the rule's ownership type, from an element that
    structure lets own (for membership: a group that lists member technologies).
    """
    source, target, kind = relationship["source"], relationship["target"], relationship["relationship_type"]
    if frozenset((source, target)) in owner_pairs:
        return True
    if owner_pair_only:
        return False
    a, b = type_of.get(source, ""), type_of.get(target, "")
    for (from_type, to_type), (rule_type, side, placed, owners) in decided.items():
        if (a, b) == (from_type, to_type):
            member, owner = (target, source) if side == "target" else (source, target)
        elif (b, a) == (from_type, to_type):
            member, owner = (source, target) if side == "target" else (target, source)
        else:
            continue
        if member in placed and (kind in OWNERSHIP_RELATIONSHIPS or kind == rule_type):
            return True
        if member not in placed and kind in OWNERSHIP_RELATIONSHIPS and (kind != rule_type or (owners is not None and owner not in owners)):
            return True
    return False


def derive_batch_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
    llm_query_fn: Any,
    temperature: float | None = None,
    max_tokens: int | None = None,
    graph_manager: GraphManager | None = None,
    llm_config: RelationshipLLMConfig | None = None,
    decided: dict[tuple[str, str], tuple[str, str, set[str], set[str] | None]] | None = None,
    owner_pairs: set[frozenset[str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Derive relationships for a batch of newly created elements.

    Handles both outbound (FROM new TO existing) and inbound (FROM existing TO new).

    Args:
        new_elements: Elements just created in this batch
        existing_elements: Elements from previous derivation steps
        element_type: The ArchiMate element type just created
        outbound_rules: Rules for relationships FROM this type
        inbound_rules: Rules for relationships TO this type
        llm_query_fn: Function to call LLM
        temperature: Optional temperature override
        max_tokens: Optional max_tokens override
        graph_manager: Optional GraphManager for graph-aware filtering.
                      If provided, filters existing_elements to only include
                      those with graph proximity to new_elements.
        llm_config: Relationship config row settings. None (row disabled)
                    skips the LLM pass; graph tiers still run.
        decided: (from type, to type) -> (relationship type, member side, placed
                    members, possible owners) for the pairs structure decides (see
                    _left_to_containment)
        owner_pairs: Element pairs that structure already related: no tier adds
                    another relationship between them.

    Returns:
        List of validated relationship dicts
    """
    # Early returns to avoid unnecessary processing
    if not new_elements:
        return []

    if not outbound_rules and not inbound_rules:
        return []  # No rules defined, skip LLM call entirely

    if not existing_elements:
        return []  # No targets for relationships

    # Check if there are any applicable rules with available targets/sources
    has_outbound_targets = any(any(e.get("element_type") == rule.target_type for e in existing_elements) for rule in outbound_rules)
    has_inbound_sources = any(any(e.get("element_type") == rule.target_type for e in existing_elements) for rule in inbound_rules)

    if not has_outbound_targets and not has_inbound_sources:
        logger.debug("No applicable relationship rules for %s batch", element_type)
        return []

    # Filter existing_elements to only include relevant types (reduces prompt size)
    relevant_types = {r.target_type for r in outbound_rules} | {r.target_type for r in inbound_rules}
    filtered_existing = [e for e in existing_elements if e.get("element_type") in relevant_types]

    # Phase 4.3: Apply graph-aware pre-filtering if graph_manager provided
    # This keeps only elements with graph proximity to new_elements
    if graph_manager and len(filtered_existing) > 20:
        # Extract source IDs from new elements
        new_source_ids = [e.get("properties", {}).get("source") for e in new_elements if e.get("properties", {}).get("source")]
        if new_source_ids:
            # Get connected node IDs (within 2 hops)
            connected_ids = get_connected_source_ids(graph_manager, new_source_ids, max_hops=2)
            before_count = len(filtered_existing)
            filtered_existing = filter_by_graph_proximity(filtered_existing, connected_ids)
            logger.debug(
                "Graph-aware filtering: %d -> %d elements (connected to %d sources)",
                before_count,
                len(filtered_existing),
                len(connected_ids),
            )

    # Phase 4: Apply stratified sampling to limit context size
    # This keeps representation from each type while reducing tokens
    if len(filtered_existing) > 50:
        filtered_existing = stratified_sample_elements(
            filtered_existing,
            max_per_type=10,
            relevant_types=list(relevant_types),
        )
        logger.debug("Stratified sampling: reduced to %d elements", len(filtered_existing))

    logger.debug(
        "Filtered existing elements: %d -> %d (relevant types: %s)",
        len(existing_elements),
        len(filtered_existing),
        relevant_types,
    )

    # =========================================================================
    # THREE-TIER GRAPH-FIRST RELATIONSHIP DERIVATION
    # =========================================================================
    all_relationships: list[dict[str, Any]] = []
    created_pairs: set[tuple[str, str, str]] = set()

    # What structure decided stays decided: see _left_to_containment
    decided_pairs = decided or {}
    related = owner_pairs or set()
    type_of = {e.get("identifier", ""): e.get("element_type", "") for e in list(new_elements) + list(filtered_existing)}

    def kept(relationships: list[dict[str, Any]], usage_only: bool = False) -> list[dict[str, Any]]:
        return [r for r in relationships if not _left_to_containment(r, type_of, decided_pairs, related, owner_pair_only=usage_only)]

    # -------------------------------------------------------------------------
    # TIER 1a: Community-based relationships (same Louvain community = related)
    # -------------------------------------------------------------------------
    community_rels = derive_community_relationships(
        new_elements=new_elements,
        existing_elements=filtered_existing,
        outbound_rules=outbound_rules,
        inbound_rules=inbound_rules,
    )
    for rel in kept(community_rels):
        key = (rel["source"], rel["target"], rel["relationship_type"])
        if key not in created_pairs:
            all_relationships.append(rel)
            created_pairs.add(key)

    # -------------------------------------------------------------------------
    # TIER 1b: Graph neighbor relationships (direct graph connections)
    # -------------------------------------------------------------------------
    neighbor_rels = []
    if graph_manager:
        neighbor_rels = derive_neighbor_relationships(
            new_elements=new_elements,
            existing_elements=filtered_existing,
            graph_manager=graph_manager,
            outbound_rules=outbound_rules,
            inbound_rules=inbound_rules,
        )
        for rel in kept(neighbor_rels):
            key = (rel["source"], rel["target"], rel["relationship_type"])
            if key not in created_pairs:
                all_relationships.append(rel)
                created_pairs.add(key)

    # -------------------------------------------------------------------------
    # TIER 1.5: Edge-type relationships (CALLS, IMPORTS, USES)
    # -------------------------------------------------------------------------
    edge_rels = []
    if graph_manager:
        edge_rels = derive_edge_relationships(
            new_elements=new_elements,
            existing_elements=filtered_existing,
            graph_manager=graph_manager,
            element_type=element_type,
            outbound_rules=outbound_rules,
            inbound_rules=inbound_rules,
        )
        for rel in kept(edge_rels, usage_only=True):
            key = (rel["source"], rel["target"], rel["relationship_type"])
            if key not in created_pairs:
                all_relationships.append(rel)
                created_pairs.add(key)

    # -------------------------------------------------------------------------
    # TIER 1c: Name/file matching (semantic word overlap + same source file)
    # -------------------------------------------------------------------------
    deterministic_rels = derive_deterministic_relationships(
        new_elements=new_elements,
        existing_elements=filtered_existing,
        element_type=element_type,
        outbound_rules=outbound_rules,
        inbound_rules=inbound_rules,
    )
    for rel in kept(deterministic_rels):
        key = (rel["source"], rel["target"], rel["relationship_type"])
        if key not in created_pairs:
            all_relationships.append(rel)
            created_pairs.add(key)

    all_relationships = dedupe_relationships(all_relationships)

    # Log deterministic results
    logger.info(
        "Deterministic derivation: %d relationships (%d community, %d neighbor, %d edge, %d name/file) for %s",
        len(all_relationships),
        len(community_rels),
        len(neighbor_rels),
        len(edge_rels),
        len(deterministic_rels),
        element_type,
    )

    # -------------------------------------------------------------------------
    # LLM REFINEMENT: Skip only when deterministic tiers found DIVERSE types
    # -------------------------------------------------------------------------
    # The LLM is the only source for Aggregation, Realization, Flow, and
    # Triggering. Deterministic tiers mostly produce Composition and Serving.
    # Only skip LLM when multiple relationship types were already found.
    deterministic_types = {r["relationship_type"] for r in all_relationships}
    if len(deterministic_types) >= 2 and len(all_relationships) >= 3:
        logger.info(
            "Skipping LLM refinement for %s: %d deterministic relationships across %d types sufficient",
            element_type,
            len(all_relationships),
            len(deterministic_types),
        )
        return all_relationships

    if llm_config is None:
        logger.info("LLM relationship pass disabled for %s", element_type)
        return all_relationships

    # LLM provides relationship type diversity beyond deterministic methods
    prompt = build_unified_relationship_prompt(
        new_elements=new_elements,  # All elements for LLM consistency
        existing_elements=filtered_existing,
        element_type=element_type,
        outbound_rules=outbound_rules,
        inbound_rules=inbound_rules,
        instruction=llm_config.instruction,
        persona=llm_config.persona,
    )

    if not prompt:
        return all_relationships

    # Check prompt size and warn if too large
    estimated_tokens, over_threshold = check_prompt_size(prompt)
    if over_threshold:
        logger.warning(
            "Large prompt for %s relationships (%d tokens). Consider fewer elements.",
            element_type,
            estimated_tokens,
        )

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    try:
        response = llm_query_fn(prompt, RELATIONSHIP_SCHEMA, **llm_kwargs)
        response_content = response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error("LLM error deriving %s relationships: %s", element_type, e)
        return all_relationships  # Return Tier 1 relationships on LLM error

    parse_result = parse_relationship_response(response_content)

    if not parse_result["success"]:
        logger.warning(
            "Failed to parse %s relationships: %s",
            element_type,
            parse_result.get("errors"),
        )
        return all_relationships  # Return Tier 1 relationships on parse failure

    # Validate LLM relationships
    new_ids = {e.get("identifier", "") for e in new_elements}
    existing_ids = {e.get("identifier", "") for e in filtered_existing}
    all_ids = new_ids | existing_ids

    # A proposal must match a rule: its source type, target type and relationship type
    allowed = {(element_type, r.target_type, r.rel_type) for r in outbound_rules} | {(r.target_type, element_type, r.rel_type) for r in inbound_rules}

    llm_relationships = []
    for rel_data in parse_result.get("data", []):
        source = rel_data.get("source")
        target = rel_data.get("target")
        rel_type = rel_data.get("relationship_type")

        # Reject self-loops: an element cannot have a relationship to itself.
        if source and target and source == target:
            logger.debug(
                "Skipping self-loop relationship: %s -[%s]-> %s",
                source,
                rel_type,
                target,
            )
            continue

        # Skip if already created by deterministic derivation
        if (source, target, rel_type) in created_pairs:
            logger.debug(
                "Skipping LLM relationship (already deterministic): %s -> %s",
                source,
                target,
            )
            continue

        # Both endpoints must exist
        if source not in all_ids or target not in all_ids:
            logger.debug("Skipping relationship: endpoint not found (%s -> %s)", source, target)
            continue

        # At least one endpoint must be from new elements
        if source not in new_ids and target not in new_ids:
            logger.debug("Skipping relationship: neither endpoint is new element")
            continue

        # Validate the type pair and relationship type against the rules
        if (type_of.get(source), type_of.get(target), rel_type) not in allowed:
            logger.debug("Skipping relationship: no rule for %s -[%s]-> %s", type_of.get(source), rel_type, type_of.get(target))
            continue
        if _left_to_containment({"source": source, "target": target, "relationship_type": rel_type}, type_of, decided_pairs, related):
            continue

        # Prevent circular Composition relationships
        if rel_type == "Composition":
            reverse_key = (target, source, "Composition")
            if reverse_key in created_pairs:
                logger.debug(
                    "Skipping circular Composition: %s -> %s (reverse exists)",
                    source,
                    target,
                )
                continue

        # Enforce minimum confidence threshold for consistency
        confidence = rel_data.get("confidence", 0.5)
        if confidence < llm_config.min_confidence:
            logger.debug(
                "Skipping low-confidence relationship (%s -> %s, confidence=%s)",
                source,
                target,
                confidence,
            )
            continue

        llm_relationships.append(
            {
                "source": source,
                "target": target,
                "relationship_type": rel_type,
                "confidence": confidence,
                "derived_from": "llm",
            }
        )

    # Post-LLM graph grounding: require each LLM relationship to have
    # source_node <-> target_node connection within 2 hops in the extraction graph.
    # This prevents "name-based pairing" hallucinations disconnected from the code.
    if graph_manager and llm_relationships:
        element_by_id = {e.get("identifier", ""): e for e in list(new_elements) + list(filtered_existing)}
        before = len(llm_relationships)
        grounded: list[dict[str, Any]] = []
        for rel in llm_relationships:
            src_elem = element_by_id.get(rel["source"])
            tgt_elem = element_by_id.get(rel["target"])
            src_node = (src_elem or {}).get("properties", {}).get("source")
            tgt_node = (tgt_elem or {}).get("properties", {}).get("source")
            if not src_node or not tgt_node:
                # Missing provenance on either side -> cannot ground; drop.
                logger.debug(
                    "Dropping LLM rel without source/target node id: %s -> %s",
                    rel["source"],
                    rel["target"],
                )
                continue
            connected = get_connected_source_ids(graph_manager, [src_node], max_hops=2)
            if tgt_node in connected:
                grounded.append(rel)
            else:
                logger.debug(
                    "Dropping ungrounded LLM rel: %s -> %s (no 2-hop path in extraction graph)",
                    rel["source"],
                    rel["target"],
                )
        logger.info(
            "Graph grounding: %d/%d LLM relationships kept for %s",
            len(grounded),
            before,
            element_type,
        )
        llm_relationships = grounded

    # Add LLM relationships to the combined deterministic results
    all_relationships.extend(llm_relationships)
    logger.info(
        "Derived %d total relationships for %s batch (deterministic: %d, LLM: %d)",
        len(all_relationships),
        element_type,
        len(community_rels) + (len(neighbor_rels) if graph_manager else 0) + len(deterministic_rels),
        len(llm_relationships),
    )
    return dedupe_relationships(all_relationships)


# =============================================================================
# Consolidated Relationship Derivation (Phase 4.6)
# =============================================================================


def element_source_paths(graph_manager: GraphManager, elements: list[dict[str, Any]]) -> dict[str, str]:
    """Repository path of each element's source node: a directory's path, a file's, type's or method's file path.

    A source without a path of its own (a concept found in a directory name) lies in the directory
    that represents it; in the deepest directory shared by several.
    """
    ids = sorted({src for e in elements if (src := (e.get("properties") or {}).get("source"))})
    if not ids:
        return {}
    rows = graph_manager.query("MATCH (n) WHERE n.id IN $ids RETURN n.id AS id, n.path AS path, n.filePath AS file_path", {"ids": ids})
    paths: dict[str, str] = {}
    for row in rows:
        path = row.get("file_path") or row.get("path")
        if row.get("id") and path:
            paths[row["id"]] = str(path).replace(chr(92), "/").rstrip("/")
    missing = [i for i in ids if i not in paths]
    if missing:
        represented: dict[str, list[list[str]]] = defaultdict(list)
        for row in graph_manager.query("MATCH (d)-[:`Graph:REPRESENTS`]->(n) WHERE n.id IN $ids RETURN n.id AS id, d.path AS path", {"ids": missing}):
            if row.get("id") and row.get("path"):
                represented[row["id"]].append(str(row["path"]).replace(chr(92), "/").rstrip("/").split("/"))
        for node_id, holders in represented.items():
            shared = []
            for parts in zip(*holders, strict=False):
                if len(set(parts)) != 1:
                    break
                shared.append(parts[0])
            if shared:
                paths[node_id] = "/".join(shared)
    return paths


def derive_containment_relationships(
    elements: list[dict[str, Any]],
    source_paths: dict[str, str],
    rules: list[ContainmentRule],
) -> list[dict[str, Any]]:
    """Relationships from containment: the nearest enclosing container owns each element.

    An element of a contained type is related to the container element whose source
    directory holds its source most closely (only that one, so composition stays
    exclusive). Elements without a source path, or outside every container, stay unlinked.
    """
    if not rules:
        return []
    container_types = {r.container for r in rules}
    containers: dict[str, list[tuple[str, str]]] = defaultdict(list)  # type -> [(directory path, id)]
    for e in elements:
        path = source_paths.get((e.get("properties") or {}).get("source", ""))
        if path and e.get("element_type") in container_types:
            containers[e["element_type"]].append((path, e["identifier"]))

    relationships: list[dict[str, Any]] = []
    for e in sorted(elements, key=lambda x: x.get("identifier", "")):
        path = source_paths.get((e.get("properties") or {}).get("source", ""))
        if not path:
            continue
        for rule in rules:
            if e.get("element_type") != rule.contained:
                continue
            owners = [(p, cid) for p, cid in containers.get(rule.container, []) if cid != e["identifier"] and path.startswith(p + "/")]
            if not owners:
                continue
            _, owner = max(owners, key=lambda o: len(o[0]))
            relationships.append({"source": owner, "target": e["identifier"], "relationship_type": rule.relationship, "confidence": 1.0, "derived_from": "containment"})
    return relationships


def _member_technologies(element: dict[str, Any]) -> list[str]:
    """The technologies an element stands for: its listed ``sources``, else its source."""
    props = element.get("properties") or {}
    return list(props.get("sources") or ([props["source"]] if props.get("source") else []))


def derive_membership_relationships(elements: list[dict[str, Any]], rules: list[MembershipRule]) -> list[dict[str, Any]]:
    """Relationships between a role element and the elements of its member technologies.

    Only elements that list member technologies (``sources``, as role elements do) are
    groups; an element made from a single file or candidate groups nothing.
    """
    relationships: list[dict[str, Any]] = []
    for rule in rules:
        members: dict[str, list[str]] = defaultdict(list)
        for e in elements:
            source = (e.get("properties") or {}).get("source")
            if e.get("element_type") == rule.member and source:
                members[source].append(e["identifier"])
        for group in sorted((e for e in elements if e.get("element_type") == rule.group), key=lambda x: x.get("identifier", "")):
            for tech in (group.get("properties") or {}).get("sources") or []:
                for member in sorted(members.get(tech, [])):
                    if member == group["identifier"]:
                        continue
                    source, target = (group["identifier"], member) if rule.from_group else (member, group["identifier"])
                    relationships.append({"source": source, "target": target, "relationship_type": rule.relationship, "confidence": 1.0, "derived_from": "membership"})
    return dedupe_relationships(relationships)


def configured_technologies(graph_manager: GraphManager) -> dict[str, set[str]]:
    """File path -> the technologies the file configures (CONFIGURES edges from manifests, build and container files)."""
    rows = graph_manager.query("MATCH (f:Graph:File)-[r:`Graph:CONFIGURES`]->(t:Graph:Technology) RETURN f.filePath AS file, t.id AS tech")
    configured: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("file") and row.get("tech"):
            configured[str(row["file"]).replace(chr(92), "/")].add(row["tech"])
    return dict(configured)


def derive_configuration_relationships(
    elements: list[dict[str, Any]],
    source_paths: dict[str, str],
    configured: dict[str, set[str]],
    rules: list[ConfigurationRule],
) -> list[dict[str, Any]]:
    """A provider serves the consumer whose directory (nearest enclosing) holds a file configuring one of its technologies."""
    relationships: list[dict[str, Any]] = []
    for rule in rules:
        consumers = [
            (source_paths[src], e["identifier"]) for e in elements if e.get("element_type") == rule.consumer and (src := (e.get("properties") or {}).get("source")) in source_paths
        ]
        providers = [(e["identifier"], set(_member_technologies(e))) for e in elements if e.get("element_type") == rule.provider]
        used: dict[str, set[str]] = defaultdict(set)  # consumer id -> configured technologies
        for path, techs in configured.items():
            owners = [(p, cid) for p, cid in consumers if path.startswith(p + "/")]
            if owners:
                used[max(owners, key=lambda o: len(o[0]))[1]].update(techs)
        for consumer in sorted(used):
            for provider, techs in sorted(providers):
                if techs & used[consumer]:
                    relationships.append({"source": provider, "target": consumer, "relationship_type": rule.relationship, "confidence": 1.0, "derived_from": "configuration"})
    return relationships


def _source_name_key(element: dict[str, Any], strip_suffixes: tuple[str, ...]) -> str:
    """Canonical name key of the last part of the element's source id, without a configured suffix."""
    name = str((element.get("properties") or {}).get("source") or "").rsplit("::", 1)[-1]
    for suffix in strip_suffixes:
        if suffix and name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name_key(name)


def derive_same_name_relationships(elements: list[dict[str, Any]], rules: list[SameNameRule]) -> list[dict[str, Any]]:
    """The source element relates to every target element whose structural source carries the same name."""
    relationships: list[dict[str, Any]] = []
    for rule in rules:
        targets: dict[str, list[str]] = defaultdict(list)
        for e in elements:
            if e.get("element_type") == rule.target and (key := _source_name_key(e, ())):
                targets[key].append(e["identifier"])
        for e in sorted((x for x in elements if x.get("element_type") == rule.source), key=lambda x: x.get("identifier", "")):
            key = _source_name_key(e, rule.strip_suffixes)
            for target in sorted(targets.get(key, [])) if key else []:
                if target != e["identifier"]:
                    relationships.append({"source": e["identifier"], "target": target, "relationship_type": rule.relationship, "confidence": 1.0, "derived_from": "same_name"})
    return relationships


def file_imports(graph_manager: GraphManager) -> list[tuple[str, str]]:
    """(importing file path, imported file path) for every import between files of the repository."""
    rows = graph_manager.query("MATCH (a:Graph:File)-[:`Graph:IMPORTS`]->(b:Graph:File) RETURN a.filePath AS a, b.filePath AS b")
    return sorted({(str(r["a"]).replace(chr(92), "/"), str(r["b"]).replace(chr(92), "/")) for r in rows if r.get("a") and r.get("b")})


def derive_dependency_relationships(
    elements: list[dict[str, Any]],
    source_paths: dict[str, str],
    imports: list[tuple[str, str]],
    rules: list[DependencyRule],
) -> list[dict[str, Any]]:
    """The provider serves the consumer whose files import its files, drawn between siblings.

    Each file belongs to its nearest enclosing element. A dependency between two elements
    is lifted to the two elements just below the deepest element holding both, so a part
    that uses a part of another element shows as a dependency between those elements, and
    imports within one element or between an element and its own parts add nothing.
    """
    relationships: list[dict[str, Any]] = []
    for rule in rules:
        holders = sorted(
            (source_paths[src], e["identifier"])
            for e in elements
            if e.get("element_type") in (rule.consumer, rule.provider) and (src := (e.get("properties") or {}).get("source")) in source_paths
        )
        type_of = {e["identifier"]: e.get("element_type") for e in elements}

        def within(path: str, holder: str) -> bool:
            return path == holder or path.startswith(holder + "/")

        def nearest(path: str, element_type: str) -> tuple[str, str] | None:
            owners = [h for h in holders if path.startswith(h[0] + "/") and type_of[h[1]] == element_type]
            return max(owners, key=lambda h: len(h[0])) if owners else None

        def lift(owner: tuple[str, str], parent: str | None) -> str:
            """The outermost element holding ``owner`` below ``parent`` (anywhere when None)."""
            chain = [h for h in holders if within(owner[0], h[0]) and (parent is None or h[0].startswith(parent + "/"))]
            return min(chain, key=lambda h: len(h[0]))[1]

        pairs: set[tuple[str, str]] = set()
        for importer, imported in imports:
            consumer, provider = nearest(importer, rule.consumer), nearest(imported, rule.provider)
            if not consumer or not provider or within(consumer[0], provider[0]) or within(provider[0], consumer[0]):
                continue
            shared = [h[0] for h in holders if consumer[0].startswith(h[0] + "/") and provider[0].startswith(h[0] + "/")]
            parent = max(shared, key=lambda p: len(p)) if shared else None
            pairs.add((lift(provider, parent), lift(consumer, parent)))
        for provider_id, consumer_id in sorted(pairs):
            relationships.append({"source": provider_id, "target": consumer_id, "relationship_type": rule.relationship, "confidence": 1.0, "derived_from": "dependency"})
    return relationships


def derive_consolidated_relationships(
    all_elements: list[dict[str, Any]],
    relationship_rules: dict[str, tuple[list[RelationshipRule], list[RelationshipRule]]],
    llm_query_fn: Any,
    graph_manager: GraphManager | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    llm_config: RelationshipLLMConfig | None = None,
    containment: list[ContainmentRule] | None = None,
    membership: list[MembershipRule] | None = None,
    configuration: list[ConfigurationRule] | None = None,
    dependency: list[DependencyRule] | None = None,
    same_name: list[SameNameRule] | None = None,
) -> list[dict[str, Any]]:
    """
    Derive relationships for all elements in a single consolidated pass.

    This is used when defer_relationships=True in element generation.
    Instead of deriving relationships per-batch, this function processes
    all elements together for better context and consistency.

    Args:
        all_elements: All elements created during generation phase
        relationship_rules: Dict mapping element_type to (outbound_rules, inbound_rules)
        llm_query_fn: Function to call LLM
        graph_manager: Optional GraphManager for graph-aware filtering
        temperature: Optional temperature override
        max_tokens: Optional max_tokens override
        llm_config: Relationship config row settings (None skips the LLM pass)
        containment: Ownership decided by containment (relationship config
            ``params.containment``). For an element that containment places under an
            owner, the other tiers add no ownership relationship of those type pairs and
            nothing between it and its owner; usage to other elements stays. None: no
            containment tier
        membership: Relationships from role membership (``params.membership``), decided
            the same way. None: no membership tier
        configuration: Relationships from configuration files (``params.configuration``),
            decided the same way. None: no configuration tier
        dependency: Dependencies from file imports between siblings (``params.dependency``);
            usage, so no tier adds another relationship between the two. None: no
            dependency tier
        same_name: Relationships between elements whose sources carry the same name
            (``params.same_name``); no tier adds another relationship between the two.
            None: no same-name tier

    Returns:
        List of all derived relationship dicts
    """
    if not all_elements:
        return []

    all_relationships = []
    type_of = {e.get("identifier", ""): e.get("element_type", "") for e in all_elements}
    # (from type, to type) -> (relationship type, member side, members placed by structure,
    # elements that may own a member; None: any)
    decided: dict[tuple[str, str], tuple[str, str, set[str], set[str] | None]] = {}
    structural: list[dict[str, Any]] = []

    def decide(rels: list[dict[str, Any]], from_type: str, to_type: str, kind: str, side: str, owners: set[str] | None = None) -> None:
        mine = [r for r in rels if (type_of.get(r["source"]), type_of.get(r["target"]), r["relationship_type"]) == (from_type, to_type, kind)]
        placed = {r[side] for r in mine}
        if (from_type, to_type) in decided:
            placed |= decided[(from_type, to_type)][2]
        decided[(from_type, to_type)] = (kind, side, placed, owners)

    paths = element_source_paths(graph_manager, all_elements) if graph_manager and (containment or configuration or dependency) else {}
    if containment:
        rels = derive_containment_relationships(all_elements, paths, containment)
        structural.extend(rels)
        for rule in containment:
            decide(rels, rule.container, rule.contained, rule.relationship, "target")
    if membership:
        rels = derive_membership_relationships(all_elements, membership)
        structural.extend(rels)
        for rule in membership:
            # A group that lists no member technologies (a node made from one file) owns nothing
            groups = {e["identifier"] for e in all_elements if e.get("element_type") == rule.group and (e.get("properties") or {}).get("sources")}
            if rule.from_group:
                decide(rels, rule.group, rule.member, rule.relationship, "target", groups)
            else:
                decide(rels, rule.member, rule.group, rule.relationship, "source", groups)
    if configuration and graph_manager:
        rels = derive_configuration_relationships(all_elements, paths, configured_technologies(graph_manager), configuration)
        structural.extend(rels)
        for rule in configuration:
            decide(rels, rule.provider, rule.consumer, rule.relationship, "target")
    if dependency and graph_manager:
        structural.extend(derive_dependency_relationships(all_elements, paths, file_imports(graph_manager), dependency))
    if same_name:
        structural.extend(derive_same_name_relationships(all_elements, same_name))
    all_relationships.extend(structural)
    owner_pairs = {frozenset((r["source"], r["target"])) for r in structural}

    # Group elements by type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for elem in all_elements:
        etype = elem.get("element_type", "Unknown")
        if etype not in by_type:
            by_type[etype] = []
        by_type[etype].append(elem)

    logger.info(
        "Consolidated relationship derivation: %d elements across %d types",
        len(all_elements),
        len(by_type),
    )

    # Process each element type
    for element_type, type_elements in by_type.items():
        if element_type not in relationship_rules:
            continue

        outbound_rules, inbound_rules = relationship_rules[element_type]
        if not outbound_rules and not inbound_rules:
            continue

        # Get all other elements as potential targets
        other_elements = [e for e in all_elements if e.get("element_type") != element_type]

        relationships = derive_batch_relationships(
            new_elements=type_elements,
            existing_elements=other_elements,
            element_type=element_type,
            outbound_rules=outbound_rules,
            inbound_rules=inbound_rules,
            llm_query_fn=llm_query_fn,
            temperature=temperature,
            max_tokens=max_tokens,
            graph_manager=graph_manager,
            llm_config=llm_config,
            decided=decided,
            owner_pairs=owner_pairs,
        )

        all_relationships.extend(relationships)
        logger.debug(
            "Derived %d relationships for %s (%d elements)",
            len(relationships),
            element_type,
            len(type_elements),
        )

    # Both endpoint types' passes can derive the same relationship
    all_relationships = dedupe_relationships(all_relationships)
    logger.info("Total relationships derived: %d", len(all_relationships))
    return all_relationships


# =============================================================================
# Result Creation
# =============================================================================


def create_result(
    success: bool,
    errors: list[str] | None = None,
    stats: dict[str, Any] | None = None,
) -> PipelineResult:
    """Create a simple pipeline result."""
    return {
        "success": success,
        "errors": errors or [],
        "stats": stats or {},
        "timestamp": current_timestamp(),
    }


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Constants
    "ESSENTIAL_PROPS",
    "RELATIONSHIP_ESSENTIAL_FIELDS",
    # Utility functions
    "strip_for_relationship_prompt",
    # Data structures
    "Candidate",
    "RelationshipRule",
    "RelationshipLLMConfig",
    "PerCandidateConfig",
    "GenerationResult",
    "DerivationResult",
    # Enrichment
    "get_enrichments",
    "get_enrichments_from_graph",
    "enrich_candidate",
    # Filtering
    "filter_by_pagerank",
    "filter_by_labels",
    "filter_by_community",
    "get_community_roots",
    "get_articulation_points",
    # Token estimation & context limiting (Phase 4)
    "MODEL_CONTEXT_LIMITS",
    "estimate_tokens",
    "get_model_context_limit",
    "limit_existing_elements",
    "stratified_sample_elements",
    "check_prompt_size",
    # Graph-aware filtering (Phase 4.3)
    "get_connected_source_ids",
    "filter_by_graph_proximity",
    # Batching
    "calculate_dynamic_batch_size",
    "adjust_batch_for_tokens",
    "batch_candidates",
    # Query
    "query_candidates",
    # Schemas
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    # Prompts
    "build_derivation_prompt",
    "ElementPrompt",
    "build_single_candidate_prompt",
    "build_unified_relationship_prompt",
    # Response handling
    "extract_response_content",
    # Parsing
    "parse_derivation_response",
    "parse_relationship_response",
    # Element building
    "clamp_confidence",
    "sanitize_identifier",
    "build_element",
    "structure_element_name",
    "RoleConfig",
    "ROLE_SCHEMA",
    "build_role_prompt",
    "parse_role_answer",
    # Relationship derivation
    "derive_batch_relationships",
    "derive_consolidated_relationships",
    # Results
    "create_result",
]
