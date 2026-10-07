"""
Graph Enrichment Module - Pre-derivation graph metrics as node properties.

Computes the enrichment properties stored on graph nodes before derivation, the way
classification enriches files before extraction. The graph algorithms themselves run
natively in grafeo (the graph adapter's ``graph_metric``, on the extraction namespace,
PageRank undirected); this module turns their raw values into enrichments:

- PageRank: node importance, plus a percentile rank
- Louvain: community membership, named after the community's smallest node id
- K-core: core level, plus a percentile rank
- Articulation points: a flag on every node
- Degree: in and out degree, plus percentile ranks

Percentile ranks make the metrics comparable across graphs of different sizes. The
module is pure: the service runs the algorithms through the adapter and writes the
enrichments back.

Usage:
    from deriva.modules.derivation.prep import GraphMetrics, enrich_from_metrics

    metrics = GraphMetrics(node_ids=ids, edge_count=n, pagerank=scores_by_node_id)
    result = enrich_from_metrics(metrics)
    result.enrichments["node1"]["pagerank_percentile"]
    result.metadata.num_communities
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class GraphMetrics:
    """Raw graph-algorithm results keyed by node id, as the graph adapter computes them.

    Attributes:
        node_ids: Every node of the graph (nodes without edges included)
        edge_count: Number of edges between them
        pagerank: Node id to PageRank score
        communities: Node id to community number (any numbering; named here by smallest node id)
        core_levels: Node id to k-core level
        articulation_points: Node ids that are articulation points
        degrees: Node id to {"in_degree": int, "out_degree": int}
    """

    node_ids: list[str]
    edge_count: int
    pagerank: dict[str, float] | None = None
    communities: dict[str, int] | None = None
    core_levels: dict[str, int] | None = None
    articulation_points: list[str] | None = None
    degrees: dict[str, dict[str, int]] | None = None


# =============================================================================
# Percentile Normalization
# =============================================================================


def normalize_to_percentiles(values: Mapping[str, float]) -> dict[str, float]:
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

    # Tied values share their average rank, so the result does not depend on
    # input order (which follows set/dict order and differs per process)
    return normalize_to_percentiles_int(values)


def normalize_to_percentiles_int(
    values: Mapping[str, float],
) -> dict[str, float]:
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
    value_to_nodes: dict[float, list[str]] = defaultdict(list)
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
# Enrichment
# =============================================================================


def enrich_from_metrics(metrics: GraphMetrics, include_percentiles: bool = True) -> EnrichmentResult:
    """Turn raw graph-algorithm values into node enrichments and graph metadata.

    Args:
        metrics: Raw values keyed by node id (any subset of the algorithms)
        include_percentiles: Whether to add percentile ranks (default True)

    Returns:
        EnrichmentResult: per node id, the properties below for the algorithms present,
        ``pagerank`` / ``pagerank_percentile``, ``louvain_community``, ``kcore_level`` /
        ``kcore_percentile``, ``is_articulation_point``, ``in_degree`` / ``out_degree`` with
        their percentiles; and the graph metadata
    """
    if not metrics.node_ids:
        return EnrichmentResult()

    enrichments: dict[str, dict[str, Any]] = {node: {} for node in metrics.node_ids}
    metadata = GraphMetadata(total_nodes=len(metrics.node_ids), total_edges=metrics.edge_count)
    if metadata.total_nodes > 1:
        metadata.density = metadata.total_edges / (metadata.total_nodes * (metadata.total_nodes - 1))

    if metrics.pagerank:
        for node, score in metrics.pagerank.items():
            enrichments[node]["pagerank"] = score
        metadata.avg_pagerank = sum(metrics.pagerank.values()) / len(metrics.pagerank)
        metadata.max_pagerank = max(metrics.pagerank.values())
        if include_percentiles:
            for node, pct in normalize_to_percentiles(metrics.pagerank).items():
                enrichments[node]["pagerank_percentile"] = pct

    if metrics.communities:
        members: dict[int, list[str]] = defaultdict(list)
        for node, community in metrics.communities.items():
            members[community].append(node)
        # A community is named after its smallest node id, independent of the numbering
        for nodes in members.values():
            root = min(nodes)
            for node in nodes:
                enrichments[node]["louvain_community"] = root
        metadata.num_communities = len(members)

    if metrics.core_levels:
        for node, level in metrics.core_levels.items():
            enrichments[node]["kcore_level"] = level
        metadata.max_kcore = max(metrics.core_levels.values())
        if include_percentiles:
            for node, pct in normalize_to_percentiles_int(metrics.core_levels).items():
                enrichments[node]["kcore_percentile"] = pct

    if metrics.articulation_points is not None:
        points = set(metrics.articulation_points)
        for node in metrics.node_ids:
            enrichments[node]["is_articulation_point"] = node in points
        metadata.num_articulation_points = len(points)

    if metrics.degrees:
        in_degrees = {node: d["in_degree"] for node, d in metrics.degrees.items()}
        out_degrees = {node: d["out_degree"] for node, d in metrics.degrees.items()}
        for node in metrics.degrees:
            enrichments[node]["in_degree"] = in_degrees[node]
            enrichments[node]["out_degree"] = out_degrees[node]
        metadata.avg_in_degree = sum(in_degrees.values()) / len(in_degrees)
        metadata.avg_out_degree = sum(out_degrees.values()) / len(out_degrees)
        if include_percentiles:
            for node, pct in normalize_to_percentiles_int(in_degrees).items():
                enrichments[node]["in_degree_percentile"] = pct
            for node, pct in normalize_to_percentiles_int(out_degrees).items():
                enrichments[node]["out_degree_percentile"] = pct

    logger.info(
        "Graph enrichment: %d nodes (density %.4f, communities %d)",
        len(enrichments),
        metadata.density,
        metadata.num_communities,
    )
    return EnrichmentResult(enrichments=enrichments, metadata=metadata)


# =============================================================================
# Exports
# =============================================================================


__all__ = [
    "GraphMetadata",
    "EnrichmentResult",
    "GraphMetrics",
    "enrich_from_metrics",
    "normalize_to_percentiles",
    "normalize_to_percentiles_int",
]
