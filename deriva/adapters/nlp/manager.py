"""Candidate terms in documentation (English, German, French): pinned spaCy pipelines and translation models.

spaCy and CTranslate2 load on the first extraction, not on import. The spaCy pipelines and the
translation models are downloaded once into the models directory (`ensure_models`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deriva.common.paths import resolve
from deriva.common.settings import NlpSettings

from .models import ensure_all, ensure_spacy
from .settings import Settings


class NlpTool:
    """The deterministic multilingual term extraction (output contract: `extract.extract`)."""

    def __init__(self, models_dir: Path | None = None):
        self.models_dir = models_dir or resolve(NlpSettings().models_dir)

    def ensure_models(self) -> None:
        """Download and verify the pinned spaCy pipelines and translation models (nothing happens when they are present)."""
        ensure_spacy(self.models_dir, download=True)
        ensure_all(self.models_dir, download=True)

    def extract(self, documents: list[dict[str, str]], settings: dict[str, Any], keep_surface: list[str]) -> dict[str, Any]:
        """Candidate terms of the documents; `settings` are the thresholds from the step config."""
        thresholds = Settings.from_dict(settings)
        from . import extract, phrases, translate

        return extract.extract(documents, thresholds, phrases.load_pipelines(self.models_dir), translate.load_translators(self.models_dir), frozenset(keep_surface))
