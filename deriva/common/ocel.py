"""
OCEL 2.0 (Object-Centric Event Log) module for process mining and traceability.

This module provides OCEL 2.0 compliant event logging for the Deriva pipeline,
enabling multi-object event correlation and process mining analysis.

OCEL 2.0 Specification: https://www.ocel-standard.org/

Outputs:
- ``export_jsonl``: the lossless stream Deriva reads back (nested attributes kept)
- ``export_json``: the standard OCEL 2.0 JSON layout for PM4Py, ProM and other OCEL 2.0 tools
- ``export_case_csv`` / ``export_case_xes``: a flat log with one case per run, for Disco and
  other case-centric tools

Object Types used in Deriva:
- BenchmarkSession: Overall benchmark session
- BenchmarkRun: Single execution (repo × model × iteration)
- Repository: Source repository
- Model: LLM model identifier
- File: Source file being processed
- GraphNode: Extracted node (BusinessConcept, etc.)
- Element: Derived ArchiMate element
- Edge: Extracted graph edge (CONTAINS, DEPENDS_ON, etc.)
- Relationship: Derived ArchiMate relationship (Serving, Aggregation, etc.)

Event Types:
- StartBenchmark, CompleteBenchmark: Session lifecycle
- StartRun, CompleteRun: Individual run lifecycle
- ClassifyFile: File classification events
- ExtractNode: Node extraction with LLM metadata
- DeriveElement: ArchiMate element derivation
- ValidateElement: Validation events
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

__all__ = [
    "OCELEvent",
    "InconsistencyInfo",
    "OCELLog",
    "hash_content",
    "create_run_id",
    "create_edge_id",
    "parse_run_id",
    "load_benchmark_ocel",
]


@dataclass
class OCELEvent:
    """
    OCEL 2.0 compliant event.

    Each event has:
    - An activity name (what happened)
    - A timestamp (when it happened)
    - Related objects grouped by type (what was involved)
    - Attributes (metadata about the event)
    """

    activity: str
    timestamp: datetime
    objects: dict[str, list[str]]  # object_type -> [object_ids]
    attributes: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])

    def to_jsonl_dict(self) -> dict[str, Any]:
        """Convert to compact JSONL format for streaming."""
        return {
            "eid": self.event_id,
            "activity": self.activity,
            "timestamp": self.timestamp.isoformat(),
            "objects": self.objects,
            "attributes": self.attributes,
        }

    def has_object(self, object_type: str, object_id: str) -> bool:
        """Check if event relates to a specific object."""
        return object_id in self.objects.get(object_type, [])

    def has_object_type(self, object_type: str) -> bool:
        """Check if event relates to any object of a type."""
        return object_type in self.objects and len(self.objects[object_type]) > 0


@dataclass
class InconsistencyInfo:
    """Information about an inconsistent object across runs."""

    object_id: str
    object_type: str
    present_in: list[str]  # Run IDs where object appears
    missing_from: list[str]  # Run IDs where object is missing
    total_runs: int

    @property
    def consistency_score(self) -> float:
        """Fraction of runs where object appears (0.0 to 1.0)."""
        return len(self.present_in) / self.total_runs if self.total_runs > 0 else 0.0


@dataclass
class OCELLog:
    """
    OCEL 2.0 event log with analysis capabilities.

    Collects events and provides methods for:
    - Export to OCEL 2.0 JSON and JSONL formats
    - Object lifecycle queries
    - Consistency analysis across runs
    """

    events: list[OCELEvent] = field(default_factory=list)
    object_types: set[str] = field(default_factory=set)
    _object_index: dict[str, list[int]] = field(default_factory=dict, repr=False)
    _last_exported_index: int = field(default=0, repr=False)  # Track incremental exports

    def add_event(self, event: OCELEvent) -> None:
        """Add an event to the log and update indices."""
        event_idx = len(self.events)
        self.events.append(event)

        # Update object type registry
        self.object_types.update(event.objects.keys())

        # Update object index for fast lookups
        for obj_type, obj_ids in event.objects.items():
            for obj_id in obj_ids:
                key = f"{obj_type}:{obj_id}"
                if key not in self._object_index:
                    self._object_index[key] = []
                self._object_index[key].append(event_idx)

    def create_event(
        self,
        activity: str,
        objects: dict[str, list[str]],
        **attributes: Any,
    ) -> OCELEvent:
        """Create and add an event in one step."""
        event = OCELEvent(
            activity=activity,
            timestamp=datetime.now(),
            objects=objects,
            attributes=attributes,
        )
        self.add_event(event)
        return event

    # =========================================================================
    # EXPORT METHODS
    # =========================================================================

    def export_json(self, path: str | Path) -> None:
        """Export to the OCEL 2.0 JSON layout (see ``to_ocel2``)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_ocel2(), f, indent=2, ensure_ascii=False)

    def to_ocel2(self) -> dict[str, Any]:
        """The log in the OCEL 2.0 JSON layout: object types, event types, objects, events.

        Events relate their objects with a qualifier naming the object's role (``QUALIFIERS``);
        a run object relates its session, repository and model. Attributes are typed scalars:
        nested values become JSON text, empty ones are left out. Object ids stay as logged; an
        id that a second object type also uses becomes ``type:id`` for that type.
        """
        keys = self._ocel2_ids()
        attribute_types = _attribute_types(self.events)

        run_context: dict[str, list[dict[str, str]]] = {}
        for event in self.events:
            runs = [run for run in event.objects.get("BenchmarkRun", []) if run]
            if len(runs) == 1:
                context = run_context.setdefault(keys["BenchmarkRun", runs[0]], [])
                for relationship in _relationships(event, keys, _RUN_CONTEXT):
                    if relationship not in context:
                        context.append(relationship)

        events = [
            {
                "id": event.event_id,
                "type": event.activity,
                "time": _aware(event.timestamp).isoformat(),
                "attributes": [
                    {"name": name, "value": _ocel2_value(value, attribute_types[event.activity][name])} for name, value in event.attributes.items() if value is not None
                ],
                "relationships": _relationships(event, keys, tuple(event.objects)),
            }
            for event in self.events
        ]

        return {
            "objectTypes": [{"name": name, "attributes": []} for name in sorted({object_type for object_type, _ in keys})],
            "eventTypes": [
                {"name": activity, "attributes": [{"name": name, "type": kind} for name, kind in attribute_types.get(activity, {}).items()]}
                for activity in sorted({event.activity for event in self.events})
            ],
            "objects": [{"id": key, "type": object_type, "attributes": [], "relationships": run_context.get(key, [])} for (object_type, _), key in keys.items()],
            "events": events,
        }

    def _ocel2_ids(self) -> dict[tuple[str, str], str]:
        """The OCEL 2.0 id of every logged (type, id), in order of first appearance."""
        owner: dict[str, str] = {}  # id -> the first type that used it
        keys: dict[tuple[str, str], str] = {}
        used: set[str] = set()
        for event in self.events:
            for object_type, object_ids in event.objects.items():
                for object_id in object_ids:
                    if object_id and (object_type, object_id) not in keys:
                        key = object_id if owner.setdefault(object_id, object_type) == object_type else f"{object_type}:{object_id}"
                        while key in used:  # an id that already looks like a prefixed one
                            key = f"{object_type}:{key}"
                        used.add(key)
                        keys[object_type, object_id] = key
        return keys

    def case_events(self) -> list[dict[str, Any]]:
        """The log flattened to one case per run, ordered by case start, then time.

        Each row has ``case_id`` (the run; a repository's extraction for ``EnsureExtraction``),
        a readable ``activity`` (``Derive · <step>``, ``LLM · <step> · <call kind>``),
        ``timestamp`` and ``start_timestamp`` (steps and calls span their own duration; other
        events are instants), ``resource`` (the model), ``session``, ``repository`` and the
        event's attributes. Session events (start and end of a benchmark) belong to no run.
        """
        rows: list[dict[str, Any]] = []
        for event in self.events:
            cases = [run for run in event.objects.get("BenchmarkRun", []) if run]
            if not cases and event.activity == "EnsureExtraction":
                cases = [f"{session}:extraction:{repo}" for session in event.objects.get("BenchmarkSession", []) for repo in event.objects.get("Repository", [])]
            end = _aware(event.timestamp)
            for case_id in cases:
                session, repository = _run_context(case_id)
                rows.append(
                    {
                        **event.attributes,
                        "case_id": case_id,
                        "activity": _case_activity(event),
                        "timestamp": end,
                        "start_timestamp": end - timedelta(seconds=_span_seconds(event)),
                        "resource": ",".join(event.objects.get("Model", [])),
                        "session": ",".join(event.objects.get("BenchmarkSession", [])) or session,
                        "repository": ",".join(event.objects.get("Repository", [])) or repository,
                    }
                )
        case_start: dict[str, datetime] = {}
        for row in rows:
            case_start[row["case_id"]] = min(case_start.get(row["case_id"], row["timestamp"]), row["timestamp"])
        return sorted(rows, key=lambda row: (case_start[row["case_id"]], row["case_id"], row["timestamp"]))

    def export_case_csv(self, path: str | Path) -> None:
        """Export the case log (``case_events``) as CSV: the fixed columns, then every attribute."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.case_events()
        attributes = sorted({name for row in rows for name in row} - set(CASE_COLUMNS))

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[*CASE_COLUMNS, *attributes])
            writer.writeheader()
            for row in rows:
                writer.writerow({name: _csv_value(value) for name, value in row.items()})

    def export_case_xes(self, path: str | Path) -> None:
        """Export the case log (``case_events``) as XES 1.0: one trace per run, typed attributes."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        root = ET.Element("log", {"xes.version": "1.0", "xes.features": "nested-attributes", "xmlns": XES_NAMESPACE})
        for name, prefix in (("Concept", "concept"), ("Time", "time"), ("Organizational", "org"), ("Lifecycle", "lifecycle")):
            ET.SubElement(root, "extension", {"name": name, "prefix": prefix, "uri": f"http://www.xes-standard.org/{prefix}.xesext"})
        ET.SubElement(root, "classifier", {"name": "Activity", "keys": "concept:name"})

        traces: dict[str, ET.Element] = {}
        for row in self.case_events():
            trace = traces.get(row["case_id"])
            if trace is None:
                trace = traces[row["case_id"]] = ET.SubElement(root, "trace")
                _xes_attribute(trace, "concept:name", row["case_id"])
            event = ET.SubElement(trace, "event")
            _xes_attribute(event, "concept:name", row["activity"])
            _xes_attribute(event, "lifecycle:transition", "complete")
            _xes_attribute(event, "time:timestamp", row["timestamp"])
            if row["resource"]:
                _xes_attribute(event, "org:resource", row["resource"])
            for name, value in row.items():
                if name not in _XES_MAPPED and value is not None:
                    _xes_attribute(event, name, value)

        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def export_jsonl(self, path: str | Path) -> None:
        """Export to line-delimited JSON for streaming."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event.to_jsonl_dict(), ensure_ascii=False) + "\n")

    def export_jsonl_incremental(self, path: str | Path) -> int:
        """
        Export only NEW events since last incremental export.

        Appends to existing file, tracks last exported index.
        Use this for incremental persistence during benchmark runs.

        Args:
            path: Path to JSONL file (will append if exists)

        Returns:
            Number of new events exported
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        new_events = self.events[self._last_exported_index :]
        if not new_events:
            return 0

        # Append mode for incremental writes
        with open(path, "a", encoding="utf-8") as f:
            for event in new_events:
                f.write(json.dumps(event.to_jsonl_dict(), ensure_ascii=False) + "\n")

        exported_count = len(new_events)
        self._last_exported_index = len(self.events)
        return exported_count

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_events_for_object(self, object_type: str, object_id: str) -> list[OCELEvent]:
        """Get all events related to a specific object."""
        key = f"{object_type}:{object_id}"
        indices = self._object_index.get(key, [])
        return [self.events[i] for i in indices]

    def get_events_by_activity(self, activity: str) -> list[OCELEvent]:
        """Get all events with a specific activity."""
        return [e for e in self.events if e.activity == activity]

    def get_events_by_activity_prefix(self, prefix: str) -> list[OCELEvent]:
        """Get all events with activity starting with prefix (e.g., 'Extract:')."""
        return [e for e in self.events if e.activity.startswith(prefix)]

    def get_all_objects(self, object_type: str) -> set[str]:
        """Get all object IDs of a specific type."""
        objects: set[str] = set()
        for event in self.events:
            if object_type in event.objects:
                objects.update(event.objects[object_type])
        return objects

    def get_objects_by_run(self, object_type: str) -> dict[str, set[str]]:
        """
        Get objects grouped by run ID.

        Returns:
            Dict mapping run_id -> set of object_ids
        """
        result: dict[str, set[str]] = {}

        for event in self.events:
            runs = event.objects.get("BenchmarkRun", [])
            objects = event.objects.get(object_type, [])

            for run_id in runs:
                if run_id not in result:
                    result[run_id] = set()
                result[run_id].update(objects)

        return result

    def get_objects_by_model(self, object_type: str) -> dict[str, set[str]]:
        """
        Get objects grouped by model ID.

        Returns:
            Dict mapping model_id -> set of object_ids
        """
        result: dict[str, set[str]] = {}

        for event in self.events:
            models = event.objects.get("Model", [])
            objects = event.objects.get(object_type, [])

            for model_id in models:
                if model_id not in result:
                    result[model_id] = set()
                result[model_id].update(objects)

        return result

    # =========================================================================
    # CONSISTENCY ANALYSIS
    # =========================================================================

    def find_inconsistencies(self, object_type: str) -> dict[str, InconsistencyInfo]:
        """
        Find objects that appear in some runs but not others.

        Args:
            object_type: The type of object to analyze (e.g., "Element", "GraphNode")

        Returns:
            Dict mapping object_id -> InconsistencyInfo for inconsistent objects
        """
        by_run = self.get_objects_by_run(object_type)

        if len(by_run) < 2:
            return {}

        all_runs = list(by_run.keys())
        all_objects = set.union(*by_run.values()) if by_run else set()
        inconsistent: dict[str, InconsistencyInfo] = {}

        for obj_id in all_objects:
            present_in = [run for run, objs in by_run.items() if obj_id in objs]
            missing_from = [run for run in all_runs if run not in present_in]

            # Object is inconsistent if not in all runs
            if len(present_in) != len(all_runs):
                inconsistent[obj_id] = InconsistencyInfo(
                    object_id=obj_id,
                    object_type=object_type,
                    present_in=present_in,
                    missing_from=missing_from,
                    total_runs=len(all_runs),
                )

        return inconsistent

    def compute_consistency_score(self, object_type: str) -> float:
        """
        Compute overall consistency score for an object type.

        Returns:
            Float between 0.0 and 1.0, where 1.0 means all objects
            appear in all runs.
        """
        by_run = self.get_objects_by_run(object_type)

        if len(by_run) < 2:
            return 1.0

        all_objects = set.union(*by_run.values()) if by_run else set()
        if not all_objects:
            return 1.0

        # Count objects that appear in ALL runs
        consistent_count = sum(1 for obj in all_objects if all(obj in objs for objs in by_run.values()))

        return consistent_count / len(all_objects)

    def compare_runs(self, run_id_1: str, run_id_2: str, object_type: str) -> dict[str, Any]:
        """
        Compare two runs for a specific object type.

        Returns:
            Dict with overlap, only_in_1, only_in_2, jaccard_similarity
        """
        by_run = self.get_objects_by_run(object_type)
        objects_1 = by_run.get(run_id_1, set())
        objects_2 = by_run.get(run_id_2, set())

        overlap = objects_1 & objects_2
        only_in_1 = objects_1 - objects_2
        only_in_2 = objects_2 - objects_1
        union = objects_1 | objects_2

        jaccard = len(overlap) / len(union) if union else 1.0

        return {
            "run_1": run_id_1,
            "run_2": run_id_2,
            "object_type": object_type,
            "overlap": sorted(overlap),
            "only_in_1": sorted(only_in_1),
            "only_in_2": sorted(only_in_2),
            "jaccard_similarity": jaccard,
            "count_1": len(objects_1),
            "count_2": len(objects_2),
            "overlap_count": len(overlap),
        }

    # =========================================================================
    # LOADING
    # =========================================================================

    @classmethod
    def from_json(cls, path: str | Path) -> OCELLog:
        """Load an OCEL log from JSON: the OCEL 2.0 layout, or the OCEL 1.0-style layout of older sessions.

        From OCEL 2.0, nested attributes come back as the JSON text they were written as.
        """
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        log = cls()
        if "eventTypes" in data or "objectTypes" in data:
            type_of = {obj["id"]: obj["type"] for obj in data.get("objects", [])}
            for event_data in data.get("events", []):
                objects: dict[str, list[str]] = {}
                for relationship in event_data.get("relationships", []):
                    objects.setdefault(type_of.get(relationship["objectId"], "Object"), []).append(relationship["objectId"])
                log.add_event(
                    OCELEvent(
                        event_id=event_data["id"],
                        activity=event_data["type"],
                        timestamp=datetime.fromisoformat(event_data["time"]),
                        objects=objects,
                        attributes={attribute["name"]: attribute["value"] for attribute in event_data.get("attributes", [])},
                    )
                )
            return log

        for event_data in data.get("ocel:events", []):
            event = OCELEvent(
                event_id=event_data.get("ocel:eid", str(uuid.uuid4())[:12]),
                activity=event_data["ocel:activity"],
                timestamp=datetime.fromisoformat(event_data["ocel:timestamp"]),
                objects=event_data.get("ocel:typedOmap", {}),
                attributes=event_data.get("ocel:vmap", {}),
            )
            log.add_event(event)

        return log

    @classmethod
    def from_jsonl(cls, path: str | Path) -> OCELLog:
        """Load OCEL log from JSONL file."""
        path = Path(path)
        log = cls()

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                data = json.loads(line)
                event = OCELEvent(
                    event_id=data.get("eid", str(uuid.uuid4())[:12]),
                    activity=data["activity"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    objects=data.get("objects", {}),
                    attributes=data.get("attributes", {}),
                )
                log.add_event(event)

        return log


# =============================================================================
# OCEL 2.0 AND CASE LOG HELPERS
# =============================================================================

# The role of an object in an event (the OCEL 2.0 qualifier), by object type
QUALIFIERS = {
    "BenchmarkSession": "session",
    "BenchmarkRun": "run",
    "Repository": "repository",
    "Model": "model",
    "Config": "step",
    "GraphNode": "node",
    "Edge": "edge",
    "Element": "element",
    "Relationship": "relationship",
}

# The objects a run object relates to (OCEL 2.0 object-to-object relationships)
_RUN_CONTEXT = ("BenchmarkSession", "Repository", "Model")

# The case log's fixed columns, before the event attributes
CASE_COLUMNS = ("case_id", "activity", "timestamp", "start_timestamp", "resource", "session", "repository")

XES_NAMESPACE = "http://www.xes-standard.org/"

# Case log columns written as standard XES keys (or as the trace name) instead of plain attributes
_XES_MAPPED = frozenset({"case_id", "activity", "timestamp", "resource"})

# Readable case log activities: lifecycle events by name, steps and calls with their step
_CASE_ACTIVITIES = {"StartRun": "Start run", "CompleteRun": "Complete run", "DeriveElements": "Derive elements", "EnsureExtraction": "Ensure extraction"}
_STEP_ACTIVITIES = {"ExtractConfig": "Extract", "DeriveConfig": "Derive"}

# Events whose duration is their own work (lifecycle events such as a completed run are instants)
_SPANNED = frozenset({"ExtractConfig", "DeriveConfig", "LLMQuery", "EnsureExtraction"})


def _relationships(event: OCELEvent, keys: dict[tuple[str, str], str], object_types: tuple[str, ...]) -> list[dict[str, str]]:
    """The event's objects of the given types as OCEL 2.0 relationships (object id and role), without repeats."""
    relationships: list[dict[str, str]] = []
    for object_type in object_types:
        for object_id in event.objects.get(object_type, []):
            relationship = {"objectId": keys[object_type, object_id], "qualifier": QUALIFIERS.get(object_type, object_type.lower())} if object_id else None
            if relationship and relationship not in relationships:
                relationships.append(relationship)
    return relationships


def _aware(timestamp: datetime) -> datetime:
    """The timestamp with its UTC offset (events are logged in local time)."""
    return timestamp if timestamp.tzinfo else timestamp.astimezone()


def _ocel2_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _attribute_types(events: list[OCELEvent]) -> dict[str, dict[str, str]]:
    """Per activity, the OCEL 2.0 type of each attribute (integers with floats are float, other mixes string)."""
    seen: dict[str, dict[str, set[str]]] = {}
    for event in events:
        for name, value in event.attributes.items():
            if value is not None:
                seen.setdefault(event.activity, {}).setdefault(name, set()).add(_ocel2_type(value))
    return {
        activity: {name: next(iter(kinds)) if len(kinds) == 1 else "float" if kinds == {"integer", "float"} else "string" for name, kinds in attributes.items()}
        for activity, attributes in seen.items()
    }


def _ocel2_value(value: Any, kind: str) -> Any:
    if kind == "float":
        return float(value)
    if kind == "string" and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _run_context(case_id: str) -> tuple[str, str]:
    """Session and repository named by a run id (``session:repo:model:i``, ``session:extraction:repo``)."""
    parts = case_id.split(":")
    if len(parts) == 3 and parts[1] == "extraction":
        return parts[0], parts[2]
    return parts[0], parts[1] if len(parts) >= 4 else ""


def _case_activity(event: OCELEvent) -> str:
    step = event.attributes.get("config_id") or next(iter(event.objects.get("Config", [])), None)
    if event.activity in _STEP_ACTIVITIES:
        return " · ".join(part for part in (_STEP_ACTIVITIES[event.activity], step) if part)
    if event.activity == "LLMQuery":
        return " · ".join(str(part) for part in ("LLM", step, event.attributes.get("call_kind")) if part)
    return _CASE_ACTIVITIES.get(event.activity, event.activity)


def _number(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _span_seconds(event: OCELEvent) -> float:
    """How long the event's own work took: its duration, or an LLM call's latency and rate-limit wait."""
    if event.activity not in _SPANNED:
        return 0.0
    attributes = event.attributes
    if "duration_seconds" in attributes:
        return _number(attributes["duration_seconds"])
    return (_number(attributes.get("latency_ms")) + _number(attributes.get("wait_ms"))) / 1000


def _csv_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, default=str)
    return "" if value is None else value


def _xes_attribute(parent: ET.Element, key: str, value: Any) -> None:
    if isinstance(value, bool):
        tag, text = "boolean", "true" if value else "false"
    elif isinstance(value, int):
        tag, text = "int", str(value)
    elif isinstance(value, float):
        tag, text = "float", repr(value)
    elif isinstance(value, datetime):
        tag, text = "date", value.isoformat()
    elif isinstance(value, dict | list):
        tag, text = "string", json.dumps(value, ensure_ascii=False, default=str)
    else:
        tag, text = "string", str(value)
    ET.SubElement(parent, tag, {"key": key, "value": text})


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def hash_content(content: str) -> str:
    """Generate a short hash of content for response comparison."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def create_run_id(session_id: str, repo: str, model: str, iteration: int) -> str:
    """Create a standardized run ID."""
    return f"{session_id}:{repo}:{model}:{iteration}"


def create_edge_id(source_id: str, relationship_type: str, target_id: str) -> str:
    """
    Create a unique edge/relationship identifier using triple hash.

    Format: {relationship_type}_{source_id}_{target_id}

    Used for comparing edges (extraction) and relationships (derivation)
    across benchmark runs.

    Args:
        source_id: Source node/element identifier
        relationship_type: Edge type (CONTAINS, DEPENDS_ON) or relationship type (Serving, Aggregation)
        target_id: Target node/element identifier

    Returns:
        Unique identifier string for the edge/relationship
    """
    return f"{relationship_type}_{source_id}_{target_id}"


def parse_run_id(run_id: str) -> dict[str, str | int]:
    """Parse a run ID into components."""
    parts = run_id.split(":")
    if len(parts) >= 4:
        return {
            "session_id": parts[0],
            "repository": parts[1],
            "model": parts[2],
            "iteration": int(parts[3]),
        }
    return {"run_id": run_id}


def load_benchmark_ocel(benchmarks_dir: Path | str, session_id: str) -> OCELLog:
    """Load a benchmark session's event log.

    Looks for ``ocel/benchmark_events.jsonl`` (the lossless stream), then the session's
    ``ocel/benchmark_events.json`` (OCEL 2.0, or the OCEL 1.0-style layout of older
    sessions), then the legacy ``events.ocel.json`` / ``events.jsonl`` in the session root.
    Empty log if none exist.
    """
    session_dir = Path(benchmarks_dir) / session_id
    for path in (
        session_dir / "ocel" / "benchmark_events.jsonl",
        session_dir / "ocel" / "benchmark_events.json",
        session_dir / "events.ocel.json",
        session_dir / "events.jsonl",
    ):
        if path.exists():
            return OCELLog.from_jsonl(path) if path.suffix == ".jsonl" else OCELLog.from_json(path)
    return OCELLog()
