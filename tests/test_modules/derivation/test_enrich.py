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
        """Should return empty EnrichmentResult for empty edges."""
        result = enrich.enrich_graph([], ["pagerank"])
        assert result.enrichments == {}
        assert result.metadata.total_nodes == 0

    def test_single_algorithm(self):
        """Should run single algorithm."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["pagerank"])

        assert "A" in result.enrichments
        assert "B" in result.enrichments
        assert "pagerank" in result.enrichments["A"]
        assert "pagerank" in result.enrichments["B"]

    def test_multiple_algorithms(self):
        """Should run multiple algorithms."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["pagerank", "degree", "kcore"])

        for node in ["A", "B", "C"]:
            assert "pagerank" in result.enrichments[node]
            assert "in_degree" in result.enrichments[node]
            assert "out_degree" in result.enrichments[node]
            assert "kcore_level" in result.enrichments[node]

    def test_louvain_algorithm(self):
        """Should run louvain algorithm."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["louvain"])

        assert "louvain_community" in result.enrichments["A"]
        assert "louvain_community" in result.enrichments["B"]

    def test_articulation_points_algorithm(self):
        """Should run articulation points algorithm."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["articulation_points"])

        assert "is_articulation_point" in result.enrichments["A"]
        assert "is_articulation_point" in result.enrichments["B"]
        assert "is_articulation_point" in result.enrichments["C"]
        # B is bridge
        assert result.enrichments["B"]["is_articulation_point"] is True

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
            assert "pagerank" in result.enrichments[node]
            assert "louvain_community" in result.enrichments[node]
            assert "kcore_level" in result.enrichments[node]
            assert "is_articulation_point" in result.enrichments[node]
            assert "in_degree" in result.enrichments[node]
            assert "out_degree" in result.enrichments[node]

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

        assert "pagerank" in result.enrichments["A"]
        assert "louvain_community" in result.enrichments["A"]

    def test_no_algorithms(self):
        """Should return nodes with empty enrichments for no algorithms."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, [])

        assert "A" in result.enrichments
        assert "B" in result.enrichments
        assert result.enrichments["A"] == {}
        assert result.enrichments["B"] == {}


class TestPercentileNormalization:
    """Tests for percentile normalization functions."""

    def test_normalize_to_percentiles_empty(self):
        """Should return empty dict for empty input."""
        result = enrich.normalize_to_percentiles({})
        assert result == {}

    def test_normalize_to_percentiles_single_value(self):
        """Should return 100 for single value."""
        result = enrich.normalize_to_percentiles({"A": 0.5})
        assert result == {"A": 100.0}

    def test_normalize_to_percentiles_two_values(self):
        """Should return 0 and 100 for two values."""
        result = enrich.normalize_to_percentiles({"A": 0.1, "B": 0.9})
        assert result["A"] == 0.0
        assert result["B"] == 100.0

    def test_normalize_to_percentiles_multiple_values(self):
        """Should distribute percentiles correctly."""
        result = enrich.normalize_to_percentiles(
            {
                "A": 0.1,
                "B": 0.2,
                "C": 0.3,
                "D": 0.4,
                "E": 0.5,
            }
        )
        # With 5 values: 0, 25, 50, 75, 100
        assert result["A"] == 0.0
        assert result["B"] == 25.0
        assert result["C"] == 50.0
        assert result["D"] == 75.0
        assert result["E"] == 100.0

    def test_normalize_to_percentiles_int_empty(self):
        """Should return empty dict for empty input."""
        result = enrich.normalize_to_percentiles_int({})
        assert result == {}

    def test_normalize_to_percentiles_int_with_ties(self):
        """Should handle ties by averaging ranks."""
        result = enrich.normalize_to_percentiles_int(
            {
                "A": 1,
                "B": 1,  # Tie with A
                "C": 2,
                "D": 3,
            }
        )
        # A and B share ranks 0 and 1 -> avg rank 0.5
        # C has rank 2, D has rank 3
        assert result["A"] == result["B"]  # Same percentile for ties
        assert result["C"] > result["A"]
        assert result["D"] == 100.0


class TestGraphMetadata:
    """Tests for GraphMetadata in enrichment results."""

    def test_metadata_populated(self):
        """Should populate metadata with graph statistics."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "C", "target": "A"},
        ]
        result = enrich.enrich_graph(
            edges,
            ["pagerank", "kcore", "louvain", "articulation_points", "degree"],
        )

        assert result.metadata.total_nodes == 3
        assert result.metadata.total_edges == 3
        assert result.metadata.max_kcore >= 1
        assert result.metadata.num_communities >= 1
        assert result.metadata.avg_pagerank > 0
        assert result.metadata.density > 0

    def test_metadata_to_dict(self):
        """Should convert metadata to dict."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["pagerank"])

        meta_dict = result.metadata.to_dict()
        assert "total_nodes" in meta_dict
        assert "total_edges" in meta_dict
        assert "density" in meta_dict
        assert meta_dict["total_nodes"] == 2
        assert meta_dict["total_edges"] == 1


class TestPercentileEnrichments:
    """Tests for percentile values in enrichments."""

    def test_pagerank_percentile_included(self):
        """Should include pagerank_percentile when enabled."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["pagerank"], include_percentiles=True)

        assert "pagerank_percentile" in result.enrichments["A"]
        assert "pagerank_percentile" in result.enrichments["B"]
        assert "pagerank_percentile" in result.enrichments["C"]

    def test_percentiles_disabled(self):
        """Should not include percentiles when disabled."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph(edges, ["pagerank"], include_percentiles=False)

        assert "pagerank" in result.enrichments["A"]
        assert "pagerank_percentile" not in result.enrichments["A"]

    def test_kcore_percentile_included(self):
        """Should include kcore_percentile when enabled."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["kcore"], include_percentiles=True)

        assert "kcore_percentile" in result.enrichments["A"]
        assert "kcore_level" in result.enrichments["A"]

    def test_degree_percentiles_included(self):
        """Should include degree percentiles when enabled."""
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
        ]
        result = enrich.enrich_graph(edges, ["degree"], include_percentiles=True)

        assert "in_degree_percentile" in result.enrichments["B"]
        assert "out_degree_percentile" in result.enrichments["A"]

    def test_percentiles_are_scale_independent(self):
        """Percentiles should be comparable across different graph sizes."""
        # Small graph
        small_edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        small_result = enrich.enrich_graph(small_edges, ["pagerank"])

        # Larger graph with same structure repeated
        large_edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
            {"source": "D", "target": "E"},
            {"source": "E", "target": "F"},
            {"source": "G", "target": "H"},
            {"source": "H", "target": "I"},
        ]
        large_result = enrich.enrich_graph(large_edges, ["pagerank"])

        # Percentiles should be in valid range regardless of graph size
        for node in small_result.enrichments:
            pct = small_result.enrichments[node]["pagerank_percentile"]
            assert 0 <= pct <= 100

        for node in large_result.enrichments:
            pct = large_result.enrichments[node]["pagerank_percentile"]
            assert 0 <= pct <= 100


class TestEnrichGraphLegacy:
    """Tests for legacy wrapper function."""

    def test_returns_dict_directly(self):
        """Should return enrichments dict for backwards compatibility."""
        edges = [{"source": "A", "target": "B"}]
        result = enrich.enrich_graph_legacy(edges, ["pagerank"])

        # Should be a plain dict, not EnrichmentResult
        assert isinstance(result, dict)
        assert "A" in result
        assert "pagerank" in result["A"]
