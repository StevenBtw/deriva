"""A failed existence check is no missing node: callers would drop their edges without a word."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from deriva.adapters.grafeo.manager import close_database
from deriva.adapters.graph import GraphManager


def test_a_failed_query_raises():
    graph = GraphManager()
    graph.connect()
    try:
        assert graph.node_exists("nothing") is False
        assert graph.db is not None
        with patch.object(graph.db, "execute_read", side_effect=RuntimeError("query failed")), pytest.raises(RuntimeError, match="query failed"):
            graph.node_exists("nothing")
    finally:
        graph.disconnect()
        close_database()
