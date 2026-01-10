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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from deriva.common import current_timestamp, parse_json_array
from deriva.common.types import PipelineResult

if TYPE_CHECKING:
    from deriva.adapters.graph import GraphManager

logger = logging.getLogger(__name__)

# Essential properties to include in LLM prompts (reduces token usage)
# These are the most useful properties for element derivation
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
    louvain_community: str | None = None
    kcore_level: int = 0
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

    target_type: (
        str  # For outbound: target element type. For inbound: source element type
    )
    rel_type: str  # ArchiMate relationship type (Serving, Access, etc.)
    description: str = ""  # Human-readable description


@dataclass
class GenerationResult:
    """Result from element generation (includes relationships)."""

    success: bool
    elements_created: int = 0
    relationships_created: int = 0
    created_elements: list[dict[str, Any]] = field(default_factory=list)
    created_relationships: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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


def get_enrichments_from_neo4j(
    graph_manager: "GraphManager",
) -> dict[str, dict[str, Any]]:
    """
    Get all graph enrichment data from Neo4j node properties.

    The prep phase stores enrichments (PageRank, Louvain, k-core, etc.)
    as properties on Neo4j nodes. This function reads them back.

    Args:
        graph_manager: Connected GraphManager instance

    Returns:
        Dict mapping node_id to enrichment data
    """
    query = """
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label STARTS WITH 'Graph:')
          AND n.active = true
        RETURN n.id as node_id,
               n.pagerank as pagerank,
               n.louvain_community as louvain_community,
               n.kcore_level as kcore_level,
               n.is_articulation_point as is_articulation_point,
               n.in_degree as in_degree,
               n.out_degree as out_degree
    """
    try:
        rows = graph_manager.query(query)
        return {
            row["node_id"]: {
                "pagerank": row.get("pagerank") or 0.0,
                "louvain_community": row.get("louvain_community"),
                "kcore_level": row.get("kcore_level") or 0,
                "is_articulation_point": row.get("is_articulation_point") or False,
                "in_degree": row.get("in_degree") or 0,
                "out_degree": row.get("out_degree") or 0,
            }
            for row in rows
            if row.get("node_id")
        }
    except Exception as e:
        logger.warning(f"Failed to get enrichments from Neo4j: {e}")
        return {}


# Backward compatibility alias (deprecated)
def get_enrichments(engine: Any) -> dict[str, dict[str, Any]]:
    """Deprecated: Use get_enrichments_from_neo4j() instead."""
    logger.warning(
        "get_enrichments(engine) is deprecated - enrichments should be read from Neo4j"
    )
    return {}


def enrich_candidate(
    candidate: Candidate, enrichments: dict[str, dict[str, Any]]
) -> None:
    """Add enrichment data to a candidate in-place."""
    data = enrichments.get(candidate.node_id, {})
    candidate.pagerank = data.get("pagerank", 0.0)
    candidate.louvain_community = data.get("louvain_community")
    candidate.kcore_level = data.get("kcore_level", 0)
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
        result = [
            c for c in result if not any(lbl in c.labels for lbl in exclude_labels)
        ]

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
# Batching
# =============================================================================


def batch_candidates(
    candidates: list[Candidate],
    batch_size: int = 15,
    group_by_community: bool = True,
) -> list[list[Candidate]]:
    """
    Split candidates into batches for LLM processing.

    Args:
        candidates: List of candidates to batch
        batch_size: Maximum items per batch (default 15)
        group_by_community: If True, group candidates by Louvain community first,
                           keeping related nodes together (default True)

    Returns:
        List of batches
    """
    if not candidates:
        return []

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
    graph_manager: "GraphManager",
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

    return candidates


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
                    "required": ["identifier", "name"],
                    "additionalProperties": True,
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
                    "required": ["source", "target", "relationship_type"],
                    "additionalProperties": True,
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


def build_derivation_prompt(
    candidates: list[Candidate] | list[dict[str, Any]],
    instruction: str,
    example: str,
    element_type: str,
) -> str:
    """
    Build LLM prompt for element derivation.

    Args:
        candidates: Pre-filtered candidate nodes (Candidate objects or dicts)
        instruction: Element-specific derivation instructions
        example: Example output format
        element_type: ArchiMate element type
    """
    # Convert Candidate objects to dicts with minimal properties (reduces tokens)
    if candidates and isinstance(candidates[0], Candidate):
        candidate_list = cast(list[Candidate], candidates)
        data = [c.to_dict(include_props=ESSENTIAL_PROPS) for c in candidate_list]
    else:
        data = candidates

    data_json = json.dumps(data, indent=2, default=str)

    return f"""You are deriving ArchiMate {element_type} elements from source code graph data.

## Instructions
{instruction}

## Candidate Nodes
These nodes have been pre-filtered as potential {element_type} candidates.
Each includes graph metrics (pagerank, degree) to help assess importance.

```json
{data_json}
```

## Example Output
{example}

## Rules
1. Only create elements from the provided candidates
2. Use the node "id" as the "source" field to link back
3. Provide meaningful names (not just the node name)
4. Add documentation explaining the element's purpose
5. Set confidence based on how well the candidate matches {element_type}
6. If no candidates are suitable, return {{"elements": []}}

Return a JSON object with an "elements" array.
"""


# =============================================================================
# Prompt Building - Relationships
# =============================================================================


def build_relationship_prompt(elements: list[dict[str, Any]]) -> str:
    """Build LLM prompt for relationship derivation."""
    elements_json = json.dumps(elements, indent=2, default=str)
    valid_ids = [e.get("identifier", "") for e in elements if e.get("identifier")]

    return f"""Derive relationships between these ArchiMate elements:

```json
{elements_json}
```

CRITICAL RULES:
1. You must ONLY use identifiers from this exact list: {json.dumps(valid_ids)}
2. Do NOT invent new identifiers or modify existing ones
3. Use identifiers exactly as shown (case-sensitive, character-for-character)
4. Only create relationships where BOTH source AND target exist in the list

VALID RELATIONSHIP TYPES (use ONLY these exact names):
- Composition: element consists of other elements
- Aggregation: element combines other elements
- Serving: element provides services to another
- Realization: element realizes/implements another
- Access: element reads/writes data objects
- Flow: transfer of information between elements
- Assignment: allocates responsibility between elements

INVALID TYPES (NEVER use these):
- Association (use Serving or Flow instead)
- Dependency (use Serving instead)
- Uses (use Serving instead)

Output stable, deterministic results.
Return {{"relationships": []}} with source, target, relationship_type for each.
"""


def build_element_relationship_prompt(
    source_elements: list[dict[str, Any]],
    target_elements: list[dict[str, Any]],
    source_element_type: str,
    valid_relationships: list[dict[str, Any]],
    instruction: str | None = None,
    example: str | None = None,
) -> str:
    """Build LLM prompt for element-type-specific relationship derivation."""
    sources_json = json.dumps(source_elements, indent=2, default=str)
    targets_json = json.dumps(target_elements, indent=2, default=str)

    source_ids = [
        e.get("identifier", "") for e in source_elements if e.get("identifier")
    ]
    target_ids = [
        e.get("identifier", "") for e in target_elements if e.get("identifier")
    ]

    rel_rules = []
    for rel in valid_relationships:
        targets = ", ".join(rel["allowed_targets"])
        rel_rules.append(
            f"- {rel['relationship_type']}: {rel['description']} → can target: [{targets}]"
        )
    rel_rules_text = (
        "\n".join(rel_rules) if rel_rules else "No valid relationship types."
    )

    default_instruction = f"""Derive relationships FROM the {source_element_type} elements.
Only create relationships where the source is from the Source Elements list.
Use only the relationship types valid for {source_element_type} as specified below."""

    default_example = """{"relationships": [
  {"source": "source_id", "target": "target_id", "relationship_type": "Serving", "confidence": 0.8}
]}"""

    return f"""You are deriving ArchiMate relationships FROM {source_element_type} elements.

## Instructions
{instruction or default_instruction}

## Source Elements (type: {source_element_type})
```json
{sources_json}
```

## Target Elements (all types)
```json
{targets_json}
```

## Valid Relationship Types for {source_element_type}
{rel_rules_text}

## Example Output Format
```json
{example or default_example}
```

CRITICAL RULES:
1. Source identifiers MUST be from: {json.dumps(source_ids)}
2. Target identifiers MUST be from: {json.dumps(target_ids)}
3. Use identifiers exactly as shown (case-sensitive)
4. Only use relationship types listed above

Return {{"relationships": []}} with source, target, relationship_type for each.
"""


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


def build_element(derived: dict[str, Any], element_type: str) -> dict[str, Any]:
    """Build ArchiMate element dict from LLM output."""
    identifier = derived.get("identifier")
    name = derived.get("name")

    if not identifier or not name:
        return {"success": False, "errors": ["Missing identifier or name"]}

    identifier = sanitize_identifier(identifier)

    return {
        "success": True,
        "data": {
            "identifier": identifier,
            "name": name,
            "element_type": element_type,
            "documentation": derived.get("documentation", ""),
            "properties": {
                "source": derived.get("source"),
                "confidence": derived.get("confidence", 0.5),
                "derived_at": current_timestamp(),
            },
        },
    }


# =============================================================================
# Per-Element Relationship Derivation
# =============================================================================


def build_per_element_relationship_prompt(
    source_elements: list[dict[str, Any]],
    target_elements: list[dict[str, Any]],
    source_element_type: str,
    instruction: str,
    example: str | None = None,
    valid_relationship_types: list[str] | None = None,
) -> str:
    """
    Build LLM prompt for per-element relationship derivation.

    This is used when each element module derives its own relationships,
    providing focused context and better consistency.

    Args:
        source_elements: Elements of the current type (relationships FROM these)
        target_elements: All available target elements
        source_element_type: The ArchiMate element type being processed
        instruction: Custom instruction from database config
        example: Example output from database config
        valid_relationship_types: Allowed relationship types (from config)
    """
    source_json = json.dumps(source_elements, indent=2, default=str)
    target_json = json.dumps(target_elements, indent=2, default=str)

    source_ids = [
        e.get("identifier", "") for e in source_elements if e.get("identifier")
    ]
    target_ids = [
        e.get("identifier", "") for e in target_elements if e.get("identifier")
    ]

    prompt = f"""You are deriving ArchiMate relationships FROM {source_element_type} elements.

{instruction}

SOURCE ELEMENTS (derive relationships FROM these):
```json
{source_json}
```

TARGET ELEMENTS (derive relationships TO these):
```json
{target_json}
```

VALID SOURCE IDENTIFIERS (use EXACTLY as shown):
{json.dumps(source_ids)}

VALID TARGET IDENTIFIERS (use EXACTLY as shown):
{json.dumps(target_ids)}
"""

    if valid_relationship_types:
        prompt += f"""
ALLOWED RELATIONSHIP TYPES (use ONLY these):
{json.dumps(valid_relationship_types)}
"""

    if example:
        prompt += f"""
EXAMPLE OUTPUT:
```json
{example}
```
"""

    prompt += """
Return {"relationships": []} with source, target, relationship_type, confidence for each.
"""
    return prompt


def build_unified_relationship_prompt(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
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

    Returns:
        Prompt string for LLM
    """
    if not new_elements:
        return ""

    new_json = json.dumps(new_elements, indent=2, default=str)
    new_ids = [e.get("identifier", "") for e in new_elements if e.get("identifier")]

    # Group existing elements by type for clarity
    existing_by_type: dict[str, list[dict]] = {}
    for elem in existing_elements:
        etype = elem.get("element_type", "Unknown")
        existing_by_type.setdefault(etype, []).append(elem)

    existing_json = json.dumps(existing_elements, indent=2, default=str)
    existing_ids = [
        e.get("identifier", "") for e in existing_elements if e.get("identifier")
    ]

    # Build outbound rules text
    outbound_text = ""
    if outbound_rules:
        outbound_lines = []
        for rule in outbound_rules:
            targets_of_type = [
                e
                for e in existing_elements
                if e.get("element_type") == rule.target_type
            ]
            if targets_of_type:
                outbound_lines.append(
                    f"- {element_type} --[{rule.rel_type}]--> {rule.target_type}: {rule.description}"
                )
        if outbound_lines:
            outbound_text = "OUTBOUND (FROM new elements TO existing):\n" + "\n".join(
                outbound_lines
            )

    # Build inbound rules text
    inbound_text = ""
    if inbound_rules:
        inbound_lines = []
        for rule in inbound_rules:
            sources_of_type = [
                e
                for e in existing_elements
                if e.get("element_type") == rule.target_type
            ]
            if sources_of_type:
                inbound_lines.append(
                    f"- {rule.target_type} --[{rule.rel_type}]--> {element_type}: {rule.description}"
                )
        if inbound_lines:
            inbound_text = "INBOUND (FROM existing elements TO new):\n" + "\n".join(
                inbound_lines
            )

    # Combine all valid relationship types
    valid_rel_types = list(
        {r.rel_type for r in outbound_rules} | {r.rel_type for r in inbound_rules}
    )

    prompt = f"""You are deriving ArchiMate relationships for newly created {element_type} elements.

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

## Valid Identifiers
New element IDs: {json.dumps(new_ids)}
Existing element IDs: {json.dumps(existing_ids)}

## Allowed Relationship Types
{json.dumps(valid_rel_types)}

## Rules
1. ONLY create relationships that match the rules above
2. Source and target must BOTH exist in the provided identifiers
3. Use identifiers EXACTLY as shown (case-sensitive)
4. Set confidence based on how clear the relationship is (0.5-1.0)
5. Maximum 3 relationships per new element
6. If no valid relationships exist, return empty array

Return {{"relationships": []}} with source, target, relationship_type, confidence for each.
"""
    return prompt


def derive_batch_relationships(
    new_elements: list[dict[str, Any]],
    existing_elements: list[dict[str, Any]],
    element_type: str,
    outbound_rules: list[RelationshipRule],
    inbound_rules: list[RelationshipRule],
    llm_query_fn: Any,
    temperature: float | None = None,
    max_tokens: int | None = None,
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

    Returns:
        List of validated relationship dicts
    """
    if not new_elements:
        return []

    # Check if there are any applicable rules with available targets/sources
    has_outbound_targets = any(
        any(e.get("element_type") == rule.target_type for e in existing_elements)
        for rule in outbound_rules
    )
    has_inbound_sources = any(
        any(e.get("element_type") == rule.target_type for e in existing_elements)
        for rule in inbound_rules
    )

    if not has_outbound_targets and not has_inbound_sources:
        logger.debug("No applicable relationship rules for %s batch", element_type)
        return []

    # Filter existing_elements to only include relevant types (reduces prompt size)
    relevant_types = {r.target_type for r in outbound_rules} | {
        r.target_type for r in inbound_rules
    }
    filtered_existing = [
        e for e in existing_elements if e.get("element_type") in relevant_types
    ]

    logger.debug(
        "Filtered existing elements: %d -> %d (relevant types: %s)",
        len(existing_elements),
        len(filtered_existing),
        relevant_types,
    )

    prompt = build_unified_relationship_prompt(
        new_elements=new_elements,
        existing_elements=filtered_existing,
        element_type=element_type,
        outbound_rules=outbound_rules,
        inbound_rules=inbound_rules,
    )

    if not prompt:
        return []

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    try:
        response = llm_query_fn(prompt, RELATIONSHIP_SCHEMA, **llm_kwargs)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )
    except Exception as e:
        logger.error("LLM error deriving %s relationships: %s", element_type, e)
        return []

    parse_result = parse_relationship_response(response_content)

    if not parse_result["success"]:
        logger.warning(
            "Failed to parse %s relationships: %s",
            element_type,
            parse_result.get("errors"),
        )
        return []

    # Validate relationships (use filtered_existing for consistency with prompt)
    new_ids = {e.get("identifier", "") for e in new_elements}
    existing_ids = {e.get("identifier", "") for e in filtered_existing}
    all_ids = new_ids | existing_ids

    # Build valid relationship type set
    valid_types = {r.rel_type for r in outbound_rules} | {
        r.rel_type for r in inbound_rules
    }

    relationships = []
    for rel_data in parse_result.get("data", []):
        source = rel_data.get("source")
        target = rel_data.get("target")
        rel_type = rel_data.get("relationship_type")

        # Both endpoints must exist
        if source not in all_ids or target not in all_ids:
            logger.debug(
                "Skipping relationship: endpoint not found (%s -> %s)", source, target
            )
            continue

        # At least one endpoint must be from new elements
        if source not in new_ids and target not in new_ids:
            logger.debug("Skipping relationship: neither endpoint is new")
            continue

        # Validate relationship type
        if rel_type not in valid_types:
            logger.debug("Skipping relationship: invalid type %s", rel_type)
            continue

        relationships.append(
            {
                "source": source,
                "target": target,
                "relationship_type": rel_type,
                "confidence": rel_data.get("confidence", 0.5),
            }
        )

    logger.info(
        "Derived %d relationships for %s batch", len(relationships), element_type
    )
    return relationships


def derive_element_relationships(
    source_elements: list[dict[str, Any]],
    target_elements: list[dict[str, Any]],
    source_element_type: str,
    llm_query_fn: Any,
    instruction: str,
    example: str | None = None,
    valid_relationship_types: list[str] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """
    Derive relationships FROM a specific element type.

    This is called by each element module after generating its elements,
    to derive relationships to all available target elements.

    Args:
        source_elements: Elements just created by this module
        target_elements: All elements available as targets (from previous modules)
        source_element_type: The element type being processed
        llm_query_fn: Function to call LLM
        instruction: Prompt instruction from database config
        example: Example output from database config
        valid_relationship_types: Allowed relationship types
        temperature: LLM temperature override
        max_tokens: LLM max_tokens override

    Returns:
        List of relationship dicts ready for persistence
    """
    if not source_elements or not target_elements:
        return []

    prompt = build_per_element_relationship_prompt(
        source_elements=source_elements,
        target_elements=target_elements,
        source_element_type=source_element_type,
        instruction=instruction,
        example=example,
        valid_relationship_types=valid_relationship_types,
    )

    llm_kwargs = {}
    if temperature is not None:
        llm_kwargs["temperature"] = temperature
    if max_tokens is not None:
        llm_kwargs["max_tokens"] = max_tokens

    try:
        response = llm_query_fn(prompt, RELATIONSHIP_SCHEMA, **llm_kwargs)
        response_content = (
            response.content if hasattr(response, "content") else str(response)
        )
    except Exception as e:
        logger.error(f"LLM error deriving {source_element_type} relationships: {e}")
        return []

    parse_result = parse_relationship_response(response_content)

    if not parse_result["success"]:
        logger.warning(
            f"Failed to parse {source_element_type} relationships: {parse_result.get('errors')}"
        )
        return []

    # Validate and filter relationships
    source_ids = {e.get("identifier", "") for e in source_elements}
    target_ids = {e.get("identifier", "") for e in target_elements}
    valid_types = set(valid_relationship_types) if valid_relationship_types else None

    relationships = []
    for rel_data in parse_result.get("data", []):
        source = rel_data.get("source")
        target = rel_data.get("target")
        rel_type = rel_data.get("relationship_type")

        # Validate source is from this element type
        if source not in source_ids:
            logger.debug(
                f"Skipping relationship: source {source} not in {source_element_type}"
            )
            continue

        # Validate target exists
        if target not in target_ids:
            logger.debug(f"Skipping relationship: target {target} not found")
            continue

        # Validate relationship type
        if valid_types and rel_type not in valid_types:
            logger.debug(
                f"Skipping relationship: type {rel_type} not allowed for {source_element_type}"
            )
            continue

        relationships.append(
            {
                "source": source,
                "target": target,
                "relationship_type": rel_type,
                "confidence": rel_data.get("confidence", 0.5),
            }
        )

    logger.info(
        f"Derived {len(relationships)} relationships FROM {source_element_type}"
    )
    return relationships


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
    # Data structures
    "Candidate",
    "RelationshipRule",
    "GenerationResult",
    "DerivationResult",
    # Enrichment
    "get_enrichments",
    "get_enrichments_from_neo4j",
    "enrich_candidate",
    # Filtering
    "filter_by_pagerank",
    "filter_by_labels",
    "filter_by_community",
    "get_community_roots",
    "get_articulation_points",
    # Batching
    "batch_candidates",
    # Query
    "query_candidates",
    # Schemas
    "DERIVATION_SCHEMA",
    "RELATIONSHIP_SCHEMA",
    # Prompts
    "build_derivation_prompt",
    "build_relationship_prompt",
    "build_element_relationship_prompt",
    "build_per_element_relationship_prompt",
    "build_unified_relationship_prompt",
    # Parsing
    "parse_derivation_response",
    "parse_relationship_response",
    # Element building
    "sanitize_identifier",
    "build_element",
    # Relationship derivation
    "derive_element_relationships",
    "derive_batch_relationships",
    # Results
    "create_result",
]
