"""Settings of the extraction. The caller passes them (Deriva: from the versioned step config)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class Settings:
    """Thresholds that change results. The defaults are the values the experiments fixed up front."""

    # A document is binary when more than this share of its characters are control or replacement characters
    binary_share: float = 0.01
    # A segment is prose with at least this many alphabetic words, forming at least this share of its words
    segment_min_words: int = 3
    segment_min_alpha: float = 0.6
    # A parsed sentence is prose with at least this many alphabetic tokens, forming at least this share
    sentence_min_alpha_tokens: int = 3
    sentence_min_alpha_ratio: float = 0.6
    # Near duplicates: word shingles of this size, dropped at this Jaccard similarity with an earlier document
    dedup_shingle: int = 3
    dedup_jaccard: float = 0.8
    # Noun compound: head noun plus modifiers, at most this many nouns; English verb object at most this many
    max_noun_tokens: int = 3
    max_object_tokens: int = 2
    # Translation: greedy decoding, at most this many output tokens per term
    mt_max_decoding: int = 24
    # Context snippet around an occurrence, at most this many characters
    snippet_chars: int = 200

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Settings:
        """Settings from a JSON object; unknown names are an error, so a typo never falls back to a default."""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(unknown)}")
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
