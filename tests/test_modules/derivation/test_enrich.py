"""Tests for deriva.modules.derivation.enrich module."""

from __future__ import annotations

from deriva.modules.derivation import enrich


class TestBuildAdjacency:
    """Tests for build_adjacency function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty sets for empty edge list."""
        nodes, adj = enrich.build_adjacency([])
        assert nodes == set()
        assert adj == {}

    def test_single_edge(self):
        """Should build adjacency for single edge."""
        edges = [{"source": "A", "target": "B"}]
        nodes, adj = enrich.build_adjacency(edges)

        assert nodes == {"A", "B"}
        assert adj == {"A": {"B"}, "B": {"A"}}

    def test_multiple_edges(self):
        """Should build adjacency for multiple edges."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "A", "target": "C"},
        ]
        nodes, adj = enrich.build_adjacency(edges)

        assert nodes == {"A", "B", "C"}
        assert "B" in adj["A"] and "C" in adj["A"]
        assert "A" in adj["B"] and "C" in adj["B"]
        assert "A" in adj["C"] and "B" in adj["C"]

    def test_self_loop(self):
        """Should handle self-loop edges."""
        edges = [{"source": "A", "target": "A"}]
        nodes, adj = enrich.build_adjacency(edges)

        assert nodes == {"A"}
        assert adj == {"A": {"A"}}


class TestBuildDirectedAdjacency:
    """Tests for build_directed_adjacency function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty structures for empty edge list."""
        nodes, outgoing, incoming = enrich.build_directed_adjacency([])
        assert nodes == set()
        assert outgoing == {}
        assert incoming == {}

    def test_single_edge(self):
        """Should build directed adjacency for single edge."""
        edges = [{"source": "A", "target": "B"}]
        nodes, outgoing, incoming = enrich.build_directed_adjacency(edges)

        assert nodes == {"A", "B"}
        assert outgoing == {"A": {"B"}}
        assert incoming == {"B": {"A"}}

    def test_multiple_edges(self):
        """Should build directed adjacency correctly."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "C"},
        ]
        nodes, outgoing, incoming = enrich.build_directed_adjacency(edges)

        assert nodes == {"A", "B", "C"}
        assert outgoing["A"] == {"B", "C"}
        assert outgoing["B"] == {"C"}
        assert "A" not in outgoing.get("C", set())
        assert incoming["C"] == {"A", "B"}


class TestComputePagerank:
    """Tests for compute_pagerank function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty dict for empty edges."""
        result = enrich.compute_pagerank([])
        assert result == {}

    def test_simple_graph(self):
        """Should compute pagerank for simple graph."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        result = enrich.compute_pagerank(edges)

        assert len(result) == 3
        assert all(0 <= score <= 1 for score in result.values())
        # In a cycle, all nodes should have similar pagerank
        scores = list(result.values())
        assert max(scores) - min(scores) < 0.01

    def test_star_graph(self):
        """Should give central node higher pagerank in star graph."""
        edges = [
            {"source": "center", "target": "A"},
            {"source": "center", "target": "B"},
            {"source": "center", "target": "C"},
        ]
        result = enrich.compute_pagerank(edges)

        assert len(result) == 4
        # Center should have higher pagerank than leaves
        assert result["center"] > result["A"]

    def test_custom_damping(self):
        """Should accept custom damping factor."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.compute_pagerank(edges, damping=0.5)
        assert len(result) == 2


class TestComputeLouvain:
    """Tests for compute_louvain function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty dict for empty edges."""
        result = enrich.compute_louvain([])
        assert result == {}

    def test_connected_component(self):
        """Should assign same community to connected nodes."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.compute_louvain(edges)

        assert len(result) == 3
        # All connected nodes should be in same community
        assert result["A"] == result["B"] == result["C"]

    def test_two_components(self):
        """Should detect two separate communities."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "C", "target": "D"},
        ]
        result = enrich.compute_louvain(edges)

        assert len(result) == 4
        # Each component is its own community
        assert result["A"] == result["B"]
        assert result["C"] == result["D"]
        assert result["A"] != result["C"]


class TestComputeKcore:
    """Tests for compute_kcore function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty dict for empty edges."""
        result = enrich.compute_kcore([])
        assert result == {}

    def test_simple_graph(self):
        """Should compute kcore levels."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.compute_kcore(edges)

        assert len(result) == 3
        assert all(isinstance(level, int) for level in result.values())
        # All should have core level >= 1
        assert all(level >= 1 for level in result.values())

    def test_fully_connected(self):
        """Should give higher core level to fully connected nodes."""
        # Triangle
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        result = enrich.compute_kcore(edges)

        # Triangle has core level 2
        assert all(result[n] == 2 for n in ["A", "B", "C"])


class TestComputeArticulationPoints:
    """Tests for compute_articulation_points function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty set for empty edges."""
        result = enrich.compute_articulation_points([])
        assert result == set()

    def test_no_articulation_points(self):
        """Should return empty set when no articulation points exist."""
        # Triangle has no articulation points
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        result = enrich.compute_articulation_points(edges)
        assert result == set()

    def test_bridge_node(self):
        """Should identify bridge node as articulation point."""
        # B is a bridge between two parts
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.compute_articulation_points(edges)
        assert "B" in result


class TestComputeDegreeCentrality:
    """Tests for compute_degree_centrality function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty dict for empty edges."""
        result = enrich.compute_degree_centrality([])
        assert result == {}

    def test_single_edge(self):
        """Should compute correct degrees for single edge."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.compute_degree_centrality(edges)

        assert result["A"]["out_degree"] == 1
        assert result["A"]["in_degree"] == 0
        assert result["B"]["out_degree"] == 0
        assert result["B"]["in_degree"] == 1

    def test_multiple_edges(self):
        """Should compute correct degrees for multiple edges."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.compute_degree_centrality(edges)

        assert result["A"]["out_degree"] == 2
        assert result["A"]["in_degree"] == 0
        assert result["C"]["in_degree"] == 2
        assert result["C"]["out_degree"] == 0


class TestEnrichGraph:
    """Tests for enrich_graph function."""

    def test_empty_edges_returns_empty(self):
        """Should return empty dict for empty edges."""
        result = enrich.enrich_graph([], ["pagerank"])
        assert result == {}

    def test_single_algorithm(self):
        """Should run single algorithm."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["pagerank"])

        assert "A" in result
        assert "B" in result
        assert "pagerank" in result["A"]
        assert "pagerank" in result["B"]

    def test_multiple_algorithms(self):
        """Should run multiple algorithms."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["pagerank", "degree", "kcore"])

        for node in ["A", "B", "C"]:
            assert "pagerank" in result[node]
            assert "in_degree" in result[node]
            assert "out_degree" in result[node]
            assert "kcore_level" in result[node]

    def test_louvain_algorithm(self):
        """Should run louvain algorithm."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["louvain"])

        assert "louvain_community" in result["A"]
        assert "louvain_community" in result["B"]

    def test_articulation_points_algorithm(self):
        """Should run articulation points algorithm."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["articulation_points"])

        assert "is_articulation_point" in result["A"]
        assert "is_articulation_point" in result["B"]
        assert "is_articulation_point" in result["C"]
        # B is bridge
        assert result["B"]["is_articulation_point"] is True

    def test_all_algorithms(self):
        """Should run all algorithms together."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        result = enrich.enrich_graph(
            edges,
            ["pagerank", "louvain", "kcore", "articulation_points", "degree"],
        )

        for node in ["A", "B", "C"]:
            assert "pagerank" in result[node]
            assert "louvain_community" in result[node]
            assert "kcore_level" in result[node]
            assert "is_articulation_point" in result[node]
            assert "in_degree" in result[node]
            assert "out_degree" in result[node]

    def test_custom_params(self):
        """Should accept custom parameters for algorithms."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(
            edges,
            ["pagerank", "louvain"],
            params={
                "pagerank": {"damping": 0.5, "max_iter": 50},
                "louvain": {"resolution": 2.0},
            },
        )

        assert "pagerank" in result["A"]
        assert "louvain_community" in result["A"]

    def test_no_algorithms(self):
        """Should return nodes with empty enrichments for no algorithms."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, [])

        assert "A" in result
        assert "B" in result
        assert result["A"] == {}
        assert result["B"] == {}
