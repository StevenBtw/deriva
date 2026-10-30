"""Grafeo Connection Service - Embedded graph database for Deriva.

Embedded graph database connection for Deriva.
Provides the namespace-isolated interface that GraphManager and
ArchimateManager expect.

Features:
- Embedded graph database (no external server)
- ISO GQL queries by default; Cypher when GRAFEO_QUERY_LANGUAGE=cypher
- Namespace isolation via label prefixes
- Configurable storage: one persistent `.grafeo` file per workspace key (a repository,
  or the joined names for a combined run) in `workspace/graphs` of the home folder
  (default), or in-memory

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
import re
import shutil
import time
import weakref
from pathlib import Path
from typing import Any

from deriva.common.paths import resolve
from deriva.common.settings import QUERY_LANGUAGES, GrafeoSettings
from deriva.common.timing import query_stats

logger = logging.getLogger(__name__)


def _record_query(label: str, started: float, slow_ms: float) -> None:
    """Add a query's time to the run totals; warn above the connection's GRAFEO_SLOW_QUERY_MS (default 1000)."""
    elapsed_ms = (time.perf_counter() - started) * 1000
    query_stats.record(label, elapsed_ms)
    if elapsed_ms > slow_ms:
        logger.warning("Slow graph query (%.0f ms): %s", elapsed_ms, " ".join(label.split())[:300])


# ---------------------------------------------------------------------------
# Active database (one per workspace key)
# ---------------------------------------------------------------------------

DEFAULT_DATABASE = "default"
_LANGUAGE_NAMES = {"gql": "GQL", "cypher": "Cypher"}
# String literals and quoted names hold no statement (line comments are kept: `--` is also a Cypher edge); GQL runs
# transaction and session statements inside a transaction (grafeo 0.6.0 commits its writes on COMMIT), so the
# rolled-back path refuses them
_NO_STATEMENT = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`|/\*.*?\*/", re.DOTALL)
_ENDS_TRANSACTION = re.compile(r"(?<![.\w])(COMMIT|ROLLBACK|SESSION|START\s+TRANSACTION)(?!\w)", re.IGNORECASE)

_db: Any | None = None
_db_key: str = DEFAULT_DATABASE
# Connected GrafeoConnections; they follow the active database when it changes
_connections: weakref.WeakSet[GrafeoConnection] = weakref.WeakSet()


def database_file(key: str) -> str | None:
    """Path of the key's database file, or None for in-memory.

    GRAFEO_DB_DIR (e.g. ``workspace/graphs``, relative to the Deriva home folder) holds one ``<key>.grafeo`` file per
    workspace key (the default); an empty value means in-memory.
    """
    grafeo = GrafeoSettings()
    if grafeo.db_path:
        raise RuntimeError("GRAFEO_DB_PATH is no longer supported: set GRAFEO_DB_DIR to a directory (one <repository>.grafeo database per repository) and remove GRAFEO_DB_PATH.")
    directory = grafeo.db_dir
    if not directory:
        return None
    if not key or key in (".", "..") or any(sep in key for sep in ("/", "\\")):
        raise ValueError(f"Invalid database key {key!r}: must be a plain file name")
    folder = resolve(directory)
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder / f"{key}.grafeo")


def _stored_paths(key: str) -> tuple[Path, Path] | None:
    """The key's database file and its write-ahead log folder, never created (None in memory or for an invalid key)."""
    directory = GrafeoSettings().db_dir
    if not directory or not key or key in (".", "..") or any(sep in key for sep in ("/", "\\")):
        return None
    folder = resolve(directory)
    return folder / f"{key}.grafeo", folder / f"{key}.grafeo.wal"


def database_exists(key: str) -> bool:
    """Whether the key's database file exists; never creates it or its folder (False in memory or for an invalid key)."""
    paths = _stored_paths(key)
    return paths is not None and paths[0].exists()


def list_databases() -> list[str]:
    """The keys with a database file in GRAFEO_DB_DIR, sorted (none in memory)."""
    directory = GrafeoSettings().db_dir
    folder = resolve(directory) if directory else None
    if folder is None or not folder.is_dir():
        return []
    return sorted(path.name.removesuffix(".grafeo") for path in folder.glob("*.grafeo") if path.is_file())


def database_bytes(key: str) -> int:
    """Bytes the key's database takes on disk: its file and its write-ahead log (0 when it has none)."""
    paths = _stored_paths(key)
    if paths is None:
        return 0
    database, log = paths
    size = database.stat().st_size if database.is_file() else 0
    return size + (sum(f.stat().st_size for f in log.rglob("*") if f.is_file()) if log.is_dir() else 0)


def delete_database(key: str) -> bool:
    """Delete the key's database file and log; False when it had none. The active database is never deleted (switch
    away first): a query after the delete would create a new, empty file."""
    if key == _db_key:
        raise ValueError(f"The database {key!r} is open; switch to another one before deleting it")
    paths = _stored_paths(key)
    if paths is None or not (paths[0].exists() or paths[1].exists()):
        return False
    database, log = paths
    database.unlink(missing_ok=True)
    if log.is_dir():
        shutil.rmtree(log)
    return True


def get_database() -> Any:
    """Get or open the active GrafeoDB instance (see ``use_database``).

    Returns:
        GrafeoDB instance shared across all connections.
    """
    global _db
    if _db is None:
        import grafeo

        # Every query is in GRAFEO_QUERY_LANGUAGE; a grafeo build without it (a narrow local build) is refused before a file opens
        language = GrafeoSettings().query_language
        if language not in grafeo.features():
            raise RuntimeError(
                f"This grafeo build has no {_LANGUAGE_NAMES[language]} support, which Deriva uses for every query (GRAFEO_QUERY_LANGUAGE={language}): "
                "install the released wheel, or build the Python binding with its default features"
            )
        path = database_file(_db_key)
        _db = grafeo.GrafeoDB(path)
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
    if _db is not None:
        logger.info("Closing GrafeoDB '%s'", _db_key)
        _db.close()
        _db = None


def engine_info() -> dict[str, Any]:
    """The grafeo engine's build (version, commit, dirty flag, features), for run records."""
    import grafeo

    return dict(grafeo.build_info())


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

        grafeo = GrafeoSettings()
        self._log_queries = grafeo.log_queries
        self._slow_query_ms = grafeo.slow_query_ms
        self.query_language = grafeo.query_language

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
        """Execute a query in the connection's query language (GQL by default) and return results as list of dicts.

        Args:
            query: Query string.
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
        try:
            params = parameters if parameters is not None else {}
            result = self.db.execute(query, params) if self.query_language == "gql" else self.db.execute_cypher(query, params)
            return result.to_list()

        except Exception as e:
            logger.error("Query execution failed: %s", e)
            logger.error("Query: %s", query)
            logger.error("Parameters: %s", parameters)
            raise

        finally:
            _record_query(query, started, self._slow_query_ms)

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

    def execute_rolled_back(self, query: str, parameters: dict[str, Any] | None = None, language: str | None = None) -> list[dict[str, Any]]:
        """Run a query inside a transaction that is always rolled back: reads see the data, writes never persist.

        Used for queries typed by a user (the studio's graph view), where nothing may change the graph. ``language``
        (gql or cypher) overrides the connection's query language for this query.
        """
        if self.db is None:
            raise RuntimeError(f"Not connected to grafeo. Call connect() first. (Namespace: {self.namespace})")
        language = self.query_language if language is None else language.strip().lower()
        if language not in QUERY_LANGUAGES:
            raise ValueError(f"Unknown query language {language!r}: one of {', '.join(QUERY_LANGUAGES)}")
        if _ENDS_TRANSACTION.search(_NO_STATEMENT.sub(" ", query)):
            raise ValueError("A read-only query cannot run transaction or session statements (COMMIT, ROLLBACK, START TRANSACTION, SESSION)")
        started = time.perf_counter()
        transaction = self.db.begin_transaction()
        try:
            params = parameters if parameters is not None else {}
            result = transaction.execute(query, params) if language == "gql" else transaction.execute_cypher(query, params)
            return result.to_list()
        finally:
            transaction.rollback()
            _record_query(query, started, self._slow_query_ms)

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
        _record_query(f"set_node_properties({key})", started, self._slow_query_ms)
        return count

    def _find_nodes(self, key: str, value: Any) -> list[int]:
        """Nodes with ``key`` = ``value`` via the property index (deleted nodes are not returned)."""
        assert self.db is not None
        return list(self.db.find_nodes_by_property(key, value))

    def merge_node(self, key: str, value: Any, labels: list[str], properties: dict[str, Any], replace: bool = False) -> None:
        """Create or update the node with ``key`` = ``value`` and all ``labels``, through grafeo's index-backed upsert.

        By default ``properties`` are merged into the stored ones and a None value removes that
        property; with ``replace`` the stored properties become exactly ``{key: value, **properties}``.
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        self.db.upsert_nodes(labels, [{key: value, **properties}], key=key, replace=replace)
        _record_query(f"merge_node({':'.join(labels)})", started, self._slow_query_ms)

    def merge_edge(
        self,
        key: str,
        src_value: Any,
        dst_value: Any,
        edge_type: str,
        edge_id: str,
        properties: dict[str, Any],
    ) -> bool:
        """Create or replace the ``edge_type`` edge with ``id`` = ``edge_id`` between this namespace's nodes whose ``key`` matches.

        The edge's properties become exactly ``{"id": edge_id, **properties}``. Returns False when an
        endpoint is missing.
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        # Endpoint fields named so that no edge property can collide with them
        row = {"__src": src_value, "__dst": dst_value, "id": edge_id, **properties}
        result = self.db.upsert_edges(edge_type, [row], key="id", endpoint_key=key, endpoint_labels=[self.namespace], src_field="__src", dst_field="__dst", replace=True)
        _record_query(f"merge_edge({edge_type})", started, self._slow_query_ms)
        return not result["skipped"]

    def algorithm(self, name: str, **kwargs: Any) -> Any:
        """Run one of grafeo's graph algorithms (``db.algorithms.<name>``) on this namespace only.

        The algorithm sees a projection on the namespace label, so the other namespace in the same
        database is never scored. Results are keyed by grafeo's internal node ids.
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        started = time.perf_counter()
        try:
            self.db.create_projection(self.namespace, node_labels=[self.namespace])  # False when it exists
            return getattr(self.db.algorithms, name)(projection=self.namespace, **kwargs)
        finally:
            _record_query(f"algorithm({name})", started, self._slow_query_ms)

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
