"""English canonical form of German and French terms: a pinned local translation model, greedy decoding."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import ctranslate2
import sentencepiece

from .models import ensure_all
from .settings import Settings

LEADING = {"the", "a", "an", "to"}


class Translator:
    """One translation package (source language to English)."""

    def __init__(self, package_dir: Path):
        self.pieces = sentencepiece.SentencePieceProcessor(model_file=str(package_dir / "sentencepiece.model"))
        # ctranslate2 imports its compiled classes inside a try block, which ty reads as possibly missing
        self.model = ctranslate2.Translator(str(package_dir / "model"), device="cpu", inter_threads=4, intra_threads=1)  # ty: ignore[possibly-missing-attribute]

    def translate(self, texts: list[str], settings: Settings) -> dict[str, str]:
        """Each text on its own (batch size 1), so a translation never depends on the other texts."""
        unique = sorted(set(texts))
        tokens = [self.pieces.encode(t, out_type=str) for t in unique]
        results = self.model.translate_batch(
            tokens,
            max_batch_size=1,
            batch_type="examples",
            beam_size=1,
            max_decoding_length=settings.mt_max_decoding,
            replace_unknowns=True,
        )
        return {t: "".join(r.hypotheses[0]).replace("▁", " ").strip() for t, r in zip(unique, results, strict=True)}


def load_translators(models_dir: Path, download: bool = False) -> dict[str, Translator]:
    """A translator per non-English language, from the pinned packages in the models directory."""
    return {lang: Translator(path) for lang, path in ensure_all(models_dir, download).items()}


def english_words(text: str) -> list[str]:
    """Lowercase words of a translation, without punctuation, digits or a leading article."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s-]|_", " ", text)
    words = [w.strip("-") for w in text.lower().split()]
    words = [w for w in words if w and not w.isdigit()]
    while words and words[0] in LEADING:
        words.pop(0)
    return words
