"""Canonical names: one identity key for every spelling of a name.

Pure and shared by every layer. LLM-written and structural names are compared
and turned into identities through ``name_key``, so spelling variants of the
same name ("Claims Handling", "ClaimsHandling", "claims_handling") never become
separate graph nodes.
"""

from __future__ import annotations

import re

# =============================================================================
# Singularization Rules
# =============================================================================

# Words that shouldn't be singularized (mass nouns, collective nouns).
# Used by singularize() to avoid incorrect transformations like "data" -> "datum".
UNCOUNTABLE_WORDS = {
    "data",
    "information",
    "software",
    "hardware",
    "middleware",
    "metadata",
    "analytics",
    "logistics",
    "news",
    "status",
    "series",
    "species",
}

# Irregular plurals mapping (plural -> singular).
# Used by singularize() to handle words that don't follow standard rules.
# Example: "indices" -> "index", "criteria" -> "criterion"
IRREGULAR_PLURALS: dict[str, str] = {
    "indices": "index",
    "matrices": "matrix",
    "vertices": "vertex",
    "appendices": "appendix",
    "analyses": "analysis",
    "bases": "base",
    "crises": "crisis",
    "theses": "thesis",
    "hypotheses": "hypothesis",
    "syntheses": "synthesis",
    "diagnoses": "diagnosis",
    "prognoses": "prognosis",
    "parentheses": "parenthesis",
    "emphases": "emphasis",
    "synopses": "synopsis",
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "curricula": "curriculum",
    "memoranda": "memorandum",
    "stimuli": "stimulus",
    "radii": "radius",
    "nuclei": "nucleus",
    "data": "data",  # Keep as is
    "media": "medium",
    "children": "child",
    "people": "person",
    "men": "man",
    "women": "woman",
    "feet": "foot",
    "teeth": "tooth",
    "mice": "mouse",
    "lives": "life",
    "knives": "knife",
    "wives": "wife",
    "halves": "half",
    "shelves": "shelf",
    "selves": "self",
    "wolves": "wolf",
    "thieves": "thief",
    "heroes": "hero",
    "echoes": "echo",
    "vetoes": "veto",
    "potatoes": "potato",
    "embargoes": "embargo",
    "cargoes": "cargo",
    "quizzes": "quiz",
}

# Singular words ending in "s"; they take "-es" in the plural ("aliases", "buses").
S_ENDING_SINGULARS = {
    "alias",
    "atlas",
    "bias",
    "canvas",
    "gas",
    "lens",
    "chaos",
    "abacus",
    "apparatus",
    "bonus",
    "bus",
    "cactus",
    "campus",
    "census",
    "chorus",
    "circus",
    "consensus",
    "corpus",
    "exodus",
    "focus",
    "fungus",
    "genius",
    "hiatus",
    "nexus",
    "nucleus",
    "octopus",
    "prospectus",
    "radius",
    "stimulus",
    "stylus",
    "surplus",
    "syllabus",
    "terminus",
    "thesaurus",
    "virus",
}

# Singular words ending in "-che" or "-ie"; they only add "s" ("caches", "cookies"),
# where the rules would otherwise drop "es" or turn "-ies" into "-y".
E_ENDING_SINGULARS = {
    "cache",
    "niche",
    "headache",
    "calorie",
    "cookie",
    "hoodie",
    "pie",
    "rookie",
    "selfie",
    "tie",
    "zombie",
}


def singularize(word: str) -> str:
    """The singular form of an English word; a singular comes back unchanged, so the
    singular and the plural of a word always meet in one form.

    In order: uncountable words and singulars ending in "s" stay; irregular plurals map;
    "-es" is dropped after a singular that ends in "s" ("aliases", "classes") and after
    "x", "sh", "ch", "zz" or "tz" ("boxes", "batches"); "-ies" after a consonant becomes
    "-y" ("cities"); otherwise a final "s" is dropped ("databases", "caches", "sizes",
    "cookies"), except after "ss", "us" or "sis" ("class", "bonus", "analysis").
    """
    lower_word = word.lower()

    if lower_word in UNCOUNTABLE_WORDS or lower_word in S_ENDING_SINGULARS:
        return word

    if lower_word in IRREGULAR_PLURALS:
        # Preserve original case pattern
        singular = IRREGULAR_PLURALS[lower_word]
        if word[0].isupper():
            return singular.capitalize()
        return singular

    if lower_word.endswith("es") and lower_word[:-1] not in E_ENDING_SINGULARS:
        stem = lower_word[:-2]
        if stem.endswith("ss") or stem in S_ENDING_SINGULARS or stem in UNCOUNTABLE_WORDS:
            return word[:-2]
        if lower_word.endswith(("xes", "shes", "ches", "zzes", "tzes")):
            return word[:-2]
        if lower_word.endswith("ies") and len(lower_word) > 3 and lower_word[-4] not in "aeiou":
            return word[:-3] + ("Y" if word[-3].isupper() else "y")

    # Words that only look plural: class, analysis, bonus
    if lower_word.endswith(("ss", "sis", "us")):
        return word

    if lower_word.endswith("s") and len(lower_word) > 2:
        return word[:-1]

    return word


# ASCII camel-case words, acronym plurals, acronyms and numbers ("HTTPServer" -> HTTP, Server; "ManageAPIs" -> Manage, APIs)
_CAMEL_WORDS = re.compile(r"[A-Z]{2,}s(?![a-z])|[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
# A word with its trailing "+" or "#" ("C++", "C#"); a "+" or "#" before another word separates
_CHUNKS = re.compile(r"[^\W_]+(?:[+#]+(?![^\W_]))?")
_ACRONYM_PLURAL = re.compile(r"[A-Z]{2,}s")


def _words(name: str) -> list[str]:
    """The words of a name: split at separators and camel-case boundaries, asides dropped."""
    name = re.sub(r"\([^)]*\)", " ", name)
    words: list[str] = []
    for chunk in _CHUNKS.findall(name):
        base = chunk.rstrip("+#")
        parts = _CAMEL_WORDS.findall(base)
        # Chunks with characters the ASCII pattern does not cover (non-ASCII letters) stay whole
        if "".join(parts) != base:
            parts = [base]
        parts[-1] += chunk[len(base) :]
        words.extend(parts)
    return words


def _key_word(word: str, acronyms: bool) -> str:
    """One word of a name key: an acronym plural loses its "s", an acronym stays as written, other words are made singular."""
    if _ACRONYM_PLURAL.fullmatch(word):
        return word[:-1].casefold()
    if acronyms and word.isupper():
        return word.casefold()
    return singularize(word).casefold()


def name_key(name: str) -> str:
    """Formatting-independent identity key of a name.

    Words are split at spaces, underscores, hyphens, dots and camel-case or
    acronym boundaries, parenthetical asides are dropped, every word is made
    singular ("LikesAggregation" / "Like Aggregation"), and the casefolded words
    are joined without separators, so compound spellings ("Realtime" /
    "Real Time") share one key. Acronyms are not made singular ("AWS", "DNS
    Server"), an acronym plural meets its acronym ("APIs" / "API"), and a
    trailing "+" or "#" belongs to its word ("C++", "C#"). A name written
    entirely in capitals with several words (a constant) is made singular word
    by word, as its words are not acronyms.
    """
    words = _words(name)
    acronyms = len(words) == 1 or any(ch.islower() for ch in name)
    return "".join(_key_word(word, acronyms) for word in words)


def contains_name(text: str, name: str) -> bool:
    """Whether ``name``, in any spelling, is one or more consecutive words of ``text``: its key equals the joined keys
    of those words ("Big Data Kafka" holds "bigdata", "acme/teastore-persistence" holds "TeaStore"). Part of a word
    or part of the name does not count."""
    key = name_key(name)
    keys = [name_key(word) for word in _words(text)]
    for start in range(len(keys)):
        joined = ""
        for word in keys[start:]:
            joined += word
            if joined == key:
                return True
            if not key.startswith(joined):
                break
    return False
