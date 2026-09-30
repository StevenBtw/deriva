"""Language per document: English, German or French, by a vote of language-specific stop words."""

from __future__ import annotations

import re

from spacy.lang.de.stop_words import STOP_WORDS as DE_STOP
from spacy.lang.en.stop_words import STOP_WORDS as EN_STOP
from spacy.lang.fr.stop_words import STOP_WORDS as FR_STOP

LANGUAGES = ("en", "de", "fr")
STOP_WORDS = {"en": EN_STOP, "de": DE_STOP, "fr": FR_STOP}
# Words that are a stop word in exactly one of the languages
ONLY = {lang: frozenset(STOP_WORDS[lang] - set().union(*(STOP_WORDS[o] for o in STOP_WORDS if o != lang))) for lang in STOP_WORDS}
# Ties go to English, then German
PRIORITY = {"en": 2, "de": 1, "fr": 0}
WORD = re.compile(r"[a-zà-öø-ÿœæß]+")


def detect_language(text: str) -> str:
    """The language whose own stop words occur most often in the text."""
    words = WORD.findall(text.lower())
    votes = {lang: sum(1 for w in words if w in ONLY[lang]) for lang in LANGUAGES}
    return max(LANGUAGES, key=lambda lang: (votes[lang], PRIORITY[lang]))
