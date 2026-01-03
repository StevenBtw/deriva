"""Tests for benchmarking service models."""

from __future__ import annotations

from deriva.services.benchmarking import (
    AnalysisSummary,
    BenchmarkConfig,
    BenchmarkResult,
    InconsistencyLocalization,
    InterModelMetrics,
    IntraModelMetrics,
    RunResult,
)


class TestBenchmarkConfig:
    """Tests for BenchmarkConfig dataclass."""

    def test_creates_with_required_fields(self):
        """Should create config with minimal required fields."""
        config = BenchmarkConfig(
            repositories=["repo1", "repo2"],
            models=["gpt-4", "claude-3"],
        )
        assert config.repositories == ["repo1", "repo2"]
        assert config.models == ["gpt-4", "claude-3"]

    def test_default_runs_per_combination(self):
        """Should default to 3 runs per combination."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        assert config.runs_per_combination == 3

    def test_default_stages(self):
        """Should default to extraction and derivation stages."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        assert config.stages == ["extraction", "derivation"]

    def test_default_description(self):
        """Should default to empty description."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        assert config.description == ""

    def test_default_clear_between_runs(self):
        """Should default to clearing between runs."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        assert config.clear_between_runs is True

    def test_total_runs_calculation(self):
        """Should calculate total runs correctly."""
        config = BenchmarkConfig(
            repositories=["repo1", "repo2"],
            models=["gpt-4", "claude-3", "llama"],
            runs_per_combination=3,
        )
        # 2 repos × 3 models × 3 runs = 18
        assert config.total_runs() == 18

    def test_total_runs_single_combination(self):
        """Should calculate correctly for single combination."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
            runs_per_combination=5,
        )
        # 1 repo × 1 model × 5 runs = 5
        assert config.total_runs() == 5

    def test_total_runs_empty_lists(self):
        """Should return 0 for empty lists."""
        config = BenchmarkConfig(
            repositories=[],
            models=["gpt-4"],
        )
        assert config.total_runs() == 0

    def test_to_dict(self):
        """Should convert to dictionary."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
            runs_per_combination=2,
            stages=["extraction"],
            description="Test benchmark",
            clear_between_runs=False,
        )
        d = config.to_dict()

        assert d["repositories"] == ["repo1"]
        assert d["models"] == ["gpt-4"]
        assert d["runs_per_combination"] == 2
        assert d["stages"] == ["extraction"]
        assert d["description"] == "Test benchmark"
        assert d["clear_between_runs"] is False

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        config = BenchmarkConfig(
            repositories=["repo1", "repo2"],
            models=["gpt-4"],
        )
        d = config.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "repo1" in json_str


class TestBenchmarkResult:
    """Tests for BenchmarkResult dataclass."""

    def test_creates_with_required_fields(self):
        """Should create result with required fields."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        result = BenchmarkResult(
            session_id="session-123",
            config=config,
            runs_completed=3,
            runs_failed=0,
            ocel_path="/path/to/ocel.json",
            duration_seconds=120.5,
        )
        assert result.session_id == "session-123"
        assert result.runs_completed == 3
        assert result.duration_seconds == 120.5

    def test_default_errors_list(self):
        """Should default to empty errors list."""
        config = BenchmarkConfig(repositories=[], models=[])
        result = BenchmarkResult(
            session_id="test",
            config=config,
            runs_completed=0,
            runs_failed=0,
            ocel_path="",
            duration_seconds=0,
        )
        assert result.errors == []

    def test_success_property_when_no_failures(self):
        """Should return True when no failures."""
        config = BenchmarkConfig(repositories=[], models=[])
        result = BenchmarkResult(
            session_id="test",
            config=config,
            runs_completed=10,
            runs_failed=0,
            ocel_path="",
            duration_seconds=100,
        )
        assert result.success is True

    def test_success_property_when_failures(self):
        """Should return False when there are failures."""
        config = BenchmarkConfig(repositories=[], models=[])
        result = BenchmarkResult(
            session_id="test",
            config=config,
            runs_completed=8,
            runs_failed=2,
            ocel_path="",
            duration_seconds=100,
        )
        assert result.success is False

    def test_success_property_all_failed(self):
        """Should return False when all runs failed."""
        config = BenchmarkConfig(repositories=[], models=[])
        result = BenchmarkResult(
            session_id="test",
            config=config,
            runs_completed=0,
            runs_failed=10,
            ocel_path="",
            duration_seconds=50,
        )
        assert result.success is False

    def test_has_nested_config(self):
        """Should preserve nested config object."""
        config = BenchmarkConfig(
            repositories=["repo1", "repo2"],
            models=["gpt-4"],
            runs_per_combination=5,
        )
        result = BenchmarkResult(
            session_id="test",
            config=config,
            runs_completed=10,
            runs_failed=0,
            ocel_path="/ocel.json",
            duration_seconds=200,
        )
        assert result.config.total_runs() == 10
        assert result.config.repositories == ["repo1", "repo2"]


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_creates_with_all_fields(self):
        """Should create run result with all fields."""
        result = RunResult(
            run_id="run-001",
            repository="my-repo",
            model="gpt-4",
            iteration=1,
            status="completed",
            stats={"nodes_created": 10, "edges_created": 5},
            errors=[],
            duration_seconds=45.3,
        )
        assert result.run_id == "run-001"
        assert result.repository == "my-repo"
        assert result.model == "gpt-4"
        assert result.iteration == 1
        assert result.status == "completed"
        assert result.duration_seconds == 45.3

    def test_stats_dict_access(self):
        """Should allow access to stats dict."""
        result = RunResult(
            run_id="run-001",
            repository="repo",
            model="model",
            iteration=1,
            status="completed",
            stats={"key1": "value1", "key2": 42},
            errors=[],
            duration_seconds=10,
        )
        assert result.stats["key1"] == "value1"
        assert result.stats["key2"] == 42

    def test_errors_list(self):
        """Should store errors list."""
        result = RunResult(
            run_id="run-001",
            repository="repo",
            model="model",
            iteration=1,
            status="failed",
            stats={},
            errors=["Connection timeout", "API rate limit"],
            duration_seconds=5,
        )
        assert len(result.errors) == 2
        assert "Connection timeout" in result.errors

    def test_failed_status(self):
        """Should accept failed status."""
        result = RunResult(
            run_id="run-002",
            repository="repo",
            model="model",
            iteration=2,
            status="failed",
            stats={},
            errors=["Error occurred"],
            duration_seconds=1.5,
        )
        assert result.status == "failed"


class TestIntraModelMetrics:
    """Tests for IntraModelMetrics dataclass."""

    def test_creates_with_all_fields(self):
        """Should create metrics with all fields."""
        metrics = IntraModelMetrics(
            model="gpt-4",
            repository="my-repo",
            runs=3,
            element_counts=[10, 12, 11],
            count_variance=0.67,
            name_consistency=85.5,
            stable_elements=["Component_A", "Component_B"],
            unstable_elements={"Component_C": 2},
        )
        assert metrics.model == "gpt-4"
        assert metrics.repository == "my-repo"
        assert metrics.runs == 3
        assert metrics.name_consistency == 85.5

    def test_to_dict(self):
        """Should convert to dictionary."""
        metrics = IntraModelMetrics(
            model="claude-3",
            repository="repo1",
            runs=2,
            element_counts=[5, 6],
            count_variance=0.25,
            name_consistency=100.0,
            stable_elements=["A"],
            unstable_elements={},
        )
        d = metrics.to_dict()

        assert d["model"] == "claude-3"
        assert d["repository"] == "repo1"
        assert d["runs"] == 2
        assert d["stable_elements"] == ["A"]

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        metrics = IntraModelMetrics(
            model="model",
            repository="repo",
            runs=1,
            element_counts=[10],
            count_variance=0.0,
            name_consistency=100.0,
            stable_elements=[],
            unstable_elements={},
        )
        d = metrics.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "model" in json_str


class TestInterModelMetrics:
    """Tests for InterModelMetrics dataclass."""

    def test_creates_with_all_fields(self):
        """Should create metrics with all fields."""
        metrics = InterModelMetrics(
            repository="my-repo",
            models=["gpt-4", "claude-3"],
            elements_by_model={"gpt-4": ["A", "B"], "claude-3": ["A", "C"]},
            overlap=["A"],
            unique_by_model={"gpt-4": ["B"], "claude-3": ["C"]},
            jaccard_similarity=0.33,
        )
        assert metrics.repository == "my-repo"
        assert metrics.models == ["gpt-4", "claude-3"]
        assert metrics.overlap == ["A"]
        assert metrics.jaccard_similarity == 0.33

    def test_to_dict(self):
        """Should convert to dictionary."""
        metrics = InterModelMetrics(
            repository="repo1",
            models=["m1", "m2"],
            elements_by_model={"m1": ["X"], "m2": ["X", "Y"]},
            overlap=["X"],
            unique_by_model={"m1": [], "m2": ["Y"]},
            jaccard_similarity=0.5,
        )
        d = metrics.to_dict()

        assert d["repository"] == "repo1"
        assert d["models"] == ["m1", "m2"]
        assert d["jaccard_similarity"] == 0.5


class TestInconsistencyLocalization:
    """Tests for InconsistencyLocalization dataclass."""

    def test_creates_with_all_fields(self):
        """Should create localization with all fields."""
        localization = InconsistencyLocalization(
            by_element_type={"Element": 90.0, "GraphNode": 95.0},
            by_stage={"extraction": 100.0, "derivation": 85.0},
            by_model={"gpt-4": 92.0, "claude-3": 88.0},
            by_repository={"repo1": 90.0},
            hotspots=[{"type": "model", "name": "claude-3", "consistency": 88.0}],
        )
        assert localization.by_element_type["Element"] == 90.0
        assert localization.by_stage["derivation"] == 85.0
        assert len(localization.hotspots) == 1

    def test_to_dict(self):
        """Should convert to dictionary."""
        localization = InconsistencyLocalization(
            by_element_type={},
            by_stage={},
            by_model={},
            by_repository={},
            hotspots=[],
        )
        d = localization.to_dict()

        assert "by_element_type" in d
        assert "by_stage" in d
        assert "hotspots" in d


class TestAnalysisSummary:
    """Tests for AnalysisSummary dataclass."""

    def test_creates_with_all_fields(self):
        """Should create summary with all fields."""
        intra = [
            IntraModelMetrics(
                model="gpt-4",
                repository="repo1",
                runs=3,
                element_counts=[10, 10, 10],
                count_variance=0.0,
                name_consistency=100.0,
                stable_elements=["A"],
                unstable_elements={},
            )
        ]
        inter = [
            InterModelMetrics(
                repository="repo1",
                models=["gpt-4", "claude-3"],
                elements_by_model={},
                overlap=[],
                unique_by_model={},
                jaccard_similarity=1.0,
            )
        ]
        localization = InconsistencyLocalization(
            by_element_type={},
            by_stage={},
            by_model={},
            by_repository={},
            hotspots=[],
        )

        summary = AnalysisSummary(
            session_id="bench_20260103",
            analyzed_at="2026-01-03T12:00:00",
            intra_model=intra,
            inter_model=inter,
            localization=localization,
            overall_consistency=95.0,
        )

        assert summary.session_id == "bench_20260103"
        assert summary.overall_consistency == 95.0
        assert len(summary.intra_model) == 1
        assert len(summary.inter_model) == 1

    def test_to_dict(self):
        """Should convert to nested dictionary."""
        intra = [
            IntraModelMetrics(
                model="m1",
                repository="r1",
                runs=2,
                element_counts=[5, 5],
                count_variance=0.0,
                name_consistency=100.0,
                stable_elements=[],
                unstable_elements={},
            )
        ]
        localization = InconsistencyLocalization(
            by_element_type={},
            by_stage={},
            by_model={},
            by_repository={},
            hotspots=[],
        )

        summary = AnalysisSummary(
            session_id="test",
            analyzed_at="2026-01-03",
            intra_model=intra,
            inter_model=[],
            localization=localization,
            overall_consistency=100.0,
        )
        d = summary.to_dict()

        assert d["session_id"] == "test"
        assert d["overall_consistency"] == 100.0
        assert len(d["intra_model"]) == 1
        assert d["intra_model"][0]["model"] == "m1"

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        localization = InconsistencyLocalization(
            by_element_type={},
            by_stage={},
            by_model={},
            by_repository={},
            hotspots=[],
        )
        summary = AnalysisSummary(
            session_id="test",
            analyzed_at="2026-01-03",
            intra_model=[],
            inter_model=[],
            localization=localization,
            overall_consistency=100.0,
        )
        d = summary.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "test" in json_str
