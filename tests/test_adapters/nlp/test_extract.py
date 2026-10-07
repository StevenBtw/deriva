"""The extraction contract: documents and settings in, candidates with English forms and occurrences out."""

from __future__ import annotations

import json

import pytest

from deriva.adapters.nlp.extract import extract
from deriva.adapters.nlp.settings import Settings

pytestmark = pytest.mark.integration

DOCUMENTS = [
    {"path": "docs/b_de.md", "text": "# Ablauf\n\nDer Mitarbeiter prüft den Antrag. Der Kunde bezahlt die Rechnung pünktlich."},
    {"path": "docs/a_en.md", "text": "# Process\n\nThe clerk approves every invoice. Customers pay the invoice on time."},
    {"path": "docs/c_copy.md", "text": "# Process\n\nThe clerk approves every invoice. Customers pay the invoice on time."},
    {"path": "img/logo.png", "text": "\x89PNG\x00\x01\x02\x03\x04" * 20},
]


@pytest.fixture(scope="module")
def result(pipelines, translators):
    return extract(DOCUMENTS, Settings(), pipelines, translators, keep_surface=frozenset({"data"}))


def test_documents_report_language_and_skips(result):
    by_path = {d["path"]: d for d in result["documents"]}

    assert by_path["docs/a_en.md"]["language"] == "en"
    assert by_path["docs/b_de.md"]["language"] == "de"
    assert by_path["img/logo.png"]["skipped"] == "binary"


def test_candidates_carry_an_english_form(result):
    by_term = {(c["language"], c["term"]): c for c in result["candidates"]}

    assert by_term[("de", "Rechnung")]["english"] == "invoice"
    assert by_term[("en", "Invoice")]["english"] == "invoice"


def test_occurrences_skip_the_copied_document(result):
    invoice = next(c for c in result["candidates"] if (c["language"], c["term"]) == ("en", "Invoice"))

    assert {o["path"] for o in invoice["occurrences"]} == {"docs/a_en.md"}
    assert all(o["snippet"] for o in invoice["occurrences"])


def test_the_output_is_deterministic(pipelines, translators, result):
    again = extract(list(reversed(DOCUMENTS)), Settings(), pipelines, translators, keep_surface=frozenset({"data"}))

    assert json.dumps(again, sort_keys=True) == json.dumps(result, sort_keys=True)
