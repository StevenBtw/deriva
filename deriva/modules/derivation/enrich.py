"""
Graph Enrichment Module - Pre-derivation graph analysis using solvor.

Computes graph algorithm properties that are stored as Neo4j node properties.
Similar to how classification enriches files before extraction,
enrich prepares graph metrics before derivation.

This module contains pure functions that:
1. Take nodes and edges in a simple format
2. Run graph algorithms via solvor
3. Return enrichment dicts ready for Neo4j property updates

The service layer handles Neo4j I/O - this module has no I/O dependencies.

Algorithms:
- PageRank: Node importance/centrality
- Louvain: Community detection (natural component boundaries)
- K-core: Core vs peripheral node classification
- Articulation points: Bridge nodes (structural importance)
- Degree centrality: In/out connectivity

All algorithms treat the graph as undirected for structural analysis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from solvor.articulation import articulation_points as solvor_articulation_points
from solvor.community import louvain as solvor_louvain
from solvor.kcore import kcore_decomposition as solvor_kcore
from solvor.pagerank import pagerank as solvor_pagerank

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class GraphMetadata:
    """Metadata about the graph for scale-aware processing.

    This information helps downstream steps (refine, derivation) adapt
    their thresholds and behavior based on graph characteristics.
    """

    total_nodes: int = 0
    total_edges: int = 0
    max_kcore: int = 0
    num_communities: int = 0
    num_articulation_points: int = 0
    avg_pagerank: float = 0.0
    max_pagerank: float = 0.0
    avg_in_degree: float = 0.0
    avg_out_degree: float = 0.0
    density: float = 0.0  # edges / (nodes * (nodes-1))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "max_kcore": self.max_kcore,
            "num_communities": self.num_communities,
            "num_articulation_points": self.num_articulation_points,
            "avg_pagerank": round(self.avg_pagerank, 6),
            "max_pagerank": round(self.max_pagerank, 6),
            "avg_in_degree": round(self.avg_in_degree, 2),
            "avg_out_degree": round(self.avg_out_degree, 2),
            "density": round(self.density, 6),
        }


@dataclass
class EnrichmentResult:
    """Result from graph enrichment including node properties and metadata.

    Attributes:
        enrichments: Dict mapping node_id to enrichment properties
        metadata: Graph-level statistics for scale-aware processing
    """

    enrichments: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: GraphMetadata = field(default_factory=GraphMetadata)


# =============================================================================
# Percentile Normalization
# =============================================================================


def normalize_to_percentiles(values: dict[str, float | int]) -> dict[str, float]:
    """
    Convert absolute values to percentile ranks (0-100).

    This makes metrics comparable across graphs of different sizes.
    A node in the 90th percentile is "more important than 90% of nodes"
    regardless of whether the graph has 50 or 5000 nodes.

    Args:
        values: Dict mapping node_id to absolute value

    Returns:
        Dict mapping node_id to percentile rank (0-100)

    Example:
        >>> normalize_to_percentiles({"a": 0.1, "b": 0.5, "c": 0.3})
        {"a": 0.0, "c": 50.0, "b": 100.0}
    """
    if not values:
        return {}

    n = len(values)
    if n == 1:
        # Single node is at 100th percentile by definition
        return {k: 100.0 for k in values}

    # Sort by value (ascending)
    sorted_items = sorted(values.items(), key=lambda x: x[1])

    # Assign percentile ranks
    # Using (rank / (n-1)) * 100 to get 0-100 range
    result: dict[str, float] = {}
    for rank, (node_id, _) in enumerate(sorted_items):
        percentile = (rank / (n - 1)) * 100.0
        result[node_id] = round(percentile, 2)

    return result


def normalize_to_percentiles_int(values: dict[str, int]) -> dict[str, float]:
    """
    Convert integer values to percentile ranks, handling ties.

    For discrete values like k-core levels, nodes with the same value
    get the same percentile (average of their rank range).

    Args:
        values: Dict mapping node_id to integer value

    Returns:
        Dict mapping node_id to percentile rank (0-100)
    """
    if not values:
        return {}

    n = len(values)
    if n == 1:
        return {k: 100.0 for k in values}

    # Group nodes by value
    value_to_nodes: dict[int, list[str]] = defaultdict(list)
    for node_id, val in values.items():
        value_to_nodes[val].append(node_id)

    # Sort unique values
    sorted_values = sorted(value_to_nodes.keys())

    # Assign percentile based on cumulative position
    result: dict[str, float] = {}
    cumulative = 0
    for val in sorted_values:
        nodes = value_to_nodes[val]
        count = len(nodes)
        # Average rank for this group
        avg_rank = cumulative + (count - 1) / 2
        percentile = (avg_rank / (n - 1)) * 100.0 if n > 1 else 100.0
        for node_id in nodes:
            result[node_id] = round(percentile, 2)
        cumulative += count

    return result


# =============================================================================
# Graph Building Utilities
# =============================================================================


def build_adjacency(
    edges: list[dict[str, str]],
) -> tuple[set[str], dict[str, set[str]]]:
    """
    Build undirected adjacency from edge list.

    Args:
        edges: List of edges with 'source' and 'target' keys

    Returns:
        Tuple of (node_set, adjacency_dict)
        adjacency_dict maps node_id -> set of neighbor node_ids
    """
    nodes: set[str] = set()
    adj: dict[str, set[str]] = defaultdict(set)

    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        nodes.add(src)
        nodes.add(tgt)
        # Undirected: add both directions
        adj[src].add(tgt)
        adj[tgt].add(src)

    return nodes, dict(adj)


def build_directed_adjacency(
    edges: list[dict[str, str]],
) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    """
    Build directed adjacency from edge list.

    Args:
        edges: List of edges with 'source' and 'target' keys

    Returns:
        Tuple of (node_set, outgoing_adj, incoming_adj)
    """
    nodes: set[str] = set()
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)

    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        nodes.add(src)
        nodes.add(tgt)
        outgoing[src].add(tgt)
        incoming[tgt].add(src)

    return nodes, dict(outgoing), dict(incoming)


def neighbors_fn(adj: dict[str, set[str]]) -> Callable[[str], set[str]]:
    """Create a neighbors function for solvor from adjacency dict."""
    return lambda node: adj.get(node, set())


# =============================================================================
# Individual Algorithm Functions
# =============================================================================


def compute_pagerank(
    edges: list[dict[str, str]],
    damping: float = 0.85,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> dict[str, float]:
    """
    Compute PageRank scores for nodes.

    Uses undirected edges to measure structural importance/centrality.
    Higher scores indicate more connected/important nodes.

    Args:
        edges: List of edges with 'source' and 'target' keys
        damping: Damping factor (default 0.85)
        max_iter: Maximum iterations (default 100)
        tol: Convergence tolerance (default 1e-6)

    Returns:
        Dict mapping node_id to pagerank score (float, sums to ~1.0)
    """
    nodes, adj = build_adjacency(edges)

    if not nodes:
        return {}

    result = solvor_pagerank(
        nodes,
        neighbors_fn(adj),
        damping=damping,
        max_iter=max_iter,
        tol=tol,
    )

    logger.debug(
        f"PageRank computed for {len(nodes)} nodes in {result.iterations} iterations"
    )
    return result.solution


def compute_louvain(
    edges: list[dict[str, str]],
    resolution: float = 1.0,
) -> dict[str, str]:
    """
    Detect communities using Louvain algorithm.

    Returns the community assignment for each node, identified by
    a representative node (the first node in the community).

    Args:
        edges: List of edges with 'source' and 'target' keys
        resolution: Modularity resolution (default 1.0, higher = smaller communities)

    Returns:
        Dict mapping node_id to community_id (str, a representative node_id)
    """
    nodes, adj = build_adjacency(edges)

    if not nodes:
        return {}

    # Sort nodes for deterministic processing order in Louvain algorithm
    # This ensures consistent community assignments across runs
    sorted_nodes = sorted(nodes)

    result = solvor_louvain(
        sorted_nodes,
        neighbors_fn(adj),
        resolution=resolution,
    )

    # Convert list of sets to node -> community_root mapping
    # Use the first node in each community as the community identifier
    node_to_community: dict[str, str] = {}
    for community in result.solution:
        if community:
            # Sort for deterministic community ID
            community_list = sorted(community)
            community_id = community_list[0]
            for node in community:
                node_to_community[node] = community_id

    logger.debug(
        f"Louvain found {len(result.solution)} communities "
        f"for {len(nodes)} nodes (modularity: {result.objective:.3f})"
    )
    return node_to_community


def compute_kcore(
    edges: list[dict[str, str]],
) -> dict[str, int]:
    """
    Compute k-core decomposition.

    Returns the core number for each node. Higher core numbers indicate
    nodes in denser, more connected regions (the "core" vs "periphery").

    Args:
        edges: List of edges with 'source' and 'target' keys

    Returns:
        Dict mapping node_id to core_level (int, 0 = isolated)
    """
    nodes, adj = build_adjacency(edges)

    if not nodes:
        return {}

    result = solvor_kcore(
        nodes,
        neighbors_fn(adj),
    )

    max_core = result.objective
    logger.debug(f"K-core computed for {len(nodes)} nodes (max core: {max_core})")
    return result.solution


def compute_articulation_points(
    edges: list[dict[str, str]],
) -> set[str]:
    """
    Find articulation points (bridge nodes).

    Articulation points are nodes whose removal would disconnect the graph.
    These are critical nodes that bridge different parts of the codebase.

    Args:
        edges: List of edges with 'source' and 'target' keys

    Returns:
        Set of node_ids that are articulation points
    """
    nodes, adj = build_adjacency(edges)

    if not nodes:
        return set()

    result = solvor_articulation_points(
        nodes,
        neighbors_fn(adj),
    )

    logger.debug(
        f"Found {len(result.solution)} articulation points in {len(nodes)} nodes"
    )
    return result.solution


def compute_degree_centrality(
    edges: list[dict[str, str]],
) -> dict[str, dict[str, int]]:
    """
    Compute in-degree and out-degree for each node.

    Uses directed edges to compute directional degree counts.

    Args:
        edges: List of edges with 'source' and 'target' keys

    Returns:
        Dict mapping node_id to {"in_degree": int, "out_degree": int}
    """
    nodes, outgoing, incoming = build_directed_adjacency(edges)

    result: dict[str, dict[str, int]] = {}
    for node in nodes:
        result[node] = {
            "in_degree": len(incoming.get(node, set())),
            "out_degree": len(outgoing.get(node, set())),
        }

    return result


# =============================================================================
# Combined Enrichment Function
# =============================================================================


def enrich_graph(
    edges: list[dict[str, str]],
    algorithms: list[str],
    params: dict[str, dict[str, Any]] | None = None,
    include_percentiles: bool = True,
) -> EnrichmentResult:
    """
    Run selected algorithms and return combined enrichments with metadata.

    This is the main entry point for graph enrichment. It runs the specified
    algorithms and combines their results into a single dict per node.

    Args:
        edges: List of edges with 'source' and 'target' keys
        algorithms: List of algorithm names to run:
            - "pagerank": Node importance scores
            - "louvain": Community detection
            - "kcore": Core decomposition
            - "articulation_points": Bridge node detection
            - "degree": In/out degree centrality
        params: Optional algorithm-specific parameters:
            {
                "pagerank": {"damping": 0.85, "max_iter": 100},
                "louvain": {"resolution": 1.0},
            }
        include_percentiles: Whether to compute percentile ranks (default True).
            Percentiles make metrics comparable across different graph sizes.

    Returns:
        EnrichmentResult containing:
        - enrichments: Dict mapping node_id to properties:
            {
                "node_123": {
                    "pagerank": 0.045,
                    "pagerank_percentile": 85.5,  # scale-independent
                    "louvain_community": "node_100",
                    "kcore_level": 3,
                    "kcore_percentile": 70.0,  # scale-independent
                    "is_articulation_point": True,
                    "in_degree": 5,
                    "in_degree_percentile": 90.0,
                    "out_degree": 2,
                    "out_degree_percentile": 45.0,
                },
                ...
            }
        - metadata: GraphMetadata with graph-level statistics
    """
    if not edges:
        return EnrichmentResult()

    params = params or {}
    enrichments: dict[str, dict[str, Any]] = defaultdict(dict)
    metadata = GraphMetadata()

    # Collect all node IDs from edges
    all_nodes: set[str] = set()
    for edge in edges:
        all_nodes.add(edge["source"])
        all_nodes.add(edge["target"])

    # Initialize all nodes with empty enrichments
    for node in all_nodes:
        enrichments[node] = {}

    # Set basic metadata
    metadata.total_nodes = len(all_nodes)
    metadata.total_edges = len(edges)
    if metadata.total_nodes > 1:
        max_possible_edges = metadata.total_nodes * (metadata.total_nodes - 1)
        metadata.density = metadata.total_edges / max_possible_edges

    # Track raw values for percentile computation
    pagerank_scores: dict[str, float] = {}
    core_levels: dict[str, int] = {}
    in_degrees: dict[str, int] = {}
    out_degrees: dict[str, int] = {}

    # Run each algorithm
    if "pagerank" in algorithms:
        pr_params = params.get("pagerank", {})
        pagerank_scores = compute_pagerank(edges, **pr_params)
        for node, score in pagerank_scores.items():
            enrichments[node]["pagerank"] = score

        # Update metadata
        if pagerank_scores:
            metadata.avg_pagerank = sum(pagerank_scores.values()) / len(pagerank_scores)
            metadata.max_pagerank = max(pagerank_scores.values())

        # Compute percentiles
        if include_percentiles and pagerank_scores:
            percentiles = normalize_to_percentiles(pagerank_scores)
            for node, pct in percentiles.items():
                enrichments[node]["pagerank_percentile"] = pct

    if "louvain" in algorithms:
        louvain_params = params.get("louvain", {})
        communities = compute_louvain(edges, **louvain_params)
        for node, community in communities.items():
            enrichments[node]["louvain_community"] = community

        # Update metadata
        metadata.num_communities = len(set(communities.values()))

    if "kcore" in algorithms:
        core_levels = compute_kcore(edges)
        for node, level in core_levels.items():
            enrichments[node]["kcore_level"] = level

        # Update metadata
        if core_levels:
            metadata.max_kcore = max(core_levels.values())

        # Compute percentiles (handles ties for discrete values)
        if include_percentiles and core_levels:
            percentiles = normalize_to_percentiles_int(core_levels)
            for node, pct in percentiles.items():
                enrichments[node]["kcore_percentile"] = pct

    if "articulation_points" in algorithms:
        ap_nodes = compute_articulation_points(edges)
        for node in all_nodes:
            enrichments[node]["is_articulation_point"] = node in ap_nodes

        # Update metadata
        metadata.num_articulation_points = len(ap_nodes)

    if "degree" in algorithms:
        degrees = compute_degree_centrality(edges)
        for node, deg in degrees.items():
            enrichments[node]["in_degree"] = deg["in_degree"]
            enrichments[node]["out_degree"] = deg["out_degree"]
            in_degrees[node] = deg["in_degree"]
            out_degrees[node] = deg["out_degree"]

        # Update metadata
        if degrees:
            metadata.avg_in_degree = sum(in_degrees.values()) / len(in_degrees)
            metadata.avg_out_degree = sum(out_degrees.values()) / len(out_degrees)

        # Compute percentiles
        if include_percentiles:
            if in_degrees:
                in_pcts = normalize_to_percentiles_int(in_degrees)
                for node, pct in in_pcts.items():
                    enrichments[node]["in_degree_percentile"] = pct
            if out_degrees:
                out_pcts = normalize_to_percentiles_int(out_degrees)
                for node, pct in out_pcts.items():
                    enrichments[node]["out_degree_percentile"] = pct

    logger.info(
        "Graph enrichment complete: %d algorithms, %d nodes enriched "
        "(density: %.4f, communities: %d)",
        len(algorithms),
        len(enrichments),
        metadata.density,
        metadata.num_communities,
    )

    return EnrichmentResult(enrichments=dict(enrichments), metadata=metadata)


def enrich_graph_legacy(
    edges: list[dict[str, str]],
    algorithms: list[str],
    params: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Legacy wrapper that returns only the enrichments dict.

    For backwards compatibility with code expecting just the dict.
    New code should use enrich_graph() which returns EnrichmentResult.
    """
    result = enrich_graph(edges, algorithms, params, include_percentiles=True)
    return result.enrichments


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Data structures
    "GraphMetadata",
    "EnrichmentResult",
    # Individual algorithms
    "compute_pagerank",
    "compute_louvain",
    "compute_kcore",
    "compute_articulation_points",
    "compute_degree_centrality",
    # Combined enrichment
    "enrich_graph",
    "enrich_graph_legacy",
    # Percentile normalization
    "normalize_to_percentiles",
    "normalize_to_percentiles_int",
    # Utilities
    "build_adjacency",
    "build_directed_adjacency",
]
