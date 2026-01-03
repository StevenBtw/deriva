"""Tests for consistency analysis functions."""


from deriva.modules.analysis.consistency import (
    compare_object_sets,
    compute_consistency_score,
    find_inconsistencies,
    jaccard_similarity,
)


class TestComputeConsistencyScore:
    """Tests for compute_consistency_score function."""

    def test_single_run_returns_1(self):
        """Single run should return perfect consistency."""
        result = compute_consistency_score({"run1": {"a", "b", "c"}})
        assert result == 1.0

    def test_empty_runs_returns_1(self):
        """Empty input should return perfect consistency."""
        result = compute_consistency_score({})
        assert result == 1.0

    def test_identical_runs_returns_1(self):
        """Identical runs should return perfect consistency."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b", "c"},
            "run3": {"a", "b", "c"},
        }
        result = compute_consistency_score(objects_by_run)
        assert result == 1.0

    def test_partial_overlap_returns_fraction(self):
        """Partial overlap should return fraction of consistent objects."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b", "d"},
        }
        # a and b are in both runs, c and d are not
        # 2 consistent out of 4 total = 0.5
        result = compute_consistency_score(objects_by_run)
        assert result == 0.5

    def test_no_overlap_returns_0(self):
        """No overlap should return 0."""
        objects_by_run = {
            "run1": {"a", "b"},
            "run2": {"c", "d"},
        }
        result = compute_consistency_score(objects_by_run)
        assert result == 0.0

    def test_empty_sets_returns_1(self):
        """Empty sets in runs should return 1."""
        objects_by_run = {
            "run1": set(),
            "run2": set(),
        }
        result = compute_consistency_score(objects_by_run)
        assert result == 1.0


class TestFindInconsistencies:
    """Tests for find_inconsistencies function."""

    def test_single_run_returns_empty(self):
        """Single run should have no inconsistencies."""
        result = find_inconsistencies({"run1": {"a", "b", "c"}})
        assert result == {}

    def test_identical_runs_returns_empty(self):
        """Identical runs should have no inconsistencies."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b", "c"},
        }
        result = find_inconsistencies(objects_by_run)
        assert result == {}

    def test_finds_inconsistent_objects(self):
        """Should find objects that don't appear in all runs."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b", "d"},
        }
        result = find_inconsistencies(objects_by_run, object_type="Element")

        assert "c" in result
        assert "d" in result
        assert "a" not in result
        assert "b" not in result

        # Check c details
        assert result["c"].present_in == ["run1"]
        assert result["c"].missing_from == ["run2"]
        assert result["c"].object_type == "Element"
        assert result["c"].total_runs == 2

    def test_uses_default_object_type(self):
        """Should use default object type when not specified."""
        objects_by_run = {
            "run1": {"a"},
            "run2": {"b"},
        }
        result = find_inconsistencies(objects_by_run)
        assert result["a"].object_type == "Object"


class TestCompareObjectSets:
    """Tests for compare_object_sets function."""

    def test_identical_sets(self):
        """Identical sets should have full overlap."""
        result = compare_object_sets({"a", "b"}, {"a", "b"}, "set1", "set2")

        assert result["overlap"] == ["a", "b"]
        assert result["only_in_set1"] == []
        assert result["only_in_set2"] == []
        assert result["jaccard_similarity"] == 1.0

    def test_disjoint_sets(self):
        """Disjoint sets should have no overlap."""
        result = compare_object_sets({"a", "b"}, {"c", "d"}, "set1", "set2")

        assert result["overlap"] == []
        assert result["only_in_set1"] == ["a", "b"]
        assert result["only_in_set2"] == ["c", "d"]
        assert result["jaccard_similarity"] == 0.0

    def test_partial_overlap(self):
        """Partial overlap should be correctly computed."""
        result = compare_object_sets({"a", "b", "c"}, {"b", "c", "d"}, "A", "B")

        assert result["overlap"] == ["b", "c"]
        assert result["only_in_A"] == ["a"]
        assert result["only_in_B"] == ["d"]
        assert result["count_A"] == 3
        assert result["count_B"] == 3
        assert result["overlap_count"] == 2
        assert result["union_count"] == 4

    def test_returns_sorted_lists(self):
        """Should return sorted lists for deterministic output."""
        result = compare_object_sets({"c", "a", "b"}, {"b", "a"}, "s1", "s2")
        assert result["s1"] == ["a", "b", "c"]
        assert result["s2"] == ["a", "b"]


class TestJaccardSimilarity:
    """Tests for jaccard_similarity function."""

    def test_identical_sets(self):
        """Identical sets should have similarity 1.0."""
        result = jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"})
        assert result == 1.0

    def test_disjoint_sets(self):
        """Disjoint sets should have similarity 0.0."""
        result = jaccard_similarity({"a", "b"}, {"c", "d"})
        assert result == 0.0

    def test_partial_overlap(self):
        """Partial overlap should be intersection/union."""
        # {a,b,c} & {b,c,d} = {b,c} (size 2)
        # {a,b,c} | {b,c,d} = {a,b,c,d} (size 4)
        result = jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert result == 0.5

    def test_empty_sets_returns_1(self):
        """Two empty sets should have similarity 1.0."""
        result = jaccard_similarity(set(), set())
        assert result == 1.0

    def test_one_empty_set(self):
        """One empty set should have similarity 0.0."""
        result = jaccard_similarity({"a", "b"}, set())
        assert result == 0.0

    def test_subset_relationship(self):
        """Subset should have similarity based on size ratio."""
        # {a} & {a,b} = {a} (size 1)
        # {a} | {a,b} = {a,b} (size 2)
        result = jaccard_similarity({"a"}, {"a", "b"})
        assert result == 0.5
