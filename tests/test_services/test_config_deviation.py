"""Tests for config_deviation service."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from deriva.common.ocel import OCELLog
from deriva.modules.analysis.types import ConfigDeviation, DeviationReport
from deriva.services.config_deviation import (
    ConfigDeviationAnalyzer,
    analyze_config_deviations,
    export_config_deviations,
)


class TestConfigDeviationAnalyzerInit:
    """Tests for ConfigDeviationAnalyzer initialization."""

    def test_init_sets_session_id(self):
        """Should set session_id from constructor."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert analyzer.session_id == "session_123"

    def test_init_sets_engine(self):
        """Should set engine from constructor."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert analyzer.engine is engine

    def test_init_loads_ocel(self):
        """Should load OCEL log during init."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        mock_ocel = OCELLog()

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=mock_ocel):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert analyzer.ocel_log is mock_ocel

    def test_init_loads_runs(self):
        """Should load runs from database during init."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("run_1", "repo1", "openai", "gpt-4", 1, "completed", "{}", "2024-01-01", "2024-01-01"),
        ]

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert len(analyzer.runs) == 1
        assert analyzer.runs[0]["run_id"] == "run_1"


class TestConfigDeviationAnalyzerLoadOcel:
    """Tests for OCEL loading."""

    def test_load_ocel_returns_ocel_log(self):
        """Should return an OCELLog instance."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert isinstance(analyzer.ocel_log, OCELLog)


class TestConfigDeviationAnalyzerLoadRuns:
    """Tests for loading runs from database."""

    def test_load_runs_parses_all_fields(self):
        """Should parse all fields from database rows."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("run_1", "myrepo", "azure", "gpt-4o", 2, "completed", '{"nodes": 10}', "2024-01-01T10:00:00", "2024-01-01T10:05:00"),
        ]

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        run = analyzer.runs[0]
        assert run["run_id"] == "run_1"
        assert run["repository"] == "myrepo"
        assert run["model_provider"] == "azure"
        assert run["model_name"] == "gpt-4o"
        assert run["iteration"] == 2
        assert run["status"] == "completed"
        assert run["stats"] == {"nodes": 10}
        assert run["started_at"] == "2024-01-01T10:00:00"
        assert run["completed_at"] == "2024-01-01T10:05:00"

    def test_load_runs_handles_null_stats(self):
        """Should handle null stats field."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("run_1", "repo", "openai", "gpt-4", 1, "running", None, "2024-01-01", None),
        ]

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert analyzer.runs[0]["stats"] == {}

    def test_load_runs_empty_result(self):
        """Should return empty list when no runs found."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)

        assert analyzer.runs == []


class TestConfigDeviationAnalyzerAnalyze:
    """Tests for the analyze method."""

    def test_analyze_returns_deviation_report(self):
        """Should return a DeviationReport."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            report = analyzer.analyze()

        assert isinstance(report, DeviationReport)
        assert report.session_id == "session_123"

    def test_analyze_includes_extraction_deviations(self):
        """Should include extraction deviations in report."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        mock_deviation = ConfigDeviation(
            config_type="extraction",
            config_id="TypeDefinition",
            deviation_count=2,
            total_objects=10,
            consistency_score=0.8,
        )

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch.object(
                ConfigDeviationAnalyzer,
                "_analyze_extraction_deviations",
                return_value=[mock_deviation],
            ):
                with patch.object(
                    ConfigDeviationAnalyzer,
                    "_analyze_derivation_deviations",
                    return_value=[],
                ):
                    analyzer = ConfigDeviationAnalyzer("session_123", engine)
                    report = analyzer.analyze()

        assert len(report.config_deviations) == 1
        assert report.config_deviations[0].config_id == "TypeDefinition"

    def test_analyze_includes_derivation_deviations(self):
        """Should include derivation deviations in report."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        mock_deviation = ConfigDeviation(
            config_type="derivation",
            config_id="ApplicationComponent",
            deviation_count=0,
            total_objects=5,
            consistency_score=1.0,
        )

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            with patch.object(
                ConfigDeviationAnalyzer,
                "_analyze_extraction_deviations",
                return_value=[],
            ):
                with patch.object(
                    ConfigDeviationAnalyzer,
                    "_analyze_derivation_deviations",
                    return_value=[mock_deviation],
                ):
                    analyzer = ConfigDeviationAnalyzer("session_123", engine)
                    report = analyzer.analyze()

        assert len(report.config_deviations) == 1
        assert report.config_deviations[0].config_type == "derivation"


class TestConfigDeviationAnalyzerExtractionDeviations:
    """Tests for extraction deviation analysis."""

    def test_analyze_extraction_returns_empty_when_no_data(self):
        """Should return empty list when no extraction data."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            deviations = analyzer._analyze_extraction_deviations()

        assert deviations == []


class TestConfigDeviationAnalyzerDerivationDeviations:
    """Tests for derivation deviation analysis."""

    def test_analyze_derivation_returns_empty_when_no_data(self):
        """Should return empty list when no derivation data."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            deviations = analyzer._analyze_derivation_deviations()

        assert deviations == []


class TestConfigDeviationAnalyzerGetDeviationDetails:
    """Tests for getting deviation details."""

    def test_get_deviation_details_returns_error_for_no_runs(self):
        """Should return error when no runs found."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            details = analyzer.get_deviation_details("TypeDefinition")

        assert details["config_id"] == "TypeDefinition"
        assert "error" in details


class TestConfigDeviationAnalyzerCompareConfigs:
    """Tests for comparing configs."""

    def test_compare_configs_returns_summary(self):
        """Should return comparison summary."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            comparison = analyzer.compare_configs()

        assert comparison["session_id"] == "session_123"
        assert "summary" in comparison
        assert "most_stable" in comparison
        assert "least_stable" in comparison
        assert "recommendations" in comparison


class TestConfigDeviationAnalyzerExportJson:
    """Tests for JSON export."""

    def test_export_json_creates_file(self, tmp_path):
        """Should create JSON file at specified path."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        output_file = tmp_path / "deviations.json"

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            result = analyzer.export_json(output_file)

        assert Path(result).exists()
        with open(result, encoding="utf-8") as f:
            data = json.load(f)
        assert "session_id" in data

    def test_export_json_returns_path(self, tmp_path):
        """Should return path to exported file."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        output_file = tmp_path / "test_export.json"

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            result = analyzer.export_json(output_file)

        assert result == str(output_file)


class TestConfigDeviationAnalyzerExportSortedJson:
    """Tests for sorted JSON export."""

    def test_export_sorted_by_consistency_score(self, tmp_path):
        """Should export sorted by consistency_score."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        output_file = tmp_path / "sorted.json"

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            result = analyzer.export_sorted_json(output_file, sort_by="consistency_score")

        assert Path(result).exists()

    def test_export_sorted_by_total_objects(self, tmp_path):
        """Should export sorted by total_objects."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        output_file = tmp_path / "sorted_objects.json"

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_123", engine)
            result = analyzer.export_sorted_json(output_file, sort_by="total_objects")

        assert Path(result).exists()


class TestConfigDeviationAnalyzerLoadOcelFiles:
    """Tests for OCEL file loading paths."""

    def test_load_ocel_returns_empty_when_no_files_exist(self, tmp_path, monkeypatch):
        """Should return empty OCELLog when no files exist."""
        monkeypatch.chdir(tmp_path)

        analyzer = ConfigDeviationAnalyzer.__new__(ConfigDeviationAnalyzer)
        analyzer.session_id = "nonexistent_session"
        ocel = analyzer._load_ocel()

        assert isinstance(ocel, OCELLog)
        assert len(ocel.events) == 0

    def test_load_ocel_from_ocel_json(self, tmp_path, monkeypatch):
        """Should load from events.ocel.json if it exists."""
        monkeypatch.chdir(tmp_path)
        ocel_dir = tmp_path / "workspace" / "benchmarks" / "session_123"
        ocel_dir.mkdir(parents=True)

        ocel_file = ocel_dir / "events.ocel.json"
        ocel_data = {
            "ocel:global-event": {"ocel:activity": "__GLOBAL__"},
            "ocel:global-object": {"ocel:type": "__GLOBAL__"},
            "ocel:events": {},
            "ocel:objects": {},
        }
        ocel_file.write_text(json.dumps(ocel_data))

        analyzer = ConfigDeviationAnalyzer.__new__(ConfigDeviationAnalyzer)
        analyzer.session_id = "session_123"
        ocel = analyzer._load_ocel()

        assert isinstance(ocel, OCELLog)

    def test_load_ocel_from_jsonl(self, tmp_path, monkeypatch):
        """Should load from events.jsonl if ocel.json doesn't exist."""
        monkeypatch.chdir(tmp_path)
        ocel_dir = tmp_path / "workspace" / "benchmarks" / "session_456"
        ocel_dir.mkdir(parents=True)

        jsonl_file = ocel_dir / "events.jsonl"
        jsonl_file.write_text("")  # Empty JSONL

        analyzer = ConfigDeviationAnalyzer.__new__(ConfigDeviationAnalyzer)
        analyzer.session_id = "session_456"
        ocel = analyzer._load_ocel()

        assert isinstance(ocel, OCELLog)


class TestConfigDeviationAnalyzerExportDefaultPath:
    """Tests for export with default path."""

    def test_export_json_default_path(self, tmp_path, monkeypatch):
        """Should create file at default path when path not specified."""
        monkeypatch.chdir(tmp_path)
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_default", engine)
            result = analyzer.export_json()

        assert Path(result).exists()
        assert "session_default" in result

    def test_export_sorted_json_default_path(self, tmp_path, monkeypatch):
        """Should create sorted file at default path."""
        monkeypatch.chdir(tmp_path)
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            analyzer = ConfigDeviationAnalyzer("session_sorted", engine)
            result = analyzer.export_sorted_json(sort_by="deviation_count")

        assert Path(result).exists()


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_analyze_config_deviations_returns_report(self):
        """Should return DeviationReport."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            report = analyze_config_deviations("session_123", engine)

        assert isinstance(report, DeviationReport)

    def test_export_config_deviations_creates_file(self, tmp_path):
        """Should create export file."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []
        output_file = tmp_path / "export.json"

        with patch.object(ConfigDeviationAnalyzer, "_load_ocel", return_value=OCELLog()):
            result = export_config_deviations("session_123", engine, str(output_file))

        assert Path(result).exists()
