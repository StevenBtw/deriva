"""
Config-deviation analysis service for Deriva benchmarks.

Orchestrates loading of OCEL data and database queries,
delegating pure analysis logic to modules/analysis.

Usage:
    analyzer = ConfigDeviationAnalyzer(session_id, engine)
    report = analyzer.analyze()
    analyzer.export_json("deviations.json")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from deriva.common.ocel import OCELLog, parse_run_id
from deriva.modules.analysis import (
    ConfigDeviation,
    DeviationReport,
    analyze_from_object_types,
    build_deviation_report,
    extract_element_type,
    extract_node_type,
    generate_recommendations,
)
from deriva.modules.analysis import (
    analyze_config_deviations as analyze_deviations_pure,
)

__all__ = [
    "ConfigDeviationAnalyzer",
    "analyze_config_deviations",
    "export_config_deviations",
]


class ConfigDeviationAnalyzer:
    """
    Analyzes benchmark results to identify which configs cause deviations.

    Handles I/O (OCEL loading, database queries, JSON export) and
    delegates pure analysis to modules/analysis.
    """

    def __init__(self, session_id: str, engine: Any):
        """
        Initialize analyzer for a benchmark session.

        Args:
            session_id: Benchmark session ID
            engine: DuckDB connection
        """
        self.session_id = session_id
        self.engine = engine
        self.ocel_log = self._load_ocel()
        self.runs = self._load_runs()

    # =========================================================================
    # I/O METHODS
    # =========================================================================

    def _load_ocel(self) -> OCELLog:
        """Load OCEL log from file."""
        ocel_path = Path("workspace/benchmarks") / self.session_id / "events.ocel.json"

        if ocel_path.exists():
            return OCELLog.from_json(ocel_path)

        jsonl_path = Path("workspace/benchmarks") / self.session_id / "events.jsonl"
        if jsonl_path.exists():
            return OCELLog.from_jsonl(jsonl_path)

        return OCELLog()

    def _load_runs(self) -> list[dict[str, Any]]:
        """Load benchmark runs from database."""
        rows = self.engine.execute(
            """
            SELECT run_id, repository, model_provider, model_name, iteration,
                   status, stats, started_at, completed_at
            FROM benchmark_runs
            WHERE session_id = ?
            ORDER BY started_at
            """,
            [self.session_id],
        ).fetchall()

        return [
            {
                "run_id": row[0],
                "repository": row[1],
                "model_provider": row[2],
                "model_name": row[3],
                "iteration": row[4],
                "status": row[5],
                "stats": json.loads(row[6]) if row[6] else {},
                "started_at": row[7],
                "completed_at": row[8],
            }
            for row in rows
        ]

    # =========================================================================
    # ANALYSIS (delegates to modules/analysis)
    # =========================================================================

    def analyze(self) -> DeviationReport:
        """
        Perform full deviation analysis.

        Returns:
            DeviationReport with per-config deviation statistics
        """
        config_deviations: list[ConfigDeviation] = []

        # Analyze extraction configs
        extraction_deviations = self._analyze_extraction_deviations()
        config_deviations.extend(extraction_deviations)

        # Analyze derivation configs
        derivation_deviations = self._analyze_derivation_deviations()
        config_deviations.extend(derivation_deviations)

        # Build report using pure function
        return build_deviation_report(
            session_id=self.session_id,
            analysis_timestamp=datetime.now().isoformat(),
            total_runs=len(self.runs),
            config_deviations=config_deviations,
        )

    def _analyze_extraction_deviations(self) -> list[ConfigDeviation]:
        """Analyze deviations from extraction configs."""
        # Try enriched ExtractConfig events first
        config_events = self.ocel_log.get_events_by_activity("ExtractConfig")
        if config_events:
            return analyze_deviations_pure(config_events, "extraction")

        # Fallback: infer from object ID prefixes
        nodes_by_run = self.ocel_log.get_objects_by_run("GraphNode")
        if len(nodes_by_run) < 2:
            return []

        return analyze_from_object_types(
            objects_by_run=nodes_by_run,
            config_type="extraction",
            type_extractor=extract_node_type,
        )

    def _analyze_derivation_deviations(self) -> list[ConfigDeviation]:
        """Analyze deviations from derivation configs."""
        # Try enriched DeriveConfig events first
        config_events = self.ocel_log.get_events_by_activity("DeriveConfig")
        if config_events:
            return analyze_deviations_pure(config_events, "derivation")

        # Fallback: infer from object ID prefixes
        elements_by_run = self.ocel_log.get_objects_by_run("Element")
        if len(elements_by_run) < 2:
            return []

        return analyze_from_object_types(
            objects_by_run=elements_by_run,
            config_type="derivation",
            type_extractor=extract_element_type,
        )

    # =========================================================================
    # DETAILED ANALYSIS
    # =========================================================================

    def get_deviation_details(self, config_id: str) -> dict[str, Any]:
        """
        Get detailed deviation info for a specific config.

        Args:
            config_id: The config identifier (node_type or step_name)

        Returns:
            Detailed deviation data including per-run breakdown
        """
        nodes_by_run = self.ocel_log.get_objects_by_run("GraphNode")
        elements_by_run = self.ocel_log.get_objects_by_run("Element")

        all_runs = list(nodes_by_run.keys()) or list(elements_by_run.keys())
        if not all_runs:
            return {"config_id": config_id, "error": "No runs found"}

        # Find objects for this config
        config_objects: set[str] = set()

        for node_id in set.union(*nodes_by_run.values()) if nodes_by_run else set():
            if extract_node_type(node_id) == config_id:
                config_objects.add(node_id)

        for element_id in set.union(*elements_by_run.values()) if elements_by_run else set():
            if extract_element_type(element_id) == config_id:
                config_objects.add(element_id)

        if not config_objects:
            return {"config_id": config_id, "error": "No objects found for config"}

        # Build per-object breakdown
        object_details = []
        objects_by_run = nodes_by_run if nodes_by_run else elements_by_run

        for obj_id in config_objects:
            present_in = []
            missing_from = []

            for run_id in all_runs:
                if obj_id in objects_by_run.get(run_id, set()):
                    present_in.append(run_id)
                else:
                    missing_from.append(run_id)

            present_parsed = [parse_run_id(r) for r in present_in]
            missing_parsed = [parse_run_id(r) for r in missing_from]

            object_details.append(
                {
                    "object_id": obj_id,
                    "present_in_count": len(present_in),
                    "missing_from_count": len(missing_from),
                    "consistency": len(present_in) / len(all_runs) if all_runs else 0,
                    "present_in_runs": present_parsed,
                    "missing_from_runs": missing_parsed,
                }
            )

        object_details.sort(key=lambda x: float(x["consistency"]))

        return {
            "config_id": config_id,
            "total_objects": len(config_objects),
            "total_runs": len(all_runs),
            "objects": object_details,
        }

    def compare_configs(self) -> dict[str, Any]:
        """Compare all configs to identify most/least stable."""
        report = self.analyze()

        extraction_configs = [c for c in report.config_deviations if c.config_type == "extraction"]
        derivation_configs = [c for c in report.config_deviations if c.config_type == "derivation"]

        most_stable = sorted(report.config_deviations, key=lambda x: x.consistency_score, reverse=True)
        least_stable = sorted(report.config_deviations, key=lambda x: x.consistency_score)

        return {
            "session_id": self.session_id,
            "summary": {
                "total_configs_analyzed": len(report.config_deviations),
                "extraction_configs": len(extraction_configs),
                "derivation_configs": len(derivation_configs),
                "overall_consistency": report.overall_consistency,
            },
            "most_stable": [
                {
                    "config_id": c.config_id,
                    "type": c.config_type,
                    "consistency": c.consistency_score,
                }
                for c in most_stable[:5]
            ],
            "least_stable": [
                {
                    "config_id": c.config_id,
                    "type": c.config_type,
                    "consistency": c.consistency_score,
                }
                for c in least_stable[:5]
            ],
            "recommendations": generate_recommendations(report.config_deviations),
        }

    # =========================================================================
    # EXPORT
    # =========================================================================

    def export_json(self, path: str | Path | None = None) -> str:
        """
        Export deviation report to JSON (sorted by deviation_count desc).

        Args:
            path: Output path (default: workspace/benchmarks/{session}/config_deviations.json)

        Returns:
            Path to exported file
        """
        report = self.analyze()

        if path is None:
            output_dir = Path("workspace/benchmarks") / self.session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "config_deviations.json"
        else:
            path = Path(path)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        return str(path)

    def export_sorted_json(self, path: str | Path | None = None, sort_by: str = "deviation_count") -> str:
        """
        Export deviation report sorted by specified metric.

        Args:
            path: Output path
            sort_by: Sort key - "deviation_count", "consistency_score", "total_objects"

        Returns:
            Path to exported file
        """
        report = self.analyze()

        if sort_by == "consistency_score":
            report.config_deviations.sort(key=lambda x: x.consistency_score)
        elif sort_by == "total_objects":
            report.config_deviations.sort(key=lambda x: x.total_objects, reverse=True)

        if path is None:
            output_dir = Path("workspace/benchmarks") / self.session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / f"config_deviations_by_{sort_by}.json"
        else:
            path = Path(path)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

        return str(path)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def analyze_config_deviations(session_id: str, engine: Any) -> DeviationReport:
    """Quick analysis of config deviations for a session."""
    analyzer = ConfigDeviationAnalyzer(session_id, engine)
    return analyzer.analyze()


def export_config_deviations(session_id: str, engine: Any, path: str | None = None) -> str:
    """Analyze and export config deviations to JSON."""
    analyzer = ConfigDeviationAnalyzer(session_id, engine)
    return analyzer.export_json(path)
