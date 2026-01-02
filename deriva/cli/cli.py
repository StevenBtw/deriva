"""
CLI entry point for Deriva.

Provides headless command-line interface for pipeline operations.
Uses PipelineSession from the services layer.

Usage:
    python -m deriva.cli.cli repo clone <url>
    python -m deriva.cli.cli repo list --detailed
    python -m deriva.cli.cli repo delete <name> --force
    python -m deriva.cli.cli repo info <name>
    python -m deriva.cli.cli config list extraction
    python -m deriva.cli.cli config list derivation --phase generate
    python -m deriva.cli.cli config enable extraction BusinessConcept
    python -m deriva.cli.cli run extraction
    python -m deriva.cli.cli run derivation --phase generate
    python -m deriva.cli.cli run all --repo flask_invoice_generator
    python -m deriva.cli.cli clear graph
    python -m deriva.cli.cli clear model
    python -m deriva.cli.cli status
"""

from __future__ import annotations

import argparse
import sys

from deriva.services import config
from deriva.services.session import PipelineSession


# =============================================================================
# Config Commands
# =============================================================================


def cmd_config_list(args: argparse.Namespace) -> int:
    """List configurations for a step type."""
    with PipelineSession() as session:
        step_type = args.step_type
        enabled_only = args.enabled

        steps = session.list_steps(step_type, enabled_only=enabled_only)

        if not steps:
            print(f"No {step_type} configurations found.")
            return 0

        print(f"\n{step_type.upper()} CONFIGURATIONS")
        print("-" * 60)

        for step in steps:
            status = "enabled" if step["enabled"] else "disabled"
            name = step["name"]
            seq = step["sequence"]
            print(f"  [{seq}] {name:<30} ({status})")

        print()
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    """Show detailed configuration for a specific step."""
    with PipelineSession() as session:
        step_type = args.step_type
        name = args.name

        if step_type == "extraction":
            cfg = config.get_extraction_config(session._engine, name)
            if not cfg:
                print(f"Extraction config '{name}' not found.")
                return 1
            print(f"\nEXTRACTION CONFIG: {cfg.node_type}")
            print("-" * 60)
            print(f"  Sequence: {cfg.sequence}")
            print(f"  Enabled:  {cfg.enabled}")
            print(f"  Sources:  {cfg.input_sources or 'None'}")
            print(f"  Instruction: {(cfg.instruction or '')[:100]}...")
            print(f"  Example: {(cfg.example or '')[:100]}...")

        elif step_type == "derivation":
            cfg = config.get_derivation_config(session._engine, name)
            if not cfg:
                print(f"Derivation config '{name}' not found.")
                return 1
            print(f"\nDERIVATION CONFIG: {cfg.element_type}")
            print("-" * 60)
            print(f"  Sequence: {cfg.sequence}")
            print(f"  Enabled:  {cfg.enabled}")
            print(f"  Query:    {(cfg.input_graph_query or '')[:100]}...")
            print(f"  Instruction: {(cfg.instruction or '')[:100]}...")

        else:
            print(f"Unknown step type: {step_type}")
            return 1

        print()
    return 0


def cmd_config_enable(args: argparse.Namespace) -> int:
    """Enable a configuration step."""
    with PipelineSession() as session:
        if session.enable_step(args.step_type, args.name):
            print(f"Enabled {args.step_type} step: {args.name}")
            return 0
        else:
            print(f"Step not found: {args.step_type}/{args.name}")
            return 1


def cmd_config_disable(args: argparse.Namespace) -> int:
    """Disable a configuration step."""
    with PipelineSession() as session:
        if session.disable_step(args.step_type, args.name):
            print(f"Disabled {args.step_type} step: {args.name}")
            return 0
        else:
            print(f"Step not found: {args.step_type}/{args.name}")
            return 1


def cmd_config_update(args: argparse.Namespace) -> int:
    """Update a configuration with versioning."""
    with PipelineSession() as session:
        step_type = args.step_type
        name = args.name
        instruction = args.instruction
        example = args.example

        # Read instruction from file if provided
        if args.instruction_file:
            try:
                with open(args.instruction_file, encoding="utf-8") as f:
                    instruction = f.read()
            except Exception as e:
                print(f"Error reading instruction file: {e}")
                return 1

        # Read example from file if provided
        if args.example_file:
            try:
                with open(args.example_file, encoding="utf-8") as f:
                    example = f.read()
            except Exception as e:
                print(f"Error reading example file: {e}")
                return 1

        if step_type == "derivation":
            result = config.create_derivation_config_version(
                session._engine,
                name,
                instruction=instruction,
                example=example,
                input_graph_query=args.query,
            )
        elif step_type == "extraction":
            result = config.create_extraction_config_version(
                session._engine,
                name,
                instruction=instruction,
                example=example,
                input_sources=args.sources,
            )
        else:
            print(f"Versioned updates not yet supported for: {step_type}")
            return 1

        if result.get("success"):
            print(f"Updated {step_type} config: {name}")
            print(f"  Version: {result['old_version']} -> {result['new_version']}")
            return 0
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")
            return 1


def cmd_config_versions(args: argparse.Namespace) -> int:
    """Show active config versions."""
    with PipelineSession() as session:
        versions = config.get_active_config_versions(session._engine)

        print("\nACTIVE CONFIG VERSIONS")
        print("=" * 60)

        for step_type in ["extraction", "derivation"]:
            if versions.get(step_type):
                print(f"\n{step_type.upper()}:")
                for name, version in sorted(versions[step_type].items()):
                    print(f"  {name:<30} v{version}")

        print()
    return 0


# =============================================================================
# Run Commands
# =============================================================================


def cmd_run(args: argparse.Namespace) -> int:
    """Run pipeline stages."""
    stage = args.stage
    repo_name = getattr(args, "repo", None)
    verbose = getattr(args, "verbose", False)
    no_llm = getattr(args, "no_llm", False)
    phase = getattr(args, "phase", None)

    print(f"\n{'=' * 60}")
    print(f"AUTOMATE - Running {stage.upper()} pipeline")
    print(f"{'=' * 60}")

    if repo_name:
        print(f"Repository: {repo_name}")
    if phase:
        print(f"Phase: {phase}")

    with PipelineSession() as session:
        print("Connected to Neo4j")

        # Show LLM status
        llm_info = session.llm_info
        if llm_info and not no_llm:
            print(f"LLM configured: {llm_info['provider']}/{llm_info['model']}")
        elif no_llm:
            print("LLM disabled (--no-llm)")
        else:
            print("Warning: LLM not configured. LLM-based steps will be skipped.")

        if stage == "extraction":
            result = session.run_extraction(
                repo_name=repo_name,
                verbose=verbose,
                no_llm=no_llm,
            )
            _print_extraction_result(result)

        elif stage == "derivation":
            if not llm_info:
                print("Error: Derivation requires LLM. Configure LLM in .env file.")
                return 1
            phases = [phase] if phase else None
            result = session.run_derivation(verbose=verbose, phases=phases)
            _print_derivation_result(result)

        elif stage == "all":
            result = session.run_pipeline(repo_name=repo_name, verbose=verbose)
            _print_pipeline_result(result)

        else:
            print(f"Unknown stage: {stage}")
            return 1

    return 0 if result.get("success") else 1


def _print_extraction_result(result: dict) -> None:
    """Print extraction results."""
    print(f"\n{'-' * 60}")
    print("EXTRACTION RESULTS")
    print(f"{'-' * 60}")
    stats = result.get("stats", {})
    print(f"  Repos processed:  {stats.get('repos_processed', 0)}")
    print(f"  Nodes created:    {stats.get('nodes_created', 0)}")
    print(f"  Edges created:    {stats.get('edges_created', 0)}")
    print(f"  Steps completed:  {stats.get('steps_completed', 0)}")
    print(f"  Steps skipped:    {stats.get('steps_skipped', 0)}")

    if result.get("warnings"):
        print(f"\nWarnings ({len(result['warnings'])}):")
        for warn in result["warnings"][:5]:
            print(f"  - {warn}")
        if len(result["warnings"]) > 5:
            print(f"  ... and {len(result['warnings']) - 5} more")

    if result.get("errors"):
        print(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"][:5]:
            print(f"  - {err}")
        if len(result["errors"]) > 5:
            print(f"  ... and {len(result['errors']) - 5} more")


def _print_derivation_result(result: dict) -> None:
    """Print derivation results."""
    print(f"\n{'-' * 60}")
    print("DERIVATION RESULTS")
    print(f"{'-' * 60}")
    stats = result.get("stats", {})
    print(f"  Elements created:      {stats.get('elements_created', 0)}")
    print(f"  Relationships created: {stats.get('relationships_created', 0)}")
    print(f"  Elements validated:    {stats.get('elements_validated', 0)}")
    print(f"  Issues found:          {stats.get('issues_found', 0)}")
    print(f"  Steps completed:       {stats.get('steps_completed', 0)}")

    issues = result.get("issues", [])
    if issues:
        print(f"\nIssues ({len(issues)}):")
        for issue in issues[:10]:
            severity = issue.get("severity", "warning")
            msg = issue.get("message", "")
            print(f"  [{severity.upper()}] {msg}")
        if len(issues) > 10:
            print(f"  ... and {len(issues) - 10} more")

    if result.get("errors"):
        print(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"][:5]:
            print(f"  - {err}")


def _print_pipeline_result(result: dict) -> None:
    """Print full pipeline results."""
    print(f"\n{'=' * 60}")
    print("PIPELINE COMPLETE")
    print(f"{'=' * 60}")

    results = result.get("results", {})

    if results.get("classification"):
        stats = results["classification"].get("stats", {})
        print("\nClassification:")
        print(f"  Files classified: {stats.get('files_classified', 0)}")
        print(f"  Files undefined:  {stats.get('files_undefined', 0)}")

    if results.get("extraction"):
        stats = results["extraction"].get("stats", {})
        print("\nExtraction:")
        print(f"  Nodes created: {stats.get('nodes_created', 0)}")

    if results.get("derivation"):
        stats = results["derivation"].get("stats", {})
        print("\nDerivation:")
        print(f"  Elements created: {stats.get('elements_created', 0)}")
        print(f"  Issues found: {stats.get('issues_found', 0)}")

    if result.get("errors"):
        print(f"\nTotal errors: {len(result['errors'])}")


# =============================================================================
# Status Commands
# =============================================================================


def cmd_status(args: argparse.Namespace) -> int:
    """Show current pipeline status."""
    with PipelineSession() as session:
        print("\nAUTOMATE STATUS")
        print("=" * 60)

        # Count enabled steps per type
        for step_type in ["extraction", "derivation"]:
            all_steps = session.list_steps(step_type)
            enabled = [s for s in all_steps if s["enabled"]]
            print(
                f"  {step_type.capitalize()}: {len(enabled)}/{len(all_steps)} steps enabled"
            )

        # File types
        file_types = session.get_file_types()
        print(f"  File Types: {len(file_types)} registered")

        # Graph stats
        try:
            graph_stats = session.get_graph_stats()
            print(f"  Graph Nodes: {graph_stats['total_nodes']}")
        except Exception:
            print("  Graph Nodes: (not connected)")

        # ArchiMate stats
        try:
            archimate_stats = session.get_archimate_stats()
            print(f"  ArchiMate Elements: {archimate_stats['total_elements']}")
        except Exception:
            print("  ArchiMate Elements: (not connected)")

        print()
    return 0


# =============================================================================
# Export Commands
# =============================================================================


def cmd_export(args: argparse.Namespace) -> int:
    """Export ArchiMate model to file."""
    output_path = args.output
    model_name = args.name or "Deriva Model"
    verbose = getattr(args, "verbose", False)

    print(f"\n{'=' * 60}")
    print("AUTOMATE - Exporting ArchiMate Model")
    print(f"{'=' * 60}")

    with PipelineSession() as session:
        if verbose:
            print("Connected to Neo4j")

        result = session.export_model(output_path=output_path, model_name=model_name)

        if result["success"]:
            print(f"  Elements exported: {result['elements_exported']}")
            print(f"  Relationships exported: {result['relationships_exported']}")
            print(f"\nExported to: {result['output_path']}")
            print("Model can be opened with Archi or other ArchiMate-compatible tools.")
            return 0
        else:
            print(f"Error: {result.get('error', 'Unknown error')}")
            return 1


# =============================================================================
# Clear Commands
# =============================================================================


def cmd_clear(args: argparse.Namespace) -> int:
    """Clear graph or model data."""
    target = args.target

    print(f"\n{'=' * 60}")
    print(f"AUTOMATE - Clearing {target.upper()}")
    print(f"{'=' * 60}")

    with PipelineSession() as session:
        if target == "graph":
            result = session.clear_graph()
        elif target == "model":
            result = session.clear_model()
        else:
            print(f"Unknown clear target: {target}")
            return 1

    if result.get("success"):
        print(result.get("message", "Done"))
        return 0
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1


# =============================================================================
# Repository Commands
# =============================================================================


def cmd_repo_clone(args: argparse.Namespace) -> int:
    """Clone a repository."""
    url = args.url
    name = getattr(args, "name", None)
    branch = getattr(args, "branch", None)
    overwrite = getattr(args, "overwrite", False)

    print(f"\n{'=' * 60}")
    print("DERIVA - Cloning Repository")
    print(f"{'=' * 60}")
    print(f"URL: {url}")
    if name:
        print(f"Name: {name}")
    if branch:
        print(f"Branch: {branch}")

    with PipelineSession() as session:
        result = session.clone_repository(url=url, name=name, branch=branch, overwrite=overwrite)
        if result.get("success"):
            print("\nRepository cloned successfully!")
            print(f"  Name: {result.get('name', 'N/A')}")
            print(f"  Path: {result.get('path', 'N/A')}")
            print(f"  URL:  {result.get('url', url)}")
            return 0
        else:
            print(f"\nError: {result.get('error', 'Unknown error')}")
            return 1


def cmd_repo_list(args: argparse.Namespace) -> int:
    """List all repositories."""
    detailed = getattr(args, "detailed", False)

    with PipelineSession() as session:
        repos = session.get_repositories(detailed=detailed)

        if not repos:
            print("\nNo repositories found.")
            print(f"Workspace: {session.workspace_dir}")
            print("\nClone a repository with:")
            print("  deriva repo clone <url>")
            return 0

        print(f"\n{'=' * 60}")
        print("REPOSITORIES")
        print(f"{'=' * 60}")
        print(f"Workspace: {session.workspace_dir}\n")

        for repo in repos:
            if detailed:
                dirty = " (dirty)" if repo.get("is_dirty") else ""
                print(f"  {repo['name']}{dirty}")
                print(f"    URL:    {repo.get('url', 'N/A')}")
                print(f"    Branch: {repo.get('branch', 'N/A')}")
                print(f"    Size:   {repo.get('size_mb', 0):.2f} MB")
                print(f"    Cloned: {repo.get('cloned_at', 'N/A')}")
                print()
            else:
                print(f"  {repo['name']}")

        print(f"\nTotal: {len(repos)} repositories")
    return 0


def cmd_repo_delete(args: argparse.Namespace) -> int:
    """Delete a repository."""
    name = args.name
    force = getattr(args, "force", False)

    print(f"\n{'=' * 60}")
    print("DERIVA - Deleting Repository")
    print(f"{'=' * 60}")
    print(f"Repository: {name}")

    with PipelineSession() as session:
        try:
            result = session.delete_repository(name=name, force=force)
            if result.get("success"):
                print(f"\nRepository '{name}' deleted successfully.")
                return 0
            else:
                print(f"\nError: {result.get('error', 'Unknown error')}")
                return 1
        except Exception as e:
            print(f"\nError: {e}")
            if "uncommitted changes" in str(e).lower():
                print("Use --force to delete anyway.")
            return 1


def cmd_repo_info(args: argparse.Namespace) -> int:
    """Show repository details."""
    name = args.name

    with PipelineSession() as session:
        try:
            info = session.get_repository_info(name)

            if not info:
                print(f"\nRepository '{name}' not found.")
                return 1

            print(f"\n{'=' * 60}")
            print(f"REPOSITORY: {info['name']}")
            print(f"{'=' * 60}")
            print(f"  Path:        {info.get('path', 'N/A')}")
            print(f"  URL:         {info.get('url', 'N/A')}")
            print(f"  Branch:      {info.get('branch', 'N/A')}")
            print(f"  Last Commit: {info.get('last_commit', 'N/A')}")
            print(f"  Dirty:       {info.get('is_dirty', False)}")
            print(f"  Size:        {info.get('size_mb', 0):.2f} MB")
            print(f"  Cloned At:   {info.get('cloned_at', 'N/A')}")
            print()
            return 0
        except Exception as e:
            print(f"\nError: {e}")
            return 1


# =============================================================================
# Consistency Commands
# =============================================================================


# =============================================================================
# Benchmark Commands
# =============================================================================


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    """Run benchmark matrix."""
    repos = [r.strip() for r in args.repos.split(",")]
    models = [m.strip() for m in args.models.split(",")]
    runs = getattr(args, "runs", 3)
    stages = [s.strip() for s in args.stages.split(",")] if args.stages else None
    description = getattr(args, "description", "")
    verbose = getattr(args, "verbose", False)

    print(f"\n{'=' * 60}")
    print("AUTOMATE - Multi-Model Benchmark")
    print(f"{'=' * 60}")
    print(f"Repositories: {repos}")
    print(f"Models: {models}")
    print(f"Runs per combination: {runs}")
    print(f"Total runs: {len(repos) * len(models) * runs}")
    if stages:
        print(f"Stages: {stages}")
    print(f"{'=' * 60}\n")

    with PipelineSession() as session:
        print("Connected to Neo4j")

        result = session.run_benchmark(
            repositories=repos,
            models=models,
            runs=runs,
            stages=stages,
            description=description,
            verbose=verbose,
        )

        print(f"\n{'=' * 60}")
        print("BENCHMARK COMPLETE")
        print(f"{'=' * 60}")
        print(f"Session ID: {result.session_id}")
        print(f"Runs completed: {result.runs_completed}")
        print(f"Runs failed: {result.runs_failed}")
        print(f"Duration: {result.duration_seconds:.1f}s")
        print(f"OCEL log: {result.ocel_path}")

        if result.errors:
            print(f"\nErrors ({len(result.errors)}):")
            for err in result.errors[:5]:
                print(f"  - {err}")
            if len(result.errors) > 5:
                print(f"  ... and {len(result.errors) - 5} more")

        print("\nTo analyze results:")
        print(f"  deriva benchmark analyze {result.session_id}")

    return 0 if result.success else 1


def cmd_benchmark_list(args: argparse.Namespace) -> int:
    """List benchmark sessions."""
    limit = getattr(args, "limit", 10)

    with PipelineSession() as session:
        sessions = session.list_benchmarks(limit=limit)

        if not sessions:
            print("No benchmark sessions found.")
            return 0

        print(f"\n{'=' * 60}")
        print("BENCHMARK SESSIONS")
        print(f"{'=' * 60}")

        for s in sessions:
            status_icon = (
                ""
                if s["status"] == "completed"
                else ""
                if s["status"] == "failed"
                else ""
            )
            print(f"\n{status_icon} {s['session_id']}")
            print(f"    Status: {s['status']}")
            print(f"    Started: {s['started_at']}")
            if s.get("description"):
                print(f"    Description: {s['description']}")

        print()
    return 0


def cmd_benchmark_analyze(args: argparse.Namespace) -> int:
    """Analyze benchmark results."""
    session_id = args.session_id
    output = getattr(args, "output", None)
    fmt = getattr(args, "format", "json")

    print(f"\n{'=' * 60}")
    print(f"ANALYZING BENCHMARK: {session_id}")
    print(f"{'=' * 60}\n")

    with PipelineSession() as session:
        try:
            analyzer = session.analyze_benchmark(session_id)
        except ValueError as e:
            print(f"Error: {e}")
            return 1

        # Compute and display summary
        summary = analyzer.compute_full_analysis()

        print(f"Overall Consistency: {summary.overall_consistency:.1f}%\n")

        # Intra-model consistency
        if summary.intra_model:
            print("INTRA-MODEL CONSISTENCY (stability across runs)")
            print("-" * 50)
            for m in summary.intra_model:
                print(f"  {m.model} @ {m.repository}: {m.name_consistency:.1f}%")
            print()

        # Inter-model consistency
        if summary.inter_model:
            print("INTER-MODEL CONSISTENCY (agreement across models)")
            print("-" * 50)
            for m in summary.inter_model:
                print(f"  {m.repository}: {m.jaccard_similarity * 100:.1f}% overlap")
            print()

        # Hotspots
        if summary.localization.hotspots:
            print("INCONSISTENCY HOTSPOTS")
            print("-" * 50)
            for h in summary.localization.hotspots:
                print(
                    f"  [{h['severity'].upper()}] {h['type']}: {h['name']} ({h['consistency']:.1f}%)"
                )
            print()

        # Export
        output_path = analyzer.export_summary(output, format=fmt)
        print(f"Analysis exported to: {output_path}")

        # Save to DB
        analyzer.save_metrics_to_db()
        print("Metrics saved to database.")

    return 0


def cmd_benchmark_models(args: argparse.Namespace) -> int:
    """List available model configurations."""
    with PipelineSession() as session:
        models = session.list_benchmark_models()

    if not models:
        print("\nNo benchmark model configurations found.")
        print("\nConfigure models in .env with pattern:")
        print("  LLM_BENCH_{NAME}_PROVIDER=azure|openai|anthropic|ollama")
        print("  LLM_BENCH_{NAME}_MODEL=model-id")
        print("  LLM_BENCH_{NAME}_URL=api-url (optional)")
        print("  LLM_BENCH_{NAME}_KEY=api-key (optional)")
        return 0

    print(f"\n{'=' * 60}")
    print("AVAILABLE BENCHMARK MODELS")
    print(f"{'=' * 60}\n")

    for name, cfg in sorted(models.items()):
        print(f"  {name}")
        print(f"    Provider: {cfg.provider}")
        print(f"    Model: {cfg.model}")
        if cfg.api_url:
            print(f"    URL: {cfg.api_url[:50]}...")
        print()

    return 0


# =============================================================================
# Main Entry Point
# =============================================================================


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="deriva",
        description="Deriva CLI - Generate ArchiMate models from code repositories",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -------------------------------------------------------------------------
    # config command
    # -------------------------------------------------------------------------
    config_parser = subparsers.add_parser(
        "config", help="Manage pipeline configurations"
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_action", help="Config actions"
    )

    # config list
    config_list = config_subparsers.add_parser("list", help="List configurations")
    config_list.add_argument(
        "step_type",
        choices=["extraction", "derivation"],
        help="Type of configuration to list",
    )
    config_list.add_argument(
        "--enabled",
        action="store_true",
        help="Only show enabled configurations",
    )
    config_list.add_argument(
        "--phase",
        choices=["prep", "generate", "refine"],
        help="Filter derivation by phase",
    )
    config_list.set_defaults(func=cmd_config_list)

    # config show
    config_show = config_subparsers.add_parser(
        "show", help="Show configuration details"
    )
    config_show.add_argument(
        "step_type",
        choices=["extraction", "derivation"],
        help="Type of configuration",
    )
    config_show.add_argument(
        "name", help="Name of the configuration (node_type or step_name)"
    )
    config_show.set_defaults(func=cmd_config_show)

    # config enable
    config_enable = config_subparsers.add_parser(
        "enable", help="Enable a configuration"
    )
    config_enable.add_argument(
        "step_type",
        choices=["extraction", "derivation"],
        help="Type of configuration",
    )
    config_enable.add_argument("name", help="Name to enable")
    config_enable.set_defaults(func=cmd_config_enable)

    # config disable
    config_disable = config_subparsers.add_parser(
        "disable", help="Disable a configuration"
    )
    config_disable.add_argument(
        "step_type",
        choices=["extraction", "derivation"],
        help="Type of configuration",
    )
    config_disable.add_argument("name", help="Name to disable")
    config_disable.set_defaults(func=cmd_config_disable)

    # config update (versioned)
    config_update = config_subparsers.add_parser(
        "update", help="Update configuration (creates new version)"
    )
    config_update.add_argument(
        "step_type",
        choices=["extraction", "derivation"],
        help="Type of configuration to update",
    )
    config_update.add_argument("name", help="Name of the configuration to update")
    config_update.add_argument(
        "-i",
        "--instruction",
        type=str,
        default=None,
        help="New instruction text",
    )
    config_update.add_argument(
        "-e",
        "--example",
        type=str,
        default=None,
        help="New example text",
    )
    config_update.add_argument(
        "--instruction-file",
        type=str,
        default=None,
        help="Read instruction from file",
    )
    config_update.add_argument(
        "--example-file",
        type=str,
        default=None,
        help="Read example from file",
    )
    config_update.add_argument(
        "-q",
        "--query",
        type=str,
        default=None,
        help="New input_graph_query (derivation only)",
    )
    config_update.add_argument(
        "-s",
        "--sources",
        type=str,
        default=None,
        help="New input_sources (extraction only)",
    )
    config_update.set_defaults(func=cmd_config_update)

    # config versions
    config_versions = config_subparsers.add_parser(
        "versions", help="Show active config versions"
    )
    config_versions.set_defaults(func=cmd_config_versions)

    # -------------------------------------------------------------------------
    # run command
    # -------------------------------------------------------------------------
    run_parser = subparsers.add_parser("run", help="Run pipeline stages")
    run_parser.add_argument(
        "stage",
        choices=["extraction", "derivation", "all"],
        help="Pipeline stage to run",
    )
    run_parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Specific repository to process (default: all repos)",
    )
    run_parser.add_argument(
        "--phase",
        choices=["prep", "generate", "refine"],
        help="Run specific derivation phase only (default: all phases)",
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    run_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM-based steps (structural extraction only)",
    )
    run_parser.set_defaults(func=cmd_run)

    # -------------------------------------------------------------------------
    # status command
    # -------------------------------------------------------------------------
    status_parser = subparsers.add_parser("status", help="Show pipeline status")
    status_parser.set_defaults(func=cmd_status)

    # -------------------------------------------------------------------------
    # export command
    # -------------------------------------------------------------------------
    export_parser = subparsers.add_parser(
        "export", help="Export ArchiMate model to file"
    )
    export_parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="workspace/output/model.archimate",
        help="Output file path (default: workspace/output/model.archimate)",
    )
    export_parser.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Model name (default: Deriva Model)",
    )
    export_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    export_parser.set_defaults(func=cmd_export)

    # -------------------------------------------------------------------------
    # clear command
    # -------------------------------------------------------------------------
    clear_parser = subparsers.add_parser("clear", help="Clear graph or model data")
    clear_parser.add_argument(
        "target",
        choices=["graph", "model"],
        help="Data layer to clear",
    )
    clear_parser.set_defaults(func=cmd_clear)

    # -------------------------------------------------------------------------
    # repo command
    # -------------------------------------------------------------------------
    repo_parser = subparsers.add_parser("repo", help="Manage repositories")
    repo_subparsers = repo_parser.add_subparsers(dest="repo_action", help="Repository actions")

    # repo clone
    repo_clone = repo_subparsers.add_parser("clone", help="Clone a repository")
    repo_clone.add_argument("url", help="Repository URL to clone")
    repo_clone.add_argument(
        "-n",
        "--name",
        type=str,
        default=None,
        help="Custom name for the repository (default: derived from URL)",
    )
    repo_clone.add_argument(
        "-b",
        "--branch",
        type=str,
        default=None,
        help="Branch to clone (default: default branch)",
    )
    repo_clone.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing repository if it exists",
    )
    repo_clone.set_defaults(func=cmd_repo_clone)

    # repo list
    repo_list = repo_subparsers.add_parser("list", help="List all repositories")
    repo_list.add_argument(
        "-d",
        "--detailed",
        action="store_true",
        help="Show detailed information",
    )
    repo_list.set_defaults(func=cmd_repo_list)

    # repo delete
    repo_delete = repo_subparsers.add_parser("delete", help="Delete a repository")
    repo_delete.add_argument("name", help="Repository name to delete")
    repo_delete.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force delete even with uncommitted changes",
    )
    repo_delete.set_defaults(func=cmd_repo_delete)

    # repo info
    repo_info = repo_subparsers.add_parser("info", help="Show repository details")
    repo_info.add_argument("name", help="Repository name")
    repo_info.set_defaults(func=cmd_repo_info)

    # -------------------------------------------------------------------------
    # benchmark command
    # -------------------------------------------------------------------------
    benchmark_parser = subparsers.add_parser(
        "benchmark", help="Multi-model benchmarking"
    )
    benchmark_subparsers = benchmark_parser.add_subparsers(
        dest="benchmark_action", help="Benchmark actions"
    )

    # benchmark run
    benchmark_run = benchmark_subparsers.add_parser("run", help="Run benchmark matrix")
    benchmark_run.add_argument(
        "--repos",
        type=str,
        required=True,
        help="Comma-separated list of repository names",
    )
    benchmark_run.add_argument(
        "--models",
        type=str,
        required=True,
        help="Comma-separated list of model config names (from LLM_BENCH_* env vars)",
    )
    benchmark_run.add_argument(
        "-n",
        "--runs",
        type=int,
        default=3,
        help="Number of runs per (repo, model) combination (default: 3)",
    )
    benchmark_run.add_argument(
        "--stages",
        type=str,
        default=None,
        help="Comma-separated list of stages (default: all)",
    )
    benchmark_run.add_argument(
        "-d",
        "--description",
        type=str,
        default="",
        help="Optional description for the benchmark session",
    )
    benchmark_run.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed progress",
    )
    benchmark_run.set_defaults(func=cmd_benchmark_run)

    # benchmark list
    benchmark_list = benchmark_subparsers.add_parser(
        "list", help="List benchmark sessions"
    )
    benchmark_list.add_argument(
        "-l",
        "--limit",
        type=int,
        default=10,
        help="Number of sessions to show (default: 10)",
    )
    benchmark_list.set_defaults(func=cmd_benchmark_list)

    # benchmark analyze
    benchmark_analyze = benchmark_subparsers.add_parser(
        "analyze", help="Analyze benchmark results"
    )
    benchmark_analyze.add_argument(
        "session_id",
        help="Benchmark session ID to analyze",
    )
    benchmark_analyze.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file for analysis (default: workspace/benchmarks/{session}/analysis/summary.json)",
    )
    benchmark_analyze.add_argument(
        "-f",
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format (default: json)",
    )
    benchmark_analyze.set_defaults(func=cmd_benchmark_analyze)

    # benchmark models
    benchmark_models = benchmark_subparsers.add_parser(
        "models", help="List available model configs"
    )
    benchmark_models.set_defaults(func=cmd_benchmark_models)

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "config" and not args.config_action:
        parser.parse_args(["config", "--help"])
        return 0

    if args.command == "benchmark" and not getattr(args, "benchmark_action", None):
        parser.parse_args(["benchmark", "--help"])
        return 0

    if args.command == "repo" and not getattr(args, "repo_action", None):
        parser.parse_args(["repo", "--help"])
        return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
