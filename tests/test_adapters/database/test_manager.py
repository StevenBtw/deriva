"""Tests for adapters.database.manager module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from deriva.adapters.database.manager import (
    DB_PATH,
    SCRIPTS_DIR,
    run_sql_file,
)


class TestDbPath:
    """Tests for database path constants."""

    def test_db_path_is_path(self):
        """Should be a Path object."""
        assert isinstance(DB_PATH, Path)

    def test_scripts_dir_is_path(self):
        """Should be a Path object."""
        assert isinstance(SCRIPTS_DIR, Path)


class TestRunSqlFile:
    """Tests for run_sql_file function."""

    def test_executes_sql_statements(self, tmp_path):
        """Should execute SQL statements from file."""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1; SELECT 2; SELECT 3;")

        # Create a mock connection
        mock_conn = MagicMock()

        count = run_sql_file(sql_file, mock_conn)

        assert count == 3
        assert mock_conn.execute.call_count == 3

    def test_handles_empty_statements(self, tmp_path):
        """Should handle empty statements gracefully."""
        sql_file = tmp_path / "empty.sql"
        sql_file.write_text("SELECT 1; ; ;")

        mock_conn = MagicMock()
        count = run_sql_file(sql_file, mock_conn)

        # Only counts non-empty statements
        assert count == 1

    def test_creates_connection_if_none_provided(self, tmp_path):
        """Should create connection if none provided."""
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 1;")

        with patch("deriva.adapters.database.manager.get_connection") as mock_get:
            mock_conn = MagicMock()
            mock_get.return_value = mock_conn

            run_sql_file(sql_file, None)

            mock_get.assert_called_once()
            mock_conn.close.assert_called_once()


class TestExtractionParamsMigration:
    """Existing databases get extraction_config.params through the numbered migration."""

    def test_adds_params_column_once(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        conn.execute("CREATE TABLE extraction_config (id INTEGER PRIMARY KEY, node_type VARCHAR)")

        first = run_migrations(conn)
        second = run_migrations(conn)

        columns = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'extraction_config'").fetchall()}
        assert "params" in columns
        assert (first, second) == (1, 0)
        conn.execute("SELECT 1")  # a passed-in connection stays open


class TestEnsureDatabase:
    """A fresh install creates the schema and seeds the shipped configuration on first use."""

    CONFIG_TABLES = ("file_type_registry", "extraction_config", "derivation_config", "derivation_patterns", "system_settings")

    def test_a_missing_database_is_created_and_seeded(self, tmp_path):
        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        assert ensure_database(db) is True

        conn = duckdb.connect(str(db), read_only=True)
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in self.CONFIG_TABLES}
        conn.close()
        assert all(n > 0 for n in counts.values()), counts

    def test_seeded_steps_are_the_active_versions(self, tmp_path):
        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        ensure_database(db)

        conn = duckdb.connect(str(db), read_only=True)
        for table in ("extraction_config", "derivation_config"):
            inactive = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE NOT is_active").fetchone()[0]
            versions = conn.execute(f"SELECT MIN(version) FROM {table}").fetchone()[0]
            assert inactive == 0
            assert versions >= 1
        conn.close()

    def test_an_existing_database_is_left_alone(self, tmp_path):
        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        ensure_database(db)
        conn = duckdb.connect(str(db))
        conn.execute("UPDATE system_settings SET value = '42' WHERE key = 'default_batch_size'")
        conn.close()

        assert ensure_database(db) is False

        conn = duckdb.connect(str(db), read_only=True)
        assert conn.execute("SELECT value FROM system_settings WHERE key = 'default_batch_size'").fetchone()[0] == "42"
        conn.close()

    def test_get_connection_seeds_a_missing_database(self, tmp_path):
        from deriva.adapters.database import manager

        db = tmp_path / "sql.db"
        with patch.object(manager, "DB_PATH", db):
            conn = manager.get_connection(read_only=True)
            try:
                assert conn.execute("SELECT COUNT(*) FROM extraction_config").fetchone()[0] > 0
            finally:
                conn.close()
