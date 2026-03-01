"""
Benchmark analysis service.

Orchestrates multi-dimensional analysis of benchmark results:
- Stability analysis (extraction and derivation phases)
- Semantic matching against reference models
- Fit/underfit/overfit analysis
- Cross-repository comparison
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from deriva.common.ocel import OCELLog
from deriva.modules.analysis.cross_repo_analysis import (
    compare_across_repos,
    generate_cross_repo_recommendations,
)
from deriva.modules.analysis.fit_analysis import create_fit_analysis
from deriva.modules.analysis.semantic_matching import (
    create_semantic_match_report,
    parse_archi_xml,
    parse_exchange_format_xml,
)
from deriva.modules.analysis.stability_analysis import (
    aggregate_stability_metrics,
    compute_phase_stability,
)
from deriva.modules.analysis.types import (
    BenchmarkReport,
    CrossRepoComparison,
    FitAnalysis,
    PhaseStabilityReport,
    ReferenceElement,
    ReferenceRelationship,
    SemanticMatchReport,
)

__all__ = ["BenchmarkAnalyzer"]

# Known reference model locations
REFERENCE_MODELS = {
    "lightblue": "workspace/repositories/lightblue/docs/lightblue.archimate",
    "bigdata": "workspace/repositories/bigdata/docs/MyWorkspace.archimate",
    "Cloudbased-S-BPM-WfMS": "workspace/repositories/Cloudbased-S-BPM-WfMS/AIM18 Documentation/ist_analyse_v0.7.archimate",
}


class BenchmarkAnalyzer:
    """
    Orchestrates comprehensive analysis of benchmark results.

    Combines:
    - Stability analysis from OCEL event logs
    - Semantic matching against reference ArchiMate models
    - Fit/underfit/overfit analysis
    - Cross-repository comparison

    Usage:
        analyzer = BenchmarkAnalyzer(
            session_ids=["bench_20260113_221129", "bench_20260114_060615"],
            engine=engine,
        )
        report = analyzer.generate_report()
        analyzer.export_json("analysis_report.json")
        analyzer.export_markdown("analysis_report.md")
    """

    def __init__(
        self,
        session_ids: list[str],
        engine: Any,
        reference_models: dict[str, str] | None = None,
    ):
        """
        Initialize analyzer with multiple session IDs.

        Args:
            session_ids: List of benchmark session IDs to analyze
            engine: DuckDB connection (for session metadata)
            reference_models: Optional custom mapping of repo -> reference model path
        """
        self.session_ids = session_ids
        self.engine = engine
        self.reference_model_paths = reference_models or REFERENCE_MODELS

        # Load OCEL logs for all sessions
        self.ocel_logs: dict[str, OCELLog] = {}
        self.session_infos: dict[str, dict] = {}

        for session_id in session_ids:
            self.ocel_logs[session_id] = self._load_ocel(session_id)
            self.session_infos[session_id] = self._load_session_info(session_id)

        # Extract unique repositories and models
        self.repositories = self._extract_repositories()
        self.models = self._extract_models()

        # Cache for reference models
        self._reference_cache: dict[str, tuple[list[ReferenceElement], list[ReferenceRelationship]]] = {}

        # Analysis results
        self._stability_reports: dict[str, dict[str, PhaseStabilityReport]] = {}
        self._semantic_reports: dict[str, SemanticMatchReport] = {}
        self._fit_analyses: dict[str, FitAnalysis] = {}
        self._cross_repo: CrossRepoComparison | None = None
        self._report: BenchmarkReport | None = None

    def _load_ocel(self, session_id: str) -> OCELLog:
        """Load OCEL log from file."""
        # Try new location first (ocel/ subdirectory per BENCHMARK_OUTPUT.md)
        ocel_dir = Path("workspace/benchmarks") / session_id / "ocel"
        ocel_path = ocel_dir / "benchmark_events.json"

        if ocel_path.exists():
            return OCELLog.from_json(ocel_path)

        # Try JSONL format in new location
        jsonl_path = ocel_dir / "benchmark_events.jsonl"
        if jsonl_path.exists():
            return OCELLog.from_jsonl(jsonl_path)

        # Fallback to old location for backward compatibility
        old_ocel_path = Path("workspace/benchmarks") / session_id / "events.ocel.json"
        if old_ocel_path.exists():
            return OCELLog.from_json(old_ocel_path)

        old_jsonl_path = Path("workspace/benchmarks") / session_id / "events.jsonl"
        if old_jsonl_path.exists():
            return OCELLog.from_jsonl(old_jsonl_path)

        # Return empty log if files not found
        return OCELLog()

    def _load_session_info(self, session_id: str) -> dict:
        """Load session summary from file."""
        summary_path = Path("workspace/benchmarks") / session_id / "summary.json"

        if summary_path.exists():
            with open(summary_path) as f:
                return json.load(f)

        return {}

    def _extract_repositories(self) -> list[str]:
        """Extract unique repositories from sessions."""
        repos = set()
        for info in self.session_infos.values():
            config = info.get("config", {})
            repos.update(config.get("repositories", []))
        return sorted(repos)

    def _extract_models(self) -> list[str]:
        """Extract unique models from sessions."""
        models = set()
        for info in self.session_infos.values():
            config = info.get("config", {})
            models.update(config.get("models", []))
        return sorted(models)

    def _load_reference_model(self, repo: str) -> tuple[list[ReferenceElement], list[ReferenceRelationship]]:
        """Load and parse reference model for a repository."""
        if repo in self._reference_cache:
            return self._reference_cache[repo]

        ref_path = self.reference_model_paths.get(repo)
        if not ref_path:
            return [], []

        path = Path(ref_path)
        if not path.exists():
            return [], []

        try:
            # Try Archi format first (most common for reference models)
            elements, relationships = parse_archi_xml(path)
            if not elements:
                # Fall back to Exchange format
                elements, relationships = parse_exchange_format_xml(path)

            self._reference_cache[repo] = (elements, relationships)
            return elements, relationships
        except Exception as e:
            print(f"Warning: Failed to parse reference model for {repo}: {e}")
            return [], []

    def _get_objects_by_run(self, object_type: str, repo: str | None = None) -> dict[str, set[str]]:
        """
        Get objects grouped by run from OCEL logs.

        Args:
            object_type: Object type to extract (e.g., "Element", "Relationship")
            repo: Optional repository filter

        Returns:
            Dict mapping run_id -> set of object IDs
        """
        objects_by_run: dict[str, set[str]] = {}

        for session_id, ocel in self.ocel_logs.items():
            # Get objects from this session
            session_objects = ocel.get_objects_by_run(object_type)

            for run_id, objects in session_objects.items():
                # Filter by repository if specified
                if repo:
                    # Extract repo from run_id (format: session:repo:model:iteration)
                    parts = run_id.split(":")
                    if len(parts) >= 2 and parts[1] != repo:
                        continue

                if run_id not in objects_by_run:
                    objects_by_run[run_id] = set()
                objects_by_run[run_id].update(objects)

        return objects_by_run

    def _get_derived_elements(self, repo: str) -> list[dict[str, Any]]:
        """
        Get derived elements for a repository from OCEL logs.

        Extracts element data from the most recent successful run.
        """
        elements = []
        seen_ids = set()  # Avoid duplicates

        for session_id, ocel in self.ocel_logs.items():
            # Find runs for this repo
            for event in ocel.events:
                if event.activity == "DeriveElements":
                    repos = event.objects.get("Repository", [])

                    if repo in repos:
                        # Extract element IDs and create element dicts
                        element_ids = event.objects.get("Element", [])
                        for elem_id in element_ids:
                            if elem_id in seen_ids:
                                continue
                            seen_ids.add(elem_id)

                            # Parse element type from ID
                            elem_type = self._extract_element_type(elem_id)
                            elements.append(
                                {
                                    "id": elem_id,
                                    "name": elem_id,  # Use ID as name for now
                                    "type": elem_type,
                                }
                            )

        return elements

    def _extract_element_type(self, element_id: str) -> str:
        """Extract element type from ID prefix."""
        from deriva.modules.analysis.stability_analysis import extract_element_type

        return extract_element_type(element_id)

    # =========================================================================
    # Analysis Methods
    # =========================================================================

    def analyze_stability(self) -> dict[str, dict[str, PhaseStabilityReport]]:
        """
        Compute stability reports for all repositories.

        Returns:
            Dict mapping repo -> phase -> PhaseStabilityReport
        """
        if self._stability_reports:
            return self._stability_reports

        for repo in self.repositories:
            # Get objects by run for this repo
            nodes_by_run = self._get_objects_by_run("GraphNode", repo)
            edges_by_run = self._get_objects_by_run("Edge", repo)
            elements_by_run = self._get_objects_by_run("Element", repo)
            relationships_by_run = self._get_objects_by_run("Relationship", repo)

            # Get model name (use first model if multiple)
            model = self.models[0] if self.models else "unknown"

            # Compute phase stability
            phase_reports = compute_phase_stability(
                nodes_by_run=nodes_by_run,
                edges_by_run=edges_by_run,
                elements_by_run=elements_by_run,
                relationships_by_run=relationships_by_run,
                repository=repo,
                model=model,
            )

            self._stability_reports[repo] = phase_reports

        return self._stability_reports

    def analyze_semantic_match(self) -> dict[str, SemanticMatchReport]:
        """
        Compare derived models against reference models.

        Returns:
            Dict mapping repo -> SemanticMatchReport
        """
        if self._semantic_reports:
            return self._semantic_reports

        for repo in self.repositories:
            # Load reference model
            ref_elements, ref_relationships = self._load_reference_model(repo)

            if not ref_elements:
                continue  # Skip if no reference model

            # Get derived elements
            derived_elements = self._get_derived_elements(repo)

            if not derived_elements:
                continue

            # Get reference model path
            ref_path = self.reference_model_paths.get(repo, "")

            # Create run ID from first session
            run_id = f"{self.session_ids[0]}:{repo}"

            # Create semantic match report
            report = create_semantic_match_report(
                repository=repo,
                reference_model_path=ref_path,
                derived_run=run_id,
                derived_elements=derived_elements,
                reference_elements=ref_elements,
            )

            self._semantic_reports[repo] = report

        return self._semantic_reports

    def analyze_fit(self) -> dict[str, FitAnalysis]:
        """
        Compute fit/underfit/overfit analysis for all repositories.

        Returns:
            Dict mapping repo -> FitAnalysis
        """
        if self._fit_analyses:
            return self._fit_analyses

        # Ensure semantic analysis is done first
        semantic_reports = self.analyze_semantic_match()

        for repo in self.repositories:
            # Get reference and derived elements
            ref_elements, _ = self._load_reference_model(repo)
            derived_elements = self._get_derived_elements(repo)

            if not derived_elements:
                continue

            # Get semantic report if available
            semantic_report = semantic_reports.get(repo)

            # Create run ID
            run_id = f"{self.session_ids[0]}:{repo}"

            # Create fit analysis
            analysis = create_fit_analysis(
                repository=repo,
                run_id=run_id,
                derived_elements=derived_elements,
                reference_elements=ref_elements,
                semantic_report=semantic_report,
            )

            self._fit_analyses[repo] = analysis

        return self._fit_analyses

    def analyze_cross_repo(self) -> CrossRepoComparison | None:
        """
        Compare results across repositories.

        Returns:
            CrossRepoComparison or None if < 2 repos
        """
        if self._cross_repo:
            return self._cross_repo

        if len(self.repositories) < 2:
            return None

        # Ensure other analyses are done
        stability = self.analyze_stability()
        semantic = self.analyze_semantic_match()
        fit = self.analyze_fit()

        # Get model name
        model = self.models[0] if self.models else "unknown"

        # Create comparison
        self._cross_repo = compare_across_repos(
            stability_reports=stability,
            semantic_reports=semantic,
            fit_analyses=fit,
            model=model,
        )

        return self._cross_repo

    def generate_report(self) -> BenchmarkReport:
        """
        Generate comprehensive benchmark report.

        Returns:
            BenchmarkReport with all analysis results
        """
        if self._report:
            return self._report

        # Run all analyses
        stability = self.analyze_stability()
        semantic = self.analyze_semantic_match()
        fit = self.analyze_fit()
        cross_repo = self.analyze_cross_repo()

        # Compute summary metrics
        metrics = aggregate_stability_metrics(stability)
        overall_consistency = metrics.get("avg_derivation_consistency", 0.0)

        # Compute average precision/recall
        if semantic:
            overall_precision = sum(s.element_precision for s in semantic.values()) / len(semantic)
            overall_recall = sum(s.element_recall for s in semantic.values()) / len(semantic)
        else:
            overall_precision = 0.0
            overall_recall = 0.0

        # Generate recommendations
        recommendations = self._generate_recommendations(stability, semantic, fit, cross_repo, metrics)

        # Create report
        self._report = BenchmarkReport(
            session_ids=self.session_ids,
            repositories=self.repositories,
            models=self.models,
            generated_at=datetime.now().isoformat(),
            stability_reports=stability,
            semantic_reports=semantic,
            fit_analyses=fit,
            cross_repo=cross_repo,
            overall_consistency=overall_consistency,
            overall_precision=overall_precision,
            overall_recall=overall_recall,
            recommendations=recommendations,
        )

        return self._report

    def _generate_recommendations(
        self,
        stability: dict[str, dict[str, PhaseStabilityReport]],
        semantic: dict[str, SemanticMatchReport],
        fit: dict[str, FitAnalysis],
        cross_repo: CrossRepoComparison | None,
        metrics: dict[str, Any],
    ) -> list[str]:
        """Generate actionable recommendations from all analyses."""
        recommendations = []

        # Stability-based recommendations
        if metrics.get("worst_element_types"):
            for elem_type, score in metrics["worst_element_types"][:3]:
                if score < 0.5:
                    recommendations.append(f"HIGH: '{elem_type}' has low consistency ({score:.0%}). Review derivation prompt for stricter naming rules.")

        # Semantic-based recommendations
        for repo, sr in semantic.items():
            if sr.element_recall < 0.5:
                recommendations.append(f"MEDIUM: {repo} has low recall ({sr.element_recall:.0%}). Consider adding more derivation rules.")
            if sr.element_precision < 0.5:
                recommendations.append(f"MEDIUM: {repo} has low precision ({sr.element_precision:.0%}). Add filtering to reduce false positives.")

        # Fit-based recommendations
        for repo, fa in fit.items():
            if fa.underfit_score > 0.5:
                recommendations.append(f"HIGH: {repo} shows underfit ({fa.underfit_score:.0%}). Model is too simple.")
            if fa.overfit_score > 0.5:
                recommendations.append(f"HIGH: {repo} shows overfit ({fa.overfit_score:.0%}). Too many spurious elements.")

        # Cross-repo recommendations
        if cross_repo:
            recommendations.extend(generate_cross_repo_recommendations(cross_repo))

        return recommendations

    # =========================================================================
    # Export Methods
    # =========================================================================

    def export_json(self, path: str | Path) -> str:
        """
        Export analysis report as JSON.

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        report = self.generate_report()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        return str(path)

    def export_markdown(self, path: str | Path) -> str:
        """
        Export analysis report as Markdown.

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        report = self.generate_report()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            f.write(report.to_markdown())

        return str(path)

    def export_consistency_metrics_csv(self, path: str | Path) -> str:
        """
        Export consistency_metrics.csv with per-run element and relationship stability.

        Columns: repository, model, run, total_elements, stable_elements,
                 element_stability, total_relationships, stable_relationships,
                 relationship_stability

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        report = self.generate_report()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["repository", "model", "run", "total_elements", "stable_elements", "element_stability", "total_relationships", "stable_relationships", "relationship_stability"]
            )

            for repo, phases in report.stability_reports.items():
                derivation = phases.get("derivation")
                if derivation:
                    # Aggregate element stats
                    total_elem = sum(b.total for b in derivation.element_breakdown)
                    stable_elem = sum(b.stable for b in derivation.element_breakdown)
                    elem_stability = stable_elem / total_elem if total_elem > 0 else 0.0

                    # Aggregate relationship stats
                    total_rel = sum(b.total for b in derivation.relationship_breakdown)
                    stable_rel = sum(b.stable for b in derivation.relationship_breakdown)
                    rel_stability = stable_rel / total_rel if total_rel > 0 else 0.0

                    writer.writerow([repo, "all", "all", total_elem, stable_elem, f"{elem_stability:.2%}", total_rel, stable_rel, f"{rel_stability:.2%}"])

        return str(path)

    def export_ground_truth_comparison_csv(self, path: str | Path) -> str:
        """
        Export ground_truth_comparison.csv with precision/recall/F1 against reference models.

        Columns: repository, model, gt_elements, extracted_elements, matched,
                 precision, recall, f1

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        report = self.generate_report()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repository", "model", "gt_elements", "extracted_elements", "matched", "precision", "recall", "f1"])

            for repo, sem_report in report.semantic_reports.items():
                if sem_report:
                    writer.writerow(
                        [
                            repo,
                            "all",
                            sem_report.reference_element_count,
                            sem_report.derived_element_count,
                            len(sem_report.correctly_derived),
                            f"{sem_report.precision:.3f}",
                            f"{sem_report.recall:.3f}",
                            f"{sem_report.f1_score:.3f}",
                        ]
                    )
                else:
                    writer.writerow([repo, "all", 0, 0, 0, "N/A", "N/A", "N/A"])

        return str(path)

    def export_quality_verification_csv(self, path: str | Path) -> str:
        """
        Export quality_verification.csv with quality rubric scores.

        Columns: repository, model, validity_pct, type_correct_pct, name_quality_pct

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        report = self.generate_report()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repository", "model", "validity_pct", "type_correct_pct", "name_quality_pct"])

            for repo in report.stability_reports:
                sem_report = report.semantic_reports.get(repo)
                fit = report.fit_analyses.get(repo)

                # Validity: Precision (elements traceable to reference)
                validity = sem_report.precision if sem_report else 0.0

                # Type correct: Elements with matching ArchiMate type
                type_correct = 0.0
                if sem_report and sem_report.correctly_derived:
                    exact_matches = len([m for m in sem_report.correctly_derived if m.match_type in ("exact", "fuzzy_name")])
                    type_correct = exact_matches / max(sem_report.derived_element_count, 1)

                # Name quality: Coverage score from fit analysis
                name_quality = fit.coverage_score if fit else 0.0

                writer.writerow([repo, "all", f"{validity:.1%}", f"{type_correct:.1%}", f"{name_quality:.1%}"])

        return str(path)

    def export_execution_metrics_csv(self, path: str | Path) -> str:
        """
        Export execution_metrics.csv with runtime performance data.

        Columns: repository, model, run, duration_sec, event_count,
                 tokens_in, tokens_out, api_calls

        Args:
            path: Output file path

        Returns:
            Path to exported file
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Parse OCEL for timing data from all sessions
        run_metrics: dict[str, dict[str, Any]] = {}

        for ocel_log in self.ocel_logs.values():
            for event in ocel_log.events:
                if event.activity == "StartRun":
                    run_id = event.objects.get("BenchmarkRun", [""])[0]
                    run_metrics[run_id] = {
                        "start": event.timestamp,
                        "repo": event.objects.get("Repository", [""])[0],
                        "model": event.objects.get("Model", [""])[0],
                        "events": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                        "api_calls": 0,
                    }
                elif event.activity == "CompleteRun":
                    run_id = event.objects.get("BenchmarkRun", [""])[0]
                    if run_id in run_metrics:
                        run_metrics[run_id]["end"] = event.timestamp
                elif event.activity in ("LLMRequest", "llm_request"):
                    run_id = event.objects.get("BenchmarkRun", [""])[0]
                    if run_id in run_metrics:
                        run_metrics[run_id]["api_calls"] += 1
                        run_metrics[run_id]["tokens_in"] += event.attributes.get("tokens_in", 0)
                        run_metrics[run_id]["tokens_out"] += event.attributes.get("tokens_out", 0)

                # Count all events for this run
                for run_id in event.objects.get("BenchmarkRun", []):
                    if run_id in run_metrics:
                        run_metrics[run_id]["events"] += 1

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repository", "model", "run", "duration_sec", "event_count", "tokens_in", "tokens_out", "api_calls"])

            for run_id, metrics in run_metrics.items():
                # Parse run number from run_id (format: session:repo:model:n)
                parts = run_id.split(":")
                run_num = parts[-1] if len(parts) >= 4 else "1"

                # Calculate duration
                start = metrics.get("start")
                end = metrics.get("end", start)
                duration = 0.0
                if start and end:
                    try:
                        duration = (end - start).total_seconds()
                    except (TypeError, AttributeError):
                        duration = 0.0

                writer.writerow(
                    [metrics["repo"], metrics["model"], run_num, f"{duration:.1f}", metrics["events"], metrics["tokens_in"], metrics["tokens_out"], metrics["api_calls"]]
                )

        return str(path)

    def export_all(self, output_dir: str | Path) -> dict[str, str]:
        """
        Export all formats to results/ directory per BENCHMARK_OUTPUT.md spec.

        Creates a results/ subdirectory with:
        - inter_model_agreement.json
        - consistency_metrics.csv
        - ground_truth_comparison.csv
        - quality_verification.csv
        - execution_metrics.csv
        - benchmark_analysis.md (human-readable report)

        Args:
            output_dir: Output directory (results/ subdirectory will be created)

        Returns:
            Dict mapping format -> file path
        """
        output_dir = Path(output_dir)
        results_dir = output_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        paths = {}

        # JSON exports
        paths["inter_model_json"] = self.export_json(results_dir / "inter_model_agreement.json")
        paths["markdown"] = self.export_markdown(results_dir / "benchmark_analysis.md")

        # CSV exports per BENCHMARK_OUTPUT.md spec
        paths["consistency_csv"] = self.export_consistency_metrics_csv(results_dir / "consistency_metrics.csv")
        paths["ground_truth_csv"] = self.export_ground_truth_comparison_csv(results_dir / "ground_truth_comparison.csv")
        paths["quality_csv"] = self.export_quality_verification_csv(results_dir / "quality_verification.csv")
        paths["execution_csv"] = self.export_execution_metrics_csv(results_dir / "execution_metrics.csv")

        return paths
