"""
Benchmark CLI commands.

Provides commands for multi-model benchmarking.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from deriva.bench.session import BenchmarkSession
from deriva.cli.progress import create_benchmark_progress_reporter  # noqa: TID251 - the benchmark command is the one module that may use the CLI
from deriva.common.paths import workspace
from deriva.services.session import PipelineSession

if TYPE_CHECKING:
    pass

app = typer.Typer(name="benchmark", help="Multi-model benchmarking")


@contextmanager
def _benchmarks() -> Generator[BenchmarkSession]:
    """A connected PipelineSession with the benchmark operations."""
    with PipelineSession() as session:
        yield BenchmarkSession(session)


def _in_every_run(stable: list[str], unstable: dict[str, int]) -> str:
    """Objects in every run of all logged: 'stable/total (pct)', or '-' when none were logged."""
    total = len(stable) + len(unstable)
    return f"{len(stable)}/{total} ({len(stable) / total:.1%})" if total else "-"


@app.command("run")
def benchmark_run(
    repos: Annotated[str, typer.Option("--repos", help="Comma-separated list of repository names")],
    models: Annotated[str, typer.Option("--models", help="Comma-separated list of model config names")],
    runs: Annotated[int, typer.Option("-n", "--runs", help="Number of runs per combination", min=1)] = 3,
    stages: Annotated[str | None, typer.Option("--stages", help="Comma-separated list of stages")] = None,
    description: Annotated[str, typer.Option("-d", "--description", help="Session description")] = "",
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Print detailed progress")] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet", help="Disable progress bar")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Disable LLM response caching")] = False,
    nocache_configs: Annotated[str | None, typer.Option("--nocache-configs", help="Configs to skip cache for")] = None,
    no_export_models: Annotated[bool, typer.Option("--no-export-models", help="Disable model export")] = False,
    no_clear: Annotated[bool, typer.Option("--no-clear", help="Don't clear graph between runs")] = False,
    bench_hash: Annotated[bool, typer.Option("--bench-hash", help="Per-run cache isolation")] = False,
    defer_relationships: Annotated[
        bool,
        typer.Option(
            "--defer-relationships/--no-defer-relationships",
            help="Two-phase derivation: elements first, then the relationship pass (default). "
            "Without it, relationships come per batch and the structural tiers (containment, membership, configuration, dependency, same name) do not run",
        ),
    ] = True,
    per_repo: Annotated[bool, typer.Option("--per-repo", help="Run each repo separately")] = False,
    no_cache_extraction: Annotated[
        bool,
        typer.Option(
            "--no-cache-extraction",
            help="Force full re-extraction (ignore fingerprint cache; LLM answers still come from the LLM cache unless --no-cache)",
        ),
    ] = False,
    no_cache_extraction_llm: Annotated[
        bool,
        typer.Option(
            "--no-cache-extraction-llm",
            help="Re-run LLM extraction steps only (keep structural/AST cached; LLM answers still come from the LLM cache unless --no-cache)",
        ),
    ] = False,
    extract_per_run: Annotated[
        bool,
        typer.Option(
            "--extract-per-run",
            help="Every run repeats the complete pipeline: extraction with the run's model, no cache, on its own graph "
            "(kept in the session's graphs folder). Needs --stages extraction,derivation and --no-cache",
        ),
    ] = False,
    baseline: Annotated[
        str | None,
        typer.Option(
            "--baseline",
            help="Run a baseline instead of Deriva: b1 (one generation of the whole model from raw repository material, "
            "validated and repaired at most N times; the BaselineB1 config row). Needs --no-cache",
        ),
    ] = None,
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
    nocache_configs_list = [c.strip() for c in nocache_configs.split(",")] if nocache_configs else None

    use_cache = not no_cache
    export_models = not no_export_models
    clear_between_runs = not no_clear
    from deriva.bench.benchmarking import BenchmarkConfig, validate_config

    try:
        validate_config(
            BenchmarkConfig(
                repositories=repos_list,
                models=models_list,
                stages=stages_list or ["extraction", "derivation"],
                use_cache=use_cache,
                extract_per_run=extract_per_run,
                baseline=baseline,
            )
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

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
    if no_cache_extraction:
        typer.echo("Extraction cache: disabled (full re-extraction)")
    elif no_cache_extraction_llm:
        typer.echo("Extraction cache: structural/AST only (LLM steps re-run)")
    if extract_per_run:
        typer.echo("Extraction: per run (the run's model, no cache, a graph per run)")
    typer.echo(f"{'=' * 60}\n")

    with _benchmarks() as session:
        typer.echo("Connected to grafeo")

        # Handle --only-extraction-step and --only-derivation-step
        if only_extraction_step:
            typer.echo(f"Enabling only extraction step: {only_extraction_step}")
            extraction_configs = session.get_extraction_configs()
            if only_extraction_step not in {cfg.get("node_type", cfg.get("name", "")) for cfg in extraction_configs}:
                typer.echo(f"Error: no extraction step named {only_extraction_step!r}", err=True)
                raise typer.Exit(1)
            for cfg in extraction_configs:
                name = cfg.get("node_type", cfg.get("name", ""))
                if name == only_extraction_step:
                    session.enable_step("extraction", name)
                else:
                    session.disable_step("extraction", name)

        if only_derivation_step:
            typer.echo(f"Enabling only derivation step: {only_derivation_step}")
            derivation_configs = session.get_derivation_configs()
            if only_derivation_step not in {cfg.get("step_name", cfg.get("name", "")) for cfg in derivation_configs}:
                typer.echo(f"Error: no derivation step named {only_derivation_step!r}", err=True)
                raise typer.Exit(1)
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
                no_cache_extraction=no_cache_extraction,
                no_cache_extraction_llm=no_cache_extraction_llm,
                extract_per_run=extract_per_run,
                baseline=baseline,
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
            typer.echo(f"Model files: {workspace() / 'benchmarks' / result.session_id / 'models'}")

        if result.errors:
            typer.echo(f"\nErrors ({len(result.errors)}):")
            for err in result.errors[:5]:
                typer.echo(f"  - {err}")
            if len(result.errors) > 5:
                typer.echo(f"  ... and {len(result.errors) - 5} more")

        typer.echo("\nTo analyze results:")
        typer.echo(f"  deriva-cli benchmark analyze {result.session_id}")

        if not result.success:
            raise typer.Exit(1)


@app.command("step")
def benchmark_step(
    step: Annotated[
        str,
        typer.Argument(help="Step to repeat: an extraction or derivation step (for example BusinessConcept, DataObject, ConsolidatedRelationships), or prep for the prep phase"),
    ],
    repos: Annotated[str, typer.Option("--repos", help="Comma-separated list of repository names")],
    model: Annotated[str, typer.Option("--model", help="Model config name")],
    runs: Annotated[int, typer.Option("-n", "--runs", help="Runs per repository", min=1)] = 3,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Print detailed progress")] = False,
) -> None:
    """Repeat one step on a fixed input per repository and compare its outputs.

    The step's input (every earlier step) is built once from the LLM cache. Each run
    starts from a copy of it and calls the LLM for the step without the cache.
    """
    repos_list = [r.strip() for r in repos.split(",")]
    with _benchmarks() as session:
        result = session.run_step_benchmark(step, repositories=repos_list, model=model, runs=runs, verbose=verbose)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"STEP BENCHMARK: {result.step}")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"{'Repository':30} {'Presence':>9} {'Exact':>8}  Objects per run  Live LLM calls per run")
    for repo, consistency in result.repositories.items():
        counts = "/".join(str(n) for n in consistency.counts)
        calls = "/".join(str(n) for n in result.llm_calls.get(repo, []))
        typer.echo(f"{repo:30} {consistency.presence_score:9.1%} {consistency.exact_score:8.1%}  {counts:15}  {calls}")
        for group, scores in consistency.groups.items():
            typer.echo(f"  {group:28} {scores.presence_score:9.1%} {scores.exact_score:8.1%}  {'/'.join(str(n) for n in scores.counts)}")
        if consistency.property_differences:
            typer.echo("  differing properties: " + ", ".join(f"{name} {n}" for name, n in consistency.property_differences.items()))
        for stability in result.answer_stability.get(repo, []):
            if stability.step == result.step:
                typer.echo(f"  answer stability: {stability.identical}/{stability.prompts} ({stability.score:.1%})")
        if repo in result.decision_stability:
            decided = result.decision_stability[repo]
            typer.echo(f"  decision stability: {decided.stable}/{decided.items} ({decided.score:.1%})")
        if repo in result.output_stability:
            effect = result.output_stability[repo]
            typer.echo(f"  output stability: {effect.stable}/{effect.items} ({effect.score:.1%})")
    presence, exact = result.average("presence_score"), result.average("exact_score")
    if presence is not None and exact is not None:
        typer.echo(f"{'Average':30} {presence:9.1%} {exact:8.1%}")
    if result.unscored:
        typer.echo(f"Reported, not scored in exact: {', '.join(result.unscored)}")

    typer.echo(f"\nSession ID: {result.session_id}")
    typer.echo(f"Duration: {result.duration_seconds:.1f}s")
    typer.echo(f"Results: {workspace() / 'benchmarks' / result.session_id / 'step_results.json'}")
    if result.errors:
        typer.echo(f"\nErrors ({len(result.errors)}):")
        for err in result.errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)


@app.command("list")
def benchmark_list(
    limit: Annotated[int, typer.Option("-l", "--limit", help="Number of sessions to show")] = 10,
) -> None:
    """List benchmark sessions."""
    with _benchmarks() as session:
        sessions = session.list_benchmarks(limit=limit)

        if not sessions:
            typer.echo("No benchmark sessions found.")
            return

        typer.echo(f"\n{'=' * 60}")
        typer.echo("BENCHMARK SESSIONS")
        typer.echo(f"{'=' * 60}")

        for s in sessions:
            status_icon = "" if s["status"] == "completed" else "" if s["status"] == "failed" else ""
            typer.echo(f"\n{status_icon} {s['session_id']}")
            typer.echo(f"    Status: {s['status']}")
            typer.echo(f"    Started: {s['started_at']}")
            if s.get("description"):
                typer.echo(f"    Description: {s['description']}")

        typer.echo("")


def _megabytes(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


@app.command("delete")
def benchmark_delete(
    session_ids: Annotated[list[str], typer.Argument(help="Benchmark sessions to delete")],
) -> None:
    """Delete benchmark sessions with their runs, metrics and folders (a running session is refused)."""
    failed = False
    with _benchmarks() as session:
        for session_id in session_ids:
            try:
                result = session.delete_benchmark(session_id)
            except KeyError:
                typer.echo(f"Error: Benchmark session not found: {session_id}", err=True)
                failed = True
                continue
            except ValueError as e:
                typer.echo(f"Error: {e}", err=True)
                failed = True
                continue
            typer.echo(f"Deleted {session_id} ({result['runs']} runs, {_megabytes(result['bytes'])})")
    if failed:
        raise typer.Exit(1)


@app.command("prune")
def benchmark_prune(
    keep: Annotated[int | None, typer.Option("--keep", min=0, help="Keep the latest N sessions, delete the older ones")] = None,
    failed: Annotated[bool, typer.Option("--failed", help="Delete the failed sessions")] = False,
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Do not ask first")] = False,
) -> None:
    """Delete the failed sessions, or every session past the latest N, with their runs, metrics and folders; running sessions stay."""
    if keep is None and not failed:
        typer.echo("Error: say which sessions to delete: --keep N or --failed", err=True)
        raise typer.Exit(1)
    which = "the failed sessions" if failed else f"every session past the latest {keep}"
    if not yes and not typer.confirm(f"Delete {which}, with their runs, metrics and folders?"):
        raise typer.Exit(1)
    with _benchmarks() as session:
        deleted = session.prune_benchmarks(keep=None if failed else keep, failed=failed)
    if not deleted:
        typer.echo("No sessions to delete.")
        return
    typer.echo(f"Deleted {len(deleted)} session{'' if len(deleted) == 1 else 's'}: {', '.join(deleted)}")


@app.command("conventions")
def benchmark_conventions(
    session_ids: Annotated[list[str], typer.Argument(help="Benchmark sessions whose run snapshots are checked")],
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output folder (default: workspace/analysis/conventions/<first session>)")] = None,
    run: Annotated[int | None, typer.Option("--run", help="Check only this run number (default: every run)")] = None,
) -> None:
    """ArchiMate convention checklist: a review page per repository and model, a summary and a JSON with the findings."""
    from deriva.bench.conventions_report import write_reports

    out = output or str(workspace() / "analysis" / "conventions" / session_ids[0])
    try:
        payload = write_reports(list(session_ids), out, run=run)
    except (FileNotFoundError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Checked {len(payload['results'])} repositories; summary: {out}/summary.md")
    for name, page in payload["pages"].items():
        typer.echo(f"  {name}: {page}")


@app.command("reference")
def benchmark_reference(
    session_id: Annotated[str, typer.Argument(help="Benchmark session whose exported runs are evaluated")],
    run: Annotated[int | None, typer.Option("--run", help="Evaluate only this run number (default: every run)")] = None,
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output folder (default: workspace/analysis/reference/<session>)")] = None,
    references: Annotated[str | None, typer.Option("--references", help="Reference model folder (default: workspace/goldens/dev)")] = None,
    benchmarks: Annotated[str | None, typer.Option("--benchmarks", help="Benchmark folder (default: workspace/benchmarks)")] = None,
) -> None:
    """Recall and precision against the development reference models, per element type, relationship kind and chain."""
    from deriva.bench.reference_eval import evaluate_session, table_lines, write_report

    session_dir = (Path(benchmarks) if benchmarks else workspace() / "benchmarks") / session_id
    if not (session_dir / "models").is_dir():
        typer.echo(f"Error: no exported models in {session_dir}", err=True)
        raise typer.Exit(1)
    payload = evaluate_session(session_dir, references or workspace() / "goldens" / "dev", run=run)
    if not payload["repositories"]:
        typer.echo("Error: no exported run has a reference model", err=True)
        raise typer.Exit(1)
    for line in table_lines(payload):
        typer.echo(line)
    pages = write_report(payload, output or workspace() / "analysis" / "reference" / session_id)
    typer.echo(f"Summary and pages: {Path(next(iter(pages.values()))).parent}")


@app.command("gate")
def benchmark_gate(
    baseline: Annotated[str, typer.Option("--baseline", help="Comma-separated sessions of the baseline (one or more per repository)")],
    candidate: Annotated[str | None, typer.Option("--candidate", help="Comma-separated sessions of the change (without it: the baseline's table)")] = None,
    model: Annotated[str | None, typer.Option("--model", help="The model config to read when the sessions hold several")] = None,
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output folder (default: workspace/analysis/gate/<baseline>[_vs_<candidate>])")] = None,
    goldens: Annotated[str | None, typer.Option("--goldens", help="Development reference folder (default: workspace/goldens/dev)")] = None,
    reference: Annotated[str | None, typer.Option("--reference", help="Golden model folder (default: workspace/reference)")] = None,
    benchmarks: Annotated[str | None, typer.Option("--benchmarks", help="Benchmark folder (default: workspace/benchmarks)")] = None,
) -> None:
    """Element and relationship recall and precision and consistency by id per repository, and the verdict of a candidate.

    Accepted when one of the four measures rises by 1 point or more on at least two thirds of the measured repositories,
    none of them drops by more than 2 points anywhere, and element and relationship consistency by id stay at 95% or more.
    """
    from deriva.bench import gate

    root = Path(benchmarks) if benchmarks else workspace() / "benchmarks"
    goldens_dir = Path(goldens) if goldens else workspace() / "goldens" / "dev"
    reference_dir = Path(reference) if reference else workspace() / "reference"
    sides = {"baseline": [s.strip() for s in baseline.split(",") if s.strip()], "candidate": [s.strip() for s in (candidate or "").split(",") if s.strip()]}
    for side in sides.values():
        if missing := [s for s in side if not (root / s / "session_metadata.json").is_file()]:
            typer.echo(f"Error: no benchmark session {', '.join(missing)} in {root}", err=True)
            raise typer.Exit(1)
    try:
        measures = {
            level: {name: gate.measure([root / s for s in side], goldens_dir, reference_dir, model=model, level=level) for name, side in sides.items() if side}
            for level in gate.GATE_LEVELS
        }
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    lines = [f"# Gate: {', '.join(sides['baseline'])}" + (f" vs {', '.join(sides['candidate'])}" if sides["candidate"] else ""), ""]
    payload: dict = {"sessions": sides, "levels": {}}
    for level, by_side in measures.items():
        lines += [f"## {level.capitalize()} level", ""]
        lines += gate.table_markdown(by_side["baseline"], f"Baseline ({', '.join(sides['baseline'])})")
        lines += gate.types_markdown(by_side["baseline"])
        payload["levels"][level] = {"baseline": by_side["baseline"]}
        if "candidate" in by_side:
            lines += gate.table_markdown(by_side["candidate"], f"Candidate ({', '.join(sides['candidate'])})")
            lines += gate.types_markdown(by_side["candidate"])
            payload["levels"][level] |= {"candidate": by_side["candidate"], "verdict": gate.verdict(by_side["baseline"], by_side["candidate"])}
            lines += gate.verdict_markdown(payload["levels"][level]["verdict"])
    if sides["candidate"]:
        result, voting = gate.overall_verdict({level: entry["verdict"] for level, entry in payload["levels"].items()})
        payload["verdict"] = {"verdict": result, "levels": voting}
        lines += [f"**Overall: {result}** (levels that voted: {', '.join(voting) or 'none'})", ""]
    for line in lines:
        typer.echo(line)
    name = "_".join(sides["baseline"]) + (f"_vs_{'_'.join(sides['candidate'])}" if sides["candidate"] else "")
    paths = gate.write(Path(output) if output else workspace() / "analysis" / "gate" / name, payload, lines)
    typer.echo(f"Written: {paths['markdown']} and gate.json")


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _print_consistency(rows: list[dict]) -> None:
    header = f"{'Repository':<24} {'Model':<18} {'Runs':>4}  {'id: E / J':<11} {'R / J':<11} {'name: E / J':<12} {'R / J':<11} {'LLM part E / R (n)':<20} Layers B/A/T"
    typer.echo("-" * len(header))
    typer.echo(header)
    typer.echo("-" * len(header))
    for r in rows:
        i, n = r["identities"]["id"], r["identities"]["name"]
        llm = i["origin"]["llm"]
        layers = "/".join(_pct(i["layers"].get(layer)) for layer in ("Business", "Application", "Technology"))
        typer.echo(
            f"{r['repository'][:24]:<24} {r['model'][:18]:<18} {r['runs']:>4}  "
            f"{_pct(i['elements']['cons']) + ' / ' + _pct(i['elements']['jbar']):<11} {_pct(i['relationships']['cons']) + ' / ' + _pct(i['relationships']['jbar']):<11} "
            f"{_pct(n['elements']['cons']) + ' / ' + _pct(n['elements']['jbar']):<12} {_pct(n['relationships']['cons']) + ' / ' + _pct(n['relationships']['jbar']):<11} "
            f"{_pct(llm['elements']) + ' / ' + _pct(llm['relationships']) + f' ({llm["count"]})':<20} {layers}"
        )
    typer.echo("")


def _print_metrics_report(metrics: dict) -> None:
    """Consistency by identity (cons, J), layers and origin, the two-level table and the out-of-candidate rate."""
    if not metrics:
        return
    if metrics.get("consistency"):
        typer.echo("CONSISTENCY BY IDENTITY (cons / mean pairwise Jaccard; id = source-derived, name = type + name key; LLM part by id)")
        _print_consistency(metrics["consistency"])
    levels = metrics.get("consistency_levels") or {}
    if any(levels.values()):
        typer.echo("CONSISTENCY PER LEVEL (by id, elements / relationships; solution: direct relationships only, enterprise: the derived viewpoint)")
        header = f"{'Repository':<24} {'Model':<18} {'Solution E / R':<16} {'Enterprise E / R':<16}"
        typer.echo("-" * len(header))
        typer.echo(header)
        typer.echo("-" * len(header))
        by_key = {level: {(r["repository"], r["model"]): r["identities"]["id"] for r in rows} for level, rows in levels.items()}
        for key in sorted({k for rows in by_key.values() for k in rows}):
            cells = [by_key.get(level, {}).get(key) for level in ("solution", "enterprise")]
            shown = [f"{_pct(c['elements']['cons'])} / {_pct(c['relationships']['cons'])}" if c else "-" for c in cells]
            typer.echo(f"{key[0][:24]:<24} {key[1][:18]:<18} {shown[0]:<16} {shown[1]:<16}")
        typer.echo("")
    if metrics.get("two_level"):
        typer.echo("TWO LEVELS (answers: same prompt answered alike; decisions: each item decided alike; alpha: Krippendorff, nominal)")
        header = f"{'Repository':<24} {'Model':<18} {'Decision':<36} {'Answers':>9} {'Decisions':>11} {'alpha':>6}"
        typer.echo("-" * len(header))
        typer.echo(header)
        typer.echo("-" * len(header))
        for r in metrics["two_level"]:
            answers = f"{r['answers']['identical']}/{r['answers']['prompts']}" if r["answers"]["prompts"] else "-"
            decisions = f"{r['decisions']['stable']}/{r['decisions']['items']}" if r["decisions"]["items"] else "-"
            alpha = "-" if r["alpha"] is None else f"{r['alpha']:.2f}"
            typer.echo(f"{r['repository'][:24]:<24} {r['model'][:18]:<18} {r['decision'][:36]:<36} {answers:>9} {decisions:>11} {alpha:>6}")
        typer.echo("")
    if metrics.get("out_of_candidates"):
        typer.echo("OUT OF CANDIDATES (per model and decision type: calls, typed answers asked again, answers outside the candidates)")
        for r in metrics["out_of_candidates"]:
            typer.echo(f"  {r['model'][:24]:<24} {r['decision'][:36]:<36} {r['calls']:>5} calls  {r['re_asked']:>3} asked again  {r['outside']:>3} outside")
        typer.echo("")


@app.command("analyze")
def benchmark_analyze(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID to analyze")],
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output file for analysis")] = None,
    format: Annotated[str, typer.Option("-f", "--format", help="Output format")] = "json",
    also: Annotated[
        list[str] | None,
        typer.Option("--also", help="Further sessions (other LLMs on the same repositories): agreement across all their runs"),
    ] = None,
) -> None:
    """Analyze benchmark results."""
    if format not in ("json", "markdown"):
        typer.echo("Error: format must be 'json' or 'markdown'", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"ANALYZING BENCHMARK: {session_id}")
    typer.echo(f"{'=' * 60}\n")

    with _benchmarks() as session:
        try:
            analyzer = session.analyze_benchmark(session_id)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        # Compute and display summary
        summary = analyzer.compute_full_analysis()

        # Consistency compares runs of one repository and model; intra-model metrics exist only for pairs with 2 runs or more
        if not summary.intra_model:
            typer.echo("CONSISTENCY")
            typer.echo("-" * 75)
            typer.echo("  Not measured: consistency needs at least 2 runs of a repository with a model (run with -n 2 or more).")
            typer.echo("")
        else:
            typer.echo("INTRA-MODEL CONSISTENCY (objects created in every run of a repository with a model)")
            typer.echo("-" * 100)
            typer.echo(f"  {'Repository':<28} {'Model':<22} {'Runs':>4}  {'Elements':<16} {'Relationships':<16} {'Edges':<16}")
            typer.echo("-" * 100)
            for m in summary.intra_model:
                elements = _in_every_run(m.stable_elements, m.unstable_elements)
                relationships = _in_every_run(m.stable_relationships, m.unstable_relationships)
                edges = _in_every_run(m.stable_edges, m.unstable_edges)
                typer.echo(f"  {m.repository[:28]:<28} {m.model[:22]:<22} {m.runs:>4}  {elements:<16} {relationships:<16} {edges:<16}")
            typer.echo("  -: none logged.")
            if all(m.edge_consistency is None for m in summary.intra_model):
                typer.echo("  Edges are not compared: the runs of a session share one extraction per repository.")
            typer.echo("")

        # Inter-model consistency
        if summary.inter_model:
            typer.echo("INTER-MODEL CONSISTENCY (objects every model created, of all created)")
            typer.echo("-" * 70)
            for im in summary.inter_model:
                typer.echo(f"  {im.repository}:")
                for label, by_model, overlap in (
                    ("Elements", im.elements_by_model, im.overlap),
                    ("Relationships", im.relationships_by_model, im.relationship_overlap),
                    ("Edges", im.edges_by_model, im.edge_overlap),
                ):
                    total = len(set().union(*(set(objects) for objects in by_model.values())))
                    if total:
                        typer.echo(f"    {label}: {len(overlap)}/{total} ({len(overlap) / total:.0%})")
            typer.echo("")

        # Hotspots
        if summary.model_quality:
            typer.echo("MODEL QUALITY (structure of each exported model)")
            header = (
                f"{'Repository':<24} {'Model':<18} {'Run':>3} {'Elem':>5} {'Rel':>5} {'Per el':>6} {'Orphan%':>7} {'Comp.viol':>9} {'Double':>6} {'Dupl.el':>7} {'Ref P / R':>11}"
            )
            typer.echo("-" * len(header))
            typer.echo(header)
            typer.echo("-" * len(header))
            for q in summary.model_quality:
                ref = q.get("reference")
                ref_text = f"{ref['precision']:.2f} / {ref['recall']:.2f}" if ref else "-"
                typer.echo(
                    f"{q['repository'][:24]:<24} {q['model'][:18]:<18} {q['run']:>3} {q['elements']:>5} {q['relationships']:>5} "
                    f"{q['relationships_per_element']:>6.2f} {q['orphan_share']:>7.0%} {q['composition_violations']:>9} "
                    f"{q['duplicate_pairs']:>6} {q['duplicate_elements']:>7} {ref_text:>11}"
                )
                chains = ", ".join(f"{name} {linked}/{total}" for name, (linked, total) in q.get("chains", {}).items())
                if chains:
                    typer.echo(f"    chains: {chains}")
            typer.echo("")

        if summary.detail_level:
            typer.echo("DETAIL LEVEL (the export's members of the architect elements; not in the numbers above)")
            header = f"{'Repository':<24} {'Model':<18} {'Runs':>4} {'Elem':>6} {'Elem cons.':>10} {'Rel cons.':>9}  By type"
            typer.echo("-" * len(header))
            typer.echo(header)
            typer.echo("-" * len(header))
            for d in summary.detail_level:
                by_type = ", ".join(f"{t} {n:g}" for t, n in d["by_type"].items()) or "-"
                typer.echo(
                    f"{d['repository'][:24]:<24} {d['model'][:18]:<18} {d['runs']:>4} {d['elements']:>6.1f} "
                    f"{d['element_consistency']:>10.0%} {d['relationship_consistency']:>9.0%}  {by_type}"
                )
            typer.echo("")

        if summary.extraction_stability or summary.variance_split:
            # Extraction per run: how stable each LLM extraction step is, and which share of the differences it causes
            from deriva.bench.analysis import BenchmarkAnalyzer as ReportAnalyzer

            answers = ReportAnalyzer([session_id], session._engine).analyze_answer_stability()
            typer.echo("EXTRACTION PER RUN (each run extracted with its model, no cache)")
            header = f"{'Repository':<24} {'Model':<18} {'Step':<24} {'Decisions':>12} {'Answers':>12}"
            typer.echo("-" * len(header))
            typer.echo(header)
            typer.echo("-" * len(header))
            for row in summary.extraction_stability:
                per_step = {a.step: a for key, found in answers.items() if key in (row["repository"], f"{row['repository']} · {row['model']}") for a in found}
                for step, d in row["steps"].items():
                    a = per_step.get(step)
                    decided = f"{d['stable']}/{d['items']}" if d["items"] else "-"
                    answered = f"{a.identical}/{a.prompts}" if a and a.prompts else "-"
                    typer.echo(f"{row['repository'][:24]:<24} {row['model'][:18]:<18} {step[:24]:<24} {decided:>12} {answered:>12}")
            typer.echo("")
            if summary.variance_split:
                typer.echo("VARIANCE SPLIT (a missing element or relationship: its source node missing too = extraction, else derivation)")
                header = f"{'Repository':<24} {'Model':<18} {'Runs':>4}  {'Elements extr/deriv':<22} {'Relationships extr/deriv':<26}"
                typer.echo("-" * len(header))
                typer.echo(header)
                typer.echo("-" * len(header))
                for v in summary.variance_split:

                    def text(part: dict) -> str:
                        share = part["extraction_share"]
                        return f"{part['extraction']}/{part['derivation']}" + (f" ({share:.0%} extr.)" if share is not None else "")

                    typer.echo(f"{v['repository'][:24]:<24} {v['model'][:18]:<18} {v['runs']:>4}  {text(v['elements']):<22} {text(v['relationships']):<26}")
                typer.echo("")

        _print_metrics_report(summary.metrics)
        if also:
            from deriva.bench import session_metrics

            sessions = [workspace() / "benchmarks" / s for s in [session_id, *also]]
            agreement = [r for r in session_metrics.consistency_rows(sessions) if r["model"] == session_metrics.ALL_MODELS]
            typer.echo(f"AGREEMENT ACROSS LLMS ({', '.join([session_id, *also])})")
            _print_consistency(agreement)
            target = workspace() / "benchmarks" / session_id / "analysis" / "agreement.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"sessions": [session_id, *also], "agreement": agreement}, indent=1), encoding="utf-8")
            typer.echo(f"  -> {target}")
            typer.echo("")

        if summary.naming_fallbacks:
            typer.echo("NAME CHOICES (closed set; an unusable answer takes the structural first candidate)")
            for f in summary.naming_fallbacks:
                share = f["unusable"] / f["choices"] if f["choices"] else 0.0
                typer.echo(f"  {f['model']:<28} {f['unusable']}/{f['choices']} unusable ({share:.1%}): {f['unparsable']} no JSON, {f['outside']} outside the candidates")
            typer.echo("")

        solves = [q for q in summary.model_quality if q.get("solve")]
        if solves:
            typer.echo("MILP SAFETY NET (joint_consistency per run)")
            header = (
                f"{'Repository':<24} {'Model':<18} {'Run':>3} {'Status':<9} {'Props':>5} {'Merge c.':>8} {'Vars':>5} {'Cons':>5} "
                f"{'Rows (H1-H6)':<22} {'Cuts':>4} {'Kept':>5} {'Drop':>4} {'Merge':>5} {'Redir':>5} {'Sec':>6}"
            )
            typer.echo("-" * len(header))
            typer.echo(header)
            typer.echo("-" * len(header))
            for q in solves:
                s = q["solve"]
                rows = ", ".join(f"{k} {v}" for k, v in sorted((s.get("rows") or {}).items())) or "-"
                typer.echo(
                    f"{q['repository'][:24]:<24} {str(q.get('model') or '-')[:18]:<18} {q['run']:>3} {str(s.get('status'))[:9]:<9} {s.get('proposals', 0):>5} "
                    f"{s.get('merge_candidates', 0):>8} {s.get('variables', '-'):>5} {s.get('constraints', '-'):>5} {rows[:22]:<22} "
                    f"{s.get('cycle_cuts', 0):>4} {s.get('kept', 0):>5} {s.get('dropped', 0):>4} {s.get('merges', 0):>5} {s.get('redirects', 0):>5} {s.get('seconds', 0):>6.3f}"
                )
            typer.echo("")

        if summary.localization.hotspots:
            typer.echo("INCONSISTENCY HOTSPOTS")
            typer.echo("-" * 50)
            for h in summary.localization.hotspots:
                typer.echo(f"  [{h['severity'].upper()}] {h['type']}: {h['name']} ({h['consistency']:.1f}%)")
            typer.echo("")

        # Export
        output_path = analyzer.export_summary(output, format=format)
        typer.echo(f"Analysis exported to: {output_path}")

        # Save to DB
        analyzer.save_metrics_to_db()
        typer.echo("Metrics saved to database.")


@app.command("export")
def benchmark_export(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID")],
    output: Annotated[str, typer.Option("-o", "--output", help="Zip file to write")],
) -> None:
    """Export a benchmark session as one zip: logs, LLM calls, models, config texts, environment, sha256 manifest."""
    with _benchmarks() as session:
        try:
            manifest = session.export_benchmark(session_id, output)
        except (FileNotFoundError, ValueError) as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e

    typer.echo(f"Exported {manifest['session_id']}: {len(manifest['files'])} files with sha256 manifest -> {output}")


@app.command("mark-failed")
def benchmark_mark_failed(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID")],
) -> None:
    """End a session whose process stopped without finishing (still 'running') as failed; its files stay."""
    with _benchmarks() as session:
        try:
            runs = session.mark_benchmark_failed(session_id)
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e
    typer.echo(f"Marked {session_id} failed ({runs} unfinished run{'s' if runs != 1 else ''} with it).")


@app.command("ocel")
def benchmark_ocel(
    sessions: Annotated[str, typer.Argument(help="Comma-separated benchmark session IDs")],
    output: Annotated[str, typer.Option("-o", "--output", help="Folder to write ocel.json, cases.csv and cases.xes to")],
) -> None:
    """Export the event logs of sessions for process mining: OCEL 2.0 and a flat case log (one case per run, CSV and XES)."""
    session_ids = [s.strip() for s in sessions.split(",") if s.strip()]
    with _benchmarks() as session:
        try:
            paths = session.export_process_logs(session_ids, output)
        except (FileNotFoundError, ValueError) as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e

    typer.echo(f"Exported the event logs of {len(session_ids)} session{'s' if len(session_ids) != 1 else ''}:")
    for path in paths:
        typer.echo(f"  {path}")


@app.command("models")
def benchmark_models() -> None:
    """List available model configurations."""
    with _benchmarks() as session:
        models_dict = session.list_benchmark_models()

    if not models_dict:
        typer.echo("\nNo benchmark model configurations found.")
        typer.echo("\nConfigure models in .env with pattern:")
        typer.echo("  LLM_{NAME}_PROVIDER=azure|openai|anthropic|mistral|ollama|lmstudio")
        typer.echo("  LLM_{NAME}_MODEL=model-id")
        typer.echo("  LLM_{NAME}_URL=api-url (optional)")
        typer.echo("  LLM_{NAME}_KEY=api-key (optional)")
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
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output file")] = None,
    sort_by: Annotated[str, typer.Option("-s", "--sort-by", help="Sort metric")] = "deviation_count",
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

    with _benchmarks() as session:
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
                status = "LOW" if cd.consistency_score >= 0.8 else "MEDIUM" if cd.consistency_score >= 0.5 else "HIGH"
                typer.echo(f"  [{status}] {cd.config_type}: {cd.config_id}")
                typer.echo(f"        Consistency: {cd.consistency_score:.1%}")
                typer.echo(f"        Deviations: {cd.deviation_count}/{cd.total_objects}")
                if cd.deviating_objects[:3]:
                    typer.echo(f"        Sample: {', '.join(cd.deviating_objects[:3])}")
                typer.echo("")

            from deriva.bench.config_deviation import generate_recommendations

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
    session_ids: Annotated[list[str], typer.Argument(help="Benchmark session IDs to analyze")],
    output: Annotated[str | None, typer.Option("-o", "--output", help="Output directory (default: workspace/analysis in the Deriva home folder)")] = None,
    format: Annotated[str, typer.Option("-f", "--format", help="Which report path to print: json, markdown or both (every report file is always written)")] = "both",
    no_semantic: Annotated[bool, typer.Option("--no-semantic", help="Skip semantic matching")] = False,
) -> None:
    """Run comprehensive benchmark analysis."""
    if format not in ("json", "markdown", "both"):
        typer.echo("Error: format must be 'json', 'markdown', or 'both'", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo("BENCHMARK ANALYSIS")
    typer.echo(f"{'=' * 60}\n")
    typer.echo(f"Sessions: {', '.join(session_ids)}")

    from deriva.bench.analysis import BenchmarkAnalyzer

    with _benchmarks() as session:
        try:
            analyzer = BenchmarkAnalyzer(
                session_ids=list(session_ids),
                engine=session._engine,
            )
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        typer.echo("\nRunning analysis...")
        report = analyzer.generate_report(include_semantic=not no_semantic)

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
                    typer.echo(f"  {repo}: {phases['derivation'].overall_consistency:.1%} derivation consistency")

        if report.semantic_reports:
            typer.echo("\nSEMANTIC MATCH SUMMARY")
            typer.echo("-" * 40)
            for repo, sr in report.semantic_reports.items():
                typer.echo(f"  {repo}: P={sr.element_precision:.1%} R={sr.element_recall:.1%} F1={sr.element_f1:.2f}")

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

        output = output or str(workspace() / "analysis")
        typer.echo(f"\nExporting to: {output}")
        paths = analyzer.export_all(output)

        if format in ("json", "both"):
            typer.echo(f"  JSON: {paths.get('inter_model_json', 'N/A')}")
        if format in ("markdown", "both"):
            typer.echo(f"  Markdown: {paths.get('markdown', 'N/A')}")
