"""NLP model commands (deriva-cli nlp ...)."""

from __future__ import annotations

import typer

from deriva.services import nlp_models

app = typer.Typer(help="The language models of the BusinessConcept step")


@app.command("fetch")
def fetch() -> None:
    """Download the pinned spaCy pipelines and translation models now (about 250 MB on first use), so a run needs no
    network for them; models that are present and verified are not downloaded again."""
    try:
        result = nlp_models.fetch()
    except OSError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"NLP models in {result['models_dir']}:")
    for name, size in result["models"].items():
        typer.echo(f"  {name:<28} {size / 1_000_000:7.1f} MB")
    typer.echo(f"  {'total':<28} {sum(result['models'].values()) / 1_000_000:7.1f} MB")
