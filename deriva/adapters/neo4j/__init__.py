"""Neo4j Manager - Shared Neo4j connection service for Deriva.

This package provides a centralized Neo4j connection that multiple managers
can use with namespace isolation via label prefixes.

Example:
    >>> from neo4j_manager import Neo4jConnection
    >>>
    >>> # Connect to Neo4j
    >>> conn = Neo4jConnection(namespace="Graph")
    >>> conn.connect()
    >>>
    >>> # Execute query with namespace
    >>> conn.execute('''
    ...     CREATE (n:Repository {name: $name})
    ...     RETURN n
    ... ''', {"name": "my-repo"})
    >>>
    >>> conn.disconnect()
"""

from __future__ import annotations

from .manager import Neo4jConnection

__all__ = ["Neo4jConnection"]
__version__ = "1.0.0"
