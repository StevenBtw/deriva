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


def test_set_node_properties_stays_in_its_namespace(conn):
    conn.execute("CREATE (:Graph {id: 'shared'})")
    conn.execute("CREATE (:Model {id: 'shared'})")

    count = conn.set_node_properties("id", {"shared": {"x": 1}})

    assert count == 1
    assert conn.execute("MATCH (n:Model) RETURN n.x AS x") == [{"x": None}]


def test_set_node_properties_counts_only_nodes_it_changed(conn):
    conn.execute("CREATE (:Graph {id: 'a'})")

    assert conn.set_node_properties("id", {"a": {}}) == 0


@pytest.mark.parametrize("key", ["../elsewhere", "a/b", r"a\b", "..", ""])
def test_database_key_must_be_a_plain_file_name(key, tmp_path, monkeypatch):
    from deriva.adapters.grafeo.manager import database_file

    monkeypatch.setenv("GRAFEO_DB_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="database key"):
        database_file(key)


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

    def test_invalid_key_leaves_the_active_database_open(self, db_dir):
        """The key is checked before the current database closes, so connections keep working."""
        from deriva.adapters.grafeo.manager import get_database, use_database

        use_database("alpha")
        c = GrafeoConnection(namespace="Graph")
        c.connect()
        c.execute("CREATE (:Graph {id: 'a1'})")
        active = get_database()

        with pytest.raises(ValueError, match="Invalid database key"):
            use_database("../escape")

        assert get_database() is active
        assert c.db is active
        assert c.execute("MATCH (n) RETURN n.id AS id") == [{"id": "a1"}]
        c.disconnect()

    def test_legacy_single_file_setting_is_rejected(self, db_dir, monkeypatch):
        from deriva.adapters.grafeo.manager import get_database

        monkeypatch.setenv("GRAFEO_DB_PATH", "workspace/grafeo.db")
        with pytest.raises(RuntimeError, match="GRAFEO_DB_DIR"):
            get_database()


def test_a_grafeo_build_without_cypher_is_refused(monkeypatch):
    """Deriva queries only through Cypher; a build without it fails when the database opens, not at the first query."""
    import grafeo

    from deriva.adapters.grafeo import manager

    class BuildWithoutCypher:
        def __init__(self, path=None):
            self.closed = False

        def has_property_index(self, key):
            return True

        def close(self):
            self.closed = True

    close_database()
    monkeypatch.setattr(grafeo, "GrafeoDB", BuildWithoutCypher)

    with pytest.raises(RuntimeError, match="Cypher"):
        manager.get_database()

    assert manager._db is None  # nothing half-open stays behind


def test_tests_never_use_a_persistent_database():
    """conftest forces in-memory databases so no test can touch workspace/graphs."""
    import os

    assert os.environ.get("GRAFEO_DB_DIR") == ""


def test_llm_manager_dotenv_cannot_restore_the_database_dir(tmp_path):
    """LLMManager reloads .env with override=True; that must not undo the in-memory guard."""
    import os

    from deriva.adapters.llm import manager

    env = tmp_path / ".env"
    env.write_text("GRAFEO_DB_DIR=workspace/graphs", encoding="utf-8")
    manager.load_dotenv(env, override=True)

    assert os.environ.get("GRAFEO_DB_DIR") == ""


class TestMergeEdge:
    """Edge upserts without a per-edge Cypher lookup; existing-edge keys are cached per type."""

    def _nodes(self, conn, *ids):
        for node_id in ids:
            conn.execute("CREATE (:Graph {id: $id})", {"id": node_id})

    def test_many_edges_use_one_lookup_query_per_edge_type(self, conn):
        self._nodes(conn, *[f"n{i}" for i in range(20)])
        for i in range(19):
            conn.merge_edge("id", f"n{i}", f"n{i + 1}", "Graph:NEXT", f"e{i}", {})

        lookups = [q for q in query_stats.top(50) if "Graph:NEXT" in q["query"] and "MATCH" in q["query"]]
        assert [q["count"] for q in lookups] == [1]
        assert conn.execute("MATCH ()-[r:`Graph:NEXT`]->() RETURN count(r) AS c") == [{"c": 19}]

    def test_edges_are_recreated_after_a_delete(self, conn):
        self._nodes(conn, "a", "b")
        conn.merge_edge("id", "a", "b", "Graph:X", "e1", {})
        conn.execute("MATCH (n:Graph) DETACH DELETE n")
        self._nodes(conn, "a", "b")

        conn.merge_edge("id", "a", "b", "Graph:X", "e1", {})

        assert conn.execute("MATCH ()-[r:`Graph:X`]->() RETURN count(r) AS c") == [{"c": 1}]

    def test_missing_endpoint_returns_false(self, conn):
        self._nodes(conn, "a")
        assert conn.merge_edge("id", "a", "missing", "Graph:X", "e1", {}) is False


class TestDeletedNodesInIndex:
    """Deleted nodes never come back from the id index, so lookups need no filter of their own."""

    def _recreated(self, conn):
        conn.execute("CREATE (:Graph:File {id: 'a'})")
        conn.execute("CREATE (:Graph:File {id: 'b'})")
        conn.db.create_property_index("id")
        conn.execute("MATCH (n:Graph) DETACH DELETE n")

    def test_the_index_forgets_deleted_nodes(self, conn):
        """grafeo's own contract, relied on by every index-backed write (older grafeo kept deleted nodes in the index)."""
        self._recreated(conn)

        assert conn.db.find_nodes_by_property("id", "a") == []

    def test_merge_node_recreates_after_delete(self, conn):
        self._recreated(conn)
        conn.merge_node("id", "a", ["Graph", "File"], {"name": "A"})

        assert conn.execute("MATCH (n:File) RETURN n.id AS id, n.name AS name") == [{"id": "a", "name": "A"}]

    def test_merge_edge_and_property_writes_ignore_deleted_nodes(self, conn):
        self._recreated(conn)
        conn.merge_node("id", "a", ["Graph", "File"], {})
        conn.merge_node("id", "b", ["Graph", "File"], {})

        assert conn.merge_edge("id", "a", "b", "Graph:X", "e1", {}) is True
        assert conn.set_node_properties("id", {"a": {"x": 1}}) == 1
        assert conn.execute("MATCH (s)-[r:`Graph:X`]->(d) RETURN s.id AS s, d.id AS d") == [{"s": "a", "d": "b"}]
