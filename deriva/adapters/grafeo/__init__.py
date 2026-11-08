"""Grafeo Adapter - Embedded graph database connection for Deriva.

This package provides an embedded graph database connection using grafeo,
providing an embedded alternative to external graph databases. Multiple managers share a single
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

from .manager import (
    DEFAULT_DATABASE,
    GrafeoConnection,
    GraphDatabaseBusy,
    close_database,
    database_bytes,
    database_exists,
    database_file,
    delete_database,
    engine_info,
    get_database,
    list_databases,
    use_database,
)
from .query_guard import READ_PROCEDURES, QueryRefused, check_read_only, is_write_query, read_only_refusal, refused_procedure

__all__ = [
    "DEFAULT_DATABASE",
    "READ_PROCEDURES",
    "GrafeoConnection",
    "GraphDatabaseBusy",
    "QueryRefused",
    "check_read_only",
    "close_database",
    "database_bytes",
    "database_exists",
    "database_file",
    "delete_database",
    "engine_info",
    "get_database",
    "is_write_query",
    "list_databases",
    "read_only_refusal",
    "refused_procedure",
    "use_database",
]
