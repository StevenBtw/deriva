"""Candidate phrases with spaCy: noun compounds and verb + object pairs, lemmatized, per language."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import spacy

from .language import STOP_WORDS
from .settings import Settings

PIPELINES = {"en": "en_core_web_sm", "de": "de_core_news_sm", "fr": "fr_core_news_sm"}
# A code identifier inside a word (userId)
CAMEL = re.compile(r"[a-zäöüßàâçéèêëîïôûùüÿœ][A-ZÄÖÜ]")
# French attaches a noun modifier with de/du/des ("gestion des utilisateurs")
FR_DE = {"de", "du", "des", "d'", "d’"}


@dataclass(frozen=True)
class Occurrence:
    kind: str  # "noun" or "verb"
    language: str
    segment: int
    words: tuple[str, ...]
    surface: str
    start: int  # character offsets in the segment
    end: int
    sentence: tuple[int, int]


def load_pipelines() -> dict[str, Any]:
    """The pinned spaCy pipeline per language."""
    return {lang: spacy.load(name) for lang, name in PIPELINES.items()}


def _valid(token: Any) -> bool:
    return token.is_alpha and len(token.text) >= 2 and not token.is_stop and not CAMEL.search(token.text)


def _noun_form(token: Any, lang: str, keep_surface: frozenset[str]) -> str:
    surface = token.text.lower()
    if lang == "en" and surface in keep_surface:
        return surface  # uncountable nouns keep their form (the lemmatizer turns "data" into "datum")
    lemma = token.lemma_
    return (lemma if lemma.isalpha() else token.text).lower()


def _next_token(doc: Any, i: int) -> Any:
    j = i + 1
    while j < len(doc) and doc[j].is_space:
        j += 1
    return doc[j] if j < len(doc) else None


def _occurrence(kind: str, lang: str, segment: int, words: list[str], surface: str, tokens: list[Any], sentence: Any) -> Occurrence:
    return Occurrence(
        kind=kind,
        language=lang,
        segment=segment,
        words=tuple(words),
        surface=surface,
        start=min(t.idx for t in tokens),
        end=max(t.idx + len(t.text) for t in tokens),
        sentence=(sentence.start_char, sentence.end_char),
    )


def _prose_sentences(doc: Any, settings: Settings) -> set[int]:
    kept = set()
    for sentence in doc.sents:
        tokens = [t for t in sentence if not t.is_space]
        alpha = sum(1 for t in tokens if t.is_alpha)
        if tokens and alpha >= settings.sentence_min_alpha_tokens and alpha / len(tokens) >= settings.sentence_min_alpha_ratio:
            kept.add(sentence.start)
    return kept


def _noun_phrases(doc: Any, lang: str, segment: int, settings: Settings, keep_surface: frozenset[str], kept: set[int]) -> list[Occurrence]:
    out = []
    for chunk in doc.noun_chunks:
        root = chunk.root
        if root.sent.start not in kept or root.pos_ != "NOUN" or not _valid(root):
            continue
        following = _next_token(doc, root.i)
        if following is not None and following.like_num:
            continue  # "Figure 4", "step 2": a numbered reference, not a concept
        if lang == "fr":  # head first: noun + de + noun
            modifiers = [
                c
                for c in root.children
                if c.dep_ == "nmod" and c.pos_ == "NOUN" and _valid(c) and 0 < c.i - root.i <= 3 and any(cc.dep_ == "case" and cc.lower_ in FR_DE for cc in c.children)
            ]
            tokens, words = [root], [_noun_form(root, lang, keep_surface)]
            if modifiers:
                tokens = [root, modifiers[0]]
                words = [_noun_form(root, lang, keep_surface), "de", _noun_form(modifiers[0], lang, keep_surface)]
            out.append(_occurrence("noun", lang, segment, words, doc[root.i : tokens[-1].i + 1].text, tokens, root.sent))
            continue
        tokens = [root]
        i = root.i - 1
        while i >= chunk.start and len(tokens) < settings.max_noun_tokens:
            token = doc[i]
            if token.pos_ != "NOUN" or not _valid(token):
                break
            tokens.insert(0, token)
            i -= 1
        words = [_noun_form(t, lang, keep_surface) for t in tokens]
        out.append(_occurrence("noun", lang, segment, words, " ".join(t.text for t in tokens), tokens, root.sent))
    return out


def _verb_objects(verb: Any, lang: str) -> tuple[list[str], list[Any]]:
    lemma = verb.lemma_.lower()
    if lang == "en":
        particles = [c.lower_ for c in verb.children if c.dep_ == "prt" and c.is_alpha]
        objects = [c for c in verb.children if c.dep_ in ("dobj", "nsubjpass")]
        objects += [cc for o in list(objects) for cc in o.children if cc.dep_ == "conj"]
        return [lemma, *particles[:1]], objects
    if lang == "de":
        prefixes = [c.lower_ for c in verb.children if c.dep_ == "svp" and c.is_alpha]
        objects = [c for c in verb.children if c.dep_ == "oa"]
        if verb.tag_ == "VVPP" and verb.dep_ == "oc" and verb.head.lemma_ == "werden":
            objects += [c for c in verb.head.children if c.dep_ == "sb"]  # subject of a werden-passive
        objects += [cj for o in list(objects) for cd in o.children if cd.dep_ == "cd" for cj in cd.children if cj.dep_ == "cj"]
        return [(prefixes[0] + lemma) if prefixes else lemma], objects
    objects = [c for c in verb.children if c.dep_ in ("obj", "nsubj:pass")]
    objects += [cc for o in list(objects) for cc in o.children if cc.dep_ == "conj"]
    return [lemma], objects


def _verb_phrases(doc: Any, lang: str, segment: int, settings: Settings, keep_surface: frozenset[str], kept: set[int]) -> list[Occurrence]:
    out = []
    stop = STOP_WORDS[lang]
    for verb in doc:
        if verb.pos_ != "VERB" or verb.sent.start not in kept:
            continue
        lemma = verb.lemma_.lower()
        if not lemma.isalpha() or len(lemma) < 2 or lemma in stop or CAMEL.search(verb.text):
            continue
        verb_words, objects = _verb_objects(verb, lang)
        for obj in objects:
            if obj.pos_ != "NOUN" or not _valid(obj):
                continue
            obj_tokens = [obj]
            if lang == "en":
                compounds = [c for c in obj.children if c.dep_ == "compound" and c.i == obj.i - 1 and c.pos_ == "NOUN" and _valid(c)]
                obj_tokens = (compounds + obj_tokens)[-settings.max_object_tokens :]
            obj_words = [_noun_form(t, lang, keep_surface) for t in obj_tokens]
            obj_surface = " ".join(t.text for t in obj_tokens)
            if lang == "de":  # German verb phrases read object first ("Antrag prüfen")
                words, surface = obj_words + verb_words, f"{obj_surface} {' '.join(verb_words)}"
            else:
                words, surface = verb_words + obj_words, f"{' '.join(verb_words)} {obj_surface}"
            out.append(_occurrence("verb", lang, segment, words, surface, [verb, *obj_tokens], verb.sent))
    return out


def extract_occurrences(doc: Any, lang: str, segment: int, settings: Settings, keep_surface: frozenset[str]) -> list[Occurrence]:
    """Noun compounds and verb + object pairs in the prose sentences of one parsed segment."""
    kept = _prose_sentences(doc, settings)
    return _noun_phrases(doc, lang, segment, settings, keep_surface, kept) + _verb_phrases(doc, lang, segment, settings, keep_surface, kept)
