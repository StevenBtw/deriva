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
        archimate_manager.get_elements.return_value = [{"type": "ApplicationComponent", "name": "Test"}]
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
            assert "my-repo_azure-gpt4_3.archimate" in result
            assert "test_session" in result
            assert "models" in result

    def test_export_run_model_sanitizes_special_characters(self):
        """Should sanitize special characters in filenames."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [{"type": "ApplicationComponent", "name": "Test"}]
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
            assert "org_repo_model_variant_1.archimate" in result

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
        engine.execute.return_value.fetchone.return_value = ("sess-1", "Test", "{}", "completed", "2026-01-01", "2026-01-01")
        ocel_log = OCELLog()

        with patch.object(BenchmarkAnalyzer, "_load_ocel", return_value=ocel_log):
            with patch("deriva.services.benchmarking.get_benchmark_runs", return_value=[]):
                analyzer = BenchmarkAnalyzer("sess-1", engine)
                result = analyzer.trace_element("elem1")

        assert isinstance(result, list)
