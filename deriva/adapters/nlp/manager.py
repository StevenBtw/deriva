"""Runs `deriva-nlp` (tools/nlp) as a subprocess in its own environment and exchanges JSON files with it.

The tool needs spaCy and CTranslate2, which run on Python 3.12, so it is a separate uv project.
Its translation models are downloaded once into the models directory (`ensure_models`).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[..., subprocess.CompletedProcess]


class NlpToolError(RuntimeError):
    """The tool failed; the message carries its error output."""


class NlpTool:
    """The `deriva-nlp` command of the tools/nlp project."""

    def __init__(self, project_dir: Path | None = None, models_dir: Path | None = None, runner: Runner = subprocess.run):
        self.project_dir = project_dir or Path(os.getenv("DERIVA_NLP_PROJECT", "tools/nlp"))
        self.models_dir = models_dir or Path(os.getenv("DERIVA_NLP_MODELS_DIR", "workspace/cache/nlp"))
        self._runner = runner

    def _run(self, *args: str) -> None:
        command = ["uv", "run", "--project", str(self.project_dir), "--python", "3.12", "deriva-nlp", *args]
        # The caller's virtual environment is not the tool's
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        done = self._runner(command, capture_output=True, text=True, encoding="utf-8", env=env)
        if done.returncode != 0:
            raise NlpToolError(f"deriva-nlp {args[0]} failed: {(done.stderr or '').strip()[-2000:]}")

    def ensure_models(self) -> None:
        """Download and verify the pinned translation models (nothing happens when they are present)."""
        self._run("models", "--models-dir", str(self.models_dir.resolve()))

    def extract(self, documents: list[dict[str, str]], settings: dict[str, Any], keep_surface: list[str]) -> dict[str, Any]:
        """Candidate terms of the documents (see the tool's extract contract)."""
        with tempfile.TemporaryDirectory() as tmp:
            request, result = Path(tmp) / "request.json", Path(tmp) / "result.json"
            request.write_text(json.dumps({"documents": documents, "settings": settings, "keep_surface": keep_surface}, ensure_ascii=False), encoding="utf-8")
            self._run("extract", "--input", str(request), "--output", str(result), "--models-dir", str(self.models_dir.resolve()))
            return json.loads(result.read_text(encoding="utf-8"))
