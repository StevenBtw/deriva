"""
Benchmark analysis module for Deriva.

Provides post-run analysis of benchmark results including:
- Intra-model consistency: How stable is each model across runs?
- Inter-model consistency: How do different models compare?
- Inconsistency localization: WHERE do things diverge?

Usage:
    analyzer = BenchmarkAnalyzer(session_id, engine)

    # Compute metrics
    intra = analyzer.compute_intra_model_consistency()
    inter = analyzer.compute_inter_model_consistency()
    localization = analyzer.localize_inconsistencies()

    # Export
    analyzer.export_summary("analysis.json")
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from deriva.common.ocel import OCELLog


@dataclass
class IntraModelMetrics:
    """Consistency metrics for a single model across runs on the same repo."""

    model: str
    repository: str
    runs: int
    element_counts: list[int]
    count_variance: float
    name_consistency: float  # % of element names in ALL runs
    stable_elements: list[str]  # Names in all runs
    unstable_elements: dict[str, int]  # Name -> count of runs appeared

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class InterModelMetrics:
    """Comparison metrics across models for the same repository."""

    repository: str
    models: list[str]
    elements_by_model: dict[str, list[str]]
    overlap: list[str]  # Elements in ALL models
    unique_by_model: dict[str, list[str]]  # Elements unique to each model
    jaccard_similarity: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class InconsistencyLocalization:
    """Where inconsistencies occur in the pipeline."""

    by_element_type: dict[str, float]  # Type -> inconsistency score
    by_stage: dict[str, float]  # Stage -> inconsistency score
    by_model: dict[str, float]  # Model -> inconsistency score
    by_repository: dict[str, float]  # Repo -> inconsistency score
    hotspots: list[dict[str, Any]]  # Top inconsistent areas

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class AnalysisSummary:
    """Complete analysis summary."""

    session_id: str
    analyzed_at: str
    intra_model: list[IntraModelMetrics]
    inter_model: list[InterModelMetrics]
    localization: InconsistencyLocalization
    overall_consistency: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "analyzed_at": self.analyzed_at,
            "intra_model": [m.to_dict() for m in self.intra_model],
            "inter_model": [m.to_dict() for m in self.inter_model],
            "localization": self.localization.to_dict(),
            "overall_consistency": self.overall_consistency,
        }


class BenchmarkAnalyzer:
    """
    Post-run analysis of benchmark results.

    Loads OCEL logs and computes consistency metrics across
    models, repositories, and pipeline stages.
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

        # Load session info
        self.session_info = self._load_session()
        if not self.session_info:
            raise ValueError(f"Benchmark session not found: {session_id}")

        # Load OCEL log
        self.ocel_log = self._load_ocel()

        # Load run data
        self.runs = self._load_runs()

    def _load_session(self) -> dict[str, Any] | None:
        """Load session metadata from database."""
        row = self.engine.execute(
            """
            SELECT session_id, description, config, status, started_at, completed_at
            FROM benchmark_sessions
            WHERE session_id = ?
            """,
            [self.session_id],
        ).fetchone()

        if not row:
            return None

        return {
            "session_id": row[0],
            "description": row[1],
            "config": json.loads(row[2]) if row[2] else {},
            "status": row[3],
            "started_at": row[4],
            "completed_at": row[5],
        }

    def _load_ocel(self) -> OCELLog:
        """Load OCEL log from file."""
        ocel_path = Path("workspace/benchmarks") / self.session_id / "events.ocel.json"

        if ocel_path.exists():
            return OCELLog.from_json(ocel_path)

        # Try JSONL format
        jsonl_path = Path("workspace/benchmarks") / self.session_id / "events.jsonl"
        if jsonl_path.exists():
            return OCELLog.from_jsonl(jsonl_path)

        # Return empty log if files not found
        return OCELLog()

    def _load_runs(self) -> list[dict[str, Any]]:
        """Load run data from database."""
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
    # INTRA-MODEL CONSISTENCY
    # =========================================================================

    def compute_intra_model_consistency(self) -> list[IntraModelMetrics]:
        """
        Compute consistency metrics for each model across runs.

        Measures how stable each model is when running on the same repository
        multiple times.

        Returns:
            List of IntraModelMetrics for each (model, repo) combination
        """
        results: list[IntraModelMetrics] = []

        # Group runs by (model, repository)
        grouped: dict[tuple[str, str], list[dict]] = {}
        for run in self.runs:
            key = (run["model_name"], run["repository"])
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(run)

        for (model, repo), runs in grouped.items():
            if len(runs) < 2:
                continue  # Need at least 2 runs to compute consistency

            # Extract element counts from stats
            element_counts = []
            for run in runs:
                stats = run.get("stats", {})
                derivation_stats = stats.get("derivation", {})
                count = derivation_stats.get("elements_created", 0)
                element_counts.append(count)

            # Compute variance
            if element_counts:
                avg = sum(element_counts) / len(element_counts)
                variance = sum((c - avg) ** 2 for c in element_counts) / len(element_counts)
            else:
                variance = 0.0

            # Get elements from OCEL for this model/repo
            elements_by_run = self._get_elements_by_run(model, repo)

            # Compute name consistency
            all_elements = set()
            for elems in elements_by_run.values():
                all_elements.update(elems)

            stable = []
            unstable: dict[str, int] = {}

            for elem in all_elements:
                count = sum(1 for elems in elements_by_run.values() if elem in elems)
                if count == len(runs):
                    stable.append(elem)
                else:
                    unstable[elem] = count

            consistency = len(stable) / len(all_elements) * 100 if all_elements else 100

            results.append(
                IntraModelMetrics(
                    model=model,
                    repository=repo,
                    runs=len(runs),
                    element_counts=element_counts,
                    count_variance=variance,
                    name_consistency=consistency,
                    stable_elements=sorted(stable),
                    unstable_elements=unstable,
                )
            )

        return results

    def _get_elements_by_run(self, model: str, repo: str) -> dict[str, set[str]]:
        """Get derived elements grouped by run for a model/repo combination."""
        result: dict[str, set[str]] = {}

        for event in self.ocel_log.events:
            if event.activity != "DeriveElements":
                continue

            event_model = event.objects.get("Model", [None])[0]
            event_repo = event.objects.get("Repository", [None])[0]
            runs = event.objects.get("BenchmarkRun", [])

            if event_model == model and event_repo == repo:
                for run_id in runs:
                    if run_id not in result:
                        result[run_id] = set()
                    # Elements would be in the Element object type
                    elements = event.objects.get("Element", [])
                    result[run_id].update(elements)

        return result

    # =========================================================================
    # INTER-MODEL CONSISTENCY
    # =========================================================================

    def compute_inter_model_consistency(self) -> list[InterModelMetrics]:
        """
        Compute comparison metrics across models for the same repository.

        Measures how different models compare when processing the same
        repository.

        Returns:
            List of InterModelMetrics for each repository
        """
        results: list[InterModelMetrics] = []

        # Get unique repositories
        repositories = set(run["repository"] for run in self.runs)

        for repo in repositories:
            # Get models that processed this repo
            models_for_repo = set(run["model_name"] for run in self.runs if run["repository"] == repo)

            if len(models_for_repo) < 2:
                continue  # Need at least 2 models to compare

            # Get elements by model (aggregate across runs)
            elements_by_model: dict[str, set[str]] = {}

            for model in models_for_repo:
                elements_by_model[model] = set()
                for run_id, elems in self._get_elements_by_run(model, repo).items():
                    elements_by_model[model].update(elems)

            # Compute overlap (elements in ALL models)
            if elements_by_model:
                overlap = set.intersection(*elements_by_model.values())
            else:
                overlap = set()

            # Compute unique elements per model
            all_elements = set.union(*elements_by_model.values()) if elements_by_model else set()
            unique_by_model = {}
            for model, elems in elements_by_model.items():
                other_elems = set.union(*(e for m, e in elements_by_model.items() if m != model)) if len(elements_by_model) > 1 else set()
                unique_by_model[model] = sorted(elems - other_elems)

            # Compute Jaccard similarity
            if all_elements:
                jaccard = len(overlap) / len(all_elements)
            else:
                jaccard = 1.0

            results.append(
                InterModelMetrics(
                    repository=repo,
                    models=sorted(models_for_repo),
                    elements_by_model={m: sorted(e) for m, e in elements_by_model.items()},
                    overlap=sorted(overlap),
                    unique_by_model=unique_by_model,
                    jaccard_similarity=jaccard,
                )
            )

        return results

    # =========================================================================
    # INCONSISTENCY LOCALIZATION
    # =========================================================================

    def localize_inconsistencies(self) -> InconsistencyLocalization:
        """
        Identify WHERE inconsistencies occur in the pipeline.

        Analyzes inconsistency patterns by:
        - Element type
        - Pipeline stage
        - Model
        - Repository

        Returns:
            InconsistencyLocalization with scores and hotspots
        """
        # Compute consistency by different dimensions
        by_element_type: dict[str, float] = {}
        by_stage: dict[str, float] = {}
        by_model: dict[str, float] = {}
        by_repository: dict[str, float] = {}

        # Element type consistency from OCEL
        element_consistency = self.ocel_log.compute_consistency_score("Element")
        by_element_type["Element"] = element_consistency

        node_consistency = self.ocel_log.compute_consistency_score("GraphNode")
        by_element_type["GraphNode"] = node_consistency

        # Stage consistency from run stats
        stage_counts: dict[str, list[int]] = {
            "extraction": [],
            "derivation": [],
        }

        for run in self.runs:
            stats = run.get("stats", {})
            if "extraction" in stats:
                stage_counts["extraction"].append(stats["extraction"].get("nodes_created", 0))
            if "derivation" in stats:
                stage_counts["derivation"].append(stats["derivation"].get("elements_created", 0))

        for stage, counts in stage_counts.items():
            if len(counts) >= 2:
                avg = sum(counts) / len(counts)
                variance = sum((c - avg) ** 2 for c in counts) / len(counts)
                # Normalize: lower variance = higher consistency
                cv = (variance**0.5 / avg * 100) if avg > 0 else 0
                by_stage[stage] = max(0, 100 - cv)  # Convert to consistency %
            else:
                by_stage[stage] = 100.0

        # Model consistency
        intra_metrics = self.compute_intra_model_consistency()
        model_scores: dict[str, list[float]] = {}
        for metric in intra_metrics:
            if metric.model not in model_scores:
                model_scores[metric.model] = []
            model_scores[metric.model].append(metric.name_consistency)

        by_model = {m: sum(v) / len(v) for m, v in model_scores.items() if v}

        # Repository consistency
        repo_scores: dict[str, list[float]] = {}
        for metric in intra_metrics:
            if metric.repository not in repo_scores:
                repo_scores[metric.repository] = []
            repo_scores[metric.repository].append(metric.name_consistency)

        by_repository = {r: sum(v) / len(v) for r, v in repo_scores.items() if v}

        # Identify hotspots (lowest consistency areas)
        hotspots = []

        for model, score in sorted(by_model.items(), key=lambda x: x[1]):
            if score < 80:
                hotspots.append(
                    {
                        "type": "model",
                        "name": model,
                        "consistency": score,
                        "severity": "high" if score < 50 else "medium",
                    }
                )

        for stage, score in sorted(by_stage.items(), key=lambda x: x[1]):
            if score < 80:
                hotspots.append(
                    {
                        "type": "stage",
                        "name": stage,
                        "consistency": score,
                        "severity": "high" if score < 50 else "medium",
                    }
                )

        return InconsistencyLocalization(
            by_element_type=by_element_type,
            by_stage=by_stage,
            by_model=by_model,
            by_repository=by_repository,
            hotspots=hotspots[:10],  # Top 10 hotspots
        )

    # =========================================================================
    # OBJECT TRACING
    # =========================================================================

    def trace_element(self, element_id: str) -> list[dict[str, Any]]:
        """
        Get full event history for an element across all runs.

        Args:
            element_id: Element identifier to trace

        Returns:
            List of events involving this element
        """
        events = self.ocel_log.get_events_for_object("Element", element_id)
        return [e.to_jsonl_dict() for e in events]

    def compare_element_across_runs(self, element_name: str) -> dict[str, Any]:
        """
        Compare how an element was derived across different runs/models.

        Args:
            element_name: Element name to compare

        Returns:
            Comparison data across runs
        """
        # Find all runs that produced this element
        runs_with_element: list[str] = []
        runs_without_element: list[str] = []

        for run in self.runs:
            run_id = run["run_id"]
            elements = self.ocel_log.get_events_for_object("BenchmarkRun", run_id)

            # Check if any derivation event includes this element
            has_element = any(element_name in e.objects.get("Element", []) for e in elements if e.activity == "DeriveElements")

            if has_element:
                runs_with_element.append(run_id)
            else:
                runs_without_element.append(run_id)

        return {
            "element_name": element_name,
            "present_in_runs": runs_with_element,
            "absent_from_runs": runs_without_element,
            "consistency": len(runs_with_element) / len(self.runs) * 100 if self.runs else 0,
        }

    # =========================================================================
    # EXPORT
    # =========================================================================

    def compute_full_analysis(self) -> AnalysisSummary:
        """
        Compute complete analysis summary.

        Returns:
            AnalysisSummary with all metrics
        """
        intra = self.compute_intra_model_consistency()
        inter = self.compute_inter_model_consistency()
        localization = self.localize_inconsistencies()

        # Compute overall consistency
        all_consistencies = []
        for m in intra:
            all_consistencies.append(m.name_consistency)
        for m in inter:
            all_consistencies.append(m.jaccard_similarity * 100)

        overall = sum(all_consistencies) / len(all_consistencies) if all_consistencies else 100

        return AnalysisSummary(
            session_id=self.session_id,
            analyzed_at=datetime.now().isoformat(),
            intra_model=intra,
            inter_model=inter,
            localization=localization,
            overall_consistency=overall,
        )

    def export_summary(self, path: str | None = None, format: str = "json") -> str:
        """
        Export analysis summary to file.

        Args:
            path: Output path (default: workspace/benchmarks/{session}/analysis.json)
            format: Output format (json, markdown)

        Returns:
            Path to exported file
        """
        summary = self.compute_full_analysis()

        if path is None:
            output_dir = Path("workspace/benchmarks") / self.session_id / "analysis"
            output_dir.mkdir(parents=True, exist_ok=True)
            path = str(output_dir / f"summary.{format}")

        if format == "json":
            with open(path, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)
        elif format == "markdown":
            self._export_markdown(summary, path)
        else:
            raise ValueError(f"Unknown format: {format}")

        return path

    def _export_markdown(self, summary: AnalysisSummary, path: str) -> None:
        """Export summary as markdown report."""
        lines = [
            f"# Benchmark Analysis: {summary.session_id}",
            "",
            f"**Analyzed:** {summary.analyzed_at}",
            f"**Overall Consistency:** {summary.overall_consistency:.1f}%",
            "",
            "## Intra-Model Consistency",
            "",
            "How stable is each model across multiple runs?",
            "",
            "| Model | Repository | Runs | Consistency | Variance |",
            "|-------|------------|------|-------------|----------|",
        ]

        for m in summary.intra_model:
            lines.append(f"| {m.model} | {m.repository} | {m.runs} | {m.name_consistency:.1f}% | {m.count_variance:.2f} |")

        lines.extend(
            [
                "",
                "## Inter-Model Consistency",
                "",
                "How do different models compare on the same repository?",
                "",
                "| Repository | Models | Overlap | Jaccard |",
                "|------------|--------|---------|---------|",
            ]
        )

        for m in summary.inter_model:
            lines.append(f"| {m.repository} | {', '.join(m.models)} | {len(m.overlap)} | {m.jaccard_similarity:.2f} |")

        lines.extend(
            [
                "",
                "## Inconsistency Hotspots",
                "",
            ]
        )

        if summary.localization.hotspots:
            for hotspot in summary.localization.hotspots:
                lines.append(f"- **{hotspot['type'].title()}:** {hotspot['name']} (consistency: {hotspot['consistency']:.1f}%, severity: {hotspot['severity']})")
        else:
            lines.append("No significant hotspots detected.")

        with open(path, "w") as f:
            f.write("\n".join(lines))

    def save_metrics_to_db(self) -> None:
        """Store computed metrics in benchmark_metrics table."""
        summary = self.compute_full_analysis()

        # Clear existing metrics for this session
        self.engine.execute(
            "DELETE FROM benchmark_metrics WHERE session_id = ?",
            [self.session_id],
        )

        # Insert intra-model metrics
        for m in summary.intra_model:
            self.engine.execute(
                """
                INSERT INTO benchmark_metrics
                (session_id, metric_type, metric_key, metric_value, details)
                VALUES (?, 'intra_model', ?, ?, ?)
                """,
                [
                    self.session_id,
                    f"{m.model}:{m.repository}",
                    m.name_consistency,
                    json.dumps(m.to_dict()),
                ],
            )

        # Insert inter-model metrics
        for m in summary.inter_model:
            self.engine.execute(
                """
                INSERT INTO benchmark_metrics
                (session_id, metric_type, metric_key, metric_value, details)
                VALUES (?, 'inter_model', ?, ?, ?)
                """,
                [
                    self.session_id,
                    m.repository,
                    m.jaccard_similarity * 100,
                    json.dumps(m.to_dict()),
                ],
            )

        # Insert overall consistency
        self.engine.execute(
            """
            INSERT INTO benchmark_metrics
            (session_id, metric_type, metric_key, metric_value, details)
            VALUES (?, 'overall', 'consistency', ?, ?)
            """,
            [
                self.session_id,
                summary.overall_consistency,
                json.dumps({"analyzed_at": summary.analyzed_at}),
            ],
        )
