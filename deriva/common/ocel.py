"""
OCEL 2.0 (Object-Centric Event Log) module for process mining and traceability.

This module provides OCEL 2.0 compliant event logging for the Deriva pipeline,
enabling multi-object event correlation and process mining analysis.

OCEL 2.0 Specification: https://www.ocel-standard.org/

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

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

__all__ = [
    "OCELEvent",
    "InconsistencyInfo",
    "OCELLog",
    "hash_content",
    "create_run_id",
    "create_edge_id",
    "parse_run_id",
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

    def to_ocel_dict(self) -> dict[str, Any]:
        """Convert to OCEL 2.0 JSON format."""
        return {
            "ocel:eid": self.event_id,
            "ocel:activity": self.activity,
            "ocel:timestamp": self.timestamp.isoformat(),
            "ocel:omap": self._flatten_objects(),
            "ocel:vmap": self.attributes,
            "ocel:typedOmap": self.objects,
        }

    def to_jsonl_dict(self) -> dict[str, Any]:
        """Convert to compact JSONL format for streaming."""
        return {
            "eid": self.event_id,
            "activity": self.activity,
            "timestamp": self.timestamp.isoformat(),
            "objects": self.objects,
            "attributes": self.attributes,
        }

    def _flatten_objects(self) -> list[str]:
        """Flatten objects for OCEL 1.0 compatibility."""
        return [oid for oids in self.objects.values() for oid in oids]

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
        """Export to OCEL 2.0 JSON format."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        ocel_data = {
            "ocel:global-log": {
                "ocel:version": "2.0",
                "ocel:ordering": "timestamp",
                "ocel:object-types": sorted(self.object_types),
                "ocel:attribute-names": self._collect_attribute_names(),
                "ocel:events": len(self.events),
            },
            "ocel:events": [e.to_ocel_dict() for e in self.events],
            "ocel:objects": self._collect_objects(),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(ocel_data, f, indent=2, ensure_ascii=False)

    def export_jsonl(self, path: str | Path) -> None:
        """Export to line-delimited JSON for streaming."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for event in self.events:
                f.write(json.dumps(event.to_jsonl_dict(), ensure_ascii=False) + "\n")

    def _collect_attribute_names(self) -> list[str]:
        """Collect all attribute names used across events."""
        attrs: set[str] = set()
        for event in self.events:
            attrs.update(event.attributes.keys())
        return sorted(attrs)

    def _collect_objects(self) -> dict[str, dict[str, Any]]:
        """Collect all objects with their types for OCEL 2.0 format."""
        objects: dict[str, dict[str, Any]] = {}
        for event in self.events:
            for obj_type, obj_ids in event.objects.items():
                for obj_id in obj_ids:
                    if obj_id not in objects:
                        objects[obj_id] = {"ocel:type": obj_type}
        return objects

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_events_for_object(
        self, object_type: str, object_id: str
    ) -> list[OCELEvent]:
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
        consistent_count = sum(
            1 for obj in all_objects if all(obj in objs for objs in by_run.values())
        )

        return consistent_count / len(all_objects)

    def compare_runs(
        self, run_id_1: str, run_id_2: str, object_type: str
    ) -> dict[str, Any]:
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
        """Load OCEL log from JSON file."""
        path = Path(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        log = cls()
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
