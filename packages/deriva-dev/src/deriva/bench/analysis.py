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
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from deriva.common.ocel import OCELLog, hash_content, load_benchmark_ocel
from deriva.common.paths import workspace
from deriva.modules.analysis import decision_content
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
    compute_answer_stability,
    compute_phase_stability,
)
from deriva.modules.analysis.types import (
    AnswerStability,
    BenchmarkReport,
    CrossRepoComparison,
    FitAnalysis,
    PhaseStabilityReport,
    ReferenceElement,
    ReferenceRelationship,
    SemanticMatchReport,
)
from deriva.services.llm_log import LlmCallLog

from .session_metrics import call_key

__all__ = ["BenchmarkAnalyzer"]


def known_reference_models() -> dict[str, str]:
    """Reference models by repository name: ``workspace/reference/<repository>.archimate`` in the home folder."""
    folder = workspace() / "reference"
    return {path.stem: str(path) for path in sorted(folder.glob("*.archimate"))} if folder.is_dir() else {}


logger = logging.getLogger(__name__)


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
        self.reference_model_paths = reference_models or known_reference_models()

        # Load OCEL logs for all sessions
        self.ocel_logs: dict[str, OCELLog] = {}
        self.session_infos: dict[str, dict] = {}

        # Every LLM call with its answer, where the session kept them (llm/<run>.jsonl, sessions from 0.8.0)
        self.call_logs: dict[str, list[dict[str, Any]]] = {}

        for session_id in session_ids:
            self.ocel_logs[session_id] = self._load_ocel(session_id)
            self.session_infos[session_id] = self._load_session_info(session_id)
            calls = [call for path in sorted((workspace() / "benchmarks" / session_id / "llm").glob("*.jsonl")) for call in LlmCallLog.read(path)]
            if calls:
                self.call_logs[session_id] = calls

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
        self._skip_semantic = False  # generate_report(include_semantic=False)

    def _load_ocel(self, session_id: str) -> OCELLog:
        """Load OCEL log from file."""
        return load_benchmark_ocel(workspace() / "benchmarks", session_id)

    def _load_session_info(self, session_id: str) -> dict:
        """Load session metadata from file (``summary.json`` in sessions before the rename)."""
        session_dir = workspace() / "benchmarks" / session_id
        for name in ("session_metadata.json", "summary.json"):
            path = session_dir / name
            if path.exists():
                with open(path, encoding="utf-8") as f:
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
            elements, relationships = parse_archi_xml(path, archimate3=True)
            if not elements:
                # Fall back to Exchange format
                elements, relationships = parse_exchange_format_xml(path)

            self._reference_cache[repo] = (elements, relationships)
            return elements, relationships
        except Exception as e:
            print(f"Warning: Failed to parse reference model for {repo}: {e}")
            return [], []

    def _is_run_of(self, run_repository: str, repo: str) -> bool:
        """Whether a run's repository name is this repository, or the combined run that holds it."""
        return run_repository == repo or (repo in self.repositories and run_repository == "_".join(sorted(self.repositories)))

    def _get_objects_by_run(self, object_type: str, repo: str | None = None, model: str | None = None) -> dict[str, set[str]]:
        """
        Get objects grouped by run from OCEL logs.

        Args:
            object_type: Object type to extract (e.g., "Element", "Relationship")
            repo: Optional repository filter (a combined run counts for each of its repositories)
            model: Optional model filter

        Returns:
            Dict mapping run_id -> set of object IDs
        """
        objects_by_run: dict[str, set[str]] = {}

        for session_id, ocel in self.ocel_logs.items():
            # Get objects from this session
            session_objects = ocel.get_objects_by_run(object_type)

            for run_id, objects in session_objects.items():
                # Run ids: session:repo:model:iteration, and session:extraction:repo for a repository's
                # extraction (which belongs to no model, so a model filter keeps it)
                parts = run_id.split(":")
                extraction = len(parts) >= 3 and parts[1] == "extraction"
                run_repository = parts[2] if extraction else parts[1] if len(parts) >= 2 else ""
                if repo and len(parts) >= 2 and not self._is_run_of(run_repository, repo):
                    continue
                if model and not extraction and len(parts) >= 3 and parts[2] != model:
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
        by_run: dict[str, list[str]] = {}  # run id -> element ids, runs in log order
        completed: list[str] = []
        for ocel in self.ocel_logs.values():
            for event in ocel.events:
                if not any(self._is_run_of(name, repo) for name in event.objects.get("Repository", [])):
                    continue
                run_id = next(iter(event.objects.get("BenchmarkRun", [])), "")
                if event.activity == "DeriveElements":
                    by_run.setdefault(run_id, []).extend(event.objects.get("Element", []))
                elif event.activity == "CompleteRun" and run_id:
                    completed.append(run_id)
        # The latest run that completed and derived elements; without a completed one, the latest that derived any
        latest = next((run_id for run_id in reversed(completed) if by_run.get(run_id)), next(reversed(by_run), None) if by_run else None)
        if latest is None:
            return []
        return [{"id": elem_id, "name": elem_id, "type": self._extract_element_type(elem_id)} for elem_id in dict.fromkeys(by_run[latest])]

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
            # One model per report: runs of several models would mix repeatability with model differences,
            # so with several models the report covers the first one (the model it is labelled with)
            model = self.models[0] if self.models else "unknown"
            only = model if len(self.models) > 1 else None
            if only:
                logger.warning("Sessions hold %d models; the stability report of %s covers %s only", len(self.models), repo, model)
            nodes_by_run = self._get_objects_by_run("GraphNode", repo, only)
            edges_by_run = self._get_objects_by_run("Edge", repo, only)
            elements_by_run = self._get_objects_by_run("Element", repo, only)
            relationships_by_run = self._get_objects_by_run("Relationship", repo, only)

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

    def analyze_answer_stability(self) -> dict[str, list[AnswerStability]]:
        """Raw LLM answer stability per repository: the same prompt answered identically in every run.

        Answers are compared on their decisions. Where a session kept its LLM calls the
        decision is computed from each recorded answer (``decision_content``), so the current
        rule applies to old sessions too; otherwise the event log's ``decision_hash`` is used,
        and in sessions recorded before that the full response hash.

        Extraction runs (``session:extraction:repo``) and derivation runs
        (``session:repo:model:iteration``) are compared separately, since their prompts differ.
        Runs of different models are read per model (the key ``repo · model``; a repository
        read with one model keeps its own name): the model is part of every prompt's key, so
        mixed they would share no prompt. An extraction run belongs to its session's first model.
        """
        answers: dict[tuple[str, str | None], dict[str, dict[str, dict[tuple[str, str], list[str | None]]]]] = {}
        call_logs: dict[str, list[dict[str, Any]]] = getattr(self, "call_logs", {})
        session_model = {sid: (info.get("config", {}).get("models") or [None])[0] for sid, info in getattr(self, "session_infos", {}).items()}

        def group_of(run_id: str) -> tuple[str, str, str | None] | None:
            parts = run_id.split(":")
            if len(parts) == 3 and parts[1] == "extraction":
                return "extraction", parts[2], session_model.get(parts[0])
            if len(parts) >= 2:
                return "derivation", parts[1], parts[2] if len(parts) >= 4 else None
            return None

        # (run, step, cache key, key without the benchmark run or None, decision)
        entries: list[tuple[str, str, str, str | None, str | None]] = []
        for session_id, ocel in self.ocel_logs.items():
            if session_id in call_logs:
                continue
            for event in ocel.events:
                step, key = event.attributes.get("config_id"), event.attributes.get("cache_key")
                if event.activity != "LLMQuery" or not step or not key:
                    continue
                for run_id in event.objects.get("BenchmarkRun", []):
                    entries.append((run_id, step, key, None, event.attributes.get("decision_hash") or event.attributes.get("response_hash")))
        for calls in call_logs.values():
            for call in calls:
                if call.get("step") and call.get("cache_key") and call.get("run_id"):
                    # Hashed as the event log records it (sessions read either way are compared); a failed call has no answer
                    content = call.get("response")
                    decision = hash_content(decision_content(content)) if content and not call.get("error") else None
                    entries.append((call["run_id"], call["step"], call["cache_key"], call_key(call), decision))
        # A call log keys a prompt without the benchmark run (--bench-hash puts the run into every cache key); a group
        # with a run read from its event log, which holds only the cache key, keys every run by the cache key
        by_cache_key = {(g[1], g[2]) for run_id, _, _, own, _ in entries if own is None and (g := group_of(run_id))}
        for run_id, step, cache, own, decision in entries:
            group = group_of(run_id)
            if group is None:
                continue
            family, repo, model = group
            key = cache if own is None or (repo, model) in by_cache_key else own
            answers.setdefault((repo, model), {}).setdefault(family, {}).setdefault(run_id, {}).setdefault((step, key), []).append(decision)
        # A combined session derives once over all repositories, under their joined name
        names = list(self.repositories) + (["_".join(sorted(self.repositories))] if len(self.repositories) > 1 else [])
        result: dict[str, list[AnswerStability]] = {}
        for repo in names:
            groups = {model: families for (name, model), families in answers.items() if name == repo}
            # An extraction run of an unknown model (no session info) belongs to the repository's only model
            if None in groups and len(groups) == 2:
                unknown = groups.pop(None)
                (families,) = groups.values()
                for family, runs in unknown.items():
                    families.setdefault(family, {}).update(runs)
            for model, families in sorted(groups.items(), key=lambda item: str(item[0])):
                key = repo if len(groups) == 1 else f"{repo} · {model}"
                result[key] = [s for family in ("extraction", "derivation") for s in compute_answer_stability(families.get(family, {}))]
        return result

    def analyze_semantic_match(self) -> dict[str, SemanticMatchReport]:
        """
        Compare derived models against reference models.

        Returns:
            Dict mapping repo -> SemanticMatchReport
        """
        if self._semantic_reports or self._skip_semantic:
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

    def generate_report(self, include_semantic: bool = True) -> BenchmarkReport:
        """
        Generate comprehensive benchmark report.

        Args:
            include_semantic: False skips the comparison with the reference models (and the fit and
                cross-repository parts that read it get no reference data)

        Returns:
            BenchmarkReport with all analysis results
        """
        if self._report:
            return self._report

        # Run all analyses
        self._skip_semantic = not include_semantic
        stability = self.analyze_stability()
        answer_stability = self.analyze_answer_stability()
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
            answer_stability=answer_stability,
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
                    total_elem = sum(b.total_count for b in derivation.element_breakdown)
                    stable_elem = sum(b.stable_count for b in derivation.element_breakdown)
                    elem_stability = stable_elem / total_elem if total_elem > 0 else 0.0

                    # Aggregate relationship stats
                    total_rel = sum(b.total_count for b in derivation.relationship_breakdown)
                    stable_rel = sum(b.stable_count for b in derivation.relationship_breakdown)
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
                            sem_report.total_reference_elements,
                            sem_report.total_derived_elements,
                            len(sem_report.correctly_derived),
                            f"{sem_report.element_precision:.3f}",
                            f"{sem_report.element_recall:.3f}",
                            f"{(2 * sem_report.element_precision * sem_report.element_recall / max(sem_report.element_precision + sem_report.element_recall, 0.001)):.3f}",
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
                validity = sem_report.element_precision if sem_report else 0.0

                # Type correct: Elements with matching ArchiMate type
                type_correct = 0.0
                if sem_report and sem_report.correctly_derived:
                    exact_matches = len([m for m in sem_report.correctly_derived if m.derived_type == m.reference_type])
                    type_correct = exact_matches / max(sem_report.total_derived_elements, 1)

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
                elif event.activity in ("LLMQuery", "LLMRequest", "llm_request"):  # older sessions used the last two
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
                    except TypeError, AttributeError:
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
