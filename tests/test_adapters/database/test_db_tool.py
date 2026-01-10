"""Tests for adapters.database.db_tool module."""

from __future__ import annotations

from deriva.adapters.database.db_tool import TABLES, get_connection


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
