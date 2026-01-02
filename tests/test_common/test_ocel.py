"""Tests for common.ocel module."""

from __future__ import annotations

import json
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

    def test_to_ocel_dict(self):
        """Should convert to OCEL 2.0 JSON format."""
        event = OCELEvent(
            activity="ExtractNode",
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            objects={"File": ["file_1"]},
            attributes={"tokens": 100},
            event_id="evt_12345",
        )

        ocel_dict = event.to_ocel_dict()

        assert ocel_dict["ocel:eid"] == "evt_12345"
        assert ocel_dict["ocel:activity"] == "ExtractNode"
        assert "2024-01-15" in ocel_dict["ocel:timestamp"]
        assert ocel_dict["ocel:vmap"]["tokens"] == 100
        assert ocel_dict["ocel:typedOmap"]["File"] == ["file_1"]

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

    def test_flatten_objects(self):
        """Should flatten objects for OCEL 1.0 compatibility."""
        event = OCELEvent(
            activity="Test",
            timestamp=datetime.now(),
            objects={"File": ["f1", "f2"], "Node": ["n1"]},
        )

        ocel_dict = event.to_ocel_dict()
        flat = ocel_dict["ocel:omap"]

        assert "f1" in flat
        assert "f2" in flat
        assert "n1" in flat
        assert len(flat) == 3

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
