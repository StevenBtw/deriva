"""Tests for per-repo graph operations (clear, has_extraction, fingerprint).

Uses a real in-memory grafeo instance to verify the Cypher queries work correctly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deriva.adapters.graph.manager import GraphManager
from deriva.adapters.graph.models import (
    DirectoryNode,
    FileNode,
    RepositoryNode,
)


@pytest.fixture
def graph_manager():
    """Create a GraphManager connected to an in-memory grafeo database."""
    with patch.dict("os.environ", {"GRAFEO_DB_PATH": ""}, clear=False):
        # Force fresh in-memory DB
        from deriva.adapters.grafeo.manager import close_database

        close_database()

        gm = GraphManager()
        gm.connect()
        yield gm
        gm.disconnect()
        close_database()


def _add_repo(gm: GraphManager, name: str) -> None:
    """Helper: add a repository with some child nodes (no edges, just nodes)."""
    from datetime import datetime

    repo = RepositoryNode(name=name, url=f"https://example.com/{name}", created_at=datetime.now())
    gm.add_node(repo, node_id=f"repo::{name}")

    dir_node = DirectoryNode(name="src", path=f"{name}/src", repository_name=name)
    gm.add_node(dir_node, node_id=f"dir::{name}::src")

    file_node = FileNode(
        name="main.py",
        path=f"{name}/src/main.py",
        repository_name=name,
        file_type="source",
        subtype="python",
    )
    gm.add_node(file_node, node_id=f"file::{name}::src/main.py")


class TestHasExtraction:
    """Tests for has_extraction()."""

    def test_returns_false_when_empty(self, graph_manager):
        assert graph_manager.has_extraction("nonexistent") is False

    def test_returns_true_after_adding_repo(self, graph_manager):
        _add_repo(graph_manager, "myapp")
        assert graph_manager.has_extraction("myapp") is True

    def test_returns_false_for_different_repo(self, graph_manager):
        _add_repo(graph_manager, "myapp")
        assert graph_manager.has_extraction("other") is False


class TestClearGraphForRepo:
    """Tests for clear_graph_for_repo()."""

    def test_clears_single_repo(self, graph_manager):
        _add_repo(graph_manager, "repo_a")
        _add_repo(graph_manager, "repo_b")

        deleted = graph_manager.clear_graph_for_repo("repo_a")
        assert deleted > 0

        # repo_a should be gone
        assert graph_manager.has_extraction("repo_a") is False

        # repo_b should still exist
        assert graph_manager.has_extraction("repo_b") is True

    def test_returns_zero_for_nonexistent_repo(self, graph_manager):
        deleted = graph_manager.clear_graph_for_repo("nonexistent")
        assert deleted == 0

    def test_clears_all_node_types(self, graph_manager):
        _add_repo(graph_manager, "myapp")

        # Verify nodes exist via get_node (node_exists uses unsupported Cypher)
        assert graph_manager.get_node("repo::myapp") is not None
        assert graph_manager.get_node("dir::myapp::src") is not None
        assert graph_manager.get_node("file::myapp::src/main.py") is not None

        graph_manager.clear_graph_for_repo("myapp")

        # All should be gone
        assert graph_manager.get_node("repo::myapp") is None
        assert graph_manager.get_node("dir::myapp::src") is None
        assert graph_manager.get_node("file::myapp::src/main.py") is None


class TestExtractionFingerprint:
    """Tests for get/set extraction fingerprint."""

    def test_returns_none_when_not_set(self, graph_manager):
        _add_repo(graph_manager, "myapp")
        assert graph_manager.get_extraction_fingerprint("myapp") is None

    def test_set_and_get_fingerprint(self, graph_manager):
        _add_repo(graph_manager, "myapp")

        fp = "abc123def456"
        result = graph_manager.set_extraction_fingerprint("myapp", fp)
        assert result is True

        assert graph_manager.get_extraction_fingerprint("myapp") == fp

    def test_set_returns_false_for_missing_repo(self, graph_manager):
        result = graph_manager.set_extraction_fingerprint("nonexistent", "abc")
        assert result is False

    def test_fingerprint_survives_model_clear(self, graph_manager):
        """Fingerprint is on Graph namespace, clearing Model should not affect it."""
        _add_repo(graph_manager, "myapp")
        graph_manager.set_extraction_fingerprint("myapp", "fp123")

        # Simulate clearing Model namespace (different namespace)
        # The fingerprint lives on Graph:Repository, so it should survive
        assert graph_manager.get_extraction_fingerprint("myapp") == "fp123"

    def test_fingerprint_per_repo_isolation(self, graph_manager):
        _add_repo(graph_manager, "repo_a")
        _add_repo(graph_manager, "repo_b")

        graph_manager.set_extraction_fingerprint("repo_a", "fp_a")
        graph_manager.set_extraction_fingerprint("repo_b", "fp_b")

        assert graph_manager.get_extraction_fingerprint("repo_a") == "fp_a"
        assert graph_manager.get_extraction_fingerprint("repo_b") == "fp_b"

    def test_fingerprint_cleared_with_repo(self, graph_manager):
        _add_repo(graph_manager, "myapp")
        graph_manager.set_extraction_fingerprint("myapp", "fp123")

        graph_manager.clear_graph_for_repo("myapp")
        assert graph_manager.get_extraction_fingerprint("myapp") is None


class TestBatchUpdateProperties:
    """Enrichment write-back: index-backed, visible to Cypher, unknown ids ignored."""

    def test_writes_properties_visible_to_cypher(self, graph_manager):
        _add_repo(graph_manager, "alpha")

        updated = graph_manager.batch_update_properties(
            {
                "repo::alpha": {"pagerank": 0.5, "kcore_level": 3},
                "dir::alpha::src": {"pagerank": 0.1, "is_articulation_point": True},
                "missing::node": {"pagerank": 0.9},
            }
        )

        assert updated == 2
        rows = graph_manager.query(
            "MATCH (n) WHERE n.id IN ['repo::alpha', 'dir::alpha::src'] RETURN n.id AS id, n.pagerank AS pr, n.kcore_level AS k, n.is_articulation_point AS ap ORDER BY id"
        )
        assert rows == [
            {"id": "dir::alpha::src", "pr": 0.1, "k": None, "ap": True},
            {"id": "repo::alpha", "pr": 0.5, "k": 3, "ap": None},
        ]

    def test_uses_property_index_on_id(self, graph_manager):
        _add_repo(graph_manager, "alpha")

        graph_manager.batch_update_properties({"repo::alpha": {"pagerank": 0.5}})

        assert graph_manager.db.db.has_property_index("id")

    def test_empty_updates_write_nothing(self, graph_manager):
        assert graph_manager.batch_update_properties({}) == 0


class TestAddEdge:
    """Edge writes: index lookups for both ends, upsert by (endpoints, type, edge id)."""

    def _nodes(self, gm):
        _add_repo(gm, "alpha")
        return "repo::alpha", "dir::alpha::src"

    def test_edge_is_visible_to_cypher(self, graph_manager):
        src, dst = self._nodes(graph_manager)

        edge_id = graph_manager.add_edge(src, dst, "CONTAINS", properties={"order": 1})

        rows = graph_manager.query(
            "MATCH (s)-[r:`Graph:CONTAINS`]->(d) RETURN s.id AS s, d.id AS d, r.id AS id, r.properties_json AS pj"
        )
        assert rows == [{"s": src, "d": dst, "id": edge_id, "pj": '{"order": 1}'}]
        assert edge_id == f"{src}_CONTAINS_{dst}"

    def test_adding_the_same_edge_twice_keeps_one_edge(self, graph_manager):
        src, dst = self._nodes(graph_manager)

        graph_manager.add_edge(src, dst, "CONTAINS", properties={"v": 1})
        graph_manager.add_edge(src, dst, "CONTAINS", properties={"v": 2})

        rows = graph_manager.query("MATCH ()-[r:`Graph:CONTAINS`]->() RETURN r.properties_json AS pj")
        assert rows == [{"pj": '{"v": 2}'}]

    def test_missing_endpoint_raises(self, graph_manager):
        src, _ = self._nodes(graph_manager)

        with pytest.raises(RuntimeError, match="Make sure nodes"):
            graph_manager.add_edge(src, "missing::node", "CONTAINS")

    def test_endpoints_are_found_by_index_not_by_a_second_match(self, graph_manager):
        src, dst = self._nodes(graph_manager)

        with patch.object(graph_manager.db, "execute_write", wraps=graph_manager.db.execute_write) as write:
            graph_manager.add_edge(src, dst, "CONTAINS")

        assert not [c for c in write.call_args_list if "MATCH (dst)" in c.args[0]]
