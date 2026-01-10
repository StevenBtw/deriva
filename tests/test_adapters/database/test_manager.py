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
