"""
PageRank preparation step.

Computes PageRank scores on graph nodes to identify importance.
Stores scores as `pagerank` property on each node.
"""

from __future__ import annotations

from typing import Any

from solvor import pagerank

from deriva.common.types import PipelineResult

from .base import create_result


def run_pagerank(
    graph_manager: Any, params: dict[str, Any] | None = None
) -> PipelineResult:
    """
    Run PageRank on graph nodes and store scores.

    Args:
        graph_manager: Connected GraphManager instance
        params: Optional {damping, max_iterations, tolerance}

    Returns:
        Result dict with success, errors, stats
    """
    params = params or {}
    damping = params.get("damping", 0.85)
    max_iter = params.get("max_iterations", 100)
    tol = params.get("tolerance", 1e-6)

    # Get active nodes
    nodes_result = graph_manager.query(
        """
        MATCH (n)
        WHERE any(label IN labels(n) WHERE label STARTS WITH 'Graph:')
          AND n.active = true
        RETURN n.id as id
        """
    )
    node_ids = [r["id"] for r in nodes_result]

    if not node_ids:
        return create_result(True, errors=["No active nodes"], stats={"nodes": 0})

    # Get edges
    edges_result = graph_manager.query(
        """
        MATCH (src)-[r]->(dst)
        WHERE any(label IN labels(src) WHERE label STARTS WITH 'Graph:')
          AND any(label IN labels(dst) WHERE label STARTS WITH 'Graph:')
          AND src.active = true AND dst.active = true
        RETURN src.id as src, dst.id as dst
        """
    )

    # Build adjacency
    adjacency: dict[str, list[str]] = {n: [] for n in node_ids}
    for edge in edges_result:
        src, dst = edge["src"], edge["dst"]
        if src in adjacency:
            adjacency[src].append(dst)

    def neighbors(node_id: str) -> list[str]:
        return adjacency.get(node_id, [])

    # Compute PageRank
    result = pagerank(node_ids, neighbors, damping=damping, max_iter=max_iter, tol=tol)

    if not result.ok:
        return create_result(False, errors=[f"PageRank failed: {result.error}"])

    scores: dict[str, float] = result.solution

    # Store scores on nodes
    updated = 0
    for node_id, score in scores.items():
        try:
            graph_manager.update_node_property(node_id, "pagerank", score)
            updated += 1
        except Exception:
            pass  # Log but continue

    # Get top nodes
    sorted_nodes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_5 = [{"id": n, "score": round(s, 4)} for n, s in sorted_nodes[:5]]

    return create_result(
        True,
        stats={
            "nodes": len(node_ids),
            "edges": len(edges_result),
            "updated": updated,
            "top_nodes": top_5,
            "max_score": round(max(scores.values()), 4) if scores else 0,
            "avg_score": round(sum(scores.values()) / len(scores), 4) if scores else 0,
        },
    )


__all__ = ["run_pagerank"]
