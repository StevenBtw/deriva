"""English canonical form of German and French terms: pinned models, greedy decoding, one term at a time."""

from __future__ import annotations

import pytest

from deriva.adapters.nlp.settings import Settings
from deriva.adapters.nlp.translate import english_words

SETTINGS = Settings()


class TestEnglishWords:
    def test_lowercase_words_without_punctuation_or_leading_article(self):
        assert english_words("The Order-Management!") == ["order-management"]

    def test_leading_to_of_an_infinitive_goes(self):
        assert english_words("to send the invitation") == ["send", "the", "invitation"]

    def test_digits_go(self):
        assert english_words("Step 2 review") == ["step", "review"]


@pytest.mark.integration
class TestTranslators:
    def test_german_and_french_terms_become_english(self, translators):
        assert translators["de"].translate(["Rechnung"], SETTINGS)["Rechnung"].lower().strip(" .") == "invoice"
        assert translators["fr"].translate(["facture"], SETTINGS)["facture"].lower().strip(" .") == "invoice"

    def test_a_term_translates_the_same_whatever_else_is_translated(self, translators):
        alone = translators["de"].translate(["Rechnung"], SETTINGS)
        together = translators["de"].translate(["Kunde", "Rechnung", "Antrag prüfen"], SETTINGS)

        assert alone["Rechnung"] == together["Rechnung"]
