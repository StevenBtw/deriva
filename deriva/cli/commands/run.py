"""
Run CLI commands.

Provides commands for running pipeline stages, status, export, and clear.
"""

from __future__ import annotations

from typing import Annotated

import typer

from deriva.cli.progress import create_progress_reporter
from deriva.services.session import PipelineSession

app = typer.Typer(name="run", help="Run pipeline stages")


def _print_extraction_result(result: dict) -> None:
    """Print extraction results."""
    typer.echo(f"\n{'-' * 60}")
    typer.echo("EXTRACTION RESULTS")
    typer.echo(f"{'-' * 60}")
    stats = result.get("stats", {})
    typer.echo(f"  Repos processed:  {stats.get('repos_processed', 0)}")
    typer.echo(f"  Nodes created:    {stats.get('nodes_created', 0)}")
    typer.echo(f"  Edges created:    {stats.get('edges_created', 0)}")
    typer.echo(f"  Steps completed:  {stats.get('steps_completed', 0)}")
    typer.echo(f"  Steps skipped:    {stats.get('steps_skipped', 0)}")

    if result.get("warnings"):
        typer.echo(f"\nWarnings ({len(result['warnings'])}):")
        for warn in result["warnings"][:5]:
            typer.echo(f"  - {warn}")
        if len(result["warnings"]) > 5:
            typer.echo(f"  ... and {len(result['warnings']) - 5} more")

    if result.get("errors"):
        typer.echo(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"][:5]:
            typer.echo(f"  - {err}")
        if len(result["errors"]) > 5:
            typer.echo(f"  ... and {len(result['errors']) - 5} more")


def _print_derivation_result(result: dict) -> None:
    """Print derivation results."""
    typer.echo(f"\n{'-' * 60}")
    typer.echo("DERIVATION RESULTS")
    typer.echo(f"{'-' * 60}")
    stats = result.get("stats", {})
    typer.echo(f"  Elements created:      {stats.get('elements_created', 0)}")
    typer.echo(f"  Relationships created: {stats.get('relationships_created', 0)}")
    typer.echo(f"  Elements validated:    {stats.get('elements_validated', 0)}")
    typer.echo(f"  Issues found:          {stats.get('issues_found', 0)}")
    typer.echo(f"  Steps completed:       {stats.get('steps_completed', 0)}")

    issues = result.get("issues", [])
    if issues:
        typer.echo(f"\nIssues ({len(issues)}):")
        for issue in issues[:10]:
            severity = issue.get("severity", "warning")
            msg = issue.get("message", "")
            typer.echo(f"  [{severity.upper()}] {msg}")
        if len(issues) > 10:
            typer.echo(f"  ... and {len(issues) - 10} more")

    if result.get("errors"):
        typer.echo(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"][:5]:
            typer.echo(f"  - {err}")


def _print_pipeline_result(result: dict) -> None:
    """Print full pipeline results."""
    typer.echo(f"\n{'=' * 60}")
    typer.echo("PIPELINE COMPLETE")
    typer.echo(f"{'=' * 60}")

    results = result.get("results", {})

    if results.get("classification"):
        stats = results["classification"].get("stats", {})
        typer.echo("\nClassification:")
        typer.echo(f"  Files classified: {stats.get('files_classified', 0)}")
        typer.echo(f"  Files undefined:  {stats.get('files_undefined', 0)}")

    if results.get("extraction"):
        stats = results["extraction"].get("stats", {})
        typer.echo("\nExtraction:")
        typer.echo(f"  Nodes created: {stats.get('nodes_created', 0)}")

    if results.get("derivation"):
        stats = results["derivation"].get("stats", {})
        typer.echo("\nDerivation:")
        typer.echo(f"  Elements created: {stats.get('elements_created', 0)}")
        typer.echo(f"  Issues found: {stats.get('issues_found', 0)}")

    if result.get("errors"):
        typer.echo(f"\nTotal errors: {len(result['errors'])}")


@app.callback(invoke_without_command=True)
def run_stage(
    ctx: typer.Context,
    stage: Annotated[
        str, typer.Argument(help="Pipeline stage to run (extraction, derivation, all)")
    ],
    repo: Annotated[
        str | None, typer.Option("--repo", help="Specific repository to process")
    ] = None,
    phase: Annotated[
        str | None, typer.Option("--phase", help="Run specific phase")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Print detailed progress")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Disable progress bar")
    ] = False,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Skip LLM-based steps")
    ] = False,
    only_step: Annotated[
        str | None,
        typer.Option(
            "--only-step",
            help="Only run this step (format: 'StepName' - disables all others for the stage)",
        ),
    ] = None,
    export_candidates: Annotated[
        str | None,
        typer.Option(
            "--export-candidates",
            help="Export candidate decisions to JSON file (for threshold optimization)",
        ),
    ] = None,
) -> None:
    """Run pipeline stages."""
    if stage not in ("extraction", "derivation", "all"):
        typer.echo(
            f"Error: stage must be 'extraction', 'derivation', or 'all', got '{stage}'",
            err=True,
        )
        raise typer.Exit(1)

    # Validate phase is appropriate for stage
    extraction_phases = {"classify", "parse"}
    derivation_phases = {"prep", "generate", "refine"}
    if phase:
        if stage == "extraction" and phase not in extraction_phases:
            typer.echo(f"Error: Phase '{phase}' is not valid for extraction.", err=True)
            typer.echo(
                f"Valid extraction phases: {', '.join(sorted(extraction_phases))}"
            )
            raise typer.Exit(1)
        if stage == "derivation" and phase not in derivation_phases:
            typer.echo(f"Error: Phase '{phase}' is not valid for derivation.", err=True)
            typer.echo(
                f"Valid derivation phases: {', '.join(sorted(derivation_phases))}"
            )
            raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"DERIVA - Running {stage.upper()} pipeline")
    typer.echo(f"{'=' * 60}")

    if repo:
        typer.echo(f"Repository: {repo}")
    if phase:
        typer.echo(f"Phase: {phase}")

    with PipelineSession() as session:
        typer.echo("Connected to Neo4j")

        # Handle --only-step option
        if only_step:
            step_type = "extraction" if stage in ("extraction", "all") else "derivation"
            typer.echo(f"Enabling only {step_type} step: {only_step}")

            if step_type == "extraction":
                extraction_configs = session.get_extraction_configs()
                for cfg in extraction_configs:
                    name = cfg.get("node_type", cfg.get("name", ""))
                    if name == only_step:
                        session.enable_step("extraction", name)
                    else:
                        session.disable_step("extraction", name)
            else:
                derivation_configs = session.get_derivation_configs()
                for cfg in derivation_configs:
                    name = cfg.get("step_name", cfg.get("name", ""))
                    if name == only_step:
                        session.enable_step("derivation", name)
                    else:
                        session.disable_step("derivation", name)

        # Show LLM status
        llm_info = session.llm_info
        if llm_info and not no_llm:
            typer.echo(f"LLM configured: {llm_info['provider']}/{llm_info['model']}")
        elif no_llm:
            typer.echo("LLM disabled (--no-llm)")
        else:
            typer.echo("Warning: LLM not configured. LLM-based steps will be skipped.")

        # Create progress reporter
        progress_reporter = create_progress_reporter(quiet=quiet or verbose)

        if stage == "extraction":
            phases = [phase] if phase else None
            with progress_reporter:
                result = session.run_extraction(
                    repo_name=repo,
                    verbose=verbose,
                    no_llm=no_llm,
                    progress=progress_reporter,
                    phases=phases,
                )
            _print_extraction_result(result)

        elif stage == "derivation":
            if not llm_info:
                typer.echo(
                    "Error: Derivation requires LLM. Configure LLM in .env file.",
                    err=True,
                )
                raise typer.Exit(1)
            phases = [phase] if phase else None
            with progress_reporter:
                result = session.run_derivation(
                    verbose=verbose,
                    phases=phases,
                    progress=progress_reporter,
                )
            _print_derivation_result(result)

            # Export candidate decisions if requested
            if export_candidates and result.get("candidate_decisions"):
                import json
                from pathlib import Path

                output_path = Path(export_candidates)
                output_path.parent.mkdir(parents=True, exist_ok=True)

                candidate_data = {
                    "repo": repo or "unknown",
                    "total_candidates": len(result["candidate_decisions"]),
                    "decisions": result["candidate_decisions"],
                }

                with open(output_path, "w") as f:
                    json.dump(candidate_data, f, indent=2)

                typer.echo(
                    f"\nExported {len(result['candidate_decisions'])} candidate decisions to {output_path}"
                )

        elif stage == "all":
            with progress_reporter:
                result = session.run_pipeline(
                    repo_name=repo,
                    verbose=verbose,
                    progress=progress_reporter,
                )
            _print_pipeline_result(result)

        if not result.get("success"):
            raise typer.Exit(1)


# =============================================================================
# Additional Commands (status, export, clear)
# =============================================================================


# These are standalone commands, not subcommands of run
# They will be added to the main app directly
