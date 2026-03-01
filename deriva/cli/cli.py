"""
CLI entry point for Deriva.

Provides headless command-line interface for pipeline operations.
Uses Typer for modern CLI with auto-completion and help generation.

Usage:
    deriva repo clone <url>
    deriva repo list --detailed
    deriva repo delete <name> --force
    deriva repo info <name>
    deriva config list extraction
    deriva config list derivation --phase generate
    deriva config enable extraction BusinessConcept
    deriva run extraction
    deriva run derivation --phase generate
    deriva run all --repo flask_invoice_generator
    deriva clear graph
    deriva clear model
    deriva status
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from deriva.cli.commands.benchmark import app as benchmark_app
from deriva.cli.commands.config import app as config_app
from deriva.cli.commands.repo import app as repo_app
from deriva.cli.commands.run import (
    _print_derivation_result,
    _print_extraction_result,
    _print_pipeline_result,
)
from deriva.cli.progress import create_progress_reporter
from deriva.services.session import PipelineSession

# Create main app
app = typer.Typer(
    name="deriva",
    help="Deriva CLI - Generate ArchiMate models from code repositories",
    no_args_is_help=True,
)

# Add subcommand groups
app.add_typer(config_app, name="config")
app.add_typer(repo_app, name="repo")
app.add_typer(benchmark_app, name="benchmark")


# =============================================================================
# Run Command (standalone, not a subgroup)
# =============================================================================


@app.command("run")
def run_stage(
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
            help="Only run this step (disables all others for the stage)",
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
        typer.echo("Connected to grafeo")

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
                    f"\nExported {len(result['candidate_decisions'])} "
                    f"candidate decisions to {output_path}"
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
# Status Command
# =============================================================================


@app.command("status")
def status() -> None:
    """Show current pipeline status."""
    with PipelineSession() as session:
        typer.echo("\nDERIVA STATUS")
        typer.echo("=" * 60)

        # Count enabled steps per type
        for step_type in ["extraction", "derivation"]:
            all_steps = session.list_steps(step_type)
            enabled = [s for s in all_steps if s["enabled"]]
            typer.echo(
                f"  {step_type.capitalize()}: {len(enabled)}/{len(all_steps)} steps enabled"
            )

        # File types
        file_types = session.get_file_types()
        typer.echo(f"  File Types: {len(file_types)} registered")

        # Graph stats
        try:
            graph_stats = session.get_graph_stats()
            typer.echo(f"  Graph Nodes: {graph_stats['total_nodes']}")
        except Exception:
            typer.echo("  Graph Nodes: (not connected)")

        # ArchiMate stats
        try:
            archimate_stats = session.get_archimate_stats()
            typer.echo(f"  ArchiMate Elements: {archimate_stats['total_elements']}")
        except Exception:
            typer.echo("  ArchiMate Elements: (not connected)")

        typer.echo("")


# =============================================================================
# Export Command
# =============================================================================


@app.command("export")
def export(
    output: Annotated[
        str, typer.Option("-o", "--output", help="Output file path")
    ] = "workspace/output/model.xml",
    name: Annotated[str | None, typer.Option("-n", "--name", help="Model name")] = None,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Print detailed progress")
    ] = False,
) -> None:
    """Export ArchiMate model to file."""
    model_name = name or "Deriva Model"

    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Exporting ArchiMate Model")
    typer.echo(f"{'=' * 60}")

    with PipelineSession() as session:
        if verbose:
            typer.echo("Connected to grafeo")

        result = session.export_model(output_path=output, model_name=model_name)

        if result["success"]:
            typer.echo(f"  Elements exported: {result['elements_exported']}")
            typer.echo(f"  Relationships exported: {result['relationships_exported']}")
            typer.echo(f"\nExported to: {result['output_path']}")
            typer.echo(
                "Model can be opened with Archi or other ArchiMate-compatible tools."
            )
        else:
            typer.echo(f"Error: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(1)


# =============================================================================
# Clear Command
# =============================================================================


@app.command("clear")
def clear(
    target: Annotated[str, typer.Argument(help="Data layer to clear (graph, model)")],
) -> None:
    """Clear graph or model data."""
    if target not in ("graph", "model"):
        typer.echo(
            f"Error: target must be 'graph' or 'model', got '{target}'", err=True
        )
        raise typer.Exit(1)

    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"DERIVA - Clearing {target.upper()}")
    typer.echo(f"{'=' * 60}")

    with PipelineSession() as session:
        if target == "graph":
            result = session.clear_graph()
        elif target == "model":
            result = session.clear_model()
        else:
            typer.echo(f"Unknown clear target: {target}", err=True)
            raise typer.Exit(1)

    if result.get("success"):
        typer.echo(result.get("message", "Done"))
    else:
        typer.echo(f"Error: {result.get('error', 'Unknown error')}", err=True)
        raise typer.Exit(1)


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> int:
    """Main entry point."""
    try:
        app()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


if __name__ == "__main__":
    sys.exit(main())
