"""Grafeo Adapter - Embedded graph database connection for Deriva.

This package provides an embedded graph database connection using grafeo,
replacing the Neo4j server dependency. Multiple managers share a single
database instance with namespace isolation via label prefixes.

Example:
    >>> from deriva.adapters.grafeo import GrafeoConnection
    >>>
    >>> conn = GrafeoConnection(namespace="Graph")
    >>> conn.connect()
    >>>
    >>> conn.execute("CREATE (n:Repository {name: $name}) RETURN n", {"name": "my-repo"})
    >>>
    >>> conn.disconnect()
"""

from __future__ import annotations

from .manager import GrafeoConnection, close_database, get_database

__all__ = ["GrafeoConnection", "close_database", "get_database"]
