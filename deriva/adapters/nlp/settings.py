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
    # English only, each off by default. A capitalised word (tagged a proper noun) counts as a noun; a hyphen does not end a
    # compound
    noun_proper: bool = False
    noun_hyphens: bool = False
    # English only. A verb also takes its object through these prepositions ("apply for a permit"); a sentence's first word,
    # tagged a noun but with an object or a listed preposition, is read as a verb (imperative headings and list items)
    verb_prepositions: tuple[str, ...] = ()
    leading_verbs: bool = False
    # Translation: greedy decoding, at most this many output tokens per term
    mt_max_decoding: int = 24
    # Context snippet around an occurrence, at most this many characters
    snippet_chars: int = 200

    def __post_init__(self) -> None:
        if self.dedup_shingle < 1:
            raise ValueError(f"dedup_shingle must be at least 1 word, got {self.dedup_shingle}")

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Settings:
        """Settings from a JSON object; unknown names are an error, so a typo never falls back to a default."""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"Unknown settings: {', '.join(unknown)}")
        for f in fields(cls):
            value = values.get(f.name)
            if f.name not in values:
                continue
            if isinstance(f.default, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"{f.name} must be true or false, got {value!r}")
            elif isinstance(f.default, int) and (isinstance(value, bool) or not isinstance(value, int)):
                raise ValueError(f"{f.name} must be a whole number, got {value!r}")
            elif isinstance(f.default, float) and (isinstance(value, bool) or not isinstance(value, int | float)):
                raise ValueError(f"{f.name} must be a number, got {value!r}")
        if "verb_prepositions" in values:
            words = values["verb_prepositions"]
            if not isinstance(words, list | tuple) or not all(isinstance(w, str) and w for w in words):
                raise ValueError(f"verb_prepositions must be a list of words, got {words!r}")
            values = {**values, "verb_prepositions": tuple(words)}
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
