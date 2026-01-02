"""Database adapter - DuckDB initialization and management for Deriva.

This package manages the DuckDB database that stores:
- File type registry
- Extraction configuration versions
- Derivation configuration versions
- System settings

Usage:
    from deriva.adapters.database import get_connection, init_database, seed_database

    # Initialize schema
    init_database()

    # Seed with default data
    seed_database()

    # Get connection for queries
    conn = get_connection()
"""

from __future__ import annotations

from .manager import (
    DB_PATH,
    get_connection,
    init_database,
    reset_database,
    seed_database,
)

__all__ = [
    "get_connection",
    "init_database",
    "seed_database",
    "reset_database",
    "DB_PATH",
]

__version__ = "2.0.0"
