"""Database initialization for Deriva.

Runs SQL scripts in order to set up the database schema and seed initial data.

Usage:
    from deriva.adapters.database import init_database, seed_database

    init_database()  # Creates tables
    seed_database()  # Seeds data
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# Database location
DB_PATH = Path(__file__).parent / "sql.db"
SCRIPTS_DIR = Path(__file__).parent / "scripts"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a connection to the database."""
    return duckdb.connect(str(DB_PATH), read_only=False)


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
    schema_file = SCRIPTS_DIR / "1_schema.sql"

    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    conn = get_connection()
    count = run_sql_file(schema_file, conn)
    conn.close()

    logger.info("Schema initialized (%d statements executed)", count)
    return True


def seed_database(force: bool = False) -> bool:
    """Seed database with initial data.

    Args:
        force: If True, re-seeds even if data exists

    Returns:
        True if seeding was performed, False if skipped
    """
    conn = get_connection()

    # Check if already seeded
    if not force:
        row = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        existing_count = row[0] if row else 0

        if existing_count > 0:
            logger.info(
                "Database already seeded (%d file types). Use force=True to re-seed.",
                existing_count,
            )
            conn.close()
            return False

    # Run seed scripts in order
    seed_files = sorted(
        [
            f
            for f in SCRIPTS_DIR.glob("*.sql")
            if f.stem[0].isdigit() and int(f.stem[0]) > 1  # Skip 1_schema.sql
        ]
    )

    total_statements = 0
    for seed_file in seed_files:
        logger.debug("Running %s...", seed_file.name)
        count = run_sql_file(seed_file, conn)
        total_statements += count

    conn.close()
    logger.info("Database seeded (%d statements executed)", total_statements)
    return True


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
    # When run directly, initialize and seed
    logging.basicConfig(level=logging.INFO)
    logger.info("Initializing Deriva database...")
    init_database()
    seed_database()
    logger.info("Done!")
