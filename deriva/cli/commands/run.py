"""
Result printers of the run command (``deriva-cli run``, defined in ``deriva/cli/cli.py``).
"""

from __future__ import annotations

import typer


def _print_extraction_result(result: dict) -> None:
    """Print extraction results."""
    typer.echo(f"\n{'-' * 60}")
    typer.echo("EXTRACTION RESULTS")
    typer.echo(f"{'-' * 60}")
    stats = result.get("stats", {})
    typer.echo(f"  Repos processed:  {stats.get('repos_processed', 0)}")
    typer.echo(f"  Nodes written:    {stats.get('nodes_created', 0)}")
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
    if stats.get("elements_disabled", 0) > 0:
        typer.echo(f"  Elements disabled by refine: {stats['elements_disabled']} (excluded from export)")
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
    typer.echo("PIPELINE COMPLETE" if result.get("success") else "PIPELINE FAILED")
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
        typer.echo(f"  Nodes written: {stats.get('nodes_created', 0)}")

    if results.get("derivation"):
        stats = results["derivation"].get("stats", {})
        typer.echo("\nDerivation:")
        typer.echo(f"  Elements created: {stats.get('elements_created', 0)}")
        if stats.get("elements_disabled", 0) > 0:
            typer.echo(f"  Elements disabled by refine: {stats['elements_disabled']} (excluded from export)")
        typer.echo(f"  Issues found: {stats.get('issues_found', 0)}")

    if result.get("errors"):
        typer.echo(f"\nTotal errors: {len(result['errors'])}")
        for err in result["errors"][:10]:
            typer.echo(f"  - {err}")
        if len(result["errors"]) > 10:
            typer.echo(f"  ... and {len(result['errors']) - 10} more")
