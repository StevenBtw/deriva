# Database Adapter

DuckDB initialization and management for storing system configuration and metadata.

## Purpose

The Database adapter manages DuckDB for storing configuration data: file type registry, extraction/derivation configs, system settings, and run history. This is the single source of truth for pipeline configuration.

## Key Exports

```python
from deriva.adapters.database import (
    get_connection,     # Get DuckDB connection
    init_database,      # Initialize schema
    seed_database,      # Seed from JSON files
    reset_database,     # Clear and reinitialize
    export_database,    # Export tables to JSON
    import_database,    # Import tables from JSON
    DB_PATH,            # Database file path
)
```

## Basic Usage

```python
from deriva.adapters.database import get_connection, init_database, seed_database

# Initialize database (creates tables if needed)
init_database()

# Seed with default data from JSON files
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
- `chunk_delimiter`, `chunk_max_tokens`, `chunk_overlap`: Optional chunking config

**extraction_config**:
- `node_type`: Graph node type (Repository, File, TypeDefinition, etc.)
- `version`, `sequence`, `enabled`, `is_active`
- `input_sources`: JSON with file types and graph elements
- `instruction`, `example`: LLM prompt configuration
- `extraction_method`: 'llm', 'ast', or 'structural'

**derivation_config**:
- `step_name`: Element or algorithm name
- `phase`: prep, generate, refine, or relationship
- `llm`: Whether step uses LLM
- `input_graph_query`, `input_model_query`: Cypher queries
- `instruction`, `example`: LLM prompts
- `params`: JSON for graph algorithms

**derivation_patterns**:
- `step_name`: Element type
- `pattern_type`: include or exclude
- `patterns`: JSON array of pattern strings

**system_settings**:
- Key-value store for runtime configuration

## File Structure

```text
deriva/adapters/database/
├── __init__.py           # Package exports
├── manager.py            # Database lifecycle functions
├── db_tool.py            # Export/import CLI tool
├── sql.db                # DuckDB database file
├── scripts/
│   └── schema.sql        # Table definitions
└── data/                 # JSON seed data
    ├── file_types.json
    ├── extraction_config.json
    ├── derivation_config.json
    └── derivation_patterns.json
```

## CLI Tool

The `db_tool.py` provides a command-line interface for database operations:

```bash
# Export all tables to JSON
python -m deriva.adapters.database.db_tool export

# Export specific table
python -m deriva.adapters.database.db_tool export --table file_type_registry

# Import all JSON files
python -m deriva.adapters.database.db_tool import

# Import specific table
python -m deriva.adapters.database.db_tool import --table extraction_config

# Seed database (import if empty)
python -m deriva.adapters.database.db_tool seed
python -m deriva.adapters.database.db_tool seed --force
```

## Functions

| Function | Description |
|----------|-------------|
| `get_connection()` | Returns DuckDB connection |
| `init_database()` | Execute schema SQL, create tables |
| `seed_database(force=False)` | Seed from JSON files (skip if exists) |
| `reset_database()` | Drop all tables and reinitialize |
| `export_database()` | Export all tables to JSON |
| `import_database()` | Import all tables from JSON |
| `run_migrations()` | Apply ALTER TABLE scripts |

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
