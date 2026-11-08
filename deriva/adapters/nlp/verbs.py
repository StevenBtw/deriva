"""The verb a status value names: a state written as a past participle (APPROVED, WRITTEN_OFF) is what happened to its
object (Approve, Write Off). Read with the pinned English spaCy pipeline; without it no state gets a verb."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import SPACY_PACKAGES, ensure_spacy_package

# Penn tags of a past participle or past tense form, and of the particles that belong to its verb (off, out, over, up);
# an adverb (automatically, early, back) is no part of the verb
PARTICIPLES = ("VBD", "VBN")
PARTICLES = ("RP",)


def verb_from_tokens(tokens: list[tuple[str, str, str]]) -> str | None:
    """The verb of a state's words, ``(text, lemma, tag)`` each: the lemma of a leading participle with the particles
    right after it, in title case; None when the state does not start with a participle, or with one of two letters
    or fewer (RE_OPENED: the tagger reads "re" as a past tense)."""
    if not tokens or tokens[0][2] not in PARTICIPLES or len(tokens[0][0]) <= 2:
        return None
    words = [tokens[0][1]]
    for text, _lemma, tag in tokens[1:]:
        if tag not in PARTICLES:
            break
        words.append(text)
    return " ".join(w[:1].upper() + w[1:] for w in words)


@lru_cache(maxsize=4)
def _english(models_dir: str) -> Any | None:
    # The English pipeline alone: a missing German or French one does not hide it; a missing English one gives None
    try:
        path = ensure_spacy_package(SPACY_PACKAGES["en"], Path(models_dir), download=False)
    except FileNotFoundError:
        return None
    import spacy

    return spacy.load(path)


def has_english(models_dir: Path) -> bool:
    """Whether the pinned English pipeline is in the models directory (state_verbs gives no verb without it)."""
    try:
        return _english(str(models_dir)) is not None
    except OSError, ValueError:
        return False


def state_verbs(states: list[str], models_dir: Path) -> dict[str, str]:
    """State -> its verb, for the states that name one (``SUBMITTED_FOR_REVIEW`` reads as "submitted for review")."""
    try:
        nlp = _english(str(models_dir))
    except OSError, ValueError:
        nlp = None
    if nlp is None:
        return {}
    verbs = {}
    for state in dict.fromkeys(states):
        words = [w for w in state.lower().split("_") if w]
        if not words:
            continue
        # The leading word read alone in a frame ("it was closed") decides the verb whatever follows it; the whole
        # state gives the particles after it
        lead, doc = nlp(f"it was {words[0]}")[2:], nlp(" ".join(words))
        tokens = [(t.text, t.lemma_, t.tag_) for t in lead] + [(t.text, t.lemma_, t.tag_) for t in doc][len(lead) :]
        if verb := verb_from_tokens(tokens):
            verbs[state] = verb
    return verbs
