-- AutoMate Database Schema
-- Version 2.0 - With versioned extraction configs

-- File type registry: maps file extensions/patterns to types
CREATE TABLE IF NOT EXISTS file_type_registry (
    extension VARCHAR PRIMARY KEY,
    file_type VARCHAR NOT NULL,
    subtype VARCHAR NOT NULL
);

-- Undefined extensions: discovered during extraction
CREATE TABLE IF NOT EXISTS undefined_extensions (
    extension VARCHAR PRIMARY KEY,
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Extraction config versions: versioned prompt storage
CREATE TABLE IF NOT EXISTS extraction_config (
    id INTEGER PRIMARY KEY,
    node_type VARCHAR NOT NULL,
    version INTEGER NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN DEFAULT FALSE,
    input_sources VARCHAR,  -- JSON: {"files": [{"type": "source", "subtype": "*"}], "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]}
    instruction TEXT,
    example TEXT,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(node_type, version)
);

-- Derivation config versions (unified schema for prep/generate/refine phases)
CREATE TABLE IF NOT EXISTS derivation_config (
    id INTEGER PRIMARY KEY,
    step_name VARCHAR NOT NULL,              -- e.g., "ApplicationComponent", "k_core_filter", "Completeness"
    phase VARCHAR NOT NULL,                  -- "prep" | "generate" | "refine"
    version INTEGER NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN DEFAULT FALSE,
    llm BOOLEAN DEFAULT TRUE,                -- TRUE = uses LLM, FALSE = pure graph algorithm
    input_graph_query TEXT,                  -- Cypher for Graph namespace (nodes/edges)
    input_model_query TEXT,                  -- Cypher for Model namespace (elements/relationships)
    instruction TEXT,                        -- LLM prompt (for llm=TRUE steps)
    example TEXT,                            -- LLM example output (for llm=TRUE steps)
    params TEXT,                             -- JSON parameters (for llm=FALSE steps, e.g., {"k": 2})
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(step_name, version)
);

-- System settings
CREATE TABLE IF NOT EXISTS system_settings (
    key VARCHAR PRIMARY KEY,
    value VARCHAR,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Runs: track extraction/derivation runs
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY,
    description VARCHAR,
    is_active BOOLEAN DEFAULT FALSE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- BENCHMARKING TABLES
-- =============================================================================

-- Benchmark sessions: overall benchmark configuration and status
CREATE TABLE IF NOT EXISTS benchmark_sessions (
    session_id VARCHAR PRIMARY KEY,
    description VARCHAR,
    config JSON,                -- Full config: repos, models, runs, stages
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR DEFAULT 'pending'  -- pending, running, completed, failed
);

-- Benchmark runs: individual executions within a session
CREATE TABLE IF NOT EXISTS benchmark_runs (
    run_id VARCHAR PRIMARY KEY,
    session_id VARCHAR NOT NULL,
    repository VARCHAR NOT NULL,
    model_provider VARCHAR NOT NULL,
    model_name VARCHAR NOT NULL,
    iteration INTEGER NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR DEFAULT 'pending',  -- pending, running, completed, failed
    stats JSON,                 -- {nodes_created, elements_derived, etc.}
    ocel_events INTEGER DEFAULT 0,
    UNIQUE(session_id, repository, model_provider, model_name, iteration)
);

-- Benchmark metrics: computed analysis results
CREATE TABLE IF NOT EXISTS benchmark_metrics (
    session_id VARCHAR NOT NULL,
    metric_type VARCHAR NOT NULL,    -- intra_model, inter_model, localization
    metric_key VARCHAR NOT NULL,     -- e.g., "azure:gpt-4" or "File:auth.py"
    metric_value DOUBLE,
    details JSON,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, metric_type, metric_key)
);
