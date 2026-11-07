"""The NLP models of the BusinessConcept step (spaCy pipelines, translation models), fetched ahead of a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deriva.adapters.nlp import NlpTool


def fetch(models_dir: Path | None = None) -> dict[str, Any]:
    """Download and verify the pinned models (nothing is downloaded when they are present); the folder and the size
    of each model in bytes."""
    tool = NlpTool(models_dir)
    pinned = tool.ensure_models()
    folder = Path(tool.models_dir)
    models = {path.name: sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) for path in sorted(pinned.values(), key=lambda p: p.name)}
    return {"models_dir": str(folder), "models": models}
