"""Tests for analysis types."""

import pytest

from deriva.modules.analysis.types import (
    ConfigDeviation,
    DeviationReport,
    InconsistencyInfo,
    InterModelMetrics,
    IntraModelMetrics,
)


class TestConfigDeviation:
    """Tests for ConfigDeviation dataclass."""

    def test_creation_with_defaults(self):
        """Should create with required fields and default lists."""
        dev = ConfigDeviation(
            config_type="extraction",
            config_id="business_concept",
            deviation_count=5,
            total_objects=100,
            consistency_score=0.95,
        )

        assert dev.config_type == "extraction"
        assert dev.config_id == "business_concept"
        assert dev.deviation_count == 5
        assert dev.total_objects == 100
        assert dev.consistency_score == 0.95
        assert dev.deviating_objects == []
        assert dev.stable_objects == []

    def test_creation_with_lists(self):
        """Should create with explicit lists."""
        dev = ConfigDeviation(
            config_type="derivation",
            config_id="ApplicationComponent",
            deviation_count=2,
            total_objects=10,
            consistency_score=0.8,
            deviating_objects=["obj1", "obj2"],
            stable_objects=["obj3", "obj4", "obj5"],
        )

        assert dev.deviating_objects == ["obj1", "obj2"]
        assert dev.stable_objects == ["obj3", "obj4", "obj5"]

    def test_to_dict(self):
        """Should convert to dictionary."""
        dev = ConfigDeviation(
            config_type="extraction",
            config_id="test",
            deviation_count=1,
            total_objects=5,
            consistency_score=0.8,
            deviating_objects=["x"],
        )

        result = dev.to_dict()

        assert isinstance(result, dict)
        assert result["config_type"] == "extraction"
        assert result["config_id"] == "test"
        assert result["deviating_objects"] == ["x"]


class TestDeviationReport:
    """Tests for DeviationReport dataclass."""

    def test_creation_with_defaults(self):
        """Should create with default empty list."""
        report = DeviationReport(
            session_id="sess_123",
            analysis_timestamp="2024-01-01T00:00:00",
            total_runs=3,
            total_deviations=10,
            overall_consistency=0.9,
        )

        assert report.session_id == "sess_123"
        assert report.total_runs == 3
        assert report.config_deviations == []

    def test_creation_with_deviations(self):
        """Should create with config deviations."""
        dev = ConfigDeviation(
            config_type="extraction",
            config_id="test",
            deviation_count=1,
            total_objects=5,
            consistency_score=0.8,
        )
        report = DeviationReport(
            session_id="sess_123",
            analysis_timestamp="2024-01-01T00:00:00",
            total_runs=3,
            total_deviations=1,
            overall_consistency=0.95,
            config_deviations=[dev],
        )

        assert len(report.config_deviations) == 1
        assert report.config_deviations[0].config_id == "test"

    def test_to_dict(self):
        """Should convert to dictionary including nested deviations."""
        dev = ConfigDeviation(
            config_type="extraction",
            config_id="test",
            deviation_count=1,
            total_objects=5,
            consistency_score=0.8,
        )
        report = DeviationReport(
            session_id="sess_123",
            analysis_timestamp="2024-01-01T00:00:00",
            total_runs=3,
            total_deviations=1,
            overall_consistency=0.95,
            config_deviations=[dev],
        )

        result = report.to_dict()

        assert isinstance(result, dict)
        assert result["session_id"] == "sess_123"
        assert len(result["config_deviations"]) == 1
        assert result["config_deviations"][0]["config_id"] == "test"


class TestInconsistencyInfo:
    """Tests for InconsistencyInfo dataclass."""

    def test_creation(self):
        """Should create with required fields."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=["run1", "run2"],
            missing_from=["run3"],
            total_runs=3,
        )

        assert info.object_id == "elem_1"
        assert info.object_type == "Element"
        assert info.present_in == ["run1", "run2"]
        assert info.missing_from == ["run3"]
        assert info.total_runs == 3

    def test_consistency_score_property(self):
        """Should compute consistency score as fraction of runs."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=["run1", "run2"],
            missing_from=["run3"],
            total_runs=3,
        )

        assert info.consistency_score == pytest.approx(2 / 3)

    def test_consistency_score_zero_runs(self):
        """Should return 0 for zero total runs."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=[],
            missing_from=[],
            total_runs=0,
        )

        assert info.consistency_score == 0.0

    def test_to_dict_includes_consistency_score(self):
        """to_dict should include computed consistency_score."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=["run1"],
            missing_from=["run2"],
            total_runs=2,
        )

        result = info.to_dict()

        assert "consistency_score" in result
        assert result["consistency_score"] == 0.5


class TestIntraModelMetrics:
    """Tests for IntraModelMetrics dataclass."""

    def test_creation_with_defaults(self):
        """Should create with default empty collections."""
        metrics = IntraModelMetrics(
            model="gpt-4o",
            repository="test-repo",
            runs=5,
            element_counts=[10, 11, 10, 12, 10],
            count_variance=0.8,
            name_consistency=0.9,
        )

        assert metrics.model == "gpt-4o"
        assert metrics.runs == 5
        assert metrics.stable_elements == []
        assert metrics.unstable_elements == {}

    def test_creation_with_elements(self):
        """Should create with element lists."""
        metrics = IntraModelMetrics(
            model="gpt-4o",
            repository="test-repo",
            runs=3,
            element_counts=[10, 10, 10],
            count_variance=0.0,
            name_consistency=0.95,
            stable_elements=["elem1", "elem2"],
            unstable_elements={"elem3": 2, "elem4": 1},
        )

        assert metrics.stable_elements == ["elem1", "elem2"]
        assert metrics.unstable_elements["elem3"] == 2

    def test_to_dict(self):
        """Should convert to dictionary."""
        metrics = IntraModelMetrics(
            model="gpt-4o",
            repository="test-repo",
            runs=3,
            element_counts=[10, 10, 10],
            count_variance=0.0,
            name_consistency=0.95,
        )

        result = metrics.to_dict()

        assert isinstance(result, dict)
        assert result["model"] == "gpt-4o"
        assert result["element_counts"] == [10, 10, 10]


class TestInterModelMetrics:
    """Tests for InterModelMetrics dataclass."""

    def test_creation(self):
        """Should create with required fields."""
        metrics = InterModelMetrics(
            repository="test-repo",
            models=["gpt-4o", "claude-sonnet"],
            elements_by_model={
                "gpt-4o": ["a", "b", "c"],
                "claude-sonnet": ["b", "c", "d"],
            },
            overlap=["b", "c"],
            unique_by_model={
                "gpt-4o": ["a"],
                "claude-sonnet": ["d"],
            },
            jaccard_similarity=0.5,
        )

        assert metrics.repository == "test-repo"
        assert len(metrics.models) == 2
        assert metrics.overlap == ["b", "c"]
        assert metrics.jaccard_similarity == 0.5

    def test_to_dict(self):
        """Should convert to dictionary."""
        metrics = InterModelMetrics(
            repository="test-repo",
            models=["gpt-4o"],
            elements_by_model={"gpt-4o": ["a", "b"]},
            overlap=["a", "b"],
            unique_by_model={},
            jaccard_similarity=1.0,
        )

        result = metrics.to_dict()

        assert isinstance(result, dict)
        assert result["repository"] == "test-repo"
        assert result["jaccard_similarity"] == 1.0
