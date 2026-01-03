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


def run_migrations() -> int:
    """Run any pending migrations (ALTER TABLE scripts).

    Migrations are scripts that start with a digit and contain ALTER statements.
    This function safely skips columns that already exist.

    Returns:
        Number of migrations applied
    """
    conn = get_connection()
    migrations_applied = 0

    # Find migration scripts (numbered SQL files)
    migration_files = sorted(
        [
            f
            for f in SCRIPTS_DIR.glob("*.sql")
            if f.stem[0].isdigit()
            and int(f.stem.split("_")[0]) >= 7  # Migrations start at 7
        ]
    )

    for migration_file in migration_files:
        with open(migration_file, encoding="utf-8") as f:
            sql = f.read()

        # Process ALTER TABLE ADD COLUMN statements safely
        statements = [s.strip() for s in sql.split(";") if s.strip()]

        for statement in statements:
            if not statement or statement.startswith("--"):
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
                    logger.warning(
                        "Migration statement failed: %s - %s", statement[:50], e
                    )
            else:
                # Non-ALTER statements, just run them
                try:
                    conn.execute(statement)
                except Exception as e:
                    logger.debug("Statement failed (may be expected): %s", e)

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
