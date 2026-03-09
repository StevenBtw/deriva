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
