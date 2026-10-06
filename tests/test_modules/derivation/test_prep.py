"""Tests for deriva.modules.derivation.prep: graph metrics (computed by the graph adapter) to node enrichments."""

from __future__ import annotations

from deriva.modules.derivation import prep


def _metrics(**values):
    """A path a - b - c plus an isolated d, with the given raw algorithm values."""
    return prep.GraphMetrics(node_ids=["a", "b", "c", "d"], edge_count=2, **values)


class TestEnrichFromMetrics:
    """The prep module turns raw metric values into the enrichment properties written onto the nodes."""

    def test_no_nodes_gives_nothing(self):
        result = prep.enrich_from_metrics(prep.GraphMetrics(node_ids=[], edge_count=0))

        assert result.enrichments == {}

    def test_pagerank_values_and_percentiles(self):
        result = prep.enrich_from_metrics(_metrics(pagerank={"a": 0.2, "b": 0.3, "c": 0.2, "d": 0.3}))

        # ties share their average rank: a and c rank 0.5 of 3, b and d rank 2.5 of 3
        assert result.enrichments["b"] == {"pagerank": 0.3, "pagerank_percentile": 83.33}
        assert result.enrichments["a"]["pagerank_percentile"] == result.enrichments["c"]["pagerank_percentile"] == 16.67
        assert result.metadata.avg_pagerank == 0.25 and result.metadata.max_pagerank == 0.3

    def test_percentiles_can_be_left_out(self):
        result = prep.enrich_from_metrics(_metrics(pagerank={"a": 0.2, "b": 0.3, "c": 0.2, "d": 0.3}), include_percentiles=False)

        assert result.enrichments["a"] == {"pagerank": 0.2}

    def test_a_community_is_named_after_its_smallest_node_id(self):
        result = prep.enrich_from_metrics(_metrics(communities={"a": 7, "b": 7, "c": 3, "d": 3}))

        assert {n: e["louvain_community"] for n, e in result.enrichments.items()} == {"a": "a", "b": "a", "c": "c", "d": "c"}
        assert result.metadata.num_communities == 2

    def test_core_levels_and_percentiles(self):
        result = prep.enrich_from_metrics(_metrics(core_levels={"a": 1, "b": 1, "c": 1, "d": 0}))

        assert result.enrichments["a"]["kcore_level"] == 1 and result.enrichments["d"]["kcore_level"] == 0
        assert "kcore_percentile" in result.enrichments["d"]
        assert result.metadata.max_kcore == 1

    def test_every_node_gets_an_articulation_flag(self):
        result = prep.enrich_from_metrics(_metrics(articulation_points=["b"]))

        assert {n: e["is_articulation_point"] for n, e in result.enrichments.items()} == {"a": False, "b": True, "c": False, "d": False}
        assert result.metadata.num_articulation_points == 1

    def test_degrees_and_percentiles(self):
        degrees = {"a": {"in_degree": 0, "out_degree": 1}, "b": {"in_degree": 1, "out_degree": 1}, "c": {"in_degree": 1, "out_degree": 0}, "d": {"in_degree": 0, "out_degree": 0}}

        result = prep.enrich_from_metrics(_metrics(degrees=degrees))

        assert (result.enrichments["b"]["in_degree"], result.enrichments["b"]["out_degree"]) == (1, 1)
        assert "in_degree_percentile" in result.enrichments["b"] and "out_degree_percentile" in result.enrichments["a"]
        assert result.metadata.avg_in_degree == 0.5

    def test_metadata_counts_every_node_including_isolated_ones(self):
        result = prep.enrich_from_metrics(_metrics(pagerank={"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}))

        assert (result.metadata.total_nodes, result.metadata.total_edges) == (4, 2)
        assert result.metadata.density == 2 / 12
        assert set(result.metadata.to_dict()) >= {"total_nodes", "total_edges", "density"}


class TestPercentileNormalization:
    """Tests for percentile normalization functions."""

    def test_normalize_to_percentiles_empty(self):
        """Should return empty dict for empty input."""
        result = prep.normalize_to_percentiles({})
        assert result == {}

    def test_normalize_to_percentiles_single_value(self):
        """Should return 100 for single value."""
        result = prep.normalize_to_percentiles({"A": 0.5})
        assert result == {"A": 100.0}

    def test_normalize_to_percentiles_two_values(self):
        """Should return 0 and 100 for two values."""
        result = prep.normalize_to_percentiles({"A": 0.1, "B": 0.9})
        assert result["A"] == 0.0
        assert result["B"] == 100.0

    def test_normalize_to_percentiles_multiple_values(self):
        """Should distribute percentiles correctly."""
        result = prep.normalize_to_percentiles(
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
        result = prep.normalize_to_percentiles_int({})
        assert result == {}

    def test_normalize_to_percentiles_int_with_ties(self):
        """Should handle ties by averaging ranks."""
        result = prep.normalize_to_percentiles_int(
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


class TestDeterminism:
    """Enrichments must not depend on input order or Python's per-process hash seed."""

    def test_tied_float_values_get_the_same_percentile(self):
        result = prep.normalize_to_percentiles({"a": 0.1, "b": 0.1, "c": 0.5})
        assert result == {"a": 25.0, "b": 25.0, "c": 100.0}

    def test_percentiles_do_not_depend_on_insertion_order(self):
        forward = prep.normalize_to_percentiles({"a": 0.2, "b": 0.2, "c": 0.2, "d": 0.9})
        backward = prep.normalize_to_percentiles({"d": 0.9, "c": 0.2, "b": 0.2, "a": 0.2})
        assert forward == backward
