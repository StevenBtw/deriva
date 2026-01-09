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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization in LLM prompts."""
        return {
            "id": self.node_id,
            "name": self.name,
            "labels": self.labels,
            "properties": self.properties,
            "pagerank": round(self.pagerank, 4),
            "community": self.louvain_community,
            "kcore": self.kcore_level,
            "is_bridge": self.is_articulation_point,
            "in_degree": self.in_degree,
            "out_degree": self.out_degree,
        }


@dataclass
class GenerationResult:
    """Result from element generation."""

    success: bool
    elements_created: int = 0
    created_elements: list[dict[str, Any]] = field(default_factory=list)
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


def get_enrichments(engine: Any) -> dict[str, dict[str, Any]]:
    """
    Get all graph enrichment data from DuckDB.

    Returns:
        Dict mapping node_id to enrichment data
    """
    try:
        rows = engine.execute("""
            SELECT node_id, pagerank, louvain_community, kcore_level,
                   is_articulation_point, in_degree, out_degree
            FROM graph_enrichment
        """).fetchall()

        return {
            row[0]: {
                "pagerank": row[1] or 0.0,
                "louvain_community": row[2],
                "kcore_level": row[3] or 0,
                "is_articulation_point": row[4] or False,
                "in_degree": row[5] or 0,
                "out_degree": row[6] or 0,
            }
            for row in rows
        }
    except Exception as e:
        logger.warning(f"Failed to get enrichments: {e}")
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
) -> list[Candidate]:
    """
    Filter candidates by PageRank score.

    Args:
        candidates: List of candidates with pagerank populated
        top_n: Keep top N candidates
        percentile: Keep top X percentile (0-100)

    Returns:
        Filtered and sorted candidates (highest pagerank first)
    """
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
) -> list[list[Candidate]]:
    """
    Split candidates into batches for LLM processing.

    Args:
        candidates: List of candidates to batch
        batch_size: Maximum items per batch (default 15)

    Returns:
        List of batches
    """
    if not candidates:
        return []

    batches = []
    for i in range(0, len(candidates), batch_size):
        batches.append(candidates[i : i + batch_size])

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
    # Convert Candidate objects to dicts if needed
    if candidates and isinstance(candidates[0], Candidate):
        candidate_list = cast(list[Candidate], candidates)
        data = [c.to_dict() for c in candidate_list]
    else:
        data = candidates

    data_json = json.dumps(data, indent=2, default=str)

    return f"""You are deriving ArchiMate {element_type} elements from source code graph data.

## Instructions
{instruction}

## Candidate Nodes
These nodes have been pre-filtered as potential {element_type} candidates.
Each includes graph metrics (pagerank, community, kcore) to help assess importance.

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
    # Data structures
    "Candidate",
    "GenerationResult",
    "DerivationResult",
    # Enrichment
    "get_enrichments",
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
    # Parsing
    "parse_derivation_response",
    "parse_relationship_response",
    # Element building
    "sanitize_identifier",
    "build_element",
    # Per-element relationship derivation
    "derive_element_relationships",
    # Results
    "create_result",
]
