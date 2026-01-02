"""Export current database to SQL seed files."""

from __future__ import annotations
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).parent / "deriva.db"
SCRIPTS_DIR = Path(__file__).parent / "scripts"

conn = duckdb.connect(str(DB_PATH))

# Export file_type_registry to SQL
print("Generating 2_file_types.sql from current database...")
result = conn.execute("""
    SELECT extension, file_type, subtype
    FROM file_type_registry
    ORDER BY file_type, extension
""").fetchall()

with open(SCRIPTS_DIR / "2_file_types.sql", "w", encoding="utf-8") as f:
    f.write("-- File Type Registry\n")
    f.write("-- Exported from current database\n")
    f.write(f"-- Total entries: {len(result)}\n\n")

    current_type = None
    for ext, ftype, subtype in result:
        # Add comment for each new file type category
        if ftype != current_type:
            f.write(f"\n-- {ftype.upper()}\n")
            current_type = ftype

        # Escape single quotes
        ext_escaped = ext.replace("'", "''")
        f.write(
            f"INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('{ext_escaped}', '{ftype}', '{subtype}');\n"
        )

print(f"[OK] Generated 2_file_types.sql ({len(result)} entries)")

# Export extraction_config_versions to SQL
result = conn.execute("""
    SELECT node_type, version, enabled, input_file_types,
           input_graph_elements, instruction, example, is_active
    FROM extraction_config_versions
    ORDER BY node_type, version
""").fetchall()

print(f"[OK] Found {len(result)} extraction config versions")

if len(result) > 0:
    print("Generating 3_extraction.sql from current database...")
    with open(SCRIPTS_DIR / "3_extraction.sql", "w", encoding="utf-8") as f:
        f.write("-- Extraction Config Versions\n")
        f.write("-- Exported from current database\n")
        f.write(f"-- Total versions: {len(result)}\n\n")

        for row in result:
            (
                node_type,
                version,
                enabled,
                input_file_types,
                input_graph_elements,
                instruction,
                example,
                is_active,
            ) = row

            enabled_str = "TRUE" if enabled else "FALSE"
            is_active_str = "TRUE" if is_active else "FALSE"

            # Escape single quotes
            instruction_escaped = instruction.replace("'", "''") if instruction else ""
            example_escaped = example.replace("'", "''") if example else ""

            f.write(f"-- {node_type} v{version}\n")
            f.write(f"""INSERT INTO extraction_config_versions
    (node_type, version, enabled, input_file_types, input_graph_elements, instruction, example, is_active)
VALUES
    ('{node_type}', {version}, {enabled_str}, '{input_file_types or ""}', '{input_graph_elements or ""}', '{instruction_escaped}', '{example_escaped}', {is_active_str});

""")

    print(f"[OK] Generated 3_extraction.sql ({len(result)} versions)")
else:
    print(
        "[INFO] No extraction configs in database - keeping existing 3_extraction.sql"
    )

conn.close()
print("\n[DONE] Database export complete!")
