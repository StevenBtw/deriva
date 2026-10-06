"""
Caching functionality for graph operations.

Provides caching for graph query results, keyed by the query and a graph
state hash supplied by the caller.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from deriva.common.cache_utils import BaseDiskCache, hash_inputs

# Default graph cache directory (can be overridden via GRAPH_CACHE_DIR env var)
GRAPH_CACHE_DIR = os.getenv("GRAPH_CACHE_DIR", "workspace/cache/graph")

logger = logging.getLogger(__name__)


class QueryCache(BaseDiskCache):
    """
    Cache for Cypher query results.

    Caches query results keyed by query string + graph state hash.
    Useful for queries that are repeated multiple times per run.

    Example:
        cache = QueryCache()
        graph_hash = compute_graph_hash(graph_manager)

        cache_key = cache.generate_key(cypher_query, graph_hash)
        if cached := cache.get(cache_key):
            return cached["results"]

        results = graph_manager.query(cypher_query)
        cache.set(cache_key, {"results": results})
        return results
    """

    def __init__(self, cache_dir: str | None = None):
        """
        Initialize query cache.

        Args:
            cache_dir: Directory to store cache files (default: GRAPH_CACHE_DIR/queries)
        """
        if cache_dir is None:
            cache_dir = f"{GRAPH_CACHE_DIR}/queries"
        super().__init__(cache_dir)

    @staticmethod
    def generate_key(query: str, graph_hash: str) -> str:
        """
        Generate cache key for a query.

        Args:
            query: Cypher query string
            graph_hash: Hash from compute_graph_hash()

        Returns:
            SHA256 hash as cache key
        """
        return hash_inputs(query, graph_hash)

    def get_results(self, query: str, graph_hash: str) -> list[dict[str, Any]] | None:
        """
        Get cached query results.

        Args:
            query: Cypher query string
            graph_hash: Hash from compute_graph_hash()

        Returns:
            Query results or None if not cached
        """
        cache_key = self.generate_key(query, graph_hash)
        cached = self.get(cache_key)
        if cached is not None:
            return cached.get("results")
        return None

    def set_results(self, query: str, graph_hash: str, results: list[dict[str, Any]]) -> None:
        """
        Cache query results.

        Args:
            query: Cypher query string
            graph_hash: Hash from compute_graph_hash()
            results: Query results to cache
        """
        cache_key = self.generate_key(query, graph_hash)
        self.set(cache_key, {"results": results, "query": query[:200]})


__all__ = [
    "QueryCache",
]
