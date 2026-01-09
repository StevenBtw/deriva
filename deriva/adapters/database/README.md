# Database Adapter

DuckDB initialization and management for storing system configuration and metadata.

**Version:** 3.0.0

## Purpose

The Database adapter manages DuckDB for storing configuration data: file type registry, extraction/derivation configs, system settings, run history, and benchmarking data. This is the single source of truth for pipeline configuration.

## Key Exports

```python
from deriva.adapters.database import (
    get_connection,     # Get DuckDB connection
    init_database,      # Initialize schema
    seed_database,      # Seed from JSON files
    reset_database,     # Clear and reinitialize
    export_database,    # Export tables to JSON
    import_database,    # Import tables from JSON
    run_migrations,     # Apply ALTER TABLE scripts
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

### Configuration Tables

**file_type_registry**:
- `extension` (PK): File extension or pattern (`.py`, `Dockerfile`)
- `file_type`: Category (source, config, docs, test, build, asset, data, exclude)
- `subtype`: Specific type (python, javascript, docker, etc.)
- `chunk_delimiter`, `chunk_max_tokens`, `chunk_overlap`: Optional chunking config

**undefined_extensions**:
- `extension` (PK): Discovered file extensions not in registry
- `discovered_at`: Timestamp of discovery

**extraction_config**:
- `id` (PK), `node_type`, `version`, `sequence`
- `enabled`, `is_active`: Activation flags
- `input_sources`: JSON with file types and graph elements
- `instruction`, `example`: LLM prompt configuration
- `extraction_method`: 'llm', 'ast', or 'structural'
- `temperature`, `max_tokens`: LLM parameters

**derivation_config**:
- `id` (PK), `step_name`, `phase`, `version`, `sequence`
- `enabled`, `is_active`, `llm`: Activation and mode flags
- `input_graph_query`, `input_model_query`: Cypher queries
- `instruction`, `example`: LLM prompts
- `params`: JSON for graph algorithms
- `max_candidates`, `batch_size`: Processing limits
- `temperature`, `max_tokens`: LLM parameters

**derivation_relationship_config**:
- `id` (PK), `element_type` (unique): Element type for relationship derivation
- `enabled`, `sequence`: Activation and ordering
- `instruction`, `example`: LLM prompts
- `valid_relationship_types`: JSON array of allowed relationship types
- `target_element_types`: JSON array of target types (or null for all)
- `include_existing_elements`: Whether to include elements from previous runs
- `temperature`, `max_tokens`: LLM parameters

**derivation_patterns**:
- `id` (PK), `step_name`: Element type
- `pattern_type`: 'include' or 'exclude'
- `pattern_category`: Optional grouping category
- `patterns`: JSON array of pattern strings
- `is_active`: Whether pattern is enabled

**system_settings**:
- `key` (PK), `value`: Key-value store for runtime configuration

### Runtime Tables

**runs**:
- `run_id` (PK), `description`, `is_active`
- `started_at`, `ended_at`, `created_at`: Timestamps

### Benchmarking Tables

**benchmark_sessions**:
- `session_id` (PK), `description`, `status`
- `config`: JSON with repos, models, runs, stages
- `started_at`, `completed_at`

**benchmark_runs**:
- `run_id` (PK), `session_id`, `repository`
- `model_provider`, `model_name`, `iteration`
- `status`, `stats`: Execution metadata
- `ocel_events`: Event count

**benchmark_metrics**:
- `session_id`, `metric_type`, `metric_key` (composite PK)
- `metric_value`, `details`: Computed analysis results

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
    ├── derivation_patterns.json
    └── derivation_relationship_config.json
```

## CLI Tool

The `db_tool.py` provides a command-line interface for database operations:

```bash
# Export all tables to JSON
python -m deriva.adapters.database.db_tool export

# Export specific table
python -m deriva.adapters.database.db_tool export --table file_type_registry

# Export to custom directory
python -m deriva.adapters.database.db_tool export --output /path/to/dir

# Import all JSON files
python -m deriva.adapters.database.db_tool import

# Import specific table
python -m deriva.adapters.database.db_tool import --table extraction_config

# Import without clearing existing data
python -m deriva.adapters.database.db_tool import --no-clear

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
| `run_migrations()` | Apply ALTER TABLE scripts (migrations >= 7) |

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
