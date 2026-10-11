"""Tests for adapters.database.db_tool module."""

from __future__ import annotations

import json

from deriva.adapters.database.db_tool import TABLES, get_connection, import_table


class TestTables:
    """Tests for TABLES configuration."""

    def test_tables_is_dict(self):
        """Should be a dictionary of table configs."""
        assert isinstance(TABLES, dict)

    def test_tables_have_required_keys(self):
        """Each table config should have file, pk, order_by."""
        for table_name, config in TABLES.items():
            assert "file" in config, f"{table_name} missing 'file'"
            assert "pk" in config, f"{table_name} missing 'pk'"
            assert "order_by" in config, f"{table_name} missing 'order_by'"

    def test_tables_include_core_tables(self):
        """Should include core tables."""
        expected = ["file_type_registry", "extraction_config", "derivation_config"]
        for table in expected:
            assert table in TABLES


class TestGetConnection:
    """Tests for get_connection function."""

    def test_returns_connection_object(self, tmp_path):
        """Should return a connection object."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        try:
            assert conn is not None
            # Should be able to execute queries
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None
            assert result[0] == 1
        finally:
            conn.close()

    def test_read_only_mode(self, tmp_path):
        """Should support read-only mode."""
        db_path = tmp_path / "test.db"
        # Create the database first
        conn = get_connection(db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        # Open in read-only mode
        conn = get_connection(db_path, read_only=True)
        try:
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None
            assert result[0] == 1
        finally:
            conn.close()


class TestImportTable:
    """Tests for import_table function - seed only behavior."""

    def test_imports_into_empty_table(self, tmp_path):
        """Should import records into an empty table."""
        # Setup: create database with empty table
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        conn.execute("""
            CREATE TABLE file_type_registry (
                extension VARCHAR PRIMARY KEY,
                file_type VARCHAR,
                subtype VARCHAR
            )
        """)

        # Create test JSON file
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        json_file = data_dir / "file_types.json"
        json_file.write_text(
            json.dumps(
                [
                    {"extension": ".py", "file_type": "source", "subtype": "python"},
                    {"extension": ".js", "file_type": "source", "subtype": "javascript"},
                ]
            )
        )

        # Import should succeed
        count = import_table(conn, "file_type_registry", data_dir)

        assert count == 2

        # Verify data was inserted
        result = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        assert result is not None
        assert result[0] == 2

        conn.close()

    def test_refuses_to_overwrite_existing_data(self, tmp_path):
        """Should refuse to import when table already has data."""
        # Setup: create database with existing data
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        conn.execute("""
            CREATE TABLE file_type_registry (
                extension VARCHAR PRIMARY KEY,
                file_type VARCHAR,
                subtype VARCHAR
            )
        """)
        conn.execute("INSERT INTO file_type_registry VALUES ('.txt', 'docs', 'text')")

        # Create test JSON file with different data
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        json_file = data_dir / "file_types.json"
        json_file.write_text(
            json.dumps(
                [
                    {"extension": ".py", "file_type": "source", "subtype": "python"},
                ]
            )
        )

        # Import should be refused (returns 0)
        count = import_table(conn, "file_type_registry", data_dir)

        assert count == 0

        # Verify original data is unchanged
        result = conn.execute("SELECT extension FROM file_type_registry").fetchone()
        assert result is not None
        assert result[0] == ".txt"

        # Verify no new data was added
        total = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        assert total is not None
        assert total[0] == 1

        conn.close()

    def test_preserves_version_history_by_refusing_overwrite(self, tmp_path):
        """Should preserve existing records to maintain version history."""
        # Setup: create database with multiple existing records
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        conn.execute("""
            CREATE TABLE file_type_registry (
                extension VARCHAR PRIMARY KEY,
                file_type VARCHAR,
                subtype VARCHAR
            )
        """)
        # Insert multiple records to simulate version history
        conn.execute("INSERT INTO file_type_registry VALUES ('.py', 'source', 'python')")
        conn.execute("INSERT INTO file_type_registry VALUES ('.js', 'source', 'javascript')")

        original_result = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        assert original_result is not None
        original_count = original_result[0]

        # Create JSON file attempting to overwrite
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        json_file = data_dir / "file_types.json"
        json_file.write_text(
            json.dumps(
                [
                    {"extension": ".ts", "file_type": "source", "subtype": "typescript"},
                ]
            )
        )

        # Import should be refused
        count = import_table(conn, "file_type_registry", data_dir)

        assert count == 0

        # All original records should be preserved
        final_result = conn.execute("SELECT COUNT(*) FROM file_type_registry").fetchone()
        assert final_result is not None
        assert final_result[0] == original_count

        conn.close()


class TestExportActiveOnly:
    """Seed data holds the active configuration rows only; the version history stays local."""

    def test_active_only_leaves_out_inactive_versions(self, tmp_path):
        from deriva.adapters.database.db_tool import export_table

        conn = get_connection(tmp_path / "test.db")
        conn.execute("CREATE TABLE extraction_config (id INTEGER, node_type VARCHAR, version INTEGER, sequence INTEGER, is_active BOOLEAN)")
        conn.execute("INSERT INTO extraction_config VALUES (1, 'File', 1, 1, false), (2, 'File', 2, 1, true), (3, 'Method', 1, 2, true)")

        everything = json.loads(export_table(conn, "extraction_config", tmp_path / "all").read_text(encoding="utf-8"))
        active = json.loads(export_table(conn, "extraction_config", tmp_path / "active", active_only=True).read_text(encoding="utf-8"))
        conn.close()

        assert [r["id"] for r in everything] == [1, 2, 3]
        assert [(r["node_type"], r["version"]) for r in active] == [("File", 2), ("Method", 1)]

    def test_tables_without_versions_export_every_row(self, tmp_path):
        from deriva.adapters.database.db_tool import export_table

        conn = get_connection(tmp_path / "test.db")
        conn.execute("CREATE TABLE system_settings (key VARCHAR, value VARCHAR)")
        conn.execute("INSERT INTO system_settings VALUES ('a', '1'), ('b', '2')")

        rows = json.loads(export_table(conn, "system_settings", tmp_path, active_only=True).read_text(encoding="utf-8"))
        conn.close()

        assert [r["key"] for r in rows] == ["a", "b"]

    def test_shipped_seed_data_holds_active_rows_only(self):
        from deriva.adapters.database.db_tool import DATA_DIR

        for name in ("extraction_config.json", "derivation_config.json", "derivation_patterns.json"):
            rows = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
            assert rows, name
            assert all(r["is_active"] for r in rows), name
