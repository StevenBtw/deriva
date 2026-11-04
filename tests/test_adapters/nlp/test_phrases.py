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


def _with(pipelines, text, **settings):
    doc = pipelines["en"](text)
    return {(o.kind, " ".join(o.words)) for o in extract_occurrences(doc, "en", 0, Settings(**settings), frozenset())}


def test_the_reader_settings_change_nothing_unless_set(pipelines):
    text = "The frontend allows Front-Desk clerks to apply for a permit and read legal notices."

    assert _with(pipelines, text) == {("noun", "frontend"), ("noun", "clerk"), ("noun", "permit"), ("noun", "notice"), ("verb", "read notice")}


def test_capitalised_words_count_as_nouns(pipelines):
    assert ("noun", "help desk clerk") in _with(pipelines, "The frontend allows Help-Desk clerks to interact.", noun_proper=True, noun_hyphens=True)
    assert ("noun", "help") not in _with(pipelines, "The frontend allows Help-Desk clerks to interact.", noun_proper=True, noun_hyphens=True)
    assert ("noun", "desk clerk") in _with(pipelines, "The frontend allows Help-Desk clerks to interact.", noun_proper=True)


def test_a_verb_takes_an_object_through_a_listed_preposition(pipelines):
    found = _with(pipelines, "Members can apply for a permit and read of the report.", verb_prepositions=("for", "to"))

    assert ("verb", "apply for permit") in found
    assert not [term for kind, term in found if kind == "verb" and " of " in term]


def test_a_passage_that_opens_with_a_verb_the_tagger_missed_is_read_as_one(pipelines):
    assert ("verb", "inspect machine") in _with(pipelines, "Inspect your first machine", leading_verbs=True)
    assert ("verb", "print to archive") in _with(pipelines, "Print to the archive", leading_verbs=True, verb_prepositions=("to",))
    # A plain noun phrase with a preposition that is not listed stays a noun phrase
    assert not [term for kind, term in _with(pipelines, "Design of the system", leading_verbs=True, verb_prepositions=("to",)) if kind == "verb"]


def test_settings_read_a_json_list_of_prepositions():
    assert Settings.from_dict({"verb_prepositions": ["for", "to"]}).verb_prepositions == ("for", "to")
