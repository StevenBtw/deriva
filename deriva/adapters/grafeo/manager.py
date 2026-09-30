"""Grafeo Connection Service - Embedded graph database for Deriva.

Embedded graph database connection for Deriva.
Provides the namespace-isolated interface that GraphManager and
ArchimateManager expect.

Features:
- Embedded graph database (no external server)
- Cypher query language support
- Namespace isolation via label prefixes
- Configurable storage: in-memory (default) or one persistent `.grafeo` file per
  workspace key (a repository, or the joined names for a combined run)

Usage:
    from deriva.adapters.grafeo import GrafeoConnection

    conn = GrafeoConnection(namespace="Graph")
    conn.connect()

    result = conn.execute("MATCH (n) RETURN count(n) as count")
    print(f"Total nodes: {result[0]['count']}")

    conn.disconnect()
"""

from __future__ import annotations

import logging
import os
import time
import weakref
from pathlib import Path
from typing import Any

from deriva.common.timing import query_stats
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _record_query(label: str, started: float) -> None:
    """Add a query's time to the run totals; warn above GRAFEO_SLOW_QUERY_MS (default 1000)."""
    elapsed_ms = (time.perf_counter() - started) * 1000
    query_stats.record(label, elapsed_ms)
    if elapsed_ms > float(os.getenv("GRAFEO_SLOW_QUERY_MS", "1000")):
        logger.warning("Slow graph query (%.0f ms): %s", elapsed_ms, " ".join(label.split())[:300])


# ---------------------------------------------------------------------------
# Active database (one per workspace key)
# ---------------------------------------------------------------------------

DEFAULT_DATABASE = "default"

_db: Any | None = None
_db_key: str = DEFAULT_DATABASE
# Connected GrafeoConnections; they follow the active database when it changes
_connections: weakref.WeakSet[GrafeoConnection] = weakref.WeakSet()
# Existing edges per edge type as (source node, target node, edge id), loaded on first
# use by merge_edge; dropped on any DELETE and whenever the database closes
_edge_keys: dict[str, set[tuple[int, int, Any]]] = {}


def database_file(key: str) -> str | None:
    """Path of the key's database file, or None for in-memory.

    GRAFEO_DB_DIR (e.g. ``workspace/graphs``) holds one ``<key>.grafeo`` file per
    workspace key; empty or unset means in-memory.
    """
    if os.getenv("GRAFEO_DB_PATH"):
        raise RuntimeError("GRAFEO_DB_PATH is no longer supported: set GRAFEO_DB_DIR to a directory (one <repository>.grafeo database per repository) and remove GRAFEO_DB_PATH.")
    directory = os.getenv("GRAFEO_DB_DIR", "")
    if not directory:
        return None
    if not key or key in (".", "..") or any(sep in key for sep in ("/", "\\")):
        raise ValueError(f"Invalid database key {key!r}: must be a plain file name")
    Path(directory).mkdir(parents=True, exist_ok=True)
    return str(Path(directory) / f"{key}.grafeo")


def get_database() -> Any:
    """Get or open the active GrafeoDB instance (see ``use_database``).

    Returns:
        GrafeoDB instance shared across all connections.
    """
    global _db
    if _db is None:
        from grafeo import GrafeoDB

        load_dotenv()
        path = database_file(_db_key)
        _db = GrafeoDB(path)
        # Every query is Cypher; a grafeo build without it (a narrow local build) fails here, not at the first query
        if not hasattr(_db, "execute_cypher"):
            _db.close()
            _db = None
            raise RuntimeError(
                "This grafeo build has no Cypher support, which Deriva uses for every query: install the released wheel, or build the Python binding with its default features"
            )
        # Node lookups by id (Graph) and identifier (Model) must use an index
        for key in ("id", "identifier"):
            if not _db.has_property_index(key):
                _db.create_property_index(key)

        mode = f"persistent ({path})" if path else "in-memory"
        logger.info("Opened GrafeoDB '%s' (%s)", _db_key, mode)

    return _db


def use_database(key: str) -> None:
    """Make ``key``'s database the active one; connected connections follow."""
    global _db_key
    if key == _db_key and (_db is not None or not _connections):
        return
    # Check the key before closing, so an invalid key leaves the active database in place
    database_file(key)
    close_database()
    _db_key = key
    if _connections:
        db = get_database()
        for conn in list(_connections):
            conn.db = db


def close_database() -> None:
    """Close the active database (checkpoints the file) and release it."""
    global _db
    _edge_keys.clear()
    if _db is not None:
        logger.info("Closing GrafeoDB '%s'", _db_key)
        _db.close()
        _db = None


# ---------------------------------------------------------------------------
# GrafeoConnection
# ---------------------------------------------------------------------------


class GrafeoConnection:
    """Embedded graph database connection with namespace support.

    All managers share a single embedded GrafeoDB instance; namespace
    isolation works via label prefixes (dual-label scheme).

    Example:
        >>> conn = GrafeoConnection(namespace="Graph")
        >>> conn.connect()
        >>> conn.execute("CREATE (n:Repository {name: $name})", {"name": "test"})
        >>> conn.disconnect()
    """

    def __init__(self, namespace: str):
        """Initialize connection for a given namespace.

        Args:
            namespace: Label prefix for this manager (e.g. "Graph", "Model").
        """
        self.namespace = namespace
        self.db: Any | None = None
        self._log_queries = False

        load_dotenv()
        self._log_queries = os.getenv("GRAFEO_LOG_QUERIES", "false").lower() == "true"

        logger.info("Initialized GrafeoConnection with namespace: %s", namespace)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the shared embedded database."""
        if self.db is not None:
            logger.warning("Connection already established")
            return

        self.db = get_database()
        _connections.add(self)
        logger.info("Connected to grafeo (namespace '%s')", self.namespace)

    def disconnect(self) -> None:
        """Release reference to the shared database.

        The underlying database stays alive (singleton). Call
        ``close_database()`` to fully shut down.
        """
        if self.db is not None:
            self.db = None
            _connections.discard(self)
            logger.info("Disconnected from grafeo (namespace '%s')", self.namespace)

    def __enter__(self) -> GrafeoConnection:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        """Context manager exit."""
        self.disconnect()

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results as list of dicts.

        Args:
            query: Cypher query string.
            parameters: Query parameters (``$param`` syntax).
            database: Ignored (single embedded database).

        Returns:
            List of result records as dictionaries.
        """
        if self.db is None:
            raise RuntimeError(f"Not connected to grafeo. Call connect() first. (Namespace: {self.namespace})")

        if self._log_queries:
            logger.debug("Executing query: %s", query)
            logger.debug("Parameters: %s", parameters)

        started = time.perf_counter()
        if "DELETE" in query.upper():
            _edge_keys.clear()
        try:
            params = parameters if parameters is not None else {}
            result = self.db.execute_cypher(query, params)
            return result.to_list()

        except Exception as e:
            logger.error("Query execution failed: %s", e)
            logger.error("Query: %s", query)
            logger.error("Parameters: %s", parameters)
            raise

        finally:
            _record_query(query, started)

    def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a write query (CREATE, MERGE, DELETE).

        In embedded mode there is no read/write distinction; this delegates
        to ``execute()``.
        """
        return self.execute(query, parameters, database)

    def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read query (MATCH, RETURN).

        In embedded mode there is no read/write distinction; this delegates
        to ``execute()``.
        """
        return self.execute(query, parameters, database)

    def set_node_properties(self, key: str, updates: dict[Any, dict[str, Any]]) -> int:
        """Set properties on the nodes whose ``key`` property matches, via an index.

        Args:
            key: Property identifying the nodes (e.g. "id").
            updates: Mapping of key value to the properties to set.

        Returns:
            Number of nodes updated (unknown key values are skipped).
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        if not self.db.has_property_index(key):
            self.db.create_property_index(key)
        count = 0
        for value, props in updates.items():
            if not props:
                continue
            for node in self._find_nodes(key, value):
                # The database is shared by all namespaces; touch only this one's nodes
                if self.namespace not in (self.db.get_node_labels(node) or []):
                    continue
                for name, prop in props.items():
                    self.db.set_node_property(node, name, prop)
                count += 1
        _record_query(f"set_node_properties({key})", started)
        return count

    def _find_nodes(self, key: str, value: Any) -> list[int]:
        """Nodes with ``key`` = ``value`` via the property index (deleted nodes are not returned)."""
        assert self.db is not None
        return list(self.db.find_nodes_by_property(key, value))

    def merge_node(self, key: str, value: Any, labels: list[str], properties: dict[str, Any]) -> None:
        """Set ``properties`` on the node with ``key`` = ``value`` and all ``labels``, or create it.

        Same semantics as ``MERGE (n:L1:L2 {key: value}) SET n += properties``, but
        the node is found through the property index instead of a label scan.
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        wanted = set(labels)
        matches = [node for node in self._find_nodes(key, value) if wanted <= set(self.db.get_node_labels(node) or [])]
        for node in matches:
            for name, prop in properties.items():
                self.db.set_node_property(node, name, prop)
        if not matches:
            self.db.create_node(labels, {key: value, **properties})
        _record_query(f"merge_node({':'.join(labels)})", started)

    def merge_edge(
        self,
        key: str,
        src_value: Any,
        dst_value: Any,
        edge_type: str,
        edge_id: str,
        properties: dict[str, Any],
    ) -> bool:
        """Create or update an edge between the nodes whose ``key`` matches, via the index.

        An existing edge of ``edge_type`` with the same ``id`` between the same nodes
        is updated instead of duplicated. Returns False when an endpoint is missing.
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        sources = self._find_nodes(key, src_value)
        targets = self._find_nodes(key, dst_value)
        if not (sources and targets):
            _record_query(f"merge_edge({edge_type})", started)
            return False

        existing = _edge_keys.get(edge_type)
        if existing is None:
            # One scan per edge type instead of a lookup per edge: a lookup by endpoint
            # ids scans every edge of the type (3.45 ms per call at 10,000 edges on
            # grafeo 0.5.43, against about 11 ms for this whole scan)
            existing = {(row["s"], row["d"], row["id"]) for row in self.execute(f"MATCH (s)-[r:`{edge_type}`]->(d) RETURN id(s) AS s, id(d) AS d, r.id AS id")}
            _edge_keys[edge_type] = existing
            started = time.perf_counter()

        for src in sources:
            for dst in targets:
                if (src, dst, edge_id) in existing:
                    rows = self.db.execute_cypher(
                        f"MATCH (s)-[r:`{edge_type}`]->(d) WHERE id(s) = $s AND id(d) = $d RETURN id(r) AS eid, r.id AS id",
                        {"s": src, "d": dst},
                    ).to_list()
                    for row in rows:
                        if row["id"] == edge_id:
                            for name, value in properties.items():
                                self.db.set_edge_property(row["eid"], name, value)
                else:
                    self.db.create_edge(src, dst, edge_type, {"id": edge_id, **properties})
                    existing.add((src, dst, edge_id))
        _record_query(f"merge_edge({edge_type})", started)
        return True

    # ------------------------------------------------------------------
    # Namespace helpers
    # ------------------------------------------------------------------

    def get_label(self, base_label: str) -> str:
        """Get namespaced label.

        Args:
            base_label: Base label name (e.g. "Repository", "Element").

        Returns:
            Namespaced label (e.g. "Graph:Repository", "Model:Element").
        """
        return f"{self.namespace}:{base_label}"

    def clear_namespace(self) -> None:
        """Delete all nodes and relationships in this namespace."""
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            self.execute(
                "MATCH (n) WHERE any(label IN labels(n) WHERE label STARTS WITH $namespace) DETACH DELETE n",
                {"namespace": self.namespace},
            )
            logger.info("Cleared all data for namespace: %s", self.namespace)

        except Exception as e:
            logger.error("Failed to clear namespace %s: %s", self.namespace, e)
            raise
