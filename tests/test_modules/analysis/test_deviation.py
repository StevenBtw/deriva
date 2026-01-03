"""Tests for deviation analysis functions."""

import pytest

from deriva.modules.analysis.deviation import (
    analyze_config_deviations,
    analyze_from_object_types,
    build_deviation_report,
    compute_deviation_stats,
    extract_element_type,
    extract_node_type,
    generate_recommendations,
    group_objects_by_config,
)
from deriva.modules.analysis.types import ConfigDeviation


class TestGroupObjectsByConfig:
    """Tests for group_objects_by_config function."""

    def test_empty_events(self):
        """Empty events should return empty dict."""
        result = group_objects_by_config([], "extraction")
        assert result == {}

    def test_groups_by_config_and_run(self):
        """Should group objects by config and run."""
        events = [
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run1"],
                    "GraphNode": ["node_a", "node_b"],
                }
            },
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run2"],
                    "GraphNode": ["node_a", "node_c"],
                }
            },
        ]

        result = group_objects_by_config(events, "extraction")

        assert "config1" in result
        assert "run1" in result["config1"]
        assert "run2" in result["config1"]
        assert result["config1"]["run1"] == {"node_a", "node_b"}
        assert result["config1"]["run2"] == {"node_a", "node_c"}

    def test_uses_element_type_for_derivation(self):
        """Should use Element type for derivation config type."""
        events = [
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run1"],
                    "Element": ["elem_1", "elem_2"],
                }
            },
        ]

        result = group_objects_by_config(events, "derivation")

        assert result["config1"]["run1"] == {"elem_1", "elem_2"}

    def test_handles_multiple_configs(self):
        """Should handle events with multiple configs."""
        events = [
            {
                "objects": {
                    "Config": ["configA", "configB"],
                    "BenchmarkRun": ["run1"],
                    "GraphNode": ["node_1"],
                }
            },
        ]

        result = group_objects_by_config(events, "extraction")

        assert "configA" in result
        assert "configB" in result


class TestComputeDeviationStats:
    """Tests for compute_deviation_stats function."""

    def test_perfect_consistency(self):
        """All objects in all runs should give 1.0 consistency."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b", "c"},
            "run3": {"a", "b", "c"},
        }

        result = compute_deviation_stats("test_config", "extraction", objects_by_run)

        assert result.config_id == "test_config"
        assert result.config_type == "extraction"
        assert result.consistency_score == 1.0
        assert result.deviation_count == 0
        assert result.total_objects == 3

    def test_partial_consistency(self):
        """Some objects missing from runs should give partial consistency."""
        objects_by_run = {
            "run1": {"a", "b", "c"},
            "run2": {"a", "b"},  # missing c
        }

        result = compute_deviation_stats("test_config", "derivation", objects_by_run)

        assert result.consistency_score == pytest.approx(2 / 3)
        assert result.deviation_count == 1
        assert result.deviating_objects == ["c"]
        assert sorted(result.stable_objects) == ["a", "b"]

    def test_no_consistency(self):
        """Disjoint runs should give 0 consistency."""
        objects_by_run = {
            "run1": {"a"},
            "run2": {"b"},
        }

        result = compute_deviation_stats("test", "extraction", objects_by_run)

        assert result.consistency_score == 0.0
        assert result.deviation_count == 2

    def test_empty_runs(self):
        """Empty runs should give 1.0 consistency."""
        objects_by_run = {}

        result = compute_deviation_stats("test", "extraction", objects_by_run)

        assert result.consistency_score == 1.0
        assert result.total_objects == 0

    def test_limits_object_lists(self):
        """Should limit objects in lists to max_objects_in_list."""
        # Create many objects that deviate
        objects_by_run = {
            "run1": {f"obj_{i}" for i in range(100)},
            "run2": set(),  # Empty, so all 100 are deviating
        }

        result = compute_deviation_stats("test", "extraction", objects_by_run, max_objects_in_list=10)

        assert len(result.deviating_objects) == 10


class TestAnalyzeConfigDeviations:
    """Tests for analyze_config_deviations function."""

    def test_single_run_returns_empty(self):
        """Single run per config should return empty list."""
        events = [
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run1"],
                    "GraphNode": ["node_a"],
                }
            },
        ]

        result = analyze_config_deviations(events, "extraction")

        assert result == []

    def test_analyzes_multiple_runs(self):
        """Should analyze configs with multiple runs."""
        events = [
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run1"],
                    "GraphNode": ["node_a", "node_b"],
                }
            },
            {
                "objects": {
                    "Config": ["config1"],
                    "BenchmarkRun": ["run2"],
                    "GraphNode": ["node_a"],  # node_b missing
                }
            },
        ]

        result = analyze_config_deviations(events, "extraction")

        assert len(result) == 1
        assert result[0].config_id == "config1"
        assert result[0].deviation_count == 1


class TestAnalyzeFromObjectTypes:
    """Tests for analyze_from_object_types function."""

    def test_single_run_returns_empty(self):
        """Single run should return empty list."""
        objects_by_run = {"run1": {"TypeA_1", "TypeA_2"}}

        result = analyze_from_object_types(objects_by_run, "extraction", extract_node_type)

        assert result == []

    def test_groups_by_type_and_analyzes(self):
        """Should group by extracted type and analyze each."""
        objects_by_run = {
            "run1": {"TypeA_1", "TypeA_2", "TypeB_1"},
            "run2": {"TypeA_1", "TypeB_1", "TypeB_2"},
        }

        result = analyze_from_object_types(objects_by_run, "extraction", extract_node_type)

        # Should have deviations for TypeA and TypeB
        config_ids = {cd.config_id for cd in result}
        assert "TypeA" in config_ids
        assert "TypeB" in config_ids


class TestExtractNodeType:
    """Tests for extract_node_type function."""

    def test_extracts_first_part(self):
        """Should extract first part before underscore."""
        assert extract_node_type("BusinessConcept_repo_name") == "BusinessConcept"
        assert extract_node_type("File_myrepo_main") == "File"

    def test_handles_no_underscore(self):
        """Should return whole string if no underscore."""
        assert extract_node_type("SimpleId") == "SimpleId"

    def test_handles_empty_string(self):
        """Should return empty string for empty input."""
        assert extract_node_type("") == ""


class TestExtractElementType:
    """Tests for extract_element_type function."""

    def test_detects_component(self):
        """Should detect ApplicationComponent."""
        assert extract_element_type("ac_auth_service") == "ApplicationComponent"
        assert extract_element_type("AuthComponent") == "ApplicationComponent"

    def test_detects_service(self):
        """Should detect ApplicationService."""
        assert extract_element_type("as_login") == "ApplicationService"
        assert extract_element_type("UserService") == "ApplicationService"

    def test_detects_data_object(self):
        """Should detect DataObject."""
        assert extract_element_type("do_user") == "DataObject"
        assert extract_element_type("UserData") == "DataObject"

    def test_detects_artifact(self):
        """Should detect Artifact."""
        assert extract_element_type("art_config") == "Artifact"
        assert extract_element_type("ConfigArtifact") == "Artifact"

    def test_fallback_to_first_part(self):
        """Should fallback to first part if no pattern matches."""
        assert extract_element_type("Custom_element_id") == "Custom"


class TestGenerateRecommendations:
    """Tests for generate_recommendations function."""

    def test_high_priority_for_low_consistency(self):
        """Should generate high priority for <50% consistency."""
        deviations = [
            ConfigDeviation(
                config_type="extraction",
                config_id="bad_config",
                deviation_count=80,
                total_objects=100,
                consistency_score=0.2,
            )
        ]

        result = generate_recommendations(deviations)

        assert len(result) == 1
        assert "HIGH PRIORITY" in result[0]
        assert "bad_config" in result[0]

    def test_medium_priority_for_moderate_consistency(self):
        """Should generate medium priority for 50-80% consistency."""
        deviations = [
            ConfigDeviation(
                config_type="derivation",
                config_id="ok_config",
                deviation_count=30,
                total_objects=100,
                consistency_score=0.7,
            )
        ]

        result = generate_recommendations(deviations)

        assert len(result) == 1
        assert "MEDIUM" in result[0]

    def test_no_action_for_high_consistency(self):
        """Should say no action needed for >80% consistency."""
        deviations = [
            ConfigDeviation(
                config_type="extraction",
                config_id="good_config",
                deviation_count=5,
                total_objects=100,
                consistency_score=0.95,
            )
        ]

        result = generate_recommendations(deviations)

        assert len(result) == 1
        assert "No immediate action needed" in result[0]

    def test_empty_deviations_gives_positive_message(self):
        """Empty deviations list should give positive message."""
        result = generate_recommendations([])

        assert len(result) == 1
        assert "good consistency" in result[0]


class TestBuildDeviationReport:
    """Tests for build_deviation_report function."""

    def test_builds_report_with_stats(self):
        """Should build report with computed statistics."""
        config_devs = [
            ConfigDeviation(
                config_type="extraction",
                config_id="config_a",
                deviation_count=10,
                total_objects=100,
                consistency_score=0.9,
            ),
            ConfigDeviation(
                config_type="extraction",
                config_id="config_b",
                deviation_count=30,
                total_objects=100,
                consistency_score=0.7,
            ),
        ]

        report = build_deviation_report(
            session_id="sess_123",
            analysis_timestamp="2024-01-01T00:00:00Z",
            total_runs=5,
            config_deviations=config_devs,
        )

        assert report.session_id == "sess_123"
        assert report.total_runs == 5
        assert report.total_deviations == 40  # 10 + 30
        assert report.overall_consistency == 0.8  # (200 - 40) / 200

    def test_sorts_by_deviation_count(self):
        """Should sort deviations by count descending."""
        config_devs = [
            ConfigDeviation(
                config_type="extraction",
                config_id="low",
                deviation_count=5,
                total_objects=100,
                consistency_score=0.95,
            ),
            ConfigDeviation(
                config_type="extraction",
                config_id="high",
                deviation_count=50,
                total_objects=100,
                consistency_score=0.5,
            ),
        ]

        report = build_deviation_report("sess", "2024-01-01", 3, config_devs)

        # High deviation should be first
        assert report.config_deviations[0].config_id == "high"
        assert report.config_deviations[1].config_id == "low"

    def test_handles_empty_deviations(self):
        """Should handle empty deviations list."""
        report = build_deviation_report("sess", "2024-01-01", 3, [])

        assert report.total_deviations == 0
        assert report.overall_consistency == 1.0
        assert report.config_deviations == []
