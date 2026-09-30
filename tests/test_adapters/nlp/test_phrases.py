"""Candidate phrases: noun compounds and verb + object pairs, lemmatized, per language."""

from __future__ import annotations

from deriva.adapters.nlp.phrases import extract_occurrences
from deriva.adapters.nlp.settings import Settings

SETTINGS = Settings()


def _terms(pipelines, lang, text, keep_surface=frozenset()):
    doc = pipelines[lang](text)
    return {(o.kind, " ".join(o.words)) for o in extract_occurrences(doc, lang, 0, SETTINGS, keep_surface)}


def test_english_nouns_and_verb_objects(pipelines):
    terms = _terms(pipelines, "en", "The clerk approves every invoice request. Customers submit orders online.")

    assert ("verb", "approve request") in terms or ("verb", "approve invoice request") in terms
    assert ("verb", "submit order") in terms
    assert ("noun", "customer") in terms


def test_german_verb_object_puts_the_object_first(pipelines):
    terms = _terms(pipelines, "de", "Der Mitarbeiter prüft den Antrag und der Kunde bezahlt die Rechnung.")

    assert ("verb", "antrag prüfen") in terms
    assert ("noun", "rechnung") in terms


def test_french_noun_with_de_modifier(pipelines):
    terms = _terms(pipelines, "fr", "Le secrétaire envoie une invitation. La gestion des membres est simple.")

    assert ("verb", "envoyer invitation") in terms
    assert ("noun", "gestion de membre") in terms


def test_uncountable_words_keep_their_surface(pipelines):
    terms = _terms(pipelines, "en", "The system stores all data for the analysts.", keep_surface=frozenset({"data"}))

    assert ("noun", "data") in terms


def test_a_numbered_reference_is_not_a_concept(pipelines):
    terms = _terms(pipelines, "en", "As shown in figure 4, the invoice is approved.")

    assert ("noun", "figure") not in terms
