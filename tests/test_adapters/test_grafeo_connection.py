"""GrafeoConnection query timing: per-query totals and slow-query warnings."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from deriva.adapters.grafeo.manager import GrafeoConnection, close_database
from deriva.common.timing import query_stats


@pytest.fixture
def conn():
    with patch.dict("os.environ", {"GRAFEO_DB_PATH": ""}, clear=False):
        close_database()
        query_stats.reset()
        c = GrafeoConnection(namespace="Graph")
        c.connect()
        yield c
        c.disconnect()
        close_database()
        query_stats.reset()


def test_queries_are_timed_per_query_text(conn):
    conn.execute("CREATE (:Graph {id: $id})", {"id": "a"})
    conn.execute("CREATE (:Graph {id: $id})", {"id": "b"})

    (entry,) = [q for q in query_stats.top() if q["query"] == "CREATE (:Graph {id: $id})"]
    assert entry["count"] == 2 and entry["total_ms"] >= 0


def test_index_backed_writes_are_timed(conn):
    conn.execute("CREATE (:Graph {id: 'a'})")
    conn.set_node_properties("id", {"a": {"x": 1}})

    assert any(q["query"] == "set_node_properties(id)" for q in query_stats.top())


def test_slow_query_is_logged(conn, caplog, monkeypatch):
    monkeypatch.setenv("GRAFEO_SLOW_QUERY_MS", "0")
    with caplog.at_level(logging.WARNING, logger="deriva.adapters.grafeo.manager"):
        conn.execute("MATCH (n) RETURN count(n) AS c")

    assert any("Slow graph query" in r.message for r in caplog.records)


class TestDatabasePerKey:
    """One .grafeo database per workspace key (repo, or joined repos for combined runs)."""

    @pytest.fixture
    def db_dir(self, tmp_path, monkeypatch):
        from deriva.adapters.grafeo.manager import close_database, use_database

        monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path))
        monkeypatch.setenv("GRAFEO_DB_PATH", "")
        close_database()
        yield tmp_path
        close_database()
        use_database("default")

    def test_each_key_gets_its_own_file_and_connections_follow(self, db_dir):
        from deriva.adapters.grafeo.manager import use_database

        use_database("alpha")
        c = GrafeoConnection(namespace="Graph")
        c.connect()
        c.execute("CREATE (:Graph {id: 'a1'})")

        use_database("beta")
        assert c.execute("MATCH (n) RETURN count(n) AS n") == [{"n": 0}]

        use_database("alpha")
        assert c.execute("MATCH (n) RETURN n.id AS id") == [{"id": "a1"}]
        c.disconnect()
        assert sorted(p.name for p in db_dir.glob("*.grafeo")) == ["alpha.grafeo", "beta.grafeo"]

    def test_data_persists_after_close(self, db_dir):
        from deriva.adapters.grafeo.manager import close_database, use_database

        use_database("alpha")
        c = GrafeoConnection(namespace="Graph")
        c.connect()
        c.execute("CREATE (:Graph {id: 'kept'})")
        c.disconnect()
        close_database()

        c.connect()
        assert c.execute("MATCH (n) RETURN n.id AS id") == [{"id": "kept"}]
        c.disconnect()

    def test_id_and_identifier_are_indexed_on_open(self, db_dir):
        from deriva.adapters.grafeo.manager import get_database, use_database

        use_database("alpha")
        db = get_database()
        assert db.has_property_index("id") and db.has_property_index("identifier")

    def test_legacy_single_file_setting_is_rejected(self, db_dir, monkeypatch):
        from deriva.adapters.grafeo.manager import get_database

        monkeypatch.setenv("GRAFEO_DB_PATH", "workspace/grafeo.db")
        with pytest.raises(RuntimeError, match="GRAFEO_DB_DIR"):
            get_database()


def test_tests_never_use_a_persistent_database():
    """conftest forces in-memory databases so no test can touch workspace/graphs."""
    import os

    assert os.environ.get("GRAFEO_DB_DIR") == ""
