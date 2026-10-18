"""Database adapter - DuckDB initialization and management for Deriva.

This package manages the DuckDB database that stores:
- File type registry
- Extraction configuration
- Derivation configuration
- Derivation patterns
- System settings

Usage:
    from deriva.adapters.database import get_connection, init_database, seed_database

    # Initialize schema
    init_database()

    # Seed with default data from JSON files
    seed_database()

    # Export database to JSON files
    export_database()

    # Get connection for queries
    conn = get_connection()
"""

from __future__ import annotations

from .db_tool import DATA_DIR
from .db_tool import export_all as export_database
from .db_tool import import_all as import_database
from .manager import (
    DB_PATH,
    ConfigDatabaseBusy,
    ensure_database,
    get_connection,
    init_database,
    reset_database,
    run_migrations,
    seed_database,
)

# Bundled business function models (a config path names one of them, or a user-supplied file)
FUNCTION_MODELS_DIR = DATA_DIR / "function_models"

__all__ = [
    "FUNCTION_MODELS_DIR",
    "ConfigDatabaseBusy",
    "ensure_database",
    "get_connection",
    "init_database",
    "seed_database",
    "reset_database",
    "run_migrations",
    "export_database",
    "import_database",
    "DB_PATH",
]

__version__ = "3.0.0"
