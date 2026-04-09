"""
Benchmark CLI commands.

Provides commands for multi-model benchmarking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import typer

from deriva.cli.progress import create_benchmark_progress_reporter
from deriva.services.session import PipelineSession

if TYPE_CHECKING:
    pass

app = typer.Typer(name="benchmark", help="Multi-model benchmarking")


def _get_run_stats_from_ocel(analyzer: Any) -> dict[str, list[tuple[int, int]]]:
    """Extract node/edge counts per run from OCEL CompleteRun events."""
    result: dict[str, list[tuple[int, int]]] = {}

    for event in analyzer.ocel_log.events:
        if event.activity != "CompleteRun":
            continue

        model = event.objects.get("Model", [None])[0]
        if not model:
            continue

        stats = event.attributes.get("stats", {})
        extraction = stats.get("extraction", {})
        nodes = extraction.get("nodes_created", 0)
        edges = extraction.get("edges_created", 0)

        if model not in result:
            result[model] = []
        result[model].append((nodes, edges))

    return result


@app.command("run")
def benchmark_run(
    repos: Annotated[
        str, typer.Option("--repos", help="Comma-separated list of repository names")
    ],
    models: Annotated[
        str, typer.Option("--models", help="Comma-separated list of model config names")
    ],
    runs: Annotated[
        int, typer.Option("-n", "--runs", help="Number of runs per combination")
    ] = 3,
    stages: Annotated[
        str | None, typer.Option("--stages", help="Comma-separated list of stages")
    ] = None,
    description: Annotated[
        str, typer.Option("-d", "--description", help="Session description")
    ] = "",
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Print detailed progress")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Disable progress bar")
    ] = False,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Disable LLM response caching")
    ] = False,
    nocache_configs: Annotated[
        str | None, typer.Option("--nocache-configs", help="Configs to skip cache for")
    ] = None,
    no_export_models: Annotated[
        bool, typer.Option("--no-export-models", help="Disable model export")
    ] = False,
    no_clear: Annotated[
        bool, typer.Option("--no-clear", help="Don't clear graph between runs")
    ] = False,
    bench_hash: Annotated[
        bool, typer.Option("--bench-hash", help="Per-run cache isolation")
    ] = False,
    defer_relationships: Annotated[
        bool, typer.Option("--defer-relationships", help="Two-phase derivation")
    ] = False,
    per_repo: Annotated[
        bool, typer.Option("--per-repo", help="Run each repo separately")
    ] = False,
    no_enrichment_cache: Annotated[
        bool, typer.Option("--no-enrichment-cache", help="Disable enrichment caching")
    ] = False,
    nocache_enrichment_configs: Annotated[
        str | None,
        typer.Option(
            "--nocache-enrichment-configs",
            help="Configs to skip enrichment cache for (comma-separated)",
        ),
    ] = None,
    no_cache_extraction: Annotated[
        bool,
        typer.Option(
            "--no-cache-extraction",
            help="Force full re-extraction (ignore fingerprint cache)",
        ),
    ] = False,
    no_cache_extraction_llm: Annotated[
        bool,
        typer.Option(
            "--no-cache-extraction-llm",
            help="Re-run LLM extraction steps only (keep structural/AST cached)",
        ),
    ] = False,
    only_extraction_step: Annotated[
        str | None,
        typer.Option(
            "--only-extraction-step",
            help="Only run this extraction step (disables all others)",
        ),
    ] = None,
    only_derivation_step: Annotated[
        str | None,
        typer.Option(
            "--only-derivation-step",
            help="Only run this derivation step (disables all others)",
        ),
    ] = None,
) -> None:
    """Run benchmark matrix."""
    repos_list = [r.strip() for r in repos.split(",")]
    models_list = [m.strip() for m in models.split(",")]
    stages_list = [s.strip() for s in stages.split(",")] if stages else None
    nocache_configs_list = (
        [c.strip() for c in nocache_configs.split(",")] if nocache_configs else None
    )
    nocache_enrichment_configs_list = (
        [c.strip() for c in nocache_enrichment_configs.split(",")]
        if nocache_enrichment_configs
        else None
    )

    use_cache = not no_cache
    use_enrichment_cache_flag = not no_enrichment_cache
    export_models = not no_export_models
    clear_between_runs = not no_clear

    # Calculate total runs based on mode
    if per_repo:
        total_runs = len(repos_list) * len(models_list) * runs
    else:
        total_runs = len(models_list) * runs

    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Multi-Model Benchmark")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"Repositories: {repos_list}")
    typer.echo(f"Models: {models_list}")
    typer.echo(f"Runs per combination: {runs}")
    typer.echo(f"Mode: {'per-repo' if per_repo else 'combined'}")
    typer.echo(f"Total runs: {total_runs}")
    if stages_list:
        typer.echo(f"Stages: {stages_list}")
    typer.echo(f"Cache: {'enabled' if use_cache else 'disabled'}")
    typer.echo(f"Export models: {'enabled' if export_models else 'disabled'}")
    typer.echo(f"Clear between runs: {'yes' if clear_between_runs else 'no'}")
    if bench_hash:
        typer.echo("Bench hash: enabled (per-run cache isolation)")
    if defer_relationships:
        typer.echo("Defer relationships: enabled (two-phase derivation)")
    if nocache_configs_list:
        typer.echo(f"No-cache configs: {nocache_configs_list}")
    typer.echo(
        f"Enrichment cache: {'enabled' if use_enrichment_cache_flag else 'disabled'}"
    )
    if nocache_enrichment_configs_list:
        typer.echo(f"No-cache enrichment configs: {nocache_enrichment_configs_list}")
    if no_cache_extraction:
        typer.echo("Extraction cache: disabled (full re-extraction)")
    elif no_cache_extraction_llm:
        typer.echo("Extraction cache: structural/AST only (LLM steps re-run)")
    typer.echo(f"{'=' * 60}\n")

    with PipelineSession() as session:
        typer.echo("Connected to grafeo")

        # Handle --only-extraction-step and --only-derivation-step
        if only_extraction_step:
            typer.echo(f"Enabling only extraction step: {only_extraction_step}")
            extraction_configs = session.get_extraction_configs()
            for cfg in extraction_configs:
                name = cfg.get("node_type", cfg.get("name", ""))
                if name == only_extraction_step:
                    session.enable_step("extraction", name)
                else:
                    session.disable_step("extraction", name)

        if only_derivation_step:
            typer.echo(f"Enabling only derivation step: {only_derivation_step}")
            derivation_configs = session.get_derivation_configs()
            for cfg in derivation_configs:
                name = cfg.get("step_name", cfg.get("name", ""))
                if name == only_derivation_step:
                    session.enable_step("derivation", name)
                else:
                    session.disable_step("derivation", name)

        progress_reporter = create_benchmark_progress_reporter(quiet=quiet or verbose)

        with progress_reporter:
            result = session.run_benchmark(
                repositories=repos_list,
                models=models_list,
                runs=runs,
                stages=stages_list,
                description=description,
                verbose=verbose,
                use_cache=use_cache,
                nocache_configs=nocache_configs_list,
                progress=progress_reporter,
                export_models=export_models,
                clear_between_runs=clear_between_runs,
                bench_hash=bench_hash,
                defer_relationships=defer_relationships,
                per_repo=per_repo,
                use_enrichment_cache=use_enrichment_cache_flag,
                nocache_enrichment_configs=nocache_enrichment_configs_list,
                no_cache_extraction=no_cache_extraction,
                no_cache_extraction_llm=no_cache_extraction_llm,
            )

        typer.echo(f"\n{'=' * 60}")
        typer.echo("BENCHMARK COMPLETE")
        typer.echo(f"{'=' * 60}")
        typer.echo(f"Session ID: {result.session_id}")
        typer.echo(f"Runs completed: {result.runs_completed}")
        typer.echo(f"Runs failed: {result.runs_failed}")
        typer.echo(f"Duration: {result.duration_seconds:.1f}s")
        typer.echo(f"OCEL log: {result.ocel_path}")
        if export_models:
            typer.echo(f"Model files: workspace/benchmarks/{result.session_id}/models/")

        if result.errors:
            typer.echo(f"\nErrors ({len(result.errors)}):")
            for err in result.errors[:5]:
                typer.echo(f"  - {err}")
            if len(result.errors) > 5:
                typer.echo(f"  ... and {len(result.errors) - 5} more")

        typer.echo("\nTo analyze results:")
        typer.echo(f"  deriva benchmark analyze {result.session_id}")

        if not result.success:
            raise typer.Exit(1)


@app.command("list")
def benchmark_list(
    limit: Annotated[
        int, typer.Option("-l", "--limit", help="Number of sessions to show")
    ] = 10,
) -> None:
    """List benchmark sessions."""
    with PipelineSession() as session:
        sessions = session.list_benchmarks(limit=limit)

        if not sessions:
            typer.echo("No benchmark sessions found.")
            return

        typer.echo(f"\n{'=' * 60}")
        typer.echo("BENCHMARK SESSIONS")
        typer.echo(f"{'=' * 60}")

        for s in sessions:
            status_icon = (
                ""
                if s["status"] == "completed"
                else ""
                if s["status"] == "failed"
                else ""
            )
            typer.echo(f"\n{status_icon} {s['session_id']}")
            typer.echo(f"    Status: {s['status']}")
            typer.echo(f"    Started: {s['started_at']}")
            if s.get("description"):
                typer.echo(f"    Description: {s['description']}")

        typer.echo("")


@app.command("analyze")
def benchmark_analyze(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID to analyze")],
    output: Annotated[
        str | None, typer.Option("-o", "--output", help="Output file for analysis")
    ] = None,
    format: Annotated[
        str, typer.Option("-f", "--format", help="Output format")
    ] = "json",
) -> None:
    """Analyze benchmark results."""
    if format not in ("json", "markdown"):
        typer.echo("Error: format must be 'json' or 'markdown'", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"ANALYZING BENCHMARK: {session_id}")
    typer.echo(f"{'=' * 60}\n")

    with PipelineSession() as session:
        try:
            analyzer = session.analyze_benchmark(session_id)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        # Compute and display summary
        summary = analyzer.compute_full_analysis()

        # Get raw node/edge counts per run from OCEL
        run_stats = _get_run_stats_from_ocel(analyzer)

        # Show extraction stats per model (from run stats)
        if run_stats:
            typer.echo("INTRA-MODEL CONSISTENCY (stability across runs)")
            typer.echo("-" * 75)
            typer.echo(f"  {'Model':<22} {'Nodes':<25} {'Edges':<25}")
            typer.echo(
                f"  {'':<22} {'Min-Max (Stable/Var)':<25} {'Min-Max (Stable/Var)':<25}"
            )
            typer.echo("-" * 75)
            for model, run_list in sorted(run_stats.items()):
                node_vals = [n for n, e in run_list]
                edge_vals = [e for n, e in run_list]
                node_min, node_max = min(node_vals), max(node_vals)
                edge_min, edge_max = min(edge_vals), max(edge_vals)
                node_var = node_max - node_min
                edge_var = edge_max - edge_min
                node_str = f"{node_min}-{node_max} ({node_min}/{node_var})"
                edge_str = f"{edge_min}-{edge_max} ({edge_min}/{edge_var})"
                typer.echo(f"  {model:<22} {node_str:<25} {edge_str:<25}")
            typer.echo("")

        # Intra-model consistency
        if summary.intra_model:
            typer.echo("STRUCTURAL EDGE CONSISTENCY (OCEL tracked)")
            typer.echo("-" * 70)
            typer.echo(f"  {'Model':<22} {'Stable':<10} {'Unstable':<10} {'%':<8}")
            typer.echo("-" * 70)
            for m in summary.intra_model:
                stable_edges = len(m.stable_edges)
                unstable_edges = len(m.unstable_edges)
                total_edges = stable_edges + unstable_edges
                edge_pct = (
                    (stable_edges / total_edges * 100) if total_edges > 0 else 100
                )
                typer.echo(
                    f"  {m.model:<22} {stable_edges:<10} {unstable_edges:<10} {edge_pct:.0f}%"
                )
            typer.echo("")

        # Inter-model consistency
        if summary.inter_model:
            typer.echo("INTER-MODEL CONSISTENCY (agreement across models)")
            typer.echo("-" * 70)
            for im in summary.inter_model:
                edges_sets = [set(e) for e in im.edges_by_model.values()]
                total_edges = len(set().union(*edges_sets)) if edges_sets else 0
                overlap_edges = len(im.edge_overlap)
                pct = im.edge_jaccard * 100
                typer.echo(f"  {im.repository}:")
                typer.echo(
                    f"    Structural edges: {overlap_edges}/{total_edges} stable ({pct:.0f}%)"
                )
            typer.echo("")

        # Hotspots
        if summary.localization.hotspots:
            typer.echo("INCONSISTENCY HOTSPOTS")
            typer.echo("-" * 50)
            for h in summary.localization.hotspots:
                typer.echo(
                    f"  [{h['severity'].upper()}] {h['type']}: {h['name']} ({h['consistency']:.1f}%)"
                )
            typer.echo("")

        # Export
        output_path = analyzer.export_summary(output, format=format)
        typer.echo(f"Analysis exported to: {output_path}")

        # Save to DB
        analyzer.save_metrics_to_db()
        typer.echo("Metrics saved to database.")


@app.command("models")
def benchmark_models() -> None:
    """List available model configurations."""
    with PipelineSession() as session:
        models_dict = session.list_benchmark_models()

    if not models_dict:
        typer.echo("\nNo benchmark model configurations found.")
        typer.echo("\nConfigure models in .env with pattern:")
        typer.echo("  LLM_BENCH_{NAME}_PROVIDER=azure|openai|anthropic|ollama")
        typer.echo("  LLM_BENCH_{NAME}_MODEL=model-id")
        typer.echo("  LLM_BENCH_{NAME}_URL=api-url (optional)")
        typer.echo("  LLM_BENCH_{NAME}_KEY=api-key (optional)")
        return

    typer.echo(f"\n{'=' * 60}")
    typer.echo("AVAILABLE BENCHMARK MODELS")
    typer.echo(f"{'=' * 60}\n")

    for name, cfg in sorted(models_dict.items()):
        typer.echo(f"  {name}")
        typer.echo(f"    Provider: {cfg.provider}")
        typer.echo(f"    Model: {cfg.model}")
        if cfg.api_url:
            typer.echo(f"    URL: {cfg.api_url[:50]}...")
        typer.echo("")


@app.command("deviations")
def benchmark_deviations(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID to analyze")],
    output: Annotated[
        str | None, typer.Option("-o", "--output", help="Output file")
    ] = None,
    sort_by: Annotated[
        str, typer.Option("-s", "--sort-by", help="Sort metric")
    ] = "deviation_count",
) -> None:
    """Analyze config deviations for a benchmark session."""
    if sort_by not in ("deviation_count", "consistency_score", "total_objects"):
        typer.echo(
            "Error: sort-by must be one of: deviation_count, consistency_score, total_objects",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"CONFIG DEVIATION ANALYSIS: {session_id}")
    typer.echo(f"{'=' * 60}\n")

    with PipelineSession() as session:
        try:
            analyzer = session.analyze_config_deviations(session_id)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        report = analyzer.analyze()

        typer.echo(f"Total runs analyzed: {report.total_runs}")
        typer.echo(f"Total deviations: {report.total_deviations}")
        typer.echo(f"Overall consistency: {report.overall_consistency:.1%}\n")

        if report.config_deviations:
            typer.echo("CONFIG DEVIATIONS (sorted by deviation count)")
            typer.echo("-" * 60)

            for cd in report.config_deviations:
                status = (
                    "LOW"
                    if cd.consistency_score >= 0.8
                    else "MEDIUM"
                    if cd.consistency_score >= 0.5
                    else "HIGH"
                )
                typer.echo(f"  [{status}] {cd.config_type}: {cd.config_id}")
                typer.echo(f"        Consistency: {cd.consistency_score:.1%}")
                typer.echo(
                    f"        Deviations: {cd.deviation_count}/{cd.total_objects}"
                )
                if cd.deviating_objects[:3]:
                    typer.echo(f"        Sample: {', '.join(cd.deviating_objects[:3])}")
                typer.echo("")

            from deriva.modules.analysis import generate_recommendations

            recommendations = generate_recommendations(report.config_deviations)
            if recommendations:
                typer.echo("RECOMMENDATIONS")
                typer.echo("-" * 60)
                for rec in recommendations:
                    typer.echo(f"  - {rec}")
                typer.echo("")

        if sort_by != "deviation_count":
            output_path = analyzer.export_sorted_json(output, sort_by=sort_by)
        else:
            output_path = analyzer.export_json(output)

        typer.echo(f"Report exported to: {output_path}")


@app.command("comprehensive-analysis")
def benchmark_comprehensive(
    session_ids: Annotated[
        list[str], typer.Argument(help="Benchmark session IDs to analyze")
    ],
    output: Annotated[
        str, typer.Option("-o", "--output", help="Output directory")
    ] = "workspace/analysis",
    format: Annotated[
        str, typer.Option("-f", "--format", help="Output format")
    ] = "both",
    no_semantic: Annotated[
        bool, typer.Option("--no-semantic", help="Skip semantic matching")
    ] = False,
) -> None:
    """Run comprehensive benchmark analysis."""
    if format not in ("json", "markdown", "both"):
        typer.echo("Error: format must be 'json', 'markdown', or 'both'", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo("BENCHMARK ANALYSIS")
    typer.echo(f"{'=' * 60}\n")
    typer.echo(f"Sessions: {', '.join(session_ids)}")

    from deriva.services.analysis import BenchmarkAnalyzer

    with PipelineSession() as session:
        try:
            analyzer = BenchmarkAnalyzer(
                session_ids=list(session_ids),
                engine=session._engine,
            )
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        typer.echo("\nRunning analysis...")
        report = analyzer.generate_report()

        typer.echo(f"\nRepositories: {', '.join(report.repositories)}")
        typer.echo(f"Models: {', '.join(report.models)}")
        typer.echo("\nOVERALL METRICS")
        typer.echo("-" * 40)
        typer.echo(f"  Consistency: {report.overall_consistency:.1%}")
        typer.echo(f"  Precision:   {report.overall_precision:.1%}")
        typer.echo(f"  Recall:      {report.overall_recall:.1%}")

        if report.stability_reports:
            typer.echo("\nPER-REPOSITORY STABILITY")
            typer.echo("-" * 40)
            for repo, phases in report.stability_reports.items():
                if "derivation" in phases:
                    typer.echo(
                        f"  {repo}: {phases['derivation'].overall_consistency:.1%} derivation consistency"
                    )

        if report.semantic_reports:
            typer.echo("\nSEMANTIC MATCH SUMMARY")
            typer.echo("-" * 40)
            for repo, sr in report.semantic_reports.items():
                typer.echo(
                    f"  {repo}: P={sr.element_precision:.1%} R={sr.element_recall:.1%} F1={sr.element_f1:.2f}"
                )

        if report.cross_repo:
            if report.cross_repo.best_element_types:
                typer.echo("\nBEST ELEMENT TYPES (highest consistency)")
                typer.echo("-" * 40)
                for t, score in report.cross_repo.best_element_types[:5]:
                    typer.echo(f"  {t}: {score:.1%}")

            if report.cross_repo.worst_element_types:
                typer.echo("\nWORST ELEMENT TYPES (lowest consistency)")
                typer.echo("-" * 40)
                for t, score in report.cross_repo.worst_element_types[:5]:
                    typer.echo(f"  {t}: {score:.1%}")

        if report.recommendations:
            typer.echo("\nRECOMMENDATIONS")
            typer.echo("-" * 40)
            for rec in report.recommendations[:10]:
                typer.echo(f"  - {rec}")

        typer.echo(f"\nExporting to: {output}")
        paths = analyzer.export_all(output)

        if format in ("json", "both"):
            typer.echo(f"  JSON: {paths.get('json', 'N/A')}")
        if format in ("markdown", "both"):
            typer.echo(f"  Markdown: {paths.get('markdown', 'N/A')}")
