"""Grafeo Connection Service - Embedded graph database for Deriva.

Embedded graph database connection for Deriva.
Provides the namespace-isolated interface that GraphManager and
ArchimateManager expect.

Features:
- Embedded graph database (no external server)
- Cypher query language support
- Namespace isolation via label prefixes
- Configurable storage: in-memory (default) or persistent file

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
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared database singleton
# ---------------------------------------------------------------------------

_db: Any | None = None


def get_database() -> Any:
    """Get or create the shared GrafeoDB instance.

    Storage mode is controlled by the GRAFEO_DB_PATH environment variable:
    - Not set or empty: in-memory database (fastest, fresh each session)
    - Set to a path: persistent database file

    Returns:
        GrafeoDB instance shared across all connections.
    """
    global _db
    if _db is None:
        from grafeo import GrafeoDB

        load_dotenv()
        path = os.getenv("GRAFEO_DB_PATH") or None
        _db = GrafeoDB(path)

        mode = f"persistent ({path})" if path else "in-memory"
        logger.info("Created shared GrafeoDB instance (%s)", mode)

    return _db


def close_database() -> None:
    """Close and release the shared GrafeoDB instance."""
    global _db
    if _db is not None:
        logger.info("Closing shared GrafeoDB instance")
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
        self._log_queries = (
            os.getenv("GRAFEO_LOG_QUERIES", "false").lower() == "true"
        )

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
        logger.info(
            "Connected to grafeo (namespace '%s')", self.namespace
        )

    def disconnect(self) -> None:
        """Release reference to the shared database.

        The underlying database stays alive (singleton). Call
        ``close_database()`` to fully shut down.
        """
        if self.db is not None:
            self.db = None
            logger.info("Disconnected from grafeo (namespace '%s')", self.namespace)

    def __enter__(self) -> GrafeoConnection:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
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
            raise RuntimeError(
                f"Not connected to grafeo. Call connect() first. "
                f"(Namespace: {self.namespace})"
            )

        if self._log_queries:
            logger.debug("Executing query: %s", query)
            logger.debug("Parameters: %s", parameters)

        try:
            params = parameters if parameters is not None else {}
            result = self.db.execute_cypher(query, params)
            return result.to_list()

        except Exception as e:
            logger.error("Query execution failed: %s", e)
            logger.error("Query: %s", query)
            logger.error("Parameters: %s", parameters)
            raise

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
                "MATCH (n) "
                "WHERE any(label IN labels(n) WHERE label STARTS WITH $namespace) "
                "DETACH DELETE n",
                {"namespace": self.namespace},
            )
            logger.info("Cleared all data for namespace: %s", self.namespace)

        except Exception as e:
            logger.error("Failed to clear namespace %s: %s", self.namespace, e)
            raise

    # ------------------------------------------------------------------
    # Schema (no-ops for embedded grafeo)
    # ------------------------------------------------------------------

    def create_constraint(
        self, label: str, property_key: str, constraint_name: str | None = None
    ) -> None:
        """Create a uniqueness constraint (no-op in grafeo)."""
        logger.debug(
            "create_constraint is a no-op in grafeo (label=%s, property=%s)",
            label,
            property_key,
        )

    def create_index(
        self, label: str, property_key: str, index_name: str | None = None
    ) -> None:
        """Create an index (no-op in grafeo)."""
        logger.debug(
            "create_index is a no-op in grafeo (label=%s, property=%s)",
            label,
            property_key,
        )
