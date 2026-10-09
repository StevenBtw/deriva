"""Database initialization for Deriva.

Manages DuckDB database schema and seed data.

Usage:
    from deriva.adapters.database import init_database, seed_database

    init_database()  # Creates tables from schema.sql
    seed_database()  # Seeds data from JSON files in data/
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Database location
DB_PATH = Path(__file__).parent / "sql.db"
SCRIPTS_DIR = Path(__file__).parent / "scripts"
DATA_DIR = Path(__file__).parent / "data"


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Get a connection to the database.

    Args:
        read_only: If True, open in read-only mode (safe for queries during benchmarks).
                   Default is False for backward compatibility.

    Returns:
        DuckDB connection
    """
    # A fresh install has no database yet: create it from the schema and the shipped seed data
    if not DB_PATH.exists():
        ensure_database(DB_PATH)
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def run_sql_file(filepath: Path, conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Execute a SQL file.

    Args:
        filepath: Path to the SQL file to execute
        conn: Optional existing connection (creates new one if None)

    Returns:
        Number of statements executed
    """
    close_after = False
    if conn is None:
        conn = get_connection()
        close_after = True

    with open(filepath, encoding="utf-8") as f:
        sql = f.read()

    # Split by semicolon and execute each statement
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    for statement in statements:
        conn.execute(statement)

    if close_after:
        conn.close()

    return len(statements)


def init_database() -> bool:
    """Initialize database schema (creates tables if they don't exist).

    Returns:
        True if initialization succeeded

    Raises:
        FileNotFoundError: If schema file is not found
    """
    schema_file = SCRIPTS_DIR / "schema.sql"

    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    conn = get_connection()
    count = run_sql_file(schema_file, conn)
    conn.close()

    logger.info("Schema initialized (%d statements executed)", count)
    return True


def seed_database() -> bool:
    """Seed database with initial data from JSON files.

    Only seeds tables that are empty - does not overwrite existing data.
    To update configurations, use the CLI: `deriva config update`

    Returns:
        True if any seeding was performed, False if all tables already have data
    """
    # Import here to avoid circular imports
    from deriva.adapters.database.db_tool import seed_from_json

    return seed_from_json(DB_PATH)


def ensure_database(db_path: Path | None = None) -> bool:
    """Create and seed the configuration database when it has no schema yet (a fresh install).

    Runs the schema, the migrations and the seed from the shipped JSON files in ``data/``
    (the active configuration rows with their version numbers). An existing database is
    never changed.

    Args:
        db_path: Database file (defaults to DB_PATH)

    Returns:
        True when the database was created, False when it already had a schema
    """
    path = db_path or DB_PATH
    conn = duckdb.connect(str(path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'extraction_config'").fetchone()
        if row and row[0] > 0:
            return False
        run_sql_file(SCRIPTS_DIR / "schema.sql", conn)
        run_migrations(conn)
    finally:
        conn.close()

    # Import here to avoid circular imports
    from deriva.adapters.database.db_tool import seed_from_json

    seed_from_json(path)
    logger.info("Created the configuration database %s from the shipped seed data", path)
    return True


def run_migrations(conn: duckdb.DuckDBPyConnection | None = None) -> int:
    """Run any pending migrations (ALTER TABLE scripts).

    Migrations are scripts that start with a digit and contain ALTER statements.
    This function safely skips columns that already exist, so it can run on
    every connect.

    Args:
        conn: Connection to migrate; a new one is opened (and closed) when omitted

    Returns:
        Number of migrations applied
    """
    owns_connection = conn is None
    if conn is None:
        conn = get_connection()
    migrations_applied = 0

    # Find migration scripts (numbered SQL files)
    migration_files = sorted(
        [
            f
            for f in SCRIPTS_DIR.glob("*.sql")
            if f.stem[0].isdigit() and int(f.stem.split("_")[0]) >= 7  # Migrations start at 7
        ]
    )

    for migration_file in migration_files:
        with open(migration_file, encoding="utf-8") as f:
            sql = f.read()

        # Process ALTER TABLE ADD COLUMN statements safely; drop comment lines so a
        # comment above a statement does not hide the statement itself
        statements = ["\n".join(line for line in s.splitlines() if not line.strip().startswith("--")).strip() for s in sql.split(";")]

        for statement in statements:
            if not statement:
                continue

            # Check if this is an ALTER TABLE ADD COLUMN
            if "ALTER TABLE" in statement.upper() and "ADD COLUMN" in statement.upper():
                # Extract table and column names
                try:
                    # Parse: ALTER TABLE table_name ADD COLUMN column_name TYPE
                    parts = statement.upper().split()
                    table_idx = parts.index("TABLE") + 1
                    col_idx = parts.index("COLUMN") + 1
                    table_name = statement.split()[table_idx]
                    col_name = statement.split()[col_idx]

                    # Check if column already exists
                    result = conn.execute(
                        """
                        SELECT COUNT(*) FROM information_schema.columns
                        WHERE table_name = ? AND column_name = ?
                        """,
                        [table_name.lower(), col_name.lower()],
                    ).fetchone()

                    if result and result[0] > 0:
                        logger.debug(
                            "Column %s.%s already exists, skipping",
                            table_name,
                            col_name,
                        )
                        continue

                    # Column doesn't exist, add it
                    conn.execute(statement)
                    migrations_applied += 1
                    logger.info("Added column %s.%s", table_name, col_name)

                except Exception as e:
                    logger.warning("Migration statement failed: %s - %s", statement[:50], e)
            else:
                # Non-ALTER statements, just run them
                try:
                    conn.execute(statement)
                except Exception as e:
                    logger.debug("Statement failed (may be expected): %s", e)

    if owns_connection:
        conn.close()
    return migrations_applied


def reset_database() -> None:
    """Drop all tables and recreate from scratch.

    Warning:
        This is a destructive operation that cannot be undone.
    """
    conn = get_connection()

    # Drop all tables
    tables = conn.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
    """).fetchall()

    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table[0]} CASCADE")

    conn.close()

    logger.warning("Database reset (all tables dropped)")

    # Reinitialize
    init_database()
    seed_database()


if __name__ == "__main__":
    # When run directly, initialize, seed, and run migrations
    logging.basicConfig(level=logging.INFO)
    logger.info("Initializing Deriva database...")
    init_database()
    seed_database()
    migrations = run_migrations()
    if migrations > 0:
        logger.info("Applied %d migrations", migrations)
    logger.info("Done!")
