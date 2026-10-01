"""Candidate terms in documentation (English, German, French): pinned spaCy pipelines and translation models.

spaCy and CTranslate2 load on the first extraction, not on import. The translation models are
downloaded once into the models directory (`ensure_models`).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import ensure_all
from .settings import Settings


class NlpTool:
    """The deterministic multilingual term extraction (output contract: `extract.extract`)."""

    def __init__(self, models_dir: Path | None = None):
        load_dotenv()
        self.models_dir = models_dir or Path(os.getenv("DERIVA_NLP_MODELS_DIR", "workspace/cache/nlp"))

    def ensure_models(self) -> None:
        """Download and verify the pinned translation models (nothing happens when they are present)."""
        ensure_all(self.models_dir, download=True)

    def extract(self, documents: list[dict[str, str]], settings: dict[str, Any], keep_surface: list[str]) -> dict[str, Any]:
        """Candidate terms of the documents; `settings` are the thresholds from the step config."""
        thresholds = Settings.from_dict(settings)
        from . import extract, phrases, translate

        return extract.extract(documents, thresholds, phrases.load_pipelines(), translate.load_translators(self.models_dir), frozenset(keep_surface))
