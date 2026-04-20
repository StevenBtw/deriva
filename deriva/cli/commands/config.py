"""
Config CLI commands.

Provides commands for managing pipeline configurations.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from deriva.services import config
from deriva.services.session import PipelineSession

app = typer.Typer(name="config", help="Manage pipeline configurations")

# Filetype subapp
filetype_app = typer.Typer(name="filetype", help="Manage file type registry")
app.add_typer(filetype_app)


# =============================================================================
# Config Commands
# =============================================================================


@app.command("list")
def config_list(
    step_type: Annotated[str, typer.Argument(help="Type of configuration to list")],
    enabled: Annotated[
        bool, typer.Option("--enabled", help="Only show enabled configurations")
    ] = False,
    phase: Annotated[
        str | None,
        typer.Option(
            "--phase", help="Filter derivation by phase (prep, generate, refine)"
        ),
    ] = None,
) -> None:
    """List configurations for a step type."""
    if step_type not in ("extraction", "derivation"):
        typer.echo(
            f"Error: step_type must be 'extraction' or 'derivation', got '{step_type}'",
            err=True,
        )
        raise typer.Exit(1)

    with PipelineSession() as session:
        steps = session.list_steps(step_type, enabled_only=enabled)

        if not steps:
            typer.echo(f"No {step_type} configurations found.")
            return

        typer.echo(f"\n{step_type.upper()} CONFIGURATIONS")
        typer.echo("-" * 60)

        for step in steps:
            status = "enabled" if step["enabled"] else "disabled"
            name = step["name"]
            seq = step["sequence"]
            typer.echo(f"  [{seq}] {name:<30} ({status})")

        typer.echo("")


@app.command("show")
def config_show(
    step_type: Annotated[str, typer.Argument(help="Type of configuration")],
    name: Annotated[str, typer.Argument(help="Name of the configuration")],
) -> None:
    """Show detailed configuration for a specific step."""
    if step_type not in ("extraction", "derivation"):
        typer.echo("Error: step_type must be 'extraction' or 'derivation'", err=True)
        raise typer.Exit(1)

    with PipelineSession() as session:
        if step_type == "extraction":
            cfg = config.get_extraction_config(session._engine, name)
            if not cfg:
                typer.echo(f"Extraction config '{name}' not found.")
                raise typer.Exit(1)
            typer.echo(f"\nEXTRACTION CONFIG: {cfg.node_type}")
            typer.echo("-" * 60)
            typer.echo(f"  Sequence: {cfg.sequence}")
            typer.echo(f"  Enabled:  {cfg.enabled}")
            typer.echo(f"  Sources:  {cfg.input_sources or 'None'}")
            typer.echo(f"  Batch Size: {getattr(cfg, 'batch_size', 1)}")
            typer.echo(f"  Instruction: {(cfg.instruction or '')[:100]}...")
            typer.echo(f"  Example: {(cfg.example or '')[:100]}...")

        elif step_type == "derivation":
            cfg = config.get_derivation_config(session._engine, name)
            if not cfg:
                typer.echo(f"Derivation config '{name}' not found.")
                raise typer.Exit(1)
            typer.echo(f"\nDERIVATION CONFIG: {cfg.element_type}")
            typer.echo("-" * 60)
            typer.echo(f"  Sequence: {cfg.sequence}")
            typer.echo(f"  Enabled:  {cfg.enabled}")
            typer.echo(f"  Query:    {(cfg.input_graph_query or '')[:100]}...")
            typer.echo(f"  Instruction: {(cfg.instruction or '')[:100]}...")

        typer.echo("")


@app.command("enable")
def config_enable(
    step_type: Annotated[str, typer.Argument(help="Type of configuration")],
    name: Annotated[str, typer.Argument(help="Name to enable")],
) -> None:
    """Enable a configuration step."""
    if step_type not in ("extraction", "derivation"):
        typer.echo("Error: step_type must be 'extraction' or 'derivation'", err=True)
        raise typer.Exit(1)

    with PipelineSession() as session:
        if session.enable_step(step_type, name):
            typer.echo(f"Enabled {step_type} step: {name}")
        else:
            typer.echo(f"Step not found: {step_type}/{name}")
            raise typer.Exit(1)


@app.command("disable")
def config_disable(
    step_type: Annotated[str, typer.Argument(help="Type of configuration")],
    name: Annotated[str, typer.Argument(help="Name to disable")],
) -> None:
    """Disable a configuration step."""
    if step_type not in ("extraction", "derivation"):
        typer.echo("Error: step_type must be 'extraction' or 'derivation'", err=True)
        raise typer.Exit(1)

    with PipelineSession() as session:
        if session.disable_step(step_type, name):
            typer.echo(f"Disabled {step_type} step: {name}")
        else:
            typer.echo(f"Step not found: {step_type}/{name}")
            raise typer.Exit(1)


@app.command("update")
def config_update(
    step_type: Annotated[str, typer.Argument(help="Type of configuration to update")],
    name: Annotated[str, typer.Argument(help="Name of the configuration to update")],
    instruction: Annotated[
        str | None, typer.Option("-i", "--instruction", help="New instruction text")
    ] = None,
    example: Annotated[
        str | None, typer.Option("-e", "--example", help="New example text")
    ] = None,
    instruction_file: Annotated[
        str | None,
        typer.Option("--instruction-file", help="Read instruction from file"),
    ] = None,
    example_file: Annotated[
        str | None, typer.Option("--example-file", help="Read example from file")
    ] = None,
    query: Annotated[
        str | None,
        typer.Option("-q", "--query", help="New input_graph_query (derivation only)"),
    ] = None,
    sources: Annotated[
        str | None,
        typer.Option("-s", "--sources", help="New input_sources (extraction only)"),
    ] = None,
    params: Annotated[
        str | None,
        typer.Option("-p", "--params", help="New params JSON (derivation only)"),
    ] = None,
    params_file: Annotated[
        str | None, typer.Option("--params-file", help="Read params JSON from file")
    ] = None,
    batch_size: Annotated[
        int | None,
        typer.Option(
            "--batch-size", help="Files per LLM call for extraction (1=no batching)"
        ),
    ] = None,
    max_candidates: Annotated[
        int | None,
        typer.Option("--max-candidates", help="Maximum candidates for derivation"),
    ] = None,
) -> None:
    """Update a configuration with versioning."""
    if step_type not in ("extraction", "derivation"):
        typer.echo("Error: step_type must be 'extraction' or 'derivation'", err=True)
        raise typer.Exit(1)

    # Read instruction from file if provided
    if instruction_file:
        try:
            with open(instruction_file, encoding="utf-8") as f:
                instruction = f.read()
        except Exception as e:
            typer.echo(f"Error reading instruction file: {e}", err=True)
            raise typer.Exit(1)

    # Read example from file if provided
    if example_file:
        try:
            with open(example_file, encoding="utf-8") as f:
                example = f.read()
        except Exception as e:
            typer.echo(f"Error reading example file: {e}", err=True)
            raise typer.Exit(1)

    # Read params from file if provided
    if params_file:
        try:
            with open(params_file, encoding="utf-8") as f:
                params = f.read()
        except Exception as e:
            typer.echo(f"Error reading params file: {e}", err=True)
            raise typer.Exit(1)

    # Validate params is valid JSON if provided
    if params:
        try:
            json.loads(params)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: params must be valid JSON: {e}", err=True)
            raise typer.Exit(1)

    with PipelineSession() as session:
        if step_type == "derivation":
            result = config.create_derivation_config_version(
                session._engine,
                name,
                instruction=instruction,
                example=example,
                input_graph_query=query,
                params=params,
                batch_size=batch_size,
                max_candidates=max_candidates,
            )
        elif step_type == "extraction":
            result = config.create_extraction_config_version(
                session._engine,
                name,
                instruction=instruction,
                example=example,
                input_sources=sources,
                batch_size=batch_size,
            )
        else:
            typer.echo(f"Versioned updates not yet supported for: {step_type}")
            raise typer.Exit(1)

        if result.get("success"):
            typer.echo(f"Updated {step_type} config: {name}")
            typer.echo(f"  Version: {result['old_version']} -> {result['new_version']}")
            if params:
                typer.echo("  Params: updated")
        else:
            typer.echo(f"Error: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(1)


@app.command("sequence")
def config_sequence(
    step_type: Annotated[
        str, typer.Argument(help="Type: 'derivation' (extraction not supported)")
    ],
    order: Annotated[
        str,
        typer.Option(
            "--order",
            help="Comma-separated list of step names in desired order",
        ),
    ],
    phase: Annotated[
        str | None,
        typer.Option(
            "--phase", help="Only update steps in this phase (e.g., 'generate')"
        ),
    ] = None,
) -> None:
    """Update the execution sequence of derivation steps.

    Reorders steps based on the provided order list. Each step's sequence
    number is set to its position in the list (1-indexed).

    Example (ArchiMate bottom-up: Technology -> Application -> Business):

        deriva config sequence derivation --phase generate --order "TechnologyService,SystemSoftware,Node,Device,ApplicationComponent,ApplicationService,ApplicationInterface,DataObject,BusinessObject,BusinessProcess,BusinessFunction,BusinessActor,BusinessEvent"
    """
    if step_type != "derivation":
        typer.echo(
            "Error: Only 'derivation' step type supports sequence updates", err=True
        )
        raise typer.Exit(1)

    # Parse the order list
    step_order = [s.strip() for s in order.split(",") if s.strip()]
    if not step_order:
        typer.echo("Error: --order must contain at least one step name", err=True)
        raise typer.Exit(1)

    typer.echo(f"\nUpdating derivation sequence ({len(step_order)} steps)...")
    if phase:
        typer.echo(f"Phase filter: {phase}")

    with PipelineSession() as session:
        result = config.update_derivation_sequence(
            session._engine, step_order, phase=phase
        )

        if result["success"]:
            typer.echo(f"\nUpdated {result['total_updated']} steps:")
            for step in result["updated"]:
                typer.echo(f"  [{step['sequence']}] {step['step_name']}")
            typer.echo("\nSequence update complete.")
        else:
            typer.echo(f"\nPartially updated {result['total_updated']} steps")
            if result["errors"]:
                typer.echo("Errors:")
                for err in result["errors"]:
                    typer.echo(f"  - {err}")
            raise typer.Exit(1)


@app.command("versions")
def config_versions() -> None:
    """Show active config versions."""
    with PipelineSession() as session:
        versions = config.get_active_config_versions(session._engine)

        typer.echo("\nACTIVE CONFIG VERSIONS")
        typer.echo("=" * 60)

        for step_type in ["extraction", "derivation"]:
            if versions.get(step_type):
                typer.echo(f"\n{step_type.upper()}:")
                for name, version in sorted(versions[step_type].items()):
                    typer.echo(f"  {name:<30} v{version}")

        typer.echo("")


# =============================================================================
# Read-Only Query Commands (safe during benchmarks)
# =============================================================================


@app.command("query")
def config_query(
    step_type: Annotated[
        str, typer.Argument(help="Type: 'extraction' or 'derivation'")
    ],
    name: Annotated[str | None, typer.Argument(help="Config name (optional)")] = None,
) -> None:
    """Query configs with read-only connection (safe during benchmarks).

    This command uses a read-only database connection, so it can safely
    query configurations even while a benchmark is running without causing
    lock contention.
    """
    from deriva.adapters.database import get_connection

    if step_type not in ("extraction", "derivation"):
        typer.echo(
            f"Error: step_type must be 'extraction' or 'derivation', got '{step_type}'",
            err=True,
        )
        raise typer.Exit(1)

    # Use read-only connection for safe concurrent access
    engine = get_connection(read_only=True)

    try:
        if step_type == "extraction":
            if name:
                cfg = config.get_extraction_config(engine, name)
                if cfg:
                    typer.echo(f"\nEXTRACTION: {cfg.node_type}")
                    typer.echo(f"  Enabled: {cfg.enabled}")
                    typer.echo(f"  Sequence: {cfg.sequence}")
                    typer.echo(f"  Method: {cfg.extraction_method}")
                else:
                    typer.echo(f"Config not found: {name}")
            else:
                configs = config.get_extraction_configs(engine)
                typer.echo(f"\nEXTRACTION CONFIGS ({len(configs)}):")
                for c in configs:
                    status = "enabled" if c.enabled else "disabled"
                    typer.echo(f"  [{c.sequence}] {c.node_type:<25} ({status})")
        else:
            if name:
                cfg = config.get_derivation_config(engine, name)
                if cfg:
                    typer.echo(f"\nDERIVATION: {cfg.step_name}")
                    typer.echo(f"  Phase: {cfg.phase}")
                    typer.echo(f"  Enabled: {cfg.enabled}")
                    typer.echo(f"  Sequence: {cfg.sequence}")
                    typer.echo(f"  LLM: {cfg.llm}")
                else:
                    typer.echo(f"Config not found: {name}")
            else:
                configs = config.get_derivation_configs(engine)
                typer.echo(f"\nDERIVATION CONFIGS ({len(configs)}):")
                for c in configs:
                    status = "enabled" if c.enabled else "disabled"
                    typer.echo(
                        f"  [{c.sequence}] {c.step_name:<25} {c.phase:<10} ({status})"
                    )
    finally:
        engine.close()


@app.command("snapshot")
def config_snapshot(
    session_id: Annotated[str, typer.Argument(help="Benchmark session ID")],
) -> None:
    """Show config versions snapshot for a benchmark session.

    Benchmarks capture the active config versions at start time. This command
    shows which versions were used for a specific benchmark session.
    """
    from deriva.adapters.database import get_connection

    engine = get_connection(read_only=True)
    try:
        row = engine.execute(
            "SELECT config_versions_snapshot FROM benchmark_sessions WHERE session_id = ?",
            [session_id],
        ).fetchone()

        if not row:
            typer.echo(f"Session not found: {session_id}")
            raise typer.Exit(1)

        if not row[0]:
            typer.echo(f"No config snapshot found for session: {session_id}")
            typer.echo(
                "(This may be an older session created before snapshots were added)"
            )
            raise typer.Exit(1)

        snapshot = json.loads(row[0])
        typer.echo(f"\nCONFIG SNAPSHOT: {session_id}")
        typer.echo("=" * 60)

        for step_type, versions in snapshot.items():
            typer.echo(f"\n{step_type.upper()}:")
            for name, version in sorted(versions.items()):
                typer.echo(f"  {name:<30} v{version}")

        typer.echo("")
    finally:
        engine.close()


# =============================================================================
# Filetype Commands
# =============================================================================


@filetype_app.command("list")
def filetype_list() -> None:
    """List all registered file types."""
    with PipelineSession() as session:
        file_types = session.get_file_types()

        if not file_types:
            typer.echo("No file types registered.")
            return

        # Group by file_type
        by_type: dict[str, list] = {}
        for ft in file_types:
            ft_type = ft.get("file_type", "unknown")
            if ft_type not in by_type:
                by_type[ft_type] = []
            by_type[ft_type].append(ft)

        typer.echo(f"\n{'=' * 60}")
        typer.echo("FILE TYPE REGISTRY")
        typer.echo(f"{'=' * 60}")
        typer.echo(f"Total: {len(file_types)} registered\n")

        for ft_type in sorted(by_type.keys()):
            entries = by_type[ft_type]
            typer.echo(f"{ft_type.upper()} ({len(entries)}):")
            for ft in sorted(entries, key=lambda x: x.get("extension", "")):
                ext = ft.get("extension", "")
                subtype = ft.get("subtype", "")
                typer.echo(f"  {ext:<25} -> {subtype}")
            typer.echo("")


@filetype_app.command("add")
def filetype_add(
    extension: Annotated[
        str, typer.Argument(help="File extension (e.g., '.py', 'Dockerfile')")
    ],
    file_type: Annotated[str, typer.Argument(help="File type category")],
    subtype: Annotated[
        str, typer.Argument(help="Subtype (e.g., 'python', 'javascript')")
    ],
) -> None:
    """Add a new file type."""
    with PipelineSession() as session:
        success = session.add_file_type(extension, file_type, subtype)

        if success:
            typer.echo(f"Added file type: {extension} -> {file_type}/{subtype}")
        else:
            typer.echo(
                f"Failed to add file type (may already exist): {extension}", err=True
            )
            raise typer.Exit(1)


@filetype_app.command("delete")
def filetype_delete(
    extension: Annotated[str, typer.Argument(help="Extension to delete")],
) -> None:
    """Delete a file type."""
    with PipelineSession() as session:
        success = session.delete_file_type(extension)

        if success:
            typer.echo(f"Deleted file type: {extension}")
        else:
            typer.echo(f"File type not found: {extension}", err=True)
            raise typer.Exit(1)


@filetype_app.command("stats")
def filetype_stats() -> None:
    """Show file type statistics."""
    with PipelineSession() as session:
        stats = session.get_file_type_stats()

        typer.echo(f"\n{'=' * 60}")
        typer.echo("FILE TYPE STATISTICS")
        typer.echo(f"{'=' * 60}\n")

        for ft_type, count in sorted(stats.items(), key=lambda x: -x[1]):
            typer.echo(f"  {ft_type:<20} {count}")

        typer.echo(f"\n  {'Total':<20} {sum(stats.values())}")
