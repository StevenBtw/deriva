"""The extraction: documents in, candidate terms with English forms and their occurrences out."""

from __future__ import annotations

import re
from collections import Counter
from importlib.metadata import version
from typing import Any

from .language import detect_language
from .models import MT_PACKAGES
from .phrases import PIPELINES, Occurrence, extract_occurrences
from .settings import Settings
from .text import clean, duplicate_segments, is_binary, is_prose, segments
from .translate import Translator, english_words


def tool_versions() -> dict[str, Any]:
    """Versions of everything that decides the output (recorded next to the results)."""
    return {
        "spacy": version("spacy"),
        "pipelines": {lang: f"{name}-{version(name.replace('_', '-'))}" for lang, name in sorted(PIPELINES.items())},
        "translation": {lang: package.name for lang, package in sorted(MT_PACKAGES.items())},
        "ctranslate2": version("ctranslate2"),
    }


def original_display(words: tuple[str, ...], kind: str, lang: str) -> str:
    """Readable source-language form: German nouns capitalized, English title case, French as is."""
    if lang == "de":
        nouns = len(words) - 1 if kind == "verb" else len(words)
        return " ".join(w[:1].upper() + w[1:] if i < nouns else w for i, w in enumerate(words))
    if lang == "fr":
        return " ".join(words)
    return " ".join(w[:1].upper() + w[1:] for w in words)


def snippet(segment: str, occurrence: Occurrence, settings: Settings) -> str:
    """The occurrence's sentence, shortened around the occurrence to at most `snippet_chars` characters."""
    s0, s1 = occurrence.sentence
    sentence = segment[s0:s1]
    start, end = occurrence.start - s0, occurrence.end - s0
    if len(sentence) > settings.snippet_chars:
        half = (settings.snippet_chars - (end - start)) // 2
        a, b = max(0, start - half), min(len(sentence), end + half)
        while a > 0 and not sentence[a - 1].isspace():
            a += 1
        while b < len(sentence) and not sentence[b].isspace():
            b -= 1
        sentence = ("..." if a > 0 else "") + sentence[a:b] + ("..." if b < len(sentence) else "")
    return re.sub(r"\s+", " ", sentence).strip()


def _most_frequent(counter: Counter[str]) -> str:
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def extract(
    documents: list[dict[str, str]],
    settings: Settings,
    pipelines: dict[str, Any],
    translators: dict[str, Translator],
    keep_surface: frozenset[str],
) -> dict[str, Any]:
    """Candidate terms of a set of documents.

    Args:
        documents: [{"path", "text"}], in any order (processed in path order)
        settings: the thresholds
        pipelines: spaCy pipeline per language
        translators: translator per non-English language
        keep_surface: English nouns that keep their surface form (uncountable nouns)

    Returns:
        {"tool", "settings", "documents": per document language or skip reason,
         "candidates": per (language, kind, words): term, English form, count and occurrences}
    """
    info: list[dict[str, Any]] = []
    prose: dict[str, list[str]] = {}
    languages: dict[str, str] = {}
    for doc in sorted(documents, key=lambda d: d["path"]):
        path, text = doc["path"], doc["text"]
        if is_binary(text, settings):
            info.append({"path": path, "skipped": "binary"})
            continue
        prose[path] = [s for s in segments(clean(text)) if is_prose(s, settings)]
        languages[path] = detect_language(" ".join(prose[path]))
        info.append({"path": path, "language": languages[path], "prose_segments": len(prose[path])})

    dropped = duplicate_segments(prose, settings)
    for entry in info:
        if entry["path"] in prose:
            entry["duplicate_segments"] = sum(1 for p, _ in dropped if p == entry["path"])

    originals: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for path in sorted(prose):
        lang = languages[path]
        indices = [i for i in range(len(prose[path])) if (path, i) not in dropped]
        for i, parsed in zip(indices, pipelines[lang].pipe([prose[path][i] for i in indices], batch_size=64), strict=True):
            for o in extract_occurrences(parsed, lang, i, settings, keep_surface):
                candidate = originals.setdefault(
                    (lang, o.kind, o.words),
                    {"language": lang, "kind": o.kind, "words": list(o.words), "term": original_display(o.words, o.kind, lang), "surfaces": Counter(), "occurrences": []},
                )
                candidate["surfaces"][o.surface] += 1
                candidate["occurrences"].append({"path": path, "segment": i, "start": o.start, "snippet": snippet(prose[path][i], o, settings)})

    # English forms: English terms as they are; others translated from their most frequent surface form
    inputs: dict[str, set[str]] = {}
    for (lang, _, _), candidate in originals.items():
        if lang != "en":
            inputs.setdefault(lang, set()).add(_most_frequent(candidate["surfaces"]))
    translations = {lang: translators[lang].translate(sorted(texts), settings) for lang, texts in sorted(inputs.items())}

    candidates = []
    for key in sorted(originals):
        candidate = originals[key]
        lang = key[0]
        entry = {k: candidate[k] for k in ("language", "kind", "words", "term")}
        if lang == "en":
            entry["english"] = " ".join(candidate["words"])
        else:
            mt_input = _most_frequent(candidate["surfaces"])
            mt_output = translations[lang][mt_input]
            entry.update({"mt_input": mt_input, "mt_output": mt_output, "english": " ".join(english_words(mt_output)) or candidate["term"].lower()})
        entry["count"] = sum(candidate["surfaces"].values())
        entry["occurrences"] = sorted(candidate["occurrences"], key=lambda o: (o["path"], o["segment"], o["start"]))
        candidates.append(entry)
    return {"tool": tool_versions(), "settings": settings.to_dict(), "documents": info, "candidates": candidates}
