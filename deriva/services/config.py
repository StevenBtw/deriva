"""
Configuration service for Deriva.

Provides CRUD operations for pipeline configuration stored in DuckDB.
Used by both Marimo (visual UI) and CLI (headless) for consistent config management.

Tables managed:
    - extraction_config: LLM extraction step configurations
    - derivation_config: ArchiMate derivation configurations (prep/generate/refine phases)
    - file_type_registry: File extension to type mappings
    - system_settings: Key-value system settings
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# Type Definitions
# =============================================================================


class ExtractionConfig:
    """Extraction step configuration."""

    def __init__(
        self,
        node_type: str,
        sequence: int,
        enabled: bool,
        input_sources: str | None,
        instruction: str | None,
        example: str | None,
        extraction_method: str = "llm",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        self.node_type = node_type
        self.sequence = sequence
        self.enabled = enabled
        self.input_sources = input_sources
        self.instruction = instruction
        self.example = example
        self.extraction_method = extraction_method  # 'llm', 'ast', or 'structural'
        self.temperature = temperature  # None = use env default (LLM_TEMPERATURE)
        self.max_tokens = max_tokens  # None = use env default (LLM_MAX_TOKENS)


class DerivationConfig:
    """Unified derivation step configuration for prep/generate/refine phases."""

    def __init__(
        self,
        step_name: str,
        phase: str,
        sequence: int,
        enabled: bool,
        llm: bool,
        input_graph_query: str | None,
        input_model_query: str | None,
        instruction: str | None,
        example: str | None,
        params: str | None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_candidates: int | None = None,
        batch_size: int | None = None,
    ):
        self.step_name = step_name
        self.phase = phase  # "prep" | "generate" | "refine" | "relationship"
        self.sequence = sequence
        self.enabled = enabled
        self.llm = llm  # True = uses LLM, False = pure graph algorithm
        self.input_graph_query = input_graph_query
        self.input_model_query = input_model_query
        self.instruction = instruction
        self.example = example
        self.params = params  # JSON parameters for graph algorithms
        self.temperature = temperature  # None = use env default (LLM_TEMPERATURE)
        self.max_tokens = max_tokens  # None = use env default (LLM_MAX_TOKENS)
        self.max_candidates = max_candidates  # Max candidates to send to LLM
        self.batch_size = batch_size  # Batch size for LLM processing

    # Backward compatibility alias
    @property
    def element_type(self) -> str:
        """Backward compatibility: element_type maps to step_name."""
        return self.step_name


class RelationshipConfig:
    """Configuration for per-element-type relationship derivation."""

    def __init__(
        self,
        element_type: str,
        enabled: bool,
        sequence: int,
        instruction: str | None,
        example: str | None,
        valid_relationship_types: list[str] | None,
        target_element_types: list[str] | None,
        include_existing_elements: bool,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        self.element_type = element_type
        self.enabled = enabled
        self.sequence = sequence
        self.instruction = instruction
        self.example = example
        self.valid_relationship_types = valid_relationship_types or []
        self.target_element_types = target_element_types  # None means all types
        self.include_existing_elements = include_existing_elements
        self.temperature = temperature
        self.max_tokens = max_tokens


class FileType:
    """File type registry entry with optional chunking configuration."""

    def __init__(
        self,
        extension: str,
        file_type: str,
        subtype: str,
        chunk_delimiter: str | None = None,
        chunk_max_tokens: int | None = None,
        chunk_overlap: int = 0,
    ):
        self.extension = extension
        self.file_type = file_type
        self.subtype = subtype
        # Chunking configuration
        self.chunk_delimiter = chunk_delimiter
        self.chunk_max_tokens = chunk_max_tokens
        self.chunk_overlap = chunk_overlap


# =============================================================================
# Extraction Config Operations
# =============================================================================


def get_extraction_configs(engine: Any, enabled_only: bool = False) -> list[ExtractionConfig]:
    """
    Get all active extraction configurations.

    Args:
        engine: DuckDB connection
        enabled_only: If True, only return enabled configs

    Returns:
        List of ExtractionConfig objects ordered by sequence
    """
    query = """
        SELECT node_type, sequence, enabled, input_sources, instruction, example,
               extraction_method, temperature, max_tokens
        FROM extraction_config
        WHERE is_active = TRUE
    """
    if enabled_only:
        query += " AND enabled = TRUE"
    query += " ORDER BY sequence"

    rows = engine.execute(query).fetchall()
    return [
        ExtractionConfig(
            node_type=row[0],
            sequence=row[1],
            enabled=row[2],
            input_sources=row[3],
            instruction=row[4],
            example=row[5],
            extraction_method=row[6] or "llm",
            temperature=row[7],
            max_tokens=row[8],
        )
        for row in rows
    ]


def get_extraction_config(engine: Any, node_type: str) -> ExtractionConfig | None:
    """
    Get a specific extraction configuration by node type.

    Args:
        engine: DuckDB connection
        node_type: The node type to retrieve (e.g., 'BusinessConcept')

    Returns:
        ExtractionConfig or None if not found
    """
    row = engine.execute(
        """
        SELECT node_type, sequence, enabled, input_sources, instruction, example,
               extraction_method, temperature, max_tokens
        FROM extraction_config
        WHERE node_type = ? AND is_active = TRUE
        """,
        [node_type],
    ).fetchone()

    if not row:
        return None

    return ExtractionConfig(
        node_type=row[0],
        sequence=row[1],
        enabled=row[2],
        input_sources=row[3],
        instruction=row[4],
        example=row[5],
        extraction_method=row[6] or "llm",
        temperature=row[7],
        max_tokens=row[8],
    )


def update_extraction_config(
    engine: Any,
    node_type: str,
    *,
    enabled: bool | None = None,
    sequence: int | None = None,
    instruction: str | None = None,
    example: str | None = None,
    input_sources: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> bool:
    """
    Update an extraction configuration.

    Args:
        engine: DuckDB connection
        node_type: The node type to update
        enabled: Enable/disable the step
        sequence: Execution order
        instruction: LLM instruction prompt
        example: Example output for LLM
        input_sources: JSON string of input sources
        temperature: LLM temperature override (None = use env default)
        max_tokens: LLM max_tokens override (None = use env default)

    Returns:
        True if updated, False if not found
    """
    updates = []
    params = []

    if enabled is not None:
        updates.append("enabled = ?")
        params.append(enabled)
    if sequence is not None:
        updates.append("sequence = ?")
        params.append(sequence)
    if instruction is not None:
        updates.append("instruction = ?")
        params.append(instruction)
    if example is not None:
        updates.append("example = ?")
        params.append(example)
    if input_sources is not None:
        updates.append("input_sources = ?")
        params.append(input_sources)
    if temperature is not None:
        updates.append("temperature = ?")
        params.append(temperature)
    if max_tokens is not None:
        updates.append("max_tokens = ?")
        params.append(max_tokens)

    if not updates:
        return False

    params.append(node_type)
    query = f"UPDATE extraction_config SET {', '.join(updates)} WHERE node_type = ? AND is_active = TRUE"

    result = engine.execute(query, params)
    return result.rowcount > 0 if hasattr(result, "rowcount") else True


# =============================================================================
# Derivation Config Operations
# =============================================================================


def get_derivation_configs(
    engine: Any,
    enabled_only: bool = False,
    phase: str | None = None,
    llm_only: bool | None = None,
) -> list[DerivationConfig]:
    """
    Get all active derivation configurations.

    Args:
        engine: DuckDB connection
        enabled_only: If True, only return enabled configs
        phase: Filter by phase ("prep", "generate", "refine", "relationship")
        llm_only: If True, only LLM steps; if False, only graph algorithm steps

    Returns:
        List of DerivationConfig objects ordered by phase priority then sequence
    """
    query = """
        SELECT step_name, phase, sequence, enabled, llm, input_graph_query,
               input_model_query, instruction, example, params, temperature, max_tokens,
               max_candidates, batch_size
        FROM derivation_config
        WHERE is_active = TRUE
    """
    params = []

    if enabled_only:
        query += " AND enabled = TRUE"
    if phase is not None:
        query += " AND phase = ?"
        params.append(phase)
    if llm_only is not None:
        query += " AND llm = ?"
        params.append(llm_only)

    # Order by phase priority (prep=1, generate=2, refine=3, relationship=4) then sequence
    query += """
        ORDER BY
            CASE phase WHEN 'prep' THEN 1 WHEN 'generate' THEN 2 WHEN 'refine' THEN 3 WHEN 'relationship' THEN 4 END,
            sequence
    """

    rows = engine.execute(query, params).fetchall()
    return [
        DerivationConfig(
            step_name=row[0],
            phase=row[1],
            sequence=row[2],
            enabled=row[3],
            llm=row[4],
            input_graph_query=row[5],
            input_model_query=row[6],
            instruction=row[7],
            example=row[8],
            params=row[9],
            temperature=row[10],
            max_tokens=row[11],
            max_candidates=row[12],
            batch_size=row[13],
        )
        for row in rows
    ]


def get_derivation_config(engine: Any, step_name: str) -> DerivationConfig | None:
    """Get a specific derivation configuration by step name."""
    row = engine.execute(
        """
        SELECT step_name, phase, sequence, enabled, llm, input_graph_query,
               input_model_query, instruction, example, params, temperature, max_tokens,
               max_candidates, batch_size
        FROM derivation_config
        WHERE step_name = ? AND is_active = TRUE
        """,
        [step_name],
    ).fetchone()

    if not row:
        return None

    return DerivationConfig(
        step_name=row[0],
        phase=row[1],
        sequence=row[2],
        enabled=row[3],
        llm=row[4],
        input_graph_query=row[5],
        input_model_query=row[6],
        instruction=row[7],
        example=row[8],
        params=row[9],
        temperature=row[10],
        max_tokens=row[11],
        max_candidates=row[12],
        batch_size=row[13],
    )


# =============================================================================
# Relationship Config Operations
# =============================================================================


def get_relationship_configs(
    engine: Any,
    enabled_only: bool = True,
) -> list[RelationshipConfig]:
    """
    Get all relationship derivation configurations.

    Args:
        engine: DuckDB connection
        enabled_only: If True, only return enabled configs

    Returns:
        List of RelationshipConfig objects ordered by sequence
    """
    import json

    query = """
        SELECT element_type, enabled, sequence, instruction, example,
               valid_relationship_types, target_element_types,
               include_existing_elements, temperature, max_tokens
        FROM derivation_relationship_config
    """
    params = []

    if enabled_only:
        query += " WHERE enabled = TRUE"

    query += " ORDER BY sequence"

    try:
        rows = engine.execute(query, params).fetchall()
    except Exception:
        # Table may not exist yet
        return []

    configs = []
    for row in rows:
        # Parse JSON arrays
        valid_types = json.loads(row[5]) if row[5] else None
        target_types = json.loads(row[6]) if row[6] else None

        configs.append(
            RelationshipConfig(
                element_type=row[0],
                enabled=row[1],
                sequence=row[2],
                instruction=row[3],
                example=row[4],
                valid_relationship_types=valid_types,
                target_element_types=target_types,
                include_existing_elements=row[7] or False,
                temperature=row[8],
                max_tokens=row[9],
            )
        )
    return configs


def get_relationship_config(
    engine: Any, element_type: str
) -> RelationshipConfig | None:
    """Get relationship config for a specific element type."""
    import json

    try:
        row = engine.execute(
            """
            SELECT element_type, enabled, sequence, instruction, example,
                   valid_relationship_types, target_element_types,
                   include_existing_elements, temperature, max_tokens
            FROM derivation_relationship_config
            WHERE element_type = ? AND enabled = TRUE
            """,
            [element_type],
        ).fetchone()
    except Exception:
        return None

    if not row:
        return None

    valid_types = json.loads(row[5]) if row[5] else None
    target_types = json.loads(row[6]) if row[6] else None

    return RelationshipConfig(
        element_type=row[0],
        enabled=row[1],
        sequence=row[2],
        instruction=row[3],
        example=row[4],
        valid_relationship_types=valid_types,
        target_element_types=target_types,
        include_existing_elements=row[7] or False,
        temperature=row[8],
        max_tokens=row[9],
    )


def update_derivation_config(
    engine: Any,
    step_name: str,
    *,
    enabled: bool | None = None,
    sequence: int | None = None,
    input_graph_query: str | None = None,
    input_model_query: str | None = None,
    instruction: str | None = None,
    example: str | None = None,
    params: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> bool:
    """Update a derivation configuration."""
    updates = []
    query_params = []

    if enabled is not None:
        updates.append("enabled = ?")
        query_params.append(enabled)
    if sequence is not None:
        updates.append("sequence = ?")
        query_params.append(sequence)
    if input_graph_query is not None:
        updates.append("input_graph_query = ?")
        query_params.append(input_graph_query)
    if input_model_query is not None:
        updates.append("input_model_query = ?")
        query_params.append(input_model_query)
    if instruction is not None:
        updates.append("instruction = ?")
        query_params.append(instruction)
    if example is not None:
        updates.append("example = ?")
        query_params.append(example)
    if params is not None:
        updates.append("params = ?")
        query_params.append(params)
    if temperature is not None:
        updates.append("temperature = ?")
        query_params.append(temperature)
    if max_tokens is not None:
        updates.append("max_tokens = ?")
        query_params.append(max_tokens)

    if not updates:
        return False

    query_params.append(step_name)
    query = f"UPDATE derivation_config SET {', '.join(updates)} WHERE step_name = ? AND is_active = TRUE"

    result = engine.execute(query, query_params)
    return result.rowcount > 0 if hasattr(result, "rowcount") else True


# =============================================================================
# File Type Registry Operations
# =============================================================================


def get_file_types(engine: Any) -> list[FileType]:
    """Get all file type registry entries."""
    rows = engine.execute("SELECT extension, file_type, subtype, chunk_delimiter, chunk_max_tokens, chunk_overlap FROM file_type_registry ORDER BY file_type, extension").fetchall()
    return [
        FileType(
            extension=row[0],
            file_type=row[1],
            subtype=row[2],
            chunk_delimiter=row[3],
            chunk_max_tokens=row[4],
            chunk_overlap=row[5] or 0,
        )
        for row in rows
    ]


def get_file_type(engine: Any, extension: str) -> FileType | None:
    """Get a specific file type by extension."""
    row = engine.execute(
        "SELECT extension, file_type, subtype, chunk_delimiter, chunk_max_tokens, chunk_overlap FROM file_type_registry WHERE extension = ?",
        [extension],
    ).fetchone()

    if not row:
        return None

    return FileType(
        extension=row[0],
        file_type=row[1],
        subtype=row[2],
        chunk_delimiter=row[3],
        chunk_max_tokens=row[4],
        chunk_overlap=row[5] or 0,
    )


def add_file_type(engine: Any, extension: str, file_type: str, subtype: str) -> bool:
    """
    Add a new file type to the registry.

    Returns:
        True if added, False if already exists
    """
    existing = get_file_type(engine, extension)
    if existing:
        return False

    engine.execute(
        "INSERT INTO file_type_registry (extension, file_type, subtype) VALUES (?, ?, ?)",
        [extension, file_type, subtype],
    )
    return True


def update_file_type(engine: Any, extension: str, file_type: str, subtype: str) -> bool:
    """Update an existing file type."""
    result = engine.execute(
        "UPDATE file_type_registry SET file_type = ?, subtype = ? WHERE extension = ?",
        [file_type, subtype, extension],
    )
    return result.rowcount > 0 if hasattr(result, "rowcount") else True


def delete_file_type(engine: Any, extension: str) -> bool:
    """Delete a file type from the registry."""
    result = engine.execute(
        "DELETE FROM file_type_registry WHERE extension = ?",
        [extension],
    )
    return result.rowcount > 0 if hasattr(result, "rowcount") else True


# =============================================================================
# System Settings Operations
# =============================================================================


def get_setting(engine: Any, key: str, default: str | None = None) -> str | None:
    """Get a system setting by key."""
    row = engine.execute(
        "SELECT value FROM system_settings WHERE key = ?",
        [key],
    ).fetchone()

    if not row:
        return default

    return row[0]


def set_setting(engine: Any, key: str, value: str) -> None:
    """Set a system setting (upsert)."""
    existing = get_setting(engine, key)
    if existing is not None:
        engine.execute(
            "UPDATE system_settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
            [value, key],
        )
    else:
        engine.execute(
            "INSERT INTO system_settings (key, value) VALUES (?, ?)",
            [key, value],
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def enable_step(engine: Any, step_type: str, name: str) -> bool:
    """
    Enable a pipeline step.

    Args:
        engine: DuckDB connection
        step_type: 'extraction' or 'derivation'
        name: The node_type or step_name to enable

    Returns:
        True if updated, False if not found
    """
    if step_type == "extraction":
        return update_extraction_config(engine, name, enabled=True)
    elif step_type == "derivation":
        return update_derivation_config(engine, name, enabled=True)
    else:
        return False


def disable_step(engine: Any, step_type: str, name: str) -> bool:
    """
    Disable a pipeline step.

    Args:
        engine: DuckDB connection
        step_type: 'extraction' or 'derivation'
        name: The node_type or step_name to disable

    Returns:
        True if updated, False if not found
    """
    if step_type == "extraction":
        return update_extraction_config(engine, name, enabled=False)
    elif step_type == "derivation":
        return update_derivation_config(engine, name, enabled=False)
    else:
        return False


def list_steps(
    engine: Any,
    step_type: str,
    enabled_only: bool = False,
    phase: str | None = None,
) -> list[dict[str, Any]]:
    """
    List all steps of a given type.

    Args:
        engine: DuckDB connection
        step_type: 'extraction' or 'derivation'
        enabled_only: If True, only return enabled steps
        phase: For derivation, filter by phase ("prep", "generate", "refine")

    Returns:
        List of dicts with step info
    """
    if step_type == "extraction":
        configs = get_extraction_configs(engine, enabled_only=enabled_only)
        return [
            {
                "name": c.node_type,
                "sequence": c.sequence,
                "enabled": c.enabled,
                "has_instruction": bool(c.instruction),
            }
            for c in configs
        ]
    elif step_type == "derivation":
        configs = get_derivation_configs(engine, enabled_only=enabled_only, phase=phase)
        return [
            {
                "name": c.step_name,
                "phase": c.phase,
                "sequence": c.sequence,
                "enabled": c.enabled,
                "llm": c.llm,
                "has_query": bool(c.input_graph_query),
            }
            for c in configs
        ]
    else:
        return []


# =============================================================================
# Versioned Config Updates
# =============================================================================


def create_derivation_config_version(
    engine: Any,
    step_name: str,
    *,
    instruction: str | None = None,
    example: str | None = None,
    input_graph_query: str | None = None,
    input_model_query: str | None = None,
    params: str | None = None,
    enabled: bool | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """
    Create a new version of a derivation config (versioned update).

    This deactivates the current config and creates a new one with incremented version.

    Args:
        engine: DuckDB connection
        step_name: The step name to update
        instruction: New instruction (or None to keep current)
        example: New example (or None to keep current)
        input_graph_query: New graph query (or None to keep current)
        input_model_query: New model query (or None to keep current)
        params: New params JSON (or None to keep current)
        enabled: Enable/disable (or None to keep current)
        temperature: LLM temperature override (or None to keep current)
        max_tokens: LLM max_tokens override (or None to keep current)

    Returns:
        Dict with success, new_version, old_version
    """
    # Get current config
    current = engine.execute(
        """
        SELECT id, version, phase, sequence, enabled, llm,
               input_graph_query, input_model_query, instruction, example, params,
               temperature, max_tokens
        FROM derivation_config
        WHERE step_name = ? AND is_active = TRUE
        """,
        [step_name],
    ).fetchone()

    if not current:
        return {"success": False, "error": f"Config not found for {step_name}"}

    (old_id, old_version, phase, sequence, cur_enabled, llm, cur_graph_query, cur_model_query, cur_instruction, cur_example, cur_params, cur_temperature, cur_max_tokens) = current
    new_version = old_version + 1

    # Use current values if not provided
    new_instruction = instruction if instruction is not None else cur_instruction
    new_example = example if example is not None else cur_example
    new_graph_query = input_graph_query if input_graph_query is not None else cur_graph_query
    new_model_query = input_model_query if input_model_query is not None else cur_model_query
    new_params = params if params is not None else cur_params
    new_enabled = enabled if enabled is not None else cur_enabled
    new_temperature = temperature if temperature is not None else cur_temperature
    new_max_tokens = max_tokens if max_tokens is not None else cur_max_tokens

    # Deactivate old config
    engine.execute(
        "UPDATE derivation_config SET is_active = FALSE WHERE id = ?",
        [old_id],
    )

    # Get next ID
    max_id = engine.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM derivation_config").fetchone()
    next_id = max_id[0]

    # Insert new version
    engine.execute(
        """
        INSERT INTO derivation_config
        (id, step_name, phase, version, sequence, enabled, llm,
         input_graph_query, input_model_query, instruction, example, params,
         temperature, max_tokens, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)
        """,
        [
            next_id,
            step_name,
            phase,
            new_version,
            sequence,
            new_enabled,
            llm,
            new_graph_query,
            new_model_query,
            new_instruction,
            new_example,
            new_params,
            new_temperature,
            new_max_tokens,
        ],
    )

    return {
        "success": True,
        "step_name": step_name,
        "old_version": old_version,
        "new_version": new_version,
    }


def create_extraction_config_version(
    engine: Any,
    node_type: str,
    *,
    instruction: str | None = None,
    example: str | None = None,
    input_sources: str | None = None,
    enabled: bool | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Create a new version of an extraction config."""
    current = engine.execute(
        """
        SELECT id, version, sequence, enabled, input_sources, instruction, example,
               temperature, max_tokens
        FROM extraction_config
        WHERE node_type = ? AND is_active = TRUE
        """,
        [node_type],
    ).fetchone()

    if not current:
        return {"success": False, "error": f"Config not found for {node_type}"}

    (old_id, old_version, sequence, cur_enabled, cur_sources, cur_instruction, cur_example, cur_temperature, cur_max_tokens) = current
    new_version = old_version + 1

    new_instruction = instruction if instruction is not None else cur_instruction
    new_example = example if example is not None else cur_example
    new_sources = input_sources if input_sources is not None else cur_sources
    new_enabled = enabled if enabled is not None else cur_enabled
    new_temperature = temperature if temperature is not None else cur_temperature
    new_max_tokens = max_tokens if max_tokens is not None else cur_max_tokens

    engine.execute(
        "UPDATE extraction_config SET is_active = FALSE WHERE id = ?",
        [old_id],
    )

    # Get next ID
    next_id_result = engine.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM extraction_config").fetchone()
    next_id = next_id_result[0]

    engine.execute(
        """
        INSERT INTO extraction_config
        (id, node_type, version, sequence, enabled, input_sources, instruction, example,
         temperature, max_tokens, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, CURRENT_TIMESTAMP)
        """,
        [next_id, node_type, new_version, sequence, new_enabled, new_sources, new_instruction, new_example, new_temperature, new_max_tokens],
    )

    return {
        "success": True,
        "node_type": node_type,
        "old_version": old_version,
        "new_version": new_version,
    }


def get_active_config_versions(engine: Any) -> dict[str, dict[str, int]]:
    """
    Get current active versions for all configs.

    Returns:
        Dict with extraction and derivation (prep/generate/refine) versions
    """
    versions = {"extraction": {}, "derivation": {}}

    # Extraction
    rows = engine.execute("SELECT node_type, version FROM extraction_config WHERE is_active = TRUE").fetchall()
    for r in rows:
        versions["extraction"][r[0]] = r[1]

    # Derivation (includes all phases: prep, generate, refine)
    rows = engine.execute("SELECT step_name, version FROM derivation_config WHERE is_active = TRUE").fetchall()
    for r in rows:
        versions["derivation"][r[0]] = r[1]

    return versions


# =============================================================================
# Consistency Run Logging
# =============================================================================


def log_consistency_run(
    engine: Any,
    repo_name: str,
    num_runs: int,
    results: dict[str, Any],
    config_versions: dict[str, dict[str, int]],
) -> int:
    """
    Log a consistency run with results and config versions.

    Args:
        engine: DuckDB connection
        repo_name: Repository name
        num_runs: Number of runs performed
        results: Consistency results dict
        config_versions: Config versions used

    Returns:
        Run ID
    """
    import json

    # Ensure consistency_runs table exists
    engine.execute("""
        CREATE TABLE IF NOT EXISTS consistency_runs (
            id INTEGER PRIMARY KEY,
            repo_name VARCHAR NOT NULL,
            num_runs INTEGER NOT NULL,
            name_consistency FLOAT,
            identifier_consistency FLOAT,
            count_variance FLOAT,
            stable_elements INTEGER,
            total_elements INTEGER,
            config_versions JSON,
            raw_results JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Get next ID
    result = engine.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM consistency_runs").fetchone()
    next_id = result[0]

    engine.execute(
        """
        INSERT INTO consistency_runs
        (id, repo_name, num_runs, name_consistency, identifier_consistency, count_variance,
         stable_elements, total_elements, config_versions, raw_results, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [
            next_id,
            repo_name,
            num_runs,
            results.get("name_consistency", 0.0),
            results.get("identifier_consistency", 0.0),
            results.get("count_variance", 0.0),
            results.get("stable_count", 0),
            results.get("total_unique", 0),
            json.dumps(config_versions),
            json.dumps(results),
        ],
    )

    return next_id


def get_consistency_history(engine: Any, repo_name: str | None = None, limit: int = 10) -> list[dict]:
    """
    Get consistency run history.

    Args:
        engine: DuckDB connection
        repo_name: Filter by repo (or None for all)
        limit: Max results

    Returns:
        List of run records
    """
    import json

    # Check if table exists
    tables = engine.execute("SELECT table_name FROM information_schema.tables WHERE table_name = 'consistency_runs'").fetchall()
    if not tables:
        return []

    query = """
        SELECT id, repo_name, num_runs, name_consistency, identifier_consistency,
               count_variance, stable_elements, total_elements, config_versions, created_at
        FROM consistency_runs
    """
    params = []

    if repo_name:
        query += " WHERE repo_name = ?"
        params.append(repo_name)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = engine.execute(query, params).fetchall()

    return [
        {
            "id": r[0],
            "repo_name": r[1],
            "num_runs": r[2],
            "name_consistency": r[3],
            "identifier_consistency": r[4],
            "count_variance": r[5],
            "stable_elements": r[6],
            "total_elements": r[7],
            "config_versions": json.loads(r[8]) if r[8] else {},
            "created_at": str(r[9]),
        }
        for r in rows
    ]


# =============================================================================
# Derivation Patterns Operations
# =============================================================================


def get_derivation_patterns(
    engine: Any,
    step_name: str,
    pattern_type: str | None = None,
) -> dict[str, set[str]]:
    """
    Get derivation patterns for a step.

    Args:
        engine: DuckDB connection
        step_name: The derivation step name (e.g., 'ApplicationService')
        pattern_type: Filter by type ('include' or 'exclude'), or None for all

    Returns:
        Dict mapping pattern_type to set of patterns.
        E.g., {'include': {'get', 'post', ...}, 'exclude': {'_', 'private', ...}}

    Raises:
        ValueError: If no patterns found for the step
    """
    import json

    query = """
        SELECT pattern_type, patterns
        FROM derivation_patterns
        WHERE step_name = ? AND is_active = TRUE
    """
    params = [step_name]

    if pattern_type is not None:
        query += " AND pattern_type = ?"
        params.append(pattern_type)

    rows = engine.execute(query, params).fetchall()

    if not rows:
        raise ValueError(f"No patterns found for derivation step '{step_name}'")

    result: dict[str, set[str]] = {"include": set(), "exclude": set()}

    for row in rows:
        ptype = row[0]
        patterns_json = row[1]
        patterns_list = json.loads(patterns_json) if patterns_json else []

        if ptype in result:
            result[ptype].update(patterns_list)

    return result


def get_include_patterns(engine: Any, step_name: str) -> set[str]:
    """
    Get include patterns for a derivation step.

    Args:
        engine: DuckDB connection
        step_name: The derivation step name

    Returns:
        Set of include patterns

    Raises:
        ValueError: If no patterns found for the step
    """
    patterns = get_derivation_patterns(engine, step_name, pattern_type="include")
    return patterns.get("include", set())


def get_exclude_patterns(engine: Any, step_name: str) -> set[str]:
    """
    Get exclude patterns for a derivation step.

    Args:
        engine: DuckDB connection
        step_name: The derivation step name

    Returns:
        Set of exclude patterns

    Raises:
        ValueError: If no patterns found for the step
    """
    patterns = get_derivation_patterns(engine, step_name, pattern_type="exclude")
    return patterns.get("exclude", set())


def update_derivation_patterns(
    engine: Any,
    step_name: str,
    pattern_type: str,
    pattern_category: str,
    patterns: list[str],
) -> bool:
    """
    Update derivation patterns for a step.

    Args:
        engine: DuckDB connection
        step_name: The derivation step name
        pattern_type: 'include' or 'exclude'
        pattern_category: Category for the patterns (e.g., 'http_methods')
        patterns: List of pattern strings

    Returns:
        True if updated/inserted successfully
    """
    import json

    patterns_json = json.dumps(patterns)

    # Try update first
    result = engine.execute(
        """
        UPDATE derivation_patterns
        SET patterns = ?, is_active = TRUE
        WHERE step_name = ? AND pattern_type = ? AND pattern_category = ?
        """,
        [patterns_json, step_name, pattern_type, pattern_category],
    )

    if hasattr(result, "rowcount") and result.rowcount > 0:
        return True

    # Insert if not exists
    max_id = engine.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM derivation_patterns").fetchone()
    next_id = max_id[0]

    engine.execute(
        """
        INSERT INTO derivation_patterns (id, step_name, pattern_type, pattern_category, patterns, is_active)
        VALUES (?, ?, ?, ?, ?, TRUE)
        """,
        [next_id, step_name, pattern_type, pattern_category, patterns_json],
    )
    return True
