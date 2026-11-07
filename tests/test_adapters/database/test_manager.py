"""Tests for adapters.database.manager module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deriva.adapters.database.manager import (
    DB_PATH,
    SCRIPTS_DIR,
    run_sql_file,
)


def _scalar(conn, sql: str):
    row = conn.execute(sql).fetchone()
    assert row is not None
    return row[0]


class TestDbPath:
    """Tests for database path constants."""

    def test_db_path_is_path(self):
        """Should be a Path object."""
        assert isinstance(DB_PATH, Path)
        assert DB_PATH.name == "sql.db"

    def test_scripts_dir_is_path(self):
        """Should be a Path object."""
        # The schema scripts the database is made from
        assert SCRIPTS_DIR.is_dir() and any(p.suffix == ".sql" for p in SCRIPTS_DIR.iterdir())


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

            mock_get.assert_called_once_with()
            # The statements without their separator, then the connection it opened is closed
            mock_conn.execute.assert_called_once_with("SELECT 1")
            mock_conn.close.assert_called_once_with()


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


class TestMarkdownFileTypeMigration:
    """A database from before 0.9.0 gets the .markdown file type through a numbered migration; one that has it keeps its row."""

    @staticmethod
    def _registry(conn, md: bool = True):
        """A registry from an earlier version: seeded (it lists .md), or empty as in a fresh database before its seed."""
        conn.execute(
            "CREATE TABLE file_type_registry (extension VARCHAR PRIMARY KEY, file_type VARCHAR NOT NULL, subtype VARCHAR NOT NULL, "
            "chunk_delimiter VARCHAR, chunk_max_tokens INTEGER, chunk_overlap INTEGER DEFAULT 0)"
        )
        conn.execute("CREATE TABLE system_settings (key VARCHAR PRIMARY KEY, value VARCHAR)")
        if md:
            conn.execute("INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.md', 'docs', 'markdown')")
            conn.execute("INSERT INTO system_settings (key, value) VALUES ('default_batch_size', '10')")

    def test_an_existing_database_gets_markdown_once(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn)

        run_migrations(conn)
        run_migrations(conn)

        assert conn.execute("SELECT extension, file_type, subtype FROM file_type_registry WHERE extension = '.markdown'").fetchall() == [(".markdown", "docs", "markdown")]

    def test_markdown_is_chunked_like_md_in_the_seed_and_the_migration(self):
        import json

        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn)
        run_migrations(conn)

        seed = {r["extension"]: r for r in json.loads((SCRIPTS_DIR.parent / "data" / "file_types.json").read_text(encoding="utf-8"))}
        migrated = _scalar(conn, "SELECT chunk_delimiter FROM file_type_registry WHERE extension = '.markdown'")
        assert migrated == seed[".markdown"]["chunk_delimiter"] == seed[".md"]["chunk_delimiter"]

    def test_a_markdown_row_deleted_after_the_migration_stays_deleted(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn)
        run_migrations(conn)
        conn.execute("DELETE FROM file_type_registry WHERE extension = '.markdown'")

        run_migrations(conn)

        assert _scalar(conn, "SELECT COUNT(*) FROM file_type_registry WHERE extension = '.markdown'") == 0

    def test_an_empty_registry_is_left_to_the_seed(self):
        """The seed fills only empty tables: a row added before it would keep the whole seed out."""
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn, md=False)

        run_migrations(conn)

        assert _scalar(conn, "SELECT COUNT(*) FROM file_type_registry") == 0
        assert _scalar(conn, "SELECT COUNT(*) FROM system_settings") == 0

    def test_empty_settings_are_left_to_the_seed(self):
        """A database with file types but no settings yet gets no marker, which would keep the settings seed out."""
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn)
        conn.execute("DELETE FROM system_settings")

        run_migrations(conn)

        assert _scalar(conn, "SELECT COUNT(*) FROM system_settings") == 0

    def test_a_database_with_its_own_markdown_row_keeps_it(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        self._registry(conn)
        conn.execute("INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.markdown', 'exclude', 'generated')")

        run_migrations(conn)

        assert conn.execute("SELECT file_type, subtype FROM file_type_registry WHERE extension = '.markdown'").fetchall() == [("exclude", "generated")]


class TestProtoFileTypeMigration:
    """A database from before 0.9.0 gets the .proto file type (an interface schema) once; one that has it keeps its row."""

    def test_an_existing_database_gets_proto_once_as_in_the_seed(self):
        import json

        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        TestMarkdownFileTypeMigration._registry(conn)

        run_migrations(conn)
        run_migrations(conn)

        seed = {r["extension"]: r for r in json.loads((SCRIPTS_DIR.parent / "data" / "file_types.json").read_text(encoding="utf-8"))}
        assert conn.execute("SELECT extension, file_type, subtype FROM file_type_registry WHERE extension = '.proto'").fetchall() == [(".proto", "schema", "proto")]
        assert (seed[".proto"]["file_type"], seed[".proto"]["subtype"]) == ("schema", "proto")

    def test_a_proto_row_deleted_after_the_migration_stays_deleted(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        TestMarkdownFileTypeMigration._registry(conn)
        run_migrations(conn)
        conn.execute("DELETE FROM file_type_registry WHERE extension = '.proto'")

        run_migrations(conn)

        assert _scalar(conn, "SELECT COUNT(*) FROM file_type_registry WHERE extension = '.proto'") == 0

    def test_a_database_with_its_own_proto_row_keeps_it(self):
        import duckdb

        from deriva.adapters.database.manager import run_migrations

        conn = duckdb.connect(":memory:")
        TestMarkdownFileTypeMigration._registry(conn)
        conn.execute("INSERT INTO file_type_registry (extension, file_type, subtype) VALUES ('.proto', 'exclude', 'generated')")

        run_migrations(conn)

        assert conn.execute("SELECT file_type, subtype FROM file_type_registry WHERE extension = '.proto'").fetchall() == [("exclude", "generated")]


class TestEnsureDatabase:
    """A fresh install creates the schema and seeds the shipped configuration on first use."""

    CONFIG_TABLES = ("file_type_registry", "extraction_config", "derivation_config", "derivation_patterns", "system_settings")

    def test_a_missing_database_is_created_and_seeded(self, tmp_path):
        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        assert ensure_database(db) is True

        conn = duckdb.connect(str(db), read_only=True)
        counts = {t: _scalar(conn, f"SELECT COUNT(*) FROM {t}") for t in self.CONFIG_TABLES}
        conn.close()
        assert all(n > 0 for n in counts.values()), counts

    def test_every_shipped_seed_row_reaches_a_fresh_database(self, tmp_path):
        """Migrations run before the seed; one that adds a row to an empty table would keep that table's seed out."""
        import json

        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        ensure_database(db)

        conn = duckdb.connect(str(db), read_only=True)
        for table, file in (("file_type_registry", "file_types.json"), ("system_settings", "system_settings.json")):
            shipped = json.loads((SCRIPTS_DIR.parent / "data" / file).read_text(encoding="utf-8"))
            assert _scalar(conn, f"SELECT COUNT(*) FROM {table}") == len(shipped), table
        conn.close()

    def test_seeded_steps_are_the_active_versions(self, tmp_path):
        import duckdb

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        ensure_database(db)

        conn = duckdb.connect(str(db), read_only=True)
        for table in ("extraction_config", "derivation_config"):
            inactive = _scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE NOT is_active")
            versions = _scalar(conn, f"SELECT MIN(version) FROM {table}")
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
        assert _scalar(conn, "SELECT value FROM system_settings WHERE key = 'default_batch_size'") == "42"
        conn.close()

    def test_a_failed_seed_leaves_no_database_behind(self, tmp_path):
        """A half-made database (schema without seed) would be taken for a configured one on every later start."""
        from unittest.mock import patch

        import pytest

        from deriva.adapters.database.manager import ensure_database

        db = tmp_path / "sql.db"
        with patch("deriva.adapters.database.db_tool.seed_from_json", side_effect=OSError("seed data missing")), pytest.raises(OSError):
            ensure_database(db)

        assert list(tmp_path.iterdir()) == []
        assert ensure_database(db) is True

    def test_get_connection_seeds_a_missing_database(self, tmp_path):
        from deriva.adapters.database import manager

        db = tmp_path / "sql.db"
        with patch.object(manager, "DB_PATH", db):
            conn = manager.get_connection(read_only=True)
            try:
                assert _scalar(conn, "SELECT COUNT(*) FROM extraction_config") > 0
            finally:
                conn.close()


def test_an_existing_database_without_the_schema_keeps_its_contents(tmp_path):
    """A file that holds something else is completed in place, never replaced by a staged database."""
    import duckdb

    from deriva.adapters.database.manager import ensure_database

    db = tmp_path / "sql.db"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE notes (text VARCHAR)")
    conn.execute("INSERT INTO notes VALUES ('keep me')")
    conn.close()

    assert ensure_database(db) is True

    conn = duckdb.connect(str(db), read_only=True)
    assert _scalar(conn, "SELECT text FROM notes") == "keep me"
    assert _scalar(conn, "SELECT COUNT(*) FROM extraction_config") > 0
    conn.close()
    assert [p.name for p in tmp_path.iterdir() if "partial" in p.name] == []


def test_a_database_another_process_holds_is_named_with_what_to_do(tmp_path, monkeypatch):
    """DuckDB has one writer: when the studio or another CLI run holds the config database, the error says so."""
    import duckdb

    from deriva.adapters.database import manager

    database = tmp_path / "sql.db"
    database.touch()
    monkeypatch.setattr(manager, "DB_PATH", database)

    def locked(*_, **__):
        raise duckdb.IOException(f'IO Error: Cannot open file "{database}": The process cannot access the file because it is being used by another process.')

    monkeypatch.setattr(manager.duckdb, "connect", locked)

    with pytest.raises(manager.ConfigDatabaseBusy, match="another Deriva process") as raised:
        manager.get_connection()
    assert str(database) in str(raised.value)


def test_other_io_errors_are_not_called_busy(tmp_path, monkeypatch):
    import duckdb

    from deriva.adapters.database import manager

    database = tmp_path / "sql.db"
    database.touch()
    monkeypatch.setattr(manager, "DB_PATH", database)
    monkeypatch.setattr(manager.duckdb, "connect", lambda *_, **__: (_ for _ in ()).throw(duckdb.IOException("IO Error: disk full")))

    with pytest.raises(duckdb.IOException, match="disk full"):
        manager.get_connection()
