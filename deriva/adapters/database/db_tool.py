"""Database export/import tool for Deriva.

Provides utilities to:
- Export database tables to JSON files
- Import JSON files into the database (seed/restore)

Usage:
    # Export all tables to JSON
    python -m deriva.adapters.database.db_tool export

    # Export specific table
    python -m deriva.adapters.database.db_tool export --table file_types

    # Import all JSON files (seed database)
    python -m deriva.adapters.database.db_tool import

    # Import specific table
    python -m deriva.adapters.database.db_tool import --table extraction_config
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Paths
DB_PATH = Path(__file__).parent / "sql.db"
DATA_DIR = Path(__file__).parent / "data"

# Table configuration: maps table names to their JSON filenames and primary keys
TABLES = {
    "file_type_registry": {
        "file": "file_types.json",
        "pk": "extension",
        "order_by": "file_type, extension",
    },
    "extraction_config": {
        "file": "extraction_config.json",
        "pk": "id",
        "order_by": "sequence, node_type",
    },
    "derivation_config": {
        "file": "derivation_config.json",
        "pk": "id",
        "order_by": "phase, sequence, step_name",
    },
    "derivation_patterns": {
        "file": "derivation_patterns.json",
        "pk": "id",
        "order_by": "step_name, pattern_type, pattern_category",
    },
    "derivation_relationship_config": {
        "file": "derivation_relationship_config.json",
        "pk": "id",
        "order_by": "sequence, element_type",
    },
}


def get_connection(db_path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Get database connection."""
    path = db_path or DB_PATH
    return duckdb.connect(str(path), read_only=read_only)


def export_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    output_dir: Path | None = None,
) -> Path:
    """Export a single table to JSON.

    Args:
        conn: Database connection
        table_name: Name of the table to export
        output_dir: Output directory (defaults to DATA_DIR)

    Returns:
        Path to the exported JSON file
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}. Valid tables: {list(TABLES.keys())}")

    config = TABLES[table_name]
    output_dir = output_dir or DATA_DIR
    output_file = output_dir / config["file"]

    # Get column info
    columns = conn.execute(f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
        ORDER BY ordinal_position
    """).fetchall()

    if not columns:
        logger.warning("Table %s not found or empty", table_name)
        return output_file

    column_names = [col[0] for col in columns]

    # Query data
    query = f"SELECT * FROM {table_name} ORDER BY {config['order_by']}"
    rows = conn.execute(query).fetchall()

    # Convert to list of dicts
    data: list[dict[str, object]] = []
    for row in rows:
        record: dict[str, object] = {}
        for i, value in enumerate(row):
            col_name = column_names[i]
            # Handle None values
            if value is None:
                record[col_name] = None
            # Handle timestamps
            elif hasattr(value, "isoformat"):
                record[col_name] = value.isoformat()
            else:
                record[col_name] = value
            # Note: JSON fields (input_sources, patterns, params) are stored as strings
            # in DuckDB, so they export as strings - this is intentional
        data.append(record)

    # Write JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Exported %s: %d records -> %s", table_name, len(data), output_file.name)
    return output_file


def export_all(
    db_path: Path | None = None,
    output_dir: Path | None = None,
) -> list[Path]:
    """Export all configured tables to JSON files.

    Args:
        db_path: Database file path (defaults to DB_PATH)
        output_dir: Output directory (defaults to DATA_DIR)

    Returns:
        List of exported file paths
    """
    conn = get_connection(db_path, read_only=True)
    output_dir = output_dir or DATA_DIR
    exported = []

    try:
        for table_name in TABLES:
            path = export_table(conn, table_name, output_dir)
            exported.append(path)
    finally:
        conn.close()

    return exported


def import_table(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    input_dir: Path | None = None,
    clear_existing: bool = True,
) -> int:
    """Import a single table from JSON.

    Args:
        conn: Database connection
        table_name: Name of the table to import
        input_dir: Input directory (defaults to DATA_DIR)
        clear_existing: If True, delete existing data before import

    Returns:
        Number of records imported
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}. Valid tables: {list(TABLES.keys())}")

    config = TABLES[table_name]
    input_dir = input_dir or DATA_DIR
    input_file = input_dir / config["file"]

    if not input_file.exists():
        logger.warning("JSON file not found: %s", input_file)
        return 0

    # Load JSON
    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        logger.info("No data in %s", input_file.name)
        return 0

    # Clear existing data if requested
    if clear_existing:
        conn.execute(f"DELETE FROM {table_name}")

    # Get column names from first record
    columns = list(data[0].keys())

    # Build INSERT statement
    placeholders = ", ".join(["?" for _ in columns])
    column_list = ", ".join(columns)
    insert_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"

    # Insert records
    for record in data:
        values = [record.get(col) for col in columns]
        conn.execute(insert_sql, values)

    logger.info("Imported %s: %d records from %s", table_name, len(data), input_file.name)
    return len(data)


def import_all(
    db_path: Path | None = None,
    input_dir: Path | None = None,
    clear_existing: bool = True,
) -> dict[str, int]:
    """Import all configured tables from JSON files.

    Args:
        db_path: Database file path (defaults to DB_PATH)
        input_dir: Input directory (defaults to DATA_DIR)
        clear_existing: If True, delete existing data before import

    Returns:
        Dict mapping table names to record counts
    """
    conn = get_connection(db_path)
    input_dir = input_dir or DATA_DIR
    results = {}

    try:
        for table_name in TABLES:
            count = import_table(conn, table_name, input_dir, clear_existing)
            results[table_name] = count
    finally:
        conn.close()

    return results


def seed_from_json(db_path: Path | None = None, force: bool = False) -> bool:
    """Seed database from JSON files if empty.

    This is the function called by manager.seed_database().

    Args:
        db_path: Database file path (defaults to DB_PATH)
        force: If True, re-seed even if data exists

    Returns:
        True if seeding was performed, False if skipped
    """
    conn = get_connection(db_path)

    try:
        # Check if already seeded
        if not force:
            row = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
            existing_count = row[0] if row else 0

            if existing_count > 0:
                logger.info(
                    "Database already seeded (%d file types). Use force=True to re-seed.",
                    existing_count,
                )
                return False

        # Import all tables
        for table_name in TABLES:
            import_table(conn, table_name, DATA_DIR, clear_existing=True)

        return True

    finally:
        conn.close()


def main(args: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Database export/import tool for Deriva",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export command
    export_parser = subparsers.add_parser("export", help="Export tables to JSON")
    export_parser.add_argument(
        "--table", "-t",
        choices=list(TABLES.keys()),
        help="Export specific table (default: all)",
    )
    export_parser.add_argument(
        "--output", "-o",
        type=Path,
        help=f"Output directory (default: {DATA_DIR})",
    )
    export_parser.add_argument(
        "--db",
        type=Path,
        help=f"Database file (default: {DB_PATH})",
    )

    # Import command
    import_parser = subparsers.add_parser("import", help="Import tables from JSON")
    import_parser.add_argument(
        "--table", "-t",
        choices=list(TABLES.keys()),
        help="Import specific table (default: all)",
    )
    import_parser.add_argument(
        "--input", "-i",
        type=Path,
        dest="input_dir",
        help=f"Input directory (default: {DATA_DIR})",
    )
    import_parser.add_argument(
        "--db",
        type=Path,
        help=f"Database file (default: {DB_PATH})",
    )
    import_parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Don't clear existing data before import",
    )

    # Seed command (alias for import with defaults)
    seed_parser = subparsers.add_parser("seed", help="Seed database from JSON files")
    seed_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force re-seed even if data exists",
    )
    seed_parser.add_argument(
        "--db",
        type=Path,
        help=f"Database file (default: {DB_PATH})",
    )

    parsed = parser.parse_args(args)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    if parsed.command == "export":
        if parsed.table:
            conn = get_connection(parsed.db, read_only=True)
            try:
                export_table(conn, parsed.table, parsed.output)
            finally:
                conn.close()
        else:
            export_all(parsed.db, parsed.output)
        print("\n[OK] Export complete!")

    elif parsed.command == "import":
        if parsed.table:
            conn = get_connection(parsed.db)
            try:
                import_table(conn, parsed.table, parsed.input_dir, not parsed.no_clear)
            finally:
                conn.close()
        else:
            import_all(parsed.db, parsed.input_dir, not parsed.no_clear)
        print("\n[OK] Import complete!")

    elif parsed.command == "seed":
        if seed_from_json(parsed.db, parsed.force):
            print("\n[OK] Database seeded!")
        else:
            print("\n[SKIP] Database already seeded (use --force to re-seed)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
