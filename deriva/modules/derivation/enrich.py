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
from typing import TYPE_CHECKING, Any

from solvor.articulation import articulation_points as solvor_articulation_points
from solvor.community import louvain as solvor_louvain
from solvor.kcore import kcore_decomposition as solvor_kcore
from solvor.pagerank import pagerank as solvor_pagerank

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


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

    result = solvor_louvain(
        nodes,
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
) -> dict[str, dict[str, Any]]:
    """
    Run selected algorithms and return combined enrichments.

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

    Returns:
        Dict mapping node_id to enrichment properties:
        {
            "node_123": {
                "pagerank": 0.045,
                "louvain_community": "node_100",
                "kcore_level": 3,
                "is_articulation_point": True,
                "in_degree": 5,
                "out_degree": 2,
            },
            ...
        }
    """
    if not edges:
        return {}

    params = params or {}
    enrichments: dict[str, dict[str, Any]] = defaultdict(dict)

    # Collect all node IDs from edges
    all_nodes: set[str] = set()
    for edge in edges:
        all_nodes.add(edge["source"])
        all_nodes.add(edge["target"])

    # Initialize all nodes with empty enrichments
    for node in all_nodes:
        enrichments[node] = {}

    # Run each algorithm
    if "pagerank" in algorithms:
        pr_params = params.get("pagerank", {})
        pagerank_scores = compute_pagerank(edges, **pr_params)
        for node, score in pagerank_scores.items():
            enrichments[node]["pagerank"] = score

    if "louvain" in algorithms:
        louvain_params = params.get("louvain", {})
        communities = compute_louvain(edges, **louvain_params)
        for node, community in communities.items():
            enrichments[node]["louvain_community"] = community

    if "kcore" in algorithms:
        core_levels = compute_kcore(edges)
        for node, level in core_levels.items():
            enrichments[node]["kcore_level"] = level

    if "articulation_points" in algorithms:
        ap_nodes = compute_articulation_points(edges)
        for node in all_nodes:
            enrichments[node]["is_articulation_point"] = node in ap_nodes

    if "degree" in algorithms:
        degrees = compute_degree_centrality(edges)
        for node, deg in degrees.items():
            enrichments[node]["in_degree"] = deg["in_degree"]
            enrichments[node]["out_degree"] = deg["out_degree"]

    logger.info(
        f"Graph enrichment complete: {len(algorithms)} algorithms, "
        f"{len(enrichments)} nodes enriched"
    )

    return dict(enrichments)


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    # Individual algorithms
    "compute_pagerank",
    "compute_louvain",
    "compute_kcore",
    "compute_articulation_points",
    "compute_degree_centrality",
    # Combined enrichment
    "enrich_graph",
    # Utilities
    "build_adjacency",
    "build_directed_adjacency",
]
