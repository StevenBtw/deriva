"""Tests for benchmarking service models."""

from __future__ import annotations

import pytest

from deriva.adapters.archimate import Element
from deriva.services.benchmarking import (
    AnalysisSummary,
    BenchmarkConfig,
    BenchmarkResult,
    ConnectionStability,
    ElementStructuralStability,
    InconsistencyLocalization,
    InterModelMetrics,
    IntraModelMetrics,
    ItemStability,
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

    def test_default_export_models(self):
        """Should default to exporting models after each run."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        assert config.export_models is True

    def test_export_models_can_be_disabled(self):
        """Should allow disabling model export."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
            export_models=False,
        )
        assert config.export_models is False

    def test_total_runs_calculation(self):
        """Should calculate total runs correctly.

        Repos are processed together per (model, iteration) - they don't multiply run count.
        """
        config = BenchmarkConfig(
            repositories=["repo1", "repo2"],
            models=["gpt-4", "claude-3", "llama"],
            runs_per_combination=3,
        )
        # 3 models × 3 runs = 9 (repos processed together per run)
        assert config.total_runs() == 9

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
        """Should return 0 for empty models list."""
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=[],
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
            export_models=False,
        )
        d = config.to_dict()

        assert d["repositories"] == ["repo1"]
        assert d["models"] == ["gpt-4"]
        assert d["runs_per_combination"] == 2
        assert d["stages"] == ["extraction"]
        assert d["description"] == "Test benchmark"
        assert d["clear_between_runs"] is False
        assert d["export_models"] is False

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
            runs_completed=5,  # 1 model × 5 runs (repos processed together)
            runs_failed=0,
            ocel_path="/ocel.json",
            duration_seconds=200,
        )
        assert result.config.total_runs() == 5  # 1 model × 5 runs
        assert result.config.repositories == ["repo1", "repo2"]


class TestRunResult:
    """Tests for RunResult dataclass."""

    def test_creates_with_all_fields(self):
        """Should create run result with all fields."""
        result = RunResult(
            run_id="run-001",
            repositories=["my-repo"],
            model="gpt-4",
            iteration=1,
            status="completed",
            stats={"nodes_created": 10, "edges_created": 5},
            errors=[],
            duration_seconds=45.3,
        )
        assert result.run_id == "run-001"
        assert result.repository == "my-repo"  # Legacy property access
        assert result.repositories == ["my-repo"]
        assert result.model == "gpt-4"
        assert result.iteration == 1
        assert result.status == "completed"
        assert result.duration_seconds == 45.3

    def test_stats_dict_access(self):
        """Should allow access to stats dict."""
        result = RunResult(
            run_id="run-001",
            repositories=["repo"],
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
            repositories=["repo"],
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
            repositories=["repo"],
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

    def test_to_dict_with_stability_fields(self):
        """Should serialize stability fields correctly."""
        import json

        metrics = IntraModelMetrics(
            model="gpt-4",
            repository="repo1",
            runs=3,
            element_counts=[10, 11, 10],
            count_variance=0.33,
            name_consistency=90.0,
            stable_elements=["ComponentA"],
            unstable_elements={"ComponentB": 2},
            element_stability=[
                ItemStability("elem1", "Element", 3, 3),
                ItemStability("elem2", "Element", 2, 3),
            ],
            edge_stability=[
                ItemStability("edge1", "Edge", 3, 3),
            ],
            relationship_stability=[
                ItemStability("rel1", "Relationship", 2, 3),
            ],
            structural_stability=[
                ElementStructuralStability(
                    "elem1",
                    [ConnectionStability("elem1", "elem2", "Serving", 3, 3)],
                ),
            ],
        )
        d = metrics.to_dict()

        # Should serialize stability lists as dicts
        assert len(d["element_stability"]) == 2
        assert d["element_stability"][0]["item_id"] == "elem1"
        assert d["element_stability"][0]["stability_score"] == 100.0
        assert d["element_stability"][1]["stability_score"] == 66.67

        assert len(d["edge_stability"]) == 1
        assert len(d["relationship_stability"]) == 1

        assert len(d["structural_stability"]) == 1
        assert d["structural_stability"][0]["element_id"] == "elem1"
        assert d["structural_stability"][0]["structural_score"] == 100.0

        # Should be JSON serializable
        json_str = json.dumps(d)
        assert "element_stability" in json_str
        assert "structural_stability" in json_str


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


class TestItemStability:
    """Tests for ItemStability dataclass."""

    def test_creates_with_all_fields(self):
        """Should create item stability with all fields."""
        item = ItemStability(
            item_id="elem_1",
            item_type="Element",
            appearances=3,
            total_runs=5,
        )
        assert item.item_id == "elem_1"
        assert item.item_type == "Element"
        assert item.appearances == 3
        assert item.total_runs == 5

    def test_stability_score_calculation(self):
        """Should calculate stability score as percentage."""
        item = ItemStability(
            item_id="elem_1",
            item_type="Element",
            appearances=4,
            total_runs=5,
        )
        assert item.stability_score == 80.0

    def test_stability_score_zero_runs(self):
        """Should return 0 when total_runs is 0."""
        item = ItemStability(
            item_id="elem_1",
            item_type="Element",
            appearances=0,
            total_runs=0,
        )
        assert item.stability_score == 0.0

    def test_is_stable_when_all_runs(self):
        """Should return True when appearances equals total_runs."""
        item = ItemStability(
            item_id="elem_1",
            item_type="Element",
            appearances=5,
            total_runs=5,
        )
        assert item.is_stable is True

    def test_is_stable_when_not_all_runs(self):
        """Should return False when appearances less than total_runs."""
        item = ItemStability(
            item_id="elem_1",
            item_type="Element",
            appearances=4,
            total_runs=5,
        )
        assert item.is_stable is False

    def test_to_dict(self):
        """Should convert to dictionary."""
        item = ItemStability(
            item_id="edge_1",
            item_type="Edge",
            appearances=3,
            total_runs=4,
        )
        d = item.to_dict()

        assert d["item_id"] == "edge_1"
        assert d["item_type"] == "Edge"
        assert d["appearances"] == 3
        assert d["total_runs"] == 4
        assert d["stability_score"] == 75.0
        assert d["is_stable"] is False

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        item = ItemStability(
            item_id="rel_1",
            item_type="Relationship",
            appearances=2,
            total_runs=3,
        )
        d = item.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "rel_1" in json_str


class TestConnectionStability:
    """Tests for ConnectionStability dataclass."""

    def test_creates_with_all_fields(self):
        """Should create connection stability with all fields."""
        conn = ConnectionStability(
            element_id="comp_A",
            connected_to="comp_B",
            relationship_type="Serving",
            appearances=4,
            total_runs=5,
        )
        assert conn.element_id == "comp_A"
        assert conn.connected_to == "comp_B"
        assert conn.relationship_type == "Serving"
        assert conn.appearances == 4
        assert conn.total_runs == 5

    def test_stability_score_calculation(self):
        """Should calculate stability score as percentage."""
        conn = ConnectionStability(
            element_id="comp_A",
            connected_to="comp_B",
            relationship_type="Serving",
            appearances=3,
            total_runs=4,
        )
        assert conn.stability_score == 75.0

    def test_stability_score_zero_runs(self):
        """Should return 0 when total_runs is 0."""
        conn = ConnectionStability(
            element_id="comp_A",
            connected_to="comp_B",
            relationship_type="Serving",
            appearances=0,
            total_runs=0,
        )
        assert conn.stability_score == 0.0

    def test_to_dict(self):
        """Should convert to dictionary."""
        conn = ConnectionStability(
            element_id="comp_A",
            connected_to="comp_B",
            relationship_type="Composition",
            appearances=2,
            total_runs=3,
        )
        d = conn.to_dict()

        assert d["element_id"] == "comp_A"
        assert d["connected_to"] == "comp_B"
        assert d["relationship_type"] == "Composition"
        assert d["appearances"] == 2
        assert d["total_runs"] == 3
        assert d["stability_score"] == 66.67

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        conn = ConnectionStability(
            element_id="A",
            connected_to="B",
            relationship_type="Flow",
            appearances=1,
            total_runs=2,
        )
        d = conn.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "Flow" in json_str


class TestElementStructuralStability:
    """Tests for ElementStructuralStability dataclass."""

    def test_creates_with_element_id(self):
        """Should create with element ID and empty connections."""
        elem = ElementStructuralStability(element_id="comp_A")
        assert elem.element_id == "comp_A"
        assert elem.connections == []

    def test_creates_with_connections(self):
        """Should create with connections list."""
        conns = [
            ConnectionStability("A", "B", "Serving", 3, 3),
            ConnectionStability("A", "C", "Flow", 2, 3),
        ]
        elem = ElementStructuralStability(element_id="A", connections=conns)
        assert len(elem.connections) == 2

    def test_structural_score_empty_connections(self):
        """Should return 100 when no connections."""
        elem = ElementStructuralStability(element_id="A")
        assert elem.structural_score == 100.0

    def test_structural_score_calculation(self):
        """Should calculate average of connection stability scores."""
        conns = [
            ConnectionStability("A", "B", "Serving", 4, 4),  # 100%
            ConnectionStability("A", "C", "Flow", 2, 4),  # 50%
        ]
        elem = ElementStructuralStability(element_id="A", connections=conns)
        # (100 + 50) / 2 = 75
        assert elem.structural_score == 75.0

    def test_to_dict(self):
        """Should convert to dictionary with nested connections."""
        conns = [
            ConnectionStability("A", "B", "Serving", 3, 4),
        ]
        elem = ElementStructuralStability(element_id="A", connections=conns)
        d = elem.to_dict()

        assert d["element_id"] == "A"
        assert d["structural_score"] == 75.0
        assert len(d["connections"]) == 1
        assert d["connections"][0]["connected_to"] == "B"

    def test_to_dict_is_serializable(self):
        """Should produce JSON-serializable dict."""
        import json

        conns = [ConnectionStability("A", "B", "Access", 2, 3)]
        elem = ElementStructuralStability(element_id="A", connections=conns)
        d = elem.to_dict()

        # Should not raise
        json_str = json.dumps(d)
        assert "structural_score" in json_str


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


# =============================================================================
# OCEL Logger Tests
# =============================================================================
from unittest.mock import MagicMock, patch

from deriva.common.ocel import OCELLog
from deriva.services.benchmarking import (
    BenchmarkAnalyzer,
    BenchmarkOrchestrator,
    OCELRunLogger,
    OCELStepContext,
    get_benchmark_runs,
    get_benchmark_session,
    list_benchmark_sessions,
)


class TestOCELRunLogger:
    """Tests for OCELRunLogger class."""

    def test_verbose_logger_prints_step_completion(self, capsys):
        logger = OCELRunLogger(ocel_log=OCELLog(), run_id="run-1", session_id="s", model="m", repo="r", verbose=True)
        logger.phase_start("derivation", "")

        with patch("deriva.services.benchmarking.time.perf_counter", side_effect=[1.0, 3.25, 3.25]):
            logger.step_start("pagerank").complete()

        out = capsys.readouterr().out
        assert "pagerank" in out and "2.25s" in out

    def test_step_duration_is_measured_without_with_block(self):
        """Pipelines call step_start() without `with`; the duration must still be real."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(ocel_log=ocel_log, run_id="run-1", session_id="session-1", model="m", repo="r")
        logger.phase_start("derivation", "")

        with patch("deriva.services.benchmarking.time.perf_counter", side_effect=[10.0, 12.5]):
            logger.step_start("pagerank").complete()

        (event,) = [e for e in ocel_log.events if e.activity == "DeriveConfig"]
        assert event.attributes["duration_seconds"] == 2.5

    def test_init(self):
        """Should initialize with required fields."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        assert logger.run_id == "run-1"
        assert logger.session_id == "session-1"
        assert logger.model == "gpt-4"
        assert logger.repo == "test-repo"

    def test_phase_start_sets_current_phase(self):
        """Should set current phase on phase_start."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "Starting extraction")
        assert logger._current_phase == "extraction"

    def test_phase_complete_clears_phase(self):
        """Should clear current phase and config on phase_complete."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "Starting")
        logger._current_config = "some_config"
        logger.phase_complete("extraction", "Done")
        assert logger._current_phase is None
        assert logger._current_config is None

    def test_phase_error_clears_phase(self):
        """Should clear current phase on phase_error."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "Starting")
        logger.phase_error("extraction", "Failed!", "Error occurred")
        assert logger._current_phase is None

    def test_step_start_returns_context(self):
        """Should return OCELStepContext on step_start."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        ctx = logger.step_start("File", "Extracting files")
        assert isinstance(ctx, OCELStepContext)
        assert logger._current_config == "File"
        assert ctx.step == "File"

    def test_log_config_result_creates_event(self):
        """Should create OCEL event for config result."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.log_config_result(
            config_type="extraction",
            config_id="File",
            objects_created=["obj1", "obj2"],
            edges_created=["edge1"],
            stats={"count": 2},
            errors=[],
        )
        assert len(ocel_log.events) == 1
        assert ocel_log.events[0].activity == "ExtractConfig"

    def test_log_config_result_derivation_creates_derive_config(self):
        """Should create DeriveConfig event for derivation."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.log_config_result(
            config_type="derivation",
            config_id="ApplicationComponent",
            objects_created=["elem1"],
            relationships_created=["rel1"],
            stats={},
        )
        assert len(ocel_log.events) == 1
        assert ocel_log.events[0].activity == "DeriveConfig"

    def test_current_config_property(self):
        """Should return current config via property."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        assert logger.current_config is None
        logger.step_start("File", "Extracting")
        assert logger.current_config == "File"


class TestOCELStepContext:
    """Tests for OCELStepContext class."""

    def test_init(self):
        """Should initialize with logger reference."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        ctx = OCELStepContext(logger, "File", 1)
        assert ctx.step == "File"
        assert ctx.sequence == 1
        assert ctx.items_processed == 0

    def test_context_manager_completes_on_exit(self):
        """Should complete step when used as context manager."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "")
        ctx = OCELStepContext(logger, "File", 1)

        with ctx:
            ctx.items_created = 5

        assert ctx._completed is True
        assert len(ocel_log.events) == 1

    def test_context_manager_handles_exception(self):
        """Should log error when exception in context."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "")
        ctx = OCELStepContext(logger, "File", 1)

        try:
            with ctx:
                raise ValueError("Test error")
        except ValueError:
            pass

        assert ctx._completed is True
        # Should have logged with error
        assert len(ocel_log.events) == 1

    def test_add_object(self):
        """Should track created objects."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        ctx = OCELStepContext(logger, "File", 1)
        ctx.add_object("obj1")
        ctx.add_object("obj2")
        assert len(ctx._created_objects) == 2

    def test_add_edge(self):
        """Should track created edges."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        ctx = OCELStepContext(logger, "File", 1)
        ctx.add_edge("edge1")
        assert len(ctx._created_edges) == 1

    def test_add_relationship(self):
        """Should track created relationships."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        ctx = OCELStepContext(logger, "AppComp", 1)
        ctx.add_relationship("rel1")
        assert len(ctx._created_relationships) == 1

    def test_complete(self):
        """Should mark as completed and log result."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "")
        ctx = OCELStepContext(logger, "File", 1)
        ctx.items_created = 10
        ctx.complete("Done")
        assert ctx._completed is True
        assert len(ocel_log.events) == 1

    def test_error(self):
        """Should mark as completed with error."""
        ocel_log = OCELLog()
        logger = OCELRunLogger(
            ocel_log=ocel_log,
            run_id="run-1",
            session_id="session-1",
            model="gpt-4",
            repo="test-repo",
        )
        logger.phase_start("extraction", "")
        ctx = OCELStepContext(logger, "File", 1)
        ctx.error("Connection failed")
        assert ctx._completed is True
        assert len(ocel_log.events) == 1


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for list_benchmark_sessions, get_benchmark_session, get_benchmark_runs."""

    def test_list_benchmark_sessions(self):
        """Should query benchmark sessions from database."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("sess-1", "Test benchmark", "completed", "2026-01-01", "2026-01-01"),
            ("sess-2", "Another", "failed", "2026-01-02", None),
        ]
        result = list_benchmark_sessions(engine, limit=10)

        assert len(result) == 2
        assert result[0]["session_id"] == "sess-1"
        assert result[1]["status"] == "failed"

    def test_list_benchmark_sessions_empty(self):
        """Should return empty list when no sessions."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        result = list_benchmark_sessions(engine)
        assert result == []

    def test_get_benchmark_session(self):
        """Should return session details."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            '{"repositories": ["repo1"]}',
            "completed",
            "2026-01-01",
            "2026-01-01",
        )
        result = get_benchmark_session(engine, "sess-1")

        assert result is not None
        assert result["session_id"] == "sess-1"
        assert result["config"]["repositories"] == ["repo1"]

    def test_get_benchmark_session_not_found(self):
        """Should return None when session not found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None
        result = get_benchmark_session(engine, "nonexistent")
        assert result is None

    def test_get_benchmark_runs(self):
        """Should return runs for a session."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("run-1", "repo1", "openai", "gpt-4", 1, "completed", '{"nodes": 10}', "2026-01-01", "2026-01-01"),
            ("run-2", "repo1", "openai", "gpt-4", 2, "completed", "{}", "2026-01-01", "2026-01-01"),
        ]
        result = get_benchmark_runs(engine, "sess-1")

        assert len(result) == 2
        assert result[0]["run_id"] == "run-1"
        assert result[0]["stats"]["nodes"] == 10


# =============================================================================
# BenchmarkOrchestrator Tests
# =============================================================================


class TestBenchmarkOrchestrator:
    """Tests for BenchmarkOrchestrator class."""

    def test_init(self):
        """Should initialize orchestrator with managers."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )
        assert orchestrator.config == config
        assert orchestrator.session_id is None  # Not started yet

    def test_run_missing_models_returns_early(self):
        """Should return error when model configs missing."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["nonexistent-model"],
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )

        with patch("deriva.services.benchmarking.load_benchmark_models", return_value={}):
            result = orchestrator.run()

        # Returns early with errors - no runs attempted
        assert len(result.errors) > 0
        assert "Missing model configs" in result.errors[0]
        assert result.runs_completed == 0

    def test_export_run_model_returns_none_when_no_elements(self):
        """Should return None when no elements to export."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = []

        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
            export_models=True,
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )
        orchestrator.session_id = "test_session"

        result = orchestrator._export_run_model("repo1", "gpt-4", 1)
        assert result is None

    def test_export_run_model_generates_correct_filename(self):
        """Should generate correct filename for model export."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        mock_element = Element(name="Test", element_type="ApplicationComponent", identifier="test-id")
        archimate_manager.get_elements.return_value = [mock_element]
        archimate_manager.get_relationships.return_value = []

        config = BenchmarkConfig(
            repositories=["my-repo"],
            models=["azure-gpt4"],
            export_models=True,
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )
        orchestrator.session_id = "test_session"

        with patch("deriva.services.benchmarking.ArchiMateXMLExporter") as mock_exporter:
            mock_exporter_instance = MagicMock()
            mock_exporter.return_value = mock_exporter_instance

            result = orchestrator._export_run_model("my-repo", "azure-gpt4", 3)

            # Check export was called with correct path pattern
            assert result is not None
            assert "my-repo_azure-gpt4_run3.xml" in result
            assert "test_session" in result
            assert "models" in result

    def test_export_run_model_sanitizes_special_characters(self):
        """Should sanitize special characters in filenames."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        mock_element = Element(name="Test", element_type="ApplicationComponent", identifier="test-id")
        archimate_manager.get_elements.return_value = [mock_element]
        archimate_manager.get_relationships.return_value = []

        config = BenchmarkConfig(
            repositories=["org/repo"],
            models=["model/variant"],
            export_models=True,
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )
        orchestrator.session_id = "test_session"

        with patch("deriva.services.benchmarking.ArchiMateXMLExporter") as mock_exporter:
            mock_exporter_instance = MagicMock()
            mock_exporter.return_value = mock_exporter_instance

            result = orchestrator._export_run_model("org/repo", "model/variant", 1)

            # Should sanitize / to _
            assert result is not None
            assert "org_repo_model_variant_run1.xml" in result

    def test_export_run_model_handles_export_error(self):
        """Should return None when export fails."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [{"type": "ApplicationComponent", "name": "Test"}]
        archimate_manager.get_relationships.side_effect = Exception("Export failed")

        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
            export_models=True,
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )
        orchestrator.session_id = "test_session"

        result = orchestrator._export_run_model("repo1", "gpt-4", 1)
        assert result is None

    def test_export_ocel_incremental(self):
        """Should export new OCEL events incrementally."""
        import tempfile
        from pathlib import Path

        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )

        # Add some events to the OCEL log
        orchestrator.ocel_log.create_event("TestEvent1", objects={"File": ["f1"]})
        orchestrator.ocel_log.create_event("TestEvent2", objects={"File": ["f2"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("deriva.services.benchmarking.Path") as mock_path:
                mock_output_dir = MagicMock()
                mock_path.return_value.__truediv__.return_value = mock_output_dir
                mock_output_dir.__truediv__.return_value = Path(tmpdir) / "events.jsonl"

                orchestrator.session_id = "test_session"
                count = orchestrator._export_ocel_incremental()

                # Should export 2 events
                assert count == 2

    def test_export_ocel_incremental_no_new_events(self):
        """Should return 0 when no new events."""
        import tempfile
        from pathlib import Path

        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        config = BenchmarkConfig(
            repositories=["repo1"],
            models=["gpt-4"],
        )
        orchestrator = BenchmarkOrchestrator(
            engine=engine,
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=config,
        )

        # Add event and export once
        orchestrator.ocel_log.create_event("TestEvent", objects={"File": ["f1"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("deriva.services.benchmarking.Path") as mock_path:
                mock_output_dir = MagicMock()
                mock_path.return_value.__truediv__.return_value = mock_output_dir
                mock_output_dir.__truediv__.return_value = Path(tmpdir) / "events.jsonl"

                orchestrator.session_id = "test_session"
                orchestrator._export_ocel_incremental()

                # Second export with no new events
                count = orchestrator._export_ocel_incremental()
                assert count == 0


# =============================================================================
# BenchmarkAnalyzer Tests
# =============================================================================


class TestBenchmarkAnalyzer:
    """Tests for BenchmarkAnalyzer class."""

    def test_init_raises_for_invalid_session(self):
        """Should raise error for nonexistent session."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        import pytest

        with pytest.raises(ValueError, match="not found"):
            BenchmarkAnalyzer("nonexistent", engine)

    def test_compute_intra_model_consistency_requires_multiple_runs(self):
        """Should require at least 2 runs for consistency."""
        engine = MagicMock()
        # Session info
        engine.execute.return_value.fetchone.return_value = ("sess-1", "Test", "{}", "completed", "2026-01-01", "2026-01-01")

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[{"model_name": "gpt-4", "repository": "repo1", "stats": {}}]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)
                result = analyzer.compute_intra_model_consistency()

        # Only one run, so no metrics computed
        assert result == []

    def test_compute_inter_model_consistency_requires_multiple_models(self):
        """Should require at least 2 models for comparison."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = ("sess-1", "Test", "{}", "completed", "2026-01-01", "2026-01-01")

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch(
                "deriva.services.benchmarking.get_benchmark_runs",
                return_value=[
                    {"model_name": "gpt-4", "repository": "repo1", "stats": {}},
                    {"model_name": "gpt-4", "repository": "repo1", "stats": {}},
                ],
            ):
                analyzer = BenchmarkAnalyzer("sess-1", engine)
                result = analyzer.compute_inter_model_consistency()

        # Only one model, so no inter-model metrics
        assert result == []

    def test_trace_element(self):
        """Should return events for an element."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )
        ocel_log = OCELLog()

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)
                result = analyzer.trace_element("elem1")

        assert isinstance(result, list)

    def test_compute_structural_stability(self):
        """Should compute structural stability for elements with connections."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                # Elements in each run (no underscores - format is Type_Source_Target)
                elements_by_run = {
                    "run1": {"elemA", "elemB", "elemC"},
                    "run2": {"elemA", "elemB", "elemC"},
                    "run3": {"elemA", "elemB"},  # elemC missing in run 3
                }

                # Relationships: format is {Type}_{Source}_{Target}
                relationships_by_run = {
                    "run1": {"Serving_elemA_elemB", "Flow_elemB_elemC"},
                    "run2": {"Serving_elemA_elemB", "Flow_elemB_elemC"},
                    "run3": {"Serving_elemA_elemB"},  # Flow missing
                }

                result = analyzer._compute_structural_stability(elements_by_run, relationships_by_run, 3)

                # Should have entries for elements with connections
                assert len(result) > 0

                # Find elemA's stability
                elem_a_stability = next((s for s in result if s.element_id == "elemA"), None)
                assert elem_a_stability is not None
                # elemA -> elemB connection appears in all 3 runs
                assert len(elem_a_stability.connections) >= 1

    def test_compute_structural_stability_empty(self):
        """Should return empty list when no relationships."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._compute_structural_stability({}, {}, 3)
                assert result == []

    def test_compute_structural_stability_single_run(self):
        """Should return empty list for single run."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                elements_by_run = {"run_1": {"elem_A"}}
                relationships_by_run = {"run_1": {"Serving_elem_A_elem_B"}}

                result = analyzer._compute_structural_stability(elements_by_run, relationships_by_run, 1)
                assert result == []

    def test_compute_type_breakdown(self):
        """Should compute consistency breakdown by edge/relationship type."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                # Edges with format {Type}_{Source}_{Target}
                objects_by_run = {
                    "run1": {"CONTAINS_dirA_fileA", "CONTAINS_dirA_fileB", "IMPORTS_fileA_fileB"},
                    "run2": {"CONTAINS_dirA_fileA", "IMPORTS_fileA_fileB"},  # Missing one CONTAINS
                    "run3": {"CONTAINS_dirA_fileA", "CONTAINS_dirA_fileB", "IMPORTS_fileA_fileB"},
                }

                result = analyzer._compute_type_breakdown(objects_by_run)

                # Should have entries for both types
                assert "CONTAINS" in result
                assert "IMPORTS" in result

    def test_compute_type_breakdown_empty(self):
        """Should return empty dict for empty input."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._compute_type_breakdown({})
                assert result == {}

    def test_get_elements_by_run(self):
        """Should group elements by run from OCEL events."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "DeriveElements",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run1"],
                "Element": ["elemA", "elemB"],
            },
        )
        ocel_log.create_event(
            "DeriveElements",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run2"],
                "Element": ["elemA", "elemC"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_elements_by_run("gpt-4", "repo1")

                assert "run1" in result
                assert "run2" in result
                assert result["run1"] == {"elemA", "elemB"}
                assert result["run2"] == {"elemA", "elemC"}

    def test_get_edges_by_run(self):
        """Should group edges by run from OCEL events."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "ExtractConfig",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run1"],
                "Edge": ["edge1", "edge2"],
            },
        )
        ocel_log.create_event(
            "ExtractConfig",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run2"],
                "Edge": ["edge1", "edge3"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_edges_by_run("gpt-4", "repo1")

                assert "run1" in result
                assert "run2" in result
                assert result["run1"] == {"edge1", "edge2"}
                assert result["run2"] == {"edge1", "edge3"}

    def test_get_relationships_by_run(self):
        """Should group relationships by run from OCEL events."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "DeriveConfig",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run1"],
                "Relationship": ["Serving_A_B", "Flow_B_C"],
            },
        )
        ocel_log.create_event(
            "DeriveConfig",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run2"],
                "Relationship": ["Serving_A_B"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_relationships_by_run("gpt-4", "repo1")

                assert "run1" in result
                assert "run2" in result
                assert result["run1"] == {"Serving_A_B", "Flow_B_C"}
                assert result["run2"] == {"Serving_A_B"}

    def test_get_elements_by_run_no_match(self):
        """Should return empty dict when no matching model/repo."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "DeriveElements",
            objects={
                "Model": ["other-model"],
                "Repository": ["other-repo"],
                "BenchmarkRun": ["run1"],
                "Element": ["elemA"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_elements_by_run("gpt-4", "repo1")
                assert result == {}

    def test_get_edges_by_run_no_match(self):
        """Should return empty dict when no matching model/repo."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "ExtractConfig",
            objects={
                "Model": ["other-model"],
                "Repository": ["other-repo"],
                "BenchmarkRun": ["run1"],
                "Edge": ["edge1"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_edges_by_run("gpt-4", "repo1")
                assert result == {}

    def test_get_relationships_by_run_no_match(self):
        """Should return empty dict when no matching model/repo."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        ocel_log.create_event(
            "DeriveConfig",
            objects={
                "Model": ["other-model"],
                "Repository": ["other-repo"],
                "BenchmarkRun": ["run1"],
                "Relationship": ["rel1"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_relationships_by_run("gpt-4", "repo1")
                assert result == {}

    def test_get_elements_by_run_filters_wrong_activity(self):
        """Should ignore events with wrong activity type."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "sess-1",
            "Test",
            "{}",
            "completed",
            "2026-01-01",
            "2026-01-01",
        )

        ocel_log = OCELLog()
        # This event has wrong activity - should be ignored
        ocel_log.create_event(
            "ExtractConfig",
            objects={
                "Model": ["gpt-4"],
                "Repository": ["repo1"],
                "BenchmarkRun": ["run1"],
                "Element": ["elemA"],
            },
        )

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)

                result = analyzer._get_elements_by_run("gpt-4", "repo1")
                assert result == {}


class TestEnsureExtractionEvents:
    """Extraction appears in the benchmark event log with timing and cache status."""

    def _orchestrator(self):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["repo1"], models=["m"]),
        )
        orchestrator.session_id = "s1"
        return orchestrator

    def test_cached_extraction_emits_event(self):
        orchestrator = self._orchestrator()
        with patch("deriva.services.benchmarking.extraction.compute_extraction_fingerprint", return_value="fp"):
            orchestrator.graph_manager.get_extraction_fingerprint.return_value = "fp"
            orchestrator._ensure_extraction()

        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "EnsureExtraction"]
        assert event.attributes["cached"] is True
        assert event.attributes["repository"] == "repo1"
        assert event.attributes["duration_seconds"] >= 0

    def test_extraction_run_gets_ocel_run_logger_and_emits_event(self):
        orchestrator = self._orchestrator()
        orchestrator._model_configs = {"m": MagicMock(model="m")}
        orchestrator._make_extraction_llm_fn = MagicMock(return_value=MagicMock())
        with (
            patch("deriva.services.benchmarking.extraction.compute_extraction_fingerprint", return_value="new"),
            patch("deriva.services.benchmarking.extraction.run_extraction", return_value={"success": True, "stats": {"nodes_created": 5, "edges_created": 4}}) as run_extraction,
        ):
            orchestrator.graph_manager.get_extraction_fingerprint.return_value = "old"
            orchestrator._ensure_extraction()

        assert isinstance(run_extraction.call_args.kwargs["run_logger"], OCELRunLogger)
        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "EnsureExtraction"]
        assert event.attributes["cached"] is False
        assert (event.attributes["nodes_created"], event.attributes["edges_created"]) == (5, 4)

    def test_failed_extraction_is_not_reported_as_cached(self):
        orchestrator = self._orchestrator()
        orchestrator._model_configs = {"m": MagicMock(model="m")}
        orchestrator._make_extraction_llm_fn = MagicMock(return_value=MagicMock())
        with (
            patch("deriva.services.benchmarking.extraction.compute_extraction_fingerprint", return_value="new"),
            patch("deriva.services.benchmarking.extraction.run_extraction", side_effect=RuntimeError("boom")),
        ):
            orchestrator.graph_manager.get_extraction_fingerprint.return_value = "old"
            orchestrator._ensure_extraction()

        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "EnsureExtraction"]
        assert event.attributes["cached"] is False
        assert any("boom" in e for e in event.attributes["errors"])

    def test_llm_only_mode_clears_the_labels_of_the_llm_steps(self):
        orchestrator = self._orchestrator()
        orchestrator.config.no_cache_extraction_llm = True
        orchestrator._model_configs = {"m": MagicMock(model="m")}
        orchestrator._make_extraction_llm_fn = MagicMock(return_value=MagicMock())
        orchestrator.graph_manager.has_extraction.return_value = True
        with (
            patch("deriva.services.benchmarking.extraction.compute_extraction_fingerprint", return_value="fp"),
            patch("deriva.services.benchmarking.extraction.llm_extraction_labels", return_value=["BusinessConcept"]),
            patch("deriva.services.benchmarking.extraction.run_extraction", return_value={"success": True, "stats": {}}) as run_extraction,
        ):
            orchestrator._ensure_extraction()

        orchestrator.graph_manager.clear_nodes_by_labels.assert_called_once_with("repo1", ["BusinessConcept"])
        assert run_extraction.call_args.kwargs["extraction_methods"] == ["llm"]


class TestLLMQueryEvent:
    """The benchmark LLM wrapper logs the manager's per-call metrics."""

    def test_event_carries_call_metrics(self):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["r"], models=["m"]),
        )
        llm = MagicMock()
        llm.query.return_value = MagicMock(content="{}", usage=None)
        llm.last_call = {
            "cache_key": "k1",
            "cache_hit": False,
            "latency_ms": 812.5,
            "wait_ms": 40.0,
            "requests": 2,
            "input_tokens": 100,
            "output_tokens": 20,
            "error_type": None,
        }
        run_logger = MagicMock(current_config="ApplicationComponent")

        query_fn = orchestrator._create_logging_query_fn(llm, llm, run_logger)
        query_fn("prompt")

        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "LLMQuery"]
        a = event.attributes
        assert (a["cache_key"], a["latency_ms"], a["wait_ms"], a["requests"]) == ("k1", 812.5, 40.0, 2)
        assert (a["tokens_in"], a["tokens_out"], a["cache_hit"], a["error_type"]) == (100, 20, False, None)
        assert query_fn.used_cache_keys == ["k1"]


class TestTimingsExport:
    def test_export_writes_timings_per_run_with_top_queries(self, tmp_path, monkeypatch):
        import json

        from deriva.common.timing import query_stats
        from deriva.services.benchmarking import BenchmarkConfig

        monkeypatch.chdir(tmp_path)
        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["r"], models=["m"]),
        )
        orchestrator.session_id = "s1"
        log = orchestrator.ocel_log
        log.create_event(activity="EnsureExtraction", objects={"BenchmarkSession": ["s1"]}, repository="r", cached=True, duration_seconds=0.2)
        log.create_event(activity="DeriveConfig", objects={"BenchmarkRun": ["run-1"]}, config_id="pagerank", duration_seconds=1.5)
        log.create_event(activity="CompleteRun", objects={"BenchmarkRun": ["run-1"]}, duration_seconds=9.0)
        query_stats.reset()
        query_stats.record("MATCH (n) RETURN n", 12.0)

        orchestrator._export_ocel()

        timings = json.loads((tmp_path / "workspace/benchmarks/s1/timings.json").read_text())
        assert timings["extraction"] == [{"repository": "r", "cached": True, "seconds": 0.2}]
        assert timings["runs"]["run-1"]["run_seconds"] == 9.0
        assert timings["runs"]["run-1"]["steps"] == [{"step": "pagerank", "seconds": 1.5}]
        assert timings["top_queries"][0]["query"] == "MATCH (n) RETURN n"
        query_stats.reset()


class TestDatabasePerRepo:
    """Each benchmark repo is extracted and derived in its own graph database."""

    def _orchestrator(self, per_repo: bool):
        from deriva.services.benchmarking import BenchmarkConfig, RunResult

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["b", "a"], models=["m"], per_repo=per_repo, runs_per_combination=1),
        )
        calls: list[tuple[str, ...]] = []
        orchestrator._ensure_extraction = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda verbose=False, repositories=None: calls.append(("extract", *repositories)) or []
        )
        orchestrator._run_combined = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda repositories, **kw: (
                calls.append(("run", *repositories))
                or RunResult(run_id="r", repositories=repositories, model="m", iteration=1, status="completed", stats={}, errors=[], duration_seconds=0.0)
            )
        )
        return orchestrator, calls

    def _run(self, orchestrator, calls):
        with (
            patch("deriva.services.benchmarking.load_benchmark_models", return_value={"m": MagicMock(provider="openai", model="m")}),
            patch("deriva.services.benchmarking.use_database", side_effect=lambda key: calls.append(("db", key))),
            patch.object(orchestrator, "_create_session"),
            patch.object(orchestrator, "_complete_session"),
            patch.object(orchestrator, "_export_ocel", return_value="x"),
            patch.object(orchestrator, "_export_ocel_incremental"),
        ):
            orchestrator.run()

    def test_per_repo_mode_switches_database_before_extraction(self):
        orchestrator, calls = self._orchestrator(per_repo=True)
        self._run(orchestrator, calls)
        assert calls == [("db", "b"), ("extract", "b"), ("run", "b"), ("db", "a"), ("extract", "a"), ("run", "a")]

    def test_combined_mode_uses_one_database_for_all_repos(self):
        orchestrator, calls = self._orchestrator(per_repo=False)
        self._run(orchestrator, calls)
        assert calls == [("db", "a_b"), ("extract", "b", "a"), ("run", "b", "a")]


class TestExtractionLLMLogging:
    def test_extraction_llm_calls_are_logged_under_the_extraction_run(self):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["repo1"], models=["m"]),
        )
        orchestrator.session_id = "s1"
        orchestrator._model_configs = {"m": MagicMock(model="m")}
        llm = MagicMock()
        llm.query.return_value = MagicMock(content="{}")
        llm.last_call = {"cache_key": "k", "cache_hit": False, "latency_ms": 5.0, "wait_ms": 1.0, "requests": 1, "input_tokens": 3, "output_tokens": 2, "error_type": None}

        def fake_run_extraction(**kwargs):
            kwargs["run_logger"].step_start("BusinessConcept")
            kwargs["llm_query_fn"]("prompt")
            return {"success": True, "stats": {}}

        with (
            patch("deriva.services.benchmarking.LLMManager.from_config", return_value=llm),
            patch("deriva.services.benchmarking.extraction.run_extraction", side_effect=fake_run_extraction),
        ):
            orchestrator._extract_repo("repo1", None)

        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "LLMQuery"]
        assert event.objects["BenchmarkRun"] == ["s1:extraction:repo1"]
        assert event.attributes["config_id"] == "BusinessConcept"
        assert event.attributes["latency_ms"] == 5.0

    def test_extraction_llm_calls_name_the_benchmark_model(self):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["repo1"], models=["m"]),
        )
        orchestrator.session_id = "s1"
        orchestrator._model_configs = {"m": MagicMock(model="provider-model")}
        llm = MagicMock()
        llm.query.return_value = MagicMock(content="{}")
        llm.last_call = {}

        def fake_run_extraction(**kwargs):
            kwargs["run_logger"].step_start("BusinessConcept")
            kwargs["llm_query_fn"]("prompt")
            return {"success": True, "stats": {}}

        with (
            patch("deriva.services.benchmarking.LLMManager.from_config", return_value=llm),
            patch("deriva.services.benchmarking.extraction.run_extraction", side_effect=fake_run_extraction),
        ):
            orchestrator._extract_repo("repo1", None)

        (event,) = [e for e in orchestrator.ocel_log.events if e.activity == "LLMQuery"]
        assert event.objects["Model"] == ["m"]
        assert orchestrator._current_model is None

    def test_nocache_configs_bypass_the_cache_in_extraction(self):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["repo1"], models=["m"], nocache_configs=["BusinessConcept"]),
        )
        orchestrator._model_configs = {"m": MagicMock(model="m")}
        managers = {False: MagicMock(last_call={}), True: MagicMock(last_call={})}
        for manager in managers.values():
            manager.query.return_value = MagicMock(content="{}")
        run_logger = MagicMock(current_config="BusinessConcept")

        with patch("deriva.services.benchmarking.LLMManager.from_config", side_effect=lambda cfg, nocache: managers[nocache]):
            orchestrator._make_extraction_llm_fn(run_logger)("prompt")

        managers[True].query.assert_called_once()
        managers[False].query.assert_not_called()


class TestRunModelSnapshot:
    """Each exported run also writes a JSON snapshot with source nodes and relationship provenance."""

    def test_snapshot_next_to_the_xml(self, tmp_path, monkeypatch):
        import json

        from deriva.adapters.archimate.models import Relationship

        monkeypatch.chdir(tmp_path)
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [
            Element(name="Orders", element_type="ApplicationComponent", identifier="ac_orders", properties={"source": "dir::r::orders", "confidence": 0.9}),
            Element(name="Order", element_type="BusinessObject", identifier="bo_order", properties={"source": "concept::r::order"}),
        ]
        archimate_manager.get_relationships.return_value = [
            Relationship(source="ac_orders", target="bo_order", relationship_type="Access", identifier="r1", properties={"derived_from": "llm", "confidence": 0.8}),
        ]
        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=archimate_manager,
            config=BenchmarkConfig(repositories=["r"], models=["m"], export_models=True),
        )
        orchestrator.session_id = "s"

        with patch("deriva.services.benchmarking.ArchiMateXMLExporter"):
            xml_path = orchestrator._export_run_model("r", "m", 2)

        from pathlib import Path

        snapshot = json.loads(Path(xml_path).with_suffix(".json").read_text(encoding="utf-8"))
        assert snapshot["elements"] == [
            {"identifier": "ac_orders", "type": "ApplicationComponent", "name": "Orders", "source": "dir::r::orders"},
            {"identifier": "bo_order", "type": "BusinessObject", "name": "Order", "source": "concept::r::order"},
        ]
        assert snapshot["relationships"] == [
            {"source": "ac_orders", "target": "bo_order", "type": "Access", "derived_from": "llm", "confidence": 0.8},
        ]


class TestExtractionHonoursNoCache:
    """--no-cache must also make extraction's LLM calls live, or extraction variance is never measured."""

    @pytest.mark.parametrize(("use_cache", "nocache"), [(True, False), (False, True)])
    def test_extraction_llm_manager_follows_the_cache_setting(self, use_cache, nocache):
        from deriva.services.benchmarking import BenchmarkConfig

        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            config=BenchmarkConfig(repositories=["repo1"], models=["m"], use_cache=use_cache),
        )
        orchestrator._model_configs = {"m": MagicMock(model="m")}

        with patch("deriva.services.benchmarking.LLMManager.from_config") as from_config:
            orchestrator._make_extraction_llm_fn(MagicMock())

        # the first manager serves every config not listed in nocache_configs
        assert from_config.call_args_list[0].kwargs["nocache"] is nocache


class TestRunSnapshotGraphNodes:
    """The run snapshot also lists the LLM-created graph nodes, for extraction consistency."""

    def test_concepts_and_technologies_are_recorded(self, tmp_path, monkeypatch):
        import json
        from pathlib import Path

        monkeypatch.chdir(tmp_path)
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [Element(name="A", element_type="ApplicationComponent", identifier="a")]
        archimate_manager.get_relationships.return_value = []
        graph_manager = MagicMock()
        graph_manager.query.side_effect = lambda q, *a, **k: [{"id": "concept::r::user", "types": ["entity", "actor"]}] if "BusinessConcept" in q else [{"id": "tech::r::kafka"}]
        orchestrator = BenchmarkOrchestrator(
            engine=MagicMock(),
            graph_manager=graph_manager,
            archimate_manager=archimate_manager,
            config=BenchmarkConfig(repositories=["r"], models=["m"], export_models=True),
        )
        orchestrator.session_id = "s"

        with patch("deriva.services.benchmarking.ArchiMateXMLExporter"):
            xml_path = orchestrator._export_run_model("r", "m", 1)

        snapshot = json.loads(Path(xml_path).with_suffix(".json").read_text(encoding="utf-8"))
        assert snapshot["graph"] == {"concepts": [["concept::r::user", ["actor", "entity"]]], "technologies": ["tech::r::kafka"]}
