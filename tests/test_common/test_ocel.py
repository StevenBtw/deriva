"""Tests for common.ocel module."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from deriva.common.ocel import (
    InconsistencyInfo,
    OCELEvent,
    OCELLog,
    create_run_id,
    hash_content,
    parse_run_id,
)


class TestOCELEvent:
    """Tests for OCELEvent dataclass."""

    def test_basic_event_creation(self):
        """Should create event with required fields."""
        event = OCELEvent(
            activity="ExtractNode",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            objects={"File": ["file_1"], "GraphNode": ["node_1", "node_2"]},
        )

        assert event.activity == "ExtractNode"
        assert event.objects["File"] == ["file_1"]
        assert len(event.objects["GraphNode"]) == 2
        assert event.event_id  # Auto-generated

    def test_event_with_attributes(self):
        """Should include attributes."""
        event = OCELEvent(
            activity="ClassifyFile",
            timestamp=datetime.now(),
            objects={"File": ["file_1"]},
            attributes={"file_type": "source", "subtype": "python"},
        )

        assert event.attributes["file_type"] == "source"
        assert event.attributes["subtype"] == "python"

    def test_to_jsonl_dict(self):
        """Should convert to compact JSONL format."""
        event = OCELEvent(
            activity="ClassifyFile",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            objects={"File": ["file_1"]},
            attributes={"type": "source"},
            event_id="evt_001",
        )

        jsonl_dict = event.to_jsonl_dict()

        assert jsonl_dict["eid"] == "evt_001"
        assert jsonl_dict["activity"] == "ClassifyFile"
        assert jsonl_dict["objects"]["File"] == ["file_1"]
        assert jsonl_dict["attributes"]["type"] == "source"

    def test_has_object(self):
        """Should check if event relates to specific object."""
        event = OCELEvent(
            activity="Test",
            timestamp=datetime.now(),
            objects={"File": ["file_1", "file_2"], "Node": ["node_1"]},
        )

        assert event.has_object("File", "file_1") is True
        assert event.has_object("File", "file_3") is False
        assert event.has_object("Node", "node_1") is True
        assert event.has_object("Other", "file_1") is False

    def test_has_object_type(self):
        """Should check if event relates to any object of a type."""
        event = OCELEvent(
            activity="Test",
            timestamp=datetime.now(),
            objects={"File": ["file_1"], "Node": []},
        )

        assert event.has_object_type("File") is True
        assert event.has_object_type("Node") is False  # Empty list
        assert event.has_object_type("Other") is False


class TestInconsistencyInfo:
    """Tests for InconsistencyInfo dataclass."""

    def test_basic_creation(self):
        """Should create inconsistency info."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=["run_1", "run_2"],
            missing_from=["run_3"],
            total_runs=3,
        )

        assert info.object_id == "elem_1"
        assert info.object_type == "Element"
        assert len(info.present_in) == 2
        assert len(info.missing_from) == 1

    def test_consistency_score(self):
        """Should calculate consistency score correctly."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=["run_1", "run_2"],
            missing_from=["run_3"],
            total_runs=3,
        )

        assert info.consistency_score == pytest.approx(2 / 3)

    def test_consistency_score_zero_runs(self):
        """Should handle zero total runs."""
        info = InconsistencyInfo(
            object_id="elem_1",
            object_type="Element",
            present_in=[],
            missing_from=[],
            total_runs=0,
        )

        assert info.consistency_score == 0.0


class TestOCELLog:
    """Tests for OCELLog class."""

    def test_empty_log(self):
        """Should create empty log."""
        log = OCELLog()

        assert len(log.events) == 0
        assert len(log.object_types) == 0

    def test_add_event(self):
        """Should add event and update indices."""
        log = OCELLog()
        event = OCELEvent(
            activity="Test",
            timestamp=datetime.now(),
            objects={"File": ["file_1"]},
        )

        log.add_event(event)

        assert len(log.events) == 1
        assert "File" in log.object_types

    def test_create_event(self):
        """Should create and add event in one step."""
        log = OCELLog()

        event = log.create_event(
            activity="ClassifyFile",
            objects={"File": ["file_1"]},
            file_type="source",
        )

        assert len(log.events) == 1
        assert event.activity == "ClassifyFile"
        assert event.attributes["file_type"] == "source"

    def test_get_events_for_object(self):
        """Should retrieve events for specific object."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["file_1"]})
        log.create_event("Event2", objects={"File": ["file_1", "file_2"]})
        log.create_event("Event3", objects={"File": ["file_2"]})

        events = log.get_events_for_object("File", "file_1")

        assert len(events) == 2
        activities = [e.activity for e in events]
        assert "Event1" in activities
        assert "Event2" in activities

    def test_get_events_by_activity(self):
        """Should retrieve events by activity name."""
        log = OCELLog()
        log.create_event("ClassifyFile", objects={"File": ["f1"]})
        log.create_event("ExtractNode", objects={"File": ["f1"]})
        log.create_event("ClassifyFile", objects={"File": ["f2"]})

        events = log.get_events_by_activity("ClassifyFile")

        assert len(events) == 2

    def test_get_events_by_activity_prefix(self):
        """Should retrieve events by activity prefix."""
        log = OCELLog()
        log.create_event("Extract:TypeDefinition", objects={"File": ["f1"]})
        log.create_event("Extract:BusinessConcept", objects={"File": ["f1"]})
        log.create_event("Derive:Component", objects={"File": ["f1"]})

        events = log.get_events_by_activity_prefix("Extract:")

        assert len(events) == 2

    def test_get_all_objects(self):
        """Should get all object IDs of a type."""
        log = OCELLog()
        log.create_event("E1", objects={"File": ["f1", "f2"]})
        log.create_event("E2", objects={"File": ["f2", "f3"]})

        files = log.get_all_objects("File")

        assert files == {"f1", "f2", "f3"}

    def test_get_objects_by_run(self):
        """Should group objects by run ID."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1", "elem_2"]})
        log.create_event("E2", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_2"]})
        log.create_event("E3", objects={"BenchmarkRun": ["run_2"], "Element": ["elem_1", "elem_3"]})

        by_run = log.get_objects_by_run("Element")

        assert "run_1" in by_run
        assert "run_2" in by_run
        assert by_run["run_1"] == {"elem_1", "elem_2"}
        assert by_run["run_2"] == {"elem_1", "elem_3"}

    def test_get_objects_by_model(self):
        """Should group objects by model ID."""
        log = OCELLog()
        log.create_event("E1", objects={"Model": ["gpt-4"], "Element": ["elem_1"]})
        log.create_event("E2", objects={"Model": ["claude"], "Element": ["elem_2"]})

        by_model = log.get_objects_by_model("Element")

        assert by_model["gpt-4"] == {"elem_1"}
        assert by_model["claude"] == {"elem_2"}

    def test_find_inconsistencies(self):
        """Should find objects that appear in some runs but not others."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1", "elem_2"]})
        log.create_event("E2", objects={"BenchmarkRun": ["run_2"], "Element": ["elem_1", "elem_3"]})

        inconsistencies = log.find_inconsistencies("Element")

        # elem_1 is in both runs (consistent), elem_2 and elem_3 are inconsistent
        assert "elem_2" in inconsistencies
        assert "elem_3" in inconsistencies
        assert "elem_1" not in inconsistencies

    def test_find_inconsistencies_single_run(self):
        """Should return empty for single run."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1"]})

        inconsistencies = log.find_inconsistencies("Element")

        assert inconsistencies == {}

    def test_compute_consistency_score(self):
        """Should compute overall consistency score."""
        log = OCELLog()
        # elem_1 in both, elem_2 only in run_1
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1", "elem_2"]})
        log.create_event("E2", objects={"BenchmarkRun": ["run_2"], "Element": ["elem_1"]})

        score = log.compute_consistency_score("Element")

        # 1 out of 2 elements is consistent
        assert score == 0.5

    def test_compute_consistency_score_all_consistent(self):
        """Should return 1.0 when all objects are consistent."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1"]})
        log.create_event("E2", objects={"BenchmarkRun": ["run_2"], "Element": ["elem_1"]})

        score = log.compute_consistency_score("Element")

        assert score == 1.0

    def test_compute_consistency_score_single_run(self):
        """Should return 1.0 for single run."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["elem_1"]})

        score = log.compute_consistency_score("Element")

        assert score == 1.0

    def test_compare_runs(self):
        """Should compare two runs."""
        log = OCELLog()
        log.create_event("E1", objects={"BenchmarkRun": ["run_1"], "Element": ["a", "b", "c"]})
        log.create_event("E2", objects={"BenchmarkRun": ["run_2"], "Element": ["b", "c", "d"]})

        comparison = log.compare_runs("run_1", "run_2", "Element")

        assert set(comparison["overlap"]) == {"b", "c"}
        assert set(comparison["only_in_1"]) == {"a"}
        assert set(comparison["only_in_2"]) == {"d"}
        assert comparison["count_1"] == 3
        assert comparison["count_2"] == 3
        assert comparison["overlap_count"] == 2
        # Jaccard: 2 / 4 = 0.5
        assert comparison["jaccard_similarity"] == 0.5

    def test_export_and_load_json(self):
        """Should export to JSON and reload."""
        log = OCELLog()
        log.create_event("Test", objects={"File": ["file_1"]}, key="value")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            log.export_json(path)

            loaded = OCELLog.from_json(path)

            assert len(loaded.events) == 1
            assert loaded.events[0].activity == "Test"
            assert loaded.events[0].attributes["key"] == "value"

    def test_export_and_load_jsonl(self):
        """Should export to JSONL and reload."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["f1"]})
        log.create_event("Event2", objects={"File": ["f2"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            log.export_jsonl(path)

            loaded = OCELLog.from_jsonl(path)

            assert len(loaded.events) == 2
            activities = [e.activity for e in loaded.events]
            assert "Event1" in activities
            assert "Event2" in activities

    def test_export_jsonl_incremental_exports_new_events(self):
        """Should export only new events since last incremental export."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["f1"]})
        log.create_event("Event2", objects={"File": ["f2"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incremental.jsonl"

            # First export - should export 2 events
            count1 = log.export_jsonl_incremental(path)
            assert count1 == 2

            # Add more events
            log.create_event("Event3", objects={"File": ["f3"]})
            log.create_event("Event4", objects={"File": ["f4"]})

            # Second export - should only export 2 new events
            count2 = log.export_jsonl_incremental(path)
            assert count2 == 2

            # File should have all 4 events
            loaded = OCELLog.from_jsonl(path)
            assert len(loaded.events) == 4

    def test_export_jsonl_incremental_returns_zero_when_no_new_events(self):
        """Should return 0 when no new events to export."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["f1"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incremental.jsonl"

            # First export
            log.export_jsonl_incremental(path)

            # No new events - should return 0
            count = log.export_jsonl_incremental(path)
            assert count == 0

    def test_export_jsonl_incremental_creates_parent_dirs(self):
        """Should create parent directories if they don't exist."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["f1"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "dir" / "incremental.jsonl"

            count = log.export_jsonl_incremental(path)
            assert count == 1
            assert path.exists()

    def test_export_jsonl_incremental_appends_to_existing(self):
        """Should append to existing file content."""
        log = OCELLog()
        log.create_event("Event1", objects={"File": ["f1"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incremental.jsonl"

            # First export
            log.export_jsonl_incremental(path)

            # Create new log instance with new events
            log2 = OCELLog()
            log2.create_event("Event2", objects={"File": ["f2"]})
            log2.export_jsonl_incremental(path)

            # File should have events from both logs
            loaded = OCELLog.from_jsonl(path)
            assert len(loaded.events) == 2


class TestHashContent:
    """Tests for hash_content function."""

    def test_returns_short_hash(self):
        """Should return 16-character hash."""
        result = hash_content("test content")

        assert len(result) == 16
        assert result.isalnum()

    def test_same_content_same_hash(self):
        """Should return same hash for same content."""
        hash1 = hash_content("identical content")
        hash2 = hash_content("identical content")

        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Should return different hash for different content."""
        hash1 = hash_content("content A")
        hash2 = hash_content("content B")

        assert hash1 != hash2


class TestCreateRunId:
    """Tests for create_run_id function."""

    def test_creates_formatted_id(self):
        """Should create colon-separated run ID."""
        run_id = create_run_id("session_123", "myrepo", "gpt-4", 1)

        assert run_id == "session_123:myrepo:gpt-4:1"

    def test_handles_special_characters(self):
        """Should handle special characters in components."""
        run_id = create_run_id("sess-1", "my/repo", "gpt-4o-mini", 2)

        assert "sess-1" in run_id
        assert "my/repo" in run_id
        assert "gpt-4o-mini" in run_id


class TestParseRunId:
    """Tests for parse_run_id function."""

    def test_parses_valid_run_id(self):
        """Should parse standard run ID into components."""
        result = parse_run_id("session_123:myrepo:gpt-4:1")

        assert result["session_id"] == "session_123"
        assert result["repository"] == "myrepo"
        assert result["model"] == "gpt-4"
        assert result["iteration"] == 1

    def test_handles_invalid_format(self):
        """Should handle malformed run ID."""
        result = parse_run_id("invalid")

        assert result == {"run_id": "invalid"}

    def test_handles_partial_format(self):
        """Should handle run ID with too few parts."""
        result = parse_run_id("a:b")

        assert result == {"run_id": "a:b"}

    def test_parses_iteration_as_int(self):
        """Should parse iteration as integer."""
        result = parse_run_id("s:r:m:42")

        assert result["iteration"] == 42
        assert isinstance(result["iteration"], int)


class TestLoadBenchmarkOcel:
    """One loader for a session's event log (ocel/benchmark_events.json(l), legacy root files)."""

    def _write(self, path, activity):
        log = OCELLog()
        log.create_event(activity=activity, objects={})
        path.parent.mkdir(parents=True, exist_ok=True)
        log.export_jsonl(path)

    def test_reads_current_layout(self, tmp_path):
        from deriva.common.ocel import load_benchmark_ocel

        self._write(tmp_path / "s1" / "ocel" / "benchmark_events.jsonl", "Current")
        assert [e.activity for e in load_benchmark_ocel(tmp_path, "s1").events] == ["Current"]

    def test_falls_back_to_legacy_layout_then_empty(self, tmp_path):
        from deriva.common.ocel import load_benchmark_ocel

        self._write(tmp_path / "s1" / "events.jsonl", "Legacy")
        assert [e.activity for e in load_benchmark_ocel(tmp_path, "s1").events] == ["Legacy"]
        assert load_benchmark_ocel(tmp_path, "missing").events == []

    def test_benchmark_analyzer_uses_current_layout(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch

        from deriva.bench.benchmarking import BenchmarkAnalyzer

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DERIVA_HOME", str(tmp_path))  # benchmark folders resolve against the home folder
        self._write(tmp_path / "workspace" / "benchmarks" / "s1" / "ocel" / "benchmark_events.jsonl", "Current")
        with (
            patch("deriva.bench.benchmarking.get_benchmark_session", return_value={"session_id": "s1"}),
            patch("deriva.bench.benchmarking.get_benchmark_runs", return_value=[]),
        ):
            analyzer = BenchmarkAnalyzer("s1", MagicMock())

        assert [e.activity for e in analyzer.ocel_log.events] == ["Current"]


def test_benchmark_loader_is_exported():
    from deriva.common import ocel

    assert "load_benchmark_ocel" in ocel.__all__


# =============================================================================
# OCEL 2.0 (standard JSON layout) and the flat case log
# =============================================================================


def _run_log() -> OCELLog:
    """One run of a session: start, an LLM call, a derive step, completion; plus the session and extraction events."""
    log = OCELLog()
    t = datetime(2026, 10, 9, 12, 0, 0)
    run = {"BenchmarkSession": ["bench_1"], "BenchmarkRun": ["bench_1:repo:m:1"], "Repository": ["repo"], "Model": ["m"]}
    log.add_event(OCELEvent("StartBenchmark", t, {"BenchmarkSession": ["bench_1"]}, {"models": ["m"]}, event_id="e0"))
    log.add_event(
        OCELEvent("EnsureExtraction", t.replace(second=5), {"BenchmarkSession": ["bench_1"], "Repository": ["repo"]}, {"cached": True, "duration_seconds": 0.5}, event_id="e1")
    )
    log.add_event(OCELEvent("StartRun", t.replace(second=10), run, {"iteration": 1}, event_id="e2"))
    log.add_event(
        OCELEvent(
            "LLMQuery",
            t.replace(second=20),
            {"BenchmarkRun": ["bench_1:repo:m:1"], "Model": ["m"], "Config": ["ApplicationComponent"]},
            {"config_id": "ApplicationComponent", "call_kind": "naming", "cache_hit": False, "tokens_in": 12, "latency_ms": 1500.0, "wait_ms": 500.0, "error_type": None},
            event_id="e3",
        )
    )
    log.add_event(
        OCELEvent(
            "DeriveConfig",
            t.replace(second=30),
            {**run, "Config": ["ApplicationComponent"], "Element": ["ac_a", "ac_b"], "Relationship": ["Serving_ac_a_ac_b"]},
            {"config_id": "ApplicationComponent", "duration_seconds": 12, "stats": {"items_created": 2}, "errors": []},
            event_id="e4",
        )
    )
    log.add_event(OCELEvent("CompleteRun", t.replace(second=40), run, {"status": "completed", "duration_seconds": 30.5}, event_id="e5"))
    return log


class TestOcel2Export:
    """export_json writes the OCEL 2.0 JSON layout that PM4Py, ProM and other OCEL 2.0 readers load."""

    def _export(self, log: OCELLog, tmp_path) -> dict:
        import json

        path = tmp_path / "log.json"
        log.export_json(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def test_the_standard_top_level_layout(self, tmp_path):
        data = self._export(_run_log(), tmp_path)

        assert set(data) == {"objectTypes", "eventTypes", "objects", "events"}
        assert [t["name"] for t in data["objectTypes"]] == ["BenchmarkRun", "BenchmarkSession", "Config", "Element", "Model", "Relationship", "Repository"]
        assert all(t["attributes"] == [] for t in data["objectTypes"])

    def test_event_attributes_are_typed_scalars(self, tmp_path):
        import json

        data = self._export(_run_log(), tmp_path)
        types = {t["name"]: {a["name"]: a["type"] for a in t["attributes"]} for t in data["eventTypes"]}
        events = {e["id"]: e for e in data["events"]}

        assert types["LLMQuery"] == {"config_id": "string", "call_kind": "string", "cache_hit": "boolean", "tokens_in": "integer", "latency_ms": "float", "wait_ms": "float"}
        assert types["DeriveConfig"]["stats"] == "string"  # nested values are JSON text
        llm = {a["name"]: a["value"] for a in events["e3"]["attributes"]}
        assert "error_type" not in llm  # an empty value is left out
        assert llm["cache_hit"] is False
        derive = {a["name"]: a["value"] for a in events["e4"]["attributes"]}
        assert json.loads(derive["stats"]) == {"items_created": 2}

    def test_numbers_of_both_kinds_are_floats_and_mixed_values_strings(self, tmp_path):
        log = OCELLog()
        log.create_event("Step", {"Config": ["s"]}, duration_seconds=1, value=1)
        log.create_event("Step", {"Config": ["s"]}, duration_seconds=1.5, value="many")

        data = self._export(log, tmp_path)
        (step,) = data["eventTypes"]
        assert {a["name"]: a["type"] for a in step["attributes"]} == {"duration_seconds": "float", "value": "string"}
        values = [{a["name"]: a["value"] for a in e["attributes"]} for e in data["events"]]
        assert values == [{"duration_seconds": 1.0, "value": "1"}, {"duration_seconds": 1.5, "value": "many"}]

    def test_events_relate_objects_by_their_role(self, tmp_path):
        data = self._export(_run_log(), tmp_path)
        derive = next(e for e in data["events"] if e["id"] == "e4")

        assert derive["type"] == "DeriveConfig"
        assert datetime.fromisoformat(derive["time"]).tzinfo is not None  # times carry their offset
        assert {(r["objectId"], r["qualifier"]) for r in derive["relationships"]} == {
            ("bench_1", "session"),
            ("bench_1:repo:m:1", "run"),
            ("repo", "repository"),
            ("m", "model"),
            ("ApplicationComponent", "step"),
            ("ac_a", "element"),
            ("ac_b", "element"),
            ("Serving_ac_a_ac_b", "relationship"),
        }

    def test_every_related_object_exists_and_runs_name_their_context(self, tmp_path):
        data = self._export(_run_log(), tmp_path)
        objects = {o["id"]: o for o in data["objects"]}

        assert all(r["objectId"] in objects for e in data["events"] for r in e["relationships"])
        assert objects["ac_a"]["type"] == "Element"
        run = objects["bench_1:repo:m:1"]
        assert {(r["objectId"], r["qualifier"]) for r in run["relationships"]} == {("bench_1", "session"), ("repo", "repository"), ("m", "model")}

    def test_an_id_of_two_types_stays_unique(self, tmp_path):
        log = OCELLog()
        log.create_event("Step", {"Repository": ["shared"], "Config": ["shared"]})

        data = self._export(log, tmp_path)

        assert sorted((o["id"], o["type"]) for o in data["objects"]) == [("Config:shared", "Config"), ("shared", "Repository")]
        assert {r["objectId"] for r in data["events"][0]["relationships"]} == {"shared", "Config:shared"}

    def test_reads_back_its_own_events(self, tmp_path):
        path = tmp_path / "log.json"
        original = _run_log()
        original.export_json(path)

        loaded = OCELLog.from_json(path)

        assert [(e.event_id, e.activity) for e in loaded.events] == [(e.event_id, e.activity) for e in original.events]
        derive = loaded.events[4]
        assert sorted(derive.objects["Element"]) == ["ac_a", "ac_b"]
        assert derive.attributes["duration_seconds"] == 12.0
        assert loaded.events[3].timestamp == original.events[3].timestamp.astimezone()

    def test_still_reads_the_ocel_1_layout_of_older_sessions(self, tmp_path):
        import json

        path = tmp_path / "old.json"
        old = {
            "ocel:events": [
                {"ocel:eid": "x", "ocel:activity": "StartRun", "ocel:timestamp": "2026-01-01T10:00:00", "ocel:typedOmap": {"BenchmarkRun": ["r1"]}, "ocel:vmap": {"iteration": 1}}
            ]
        }
        path.write_text(json.dumps(old), encoding="utf-8")

        (event,) = OCELLog.from_json(path).events

        assert (event.activity, event.objects, event.attributes) == ("StartRun", {"BenchmarkRun": ["r1"]}, {"iteration": 1})

    def test_the_session_loader_prefers_the_lossless_stream(self, tmp_path):
        """The JSONL stream keeps nested attributes (run stats); the OCEL 2.0 file holds them as text."""
        from deriva.common.ocel import load_benchmark_ocel

        log = _run_log()
        folder = tmp_path / "bench_1" / "ocel"
        log.export_json(folder / "benchmark_events.json")
        log.export_jsonl(folder / "benchmark_events.jsonl")

        loaded = load_benchmark_ocel(tmp_path, "bench_1")

        assert loaded.events[4].attributes["stats"] == {"items_created": 2}


class TestCaseLog:
    """A flat event log per run (case = run) for Disco and other case-centric tools, as CSV and XES."""

    def test_one_case_per_run_with_readable_activities(self):
        rows = _run_log().case_events()

        assert [(r["case_id"], r["activity"]) for r in rows] == [
            ("bench_1:extraction:repo", "Ensure extraction"),
            ("bench_1:repo:m:1", "Start run"),
            ("bench_1:repo:m:1", "LLM · ApplicationComponent · naming"),
            ("bench_1:repo:m:1", "Derive · ApplicationComponent"),
            ("bench_1:repo:m:1", "Complete run"),
        ]  # session events (StartBenchmark) belong to no run

    def test_rows_carry_time_span_resource_and_attributes(self):
        rows = {r["activity"]: r for r in _run_log().case_events()}

        llm = rows["LLM · ApplicationComponent · naming"]
        assert llm["resource"] == "m"
        assert (llm["timestamp"] - llm["start_timestamp"]).total_seconds() == 2.0  # latency + rate-limit wait
        assert llm["cache_hit"] is False and llm["tokens_in"] == 12
        derive = rows["Derive · ApplicationComponent"]
        assert (derive["timestamp"] - derive["start_timestamp"]).total_seconds() == 12
        assert (derive["session"], derive["repository"]) == ("bench_1", "repo")
        assert rows["Start run"]["start_timestamp"] == rows["Start run"]["timestamp"]

    def test_csv(self, tmp_path):
        import csv

        path = tmp_path / "cases.csv"
        _run_log().export_case_csv(path)

        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert (reader.fieldnames or [])[:7] == ["case_id", "activity", "timestamp", "start_timestamp", "resource", "session", "repository"]
        assert [r["activity"] for r in rows][-1] == "Complete run"
        assert rows[2]["cache_hit"] == "false" and rows[2]["latency_ms"] == "1500.0"
        assert datetime.fromisoformat(rows[2]["timestamp"]).tzinfo is not None

    def test_xes(self, tmp_path):
        import xml.etree.ElementTree as ET

        path = tmp_path / "cases.xes"
        _run_log().export_case_xes(path)

        ns = {"x": "http://www.xes-standard.org/"}
        root = ET.parse(path).getroot()
        traces = root.findall("x:trace", ns)
        names = [t.find("x:string[@key='concept:name']", ns) for t in traces]
        assert [n.get("value") for n in names if n is not None] == ["bench_1:extraction:repo", "bench_1:repo:m:1"]
        llm = traces[1].findall("x:event", ns)[1]

        def value(tag: str, key: str) -> str | None:
            found = llm.find(f"x:{tag}[@key='{key}']", ns)
            return None if found is None else found.get("value")

        assert value("string", "concept:name") == "LLM · ApplicationComponent · naming"
        assert value("string", "org:resource") == "m"
        assert value("date", "time:timestamp") is not None
        assert value("boolean", "cache_hit") == "false"
        assert value("int", "tokens_in") == "12"
        assert value("float", "latency_ms") == "1500.0"
