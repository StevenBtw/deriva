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
) -> None:
    """Clone a repository."""
    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Cloning Repository")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"URL: {url}")
    if name:
        typer.echo(f"Name: {name}")
    if branch:
        typer.echo(f"Branch: {branch}")

    with PipelineSession() as session:
        result = session.clone_repository(url=url, name=name, branch=branch, overwrite=overwrite)
        if result.get("success"):
            typer.echo("\nRepository cloned successfully!")
            typer.echo(f"  Name: {result.get('name', 'N/A')}")
            typer.echo(f"  Path: {result.get('path', 'N/A')}")
            typer.echo(f"  URL:  {result.get('url', url)}")
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
            typer.echo("  deriva repo clone <url>")
            return

        typer.echo(f"\n{'=' * 60}")
        typer.echo("REPOSITORIES")
        typer.echo(f"{'=' * 60}")
        typer.echo(f"Workspace: {session.workspace_dir}\n")

        for repo in repos:
            if detailed:
                dirty = " (dirty)" if repo.get("is_dirty") else ""
                typer.echo(f"  {repo['name']}{dirty}")
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
) -> None:
    """Delete a repository."""
    typer.echo(f"\n{'=' * 60}")
    typer.echo("DERIVA - Deleting Repository")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"Repository: {name}")

    with PipelineSession() as session:
        try:
            result = session.delete_repository(name=name, force=force)
            if result.get("success"):
                typer.echo(f"\nRepository '{name}' deleted successfully.")
            else:
                typer.echo(f"\nError: {result.get('error', 'Unknown error')}", err=True)
                raise typer.Exit(1)
        except Exception as e:
            typer.echo(f"\nError: {e}", err=True)
            if "uncommitted changes" in str(e).lower():
                typer.echo("Use --force to delete anyway.")
            raise typer.Exit(1)


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
