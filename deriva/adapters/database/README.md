# Database Adapter

DuckDB initialization and management for storing system configuration and metadata.

## Purpose

The Database adapter manages DuckDB for storing configuration data: file type registry, extraction/derivation configs, system settings, and run history. This is the single source of truth for pipeline configuration.

## Key Exports

```python
from deriva.adapters.database import (
    get_connection,     # Get DuckDB connection
    init_database,      # Initialize schema
    seed_database,      # Seed with default data
    reset_database,     # Clear and reinitialize
    run_sql_file,       # Execute SQL script
    DB_PATH,            # Database file path
)
```

## Basic Usage

```python
from deriva.adapters.database import get_connection, init_database, seed_database

# Initialize database (creates tables if needed)
init_database()

# Seed with default data
seed_database()  # Skips if already seeded
seed_database(force=True)  # Force re-seed

# Query directly
conn = get_connection()
result = conn.execute("SELECT * FROM file_type_registry").fetchall()
conn.close()
```

## Database Schema

**file_type_registry**:

- `extension` (PK): File extension or pattern (`.py`, `Dockerfile`)
- `file_type`: Category (source, config, docs, test, build, asset, data, exclude)
- `subtype`: Specific type (python, javascript, docker, etc.)

**extraction_config_versions**:

- `node_type`: Graph node type (Repository, File, TypeDefinition, etc.)
- `version`, `enabled`, `is_active`
- `input_file_types`, `input_graph_elements`: JSON arrays
- `instruction`, `example`: LLM prompt configuration

**derivation_config_versions**:

- Similar structure for ArchiMate derivation prompts

**system_settings**:

- Key-value store for runtime configuration

## File Structure

```text
deriva/adapters/database/
├── __init__.py           # Package exports
├── manager.py            # Database functions
├── sql.db                # DuckDB database file
└── scripts/              # SQL initialization scripts
    ├── 1_schema.sql      # Table definitions
    ├── 2_file_types.sql  # File type registry seed
    └── 3_extraction.sql  # Extraction config seed
```

## Functions

| Function | Description |
|----------|-------------|
| `get_connection()` | Returns DuckDB connection |
| `init_database()` | Execute schema SQL, create tables |
| `seed_database(force=False)` | Seed default data (skip if exists) |
| `reset_database()` | Drop all tables and reinitialize |
| `run_sql_file(filepath)` | Execute arbitrary SQL script |

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
