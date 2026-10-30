"""
Repository CLI commands.

Provides commands for managing repositories.
"""

from __future__ import annotations

from typing import Annotated

import typer

from deriva.services.session import PipelineSession

app = typer.Typer(name="repo", help="Manage repositories")


@app.command("clone")
def repo_clone(
    url: Annotated[str, typer.Argument(help="Repository URL to clone")],
    name: Annotated[str | None, typer.Option("-n", "--name", help="Custom name for the repository")] = None,
    branch: Annotated[str | None, typer.Option("-b", "--branch", help="Branch to clone")] = None,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="Overwrite existing repository")] = False,
    no_submodules: Annotated[bool, typer.Option("--no-submodules", help="Skip git submodules")] = False,
) -> None:
    """Clone a repository (a file:// URL clones a local repository)."""
    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Cloning Repository")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"URL: {PipelineSession.shown_url(url)}")
    if name:
        typer.echo(f"Name: {name}")
    if branch:
        typer.echo(f"Branch: {branch}")

    with PipelineSession() as session:
        result = session.clone_repository(url=url, name=name, branch=branch, overwrite=overwrite, submodules=not no_submodules, allow_local=True)
        if result.get("success"):
            typer.echo("\nRepository cloned successfully!")
            typer.echo(f"  Name: {result.get('name', 'N/A')}")
            typer.echo(f"  Path: {result.get('path', 'N/A')}")
            typer.echo(f"  URL:  {PipelineSession.shown_url(result.get('url', url))}")
        else:
            typer.echo(f"\nError: {result.get('error', 'Unknown error')}", err=True)
            raise typer.Exit(1)


@app.command("list")
def repo_list(
    detailed: Annotated[bool, typer.Option("-d", "--detailed", help="Show detailed information")] = False,
) -> None:
    """List all repositories."""
    with PipelineSession() as session:
        repos = session.get_repositories(detailed=detailed)

        if not repos:
            typer.echo("\nNo repositories found.")
            typer.echo(f"Workspace: {session.workspace_dir}")
            typer.echo("\nClone a repository with:")
            typer.echo("  deriva-cli repo clone <url>")
            return

        typer.echo(f"\n{'=' * 60}")
        typer.echo("REPOSITORIES")
        typer.echo(f"{'=' * 60}")
        typer.echo(f"Workspace: {session.workspace_dir}\n")

        for repo in repos:
            if detailed:
                dirty = " (dirty)" if repo.get("is_dirty") else ""
                stale = f" (stale: {repo['stale']}; delete removes the record only)" if repo.get("stale") else ""
                typer.echo(f"  {repo['name']}{dirty}{stale}")
                typer.echo(f"    URL:    {repo.get('url', 'N/A')}")
                typer.echo(f"    Branch: {repo.get('branch', 'N/A')}")
                typer.echo(f"    Size:   {repo.get('size_mb', 0):.2f} MB")
                typer.echo(f"    Cloned: {repo.get('cloned_at', 'N/A')}")
                typer.echo("")
            else:
                typer.echo(f"  {repo['name']}")

        typer.echo(f"\nTotal: {len(repos)} repositories")


@app.command("delete")
def repo_delete(
    name: Annotated[str, typer.Argument(help="Repository name to delete")],
    force: Annotated[
        bool,
        typer.Option("-f", "--force", help="Force delete even with uncommitted changes"),
    ] = False,
    with_data: Annotated[
        bool,
        typer.Option("--with-data", help="Also delete the repository's graph database (its graph and model)"),
    ] = False,
) -> None:
    """Delete a repository."""
    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Deleting Repository")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"Repository: {name}")

    with PipelineSession() as session:
        try:
            result = session.delete_repository(name=name, force=force, with_data=with_data)
            if result.get("success"):
                typer.echo(f"\nRepository '{name}' deleted successfully.")
                if result.get("data_deleted"):
                    typer.echo("Its graph and model were deleted too.")
            else:
                typer.echo(f"\nError: {result.get('error', 'Unknown error')}", err=True)
                raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"\nError: {e}", err=True)
            if "uncommitted changes" in str(e).lower():
                typer.echo("Use --force to delete anyway.")
            raise typer.Exit(1)


@app.command("update")
def repo_update(
    name: Annotated[str, typer.Argument(help="Repository name to update")],
) -> None:
    """Pull the latest commits of a repository's branch (fast-forward only; refused with uncommitted changes)."""
    with PipelineSession() as session:
        result = session.update_repository(name)
    if not result.get("success"):
        typer.echo(f"Error: {result.get('error', 'Update failed')}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Repository '{name}' updated.")
    typer.echo(f"  Commit: {result['repository'].get('last_commit', '')}")
    typer.echo("The graph still holds the last extraction: run extraction to read the new commits.")


@app.command("register")
def repo_register(
    name: Annotated[str | None, typer.Argument(help="Folder in the workspace to register (omit to list the unregistered ones)")] = None,
) -> None:
    """Register a git folder in the workspace that has no record (a lost record, a checkout put there by hand)."""
    with PipelineSession() as session:
        if name is None:
            names = session.unregistered_repositories()
            if not names:
                typer.echo("Every git folder in the workspace is registered.")
                return
            typer.echo("Git folders in the workspace without a record:")
            for folder in names:
                typer.echo(f"  {folder}")
            typer.echo("\nRegister one with:\n  deriva-cli repo register <name>")
            return
        result = session.register_repository(name)
    if not result.get("success"):
        typer.echo(f"Error: {result.get('error', 'Register failed')}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Repository '{name}' registered.")
    typer.echo(f"  Branch: {result.get('branch') or 'N/A'}")
    typer.echo(f"  Commit: {result.get('last_commit') or 'N/A'}")


@app.command("info")
def repo_info(
    name: Annotated[str, typer.Argument(help="Repository name")],
) -> None:
    """Show repository details."""
    with PipelineSession() as session:
        try:
            info = session.get_repository_info(name)

            if not info:
                typer.echo(f"\nRepository '{name}' not found.", err=True)
                raise typer.Exit(1)

            typer.echo(f"\n{'=' * 60}")
            typer.echo(f"REPOSITORY: {info['name']}")
            typer.echo(f"{'=' * 60}")
            typer.echo(f"  Path:        {info.get('path', 'N/A')}")
            typer.echo(f"  URL:         {info.get('url', 'N/A')}")
            typer.echo(f"  Branch:      {info.get('branch', 'N/A')}")
            typer.echo(f"  Last Commit: {info.get('last_commit', 'N/A')}")
            typer.echo(f"  Dirty:       {info.get('is_dirty', False)}")
            typer.echo(f"  Size:        {info.get('size_mb', 0):.2f} MB")
            typer.echo(f"  Cloned At:   {info.get('cloned_at', 'N/A')}")
            typer.echo("")
        except Exception as e:
            typer.echo(f"\nError: {e}", err=True)
            raise typer.Exit(1)
