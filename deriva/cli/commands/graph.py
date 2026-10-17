"""Graph maintenance commands (deriva-cli graph ...)."""

from __future__ import annotations

from typing import Annotated

import typer

from deriva.services.session import PipelineSession

app = typer.Typer(help="Maintain the intermediate graph")


@app.command("tag-steps")
def tag_steps(
    repo: Annotated[str, typer.Option("--repo", help="Repository whose graph database to tag")],
) -> None:
    """Tag the graph's nodes and edges with the extraction step that wrote them (once, for graphs written before steps tagged their output; no LLM)."""
    with PipelineSession(repository=repo) as session:
        report = session.tag_graph_steps(repo)
    for kind in ("nodes", "edges"):
        counts = report.get(kind, {})
        typer.echo(f"Tagged {kind}: {sum(counts.values())}" + (f" ({', '.join(f'{k} {v}' for k, v in sorted(counts.items()))})" if counts else ""))
    for kind in ("untagged_nodes", "untagged_edges"):
        counts = report.get(kind, {})
        if counts:
            typer.echo(f"Left untagged ({kind.split('_')[1]}, no rule, never swept): {', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}")
