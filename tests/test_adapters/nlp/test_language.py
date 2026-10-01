"""Language per document: a vote of words that are stop words in only one of English, German and French."""

from __future__ import annotations

from deriva.adapters.nlp.language import detect_language


class TestDetectLanguage:
    def test_english(self):
        assert detect_language("The user can register and the admin will approve it for them.") == "en"

    def test_german(self):
        assert detect_language("Der Benutzer kann sich registrieren und der Administrator wird es genehmigen.") == "de"

    def test_french(self):
        assert detect_language("Le membre peut s'inscrire et le secrétaire valid la demande avec les autres.") == "fr"

    def test_no_votes_is_english(self):
        assert detect_language("12345 ---") == "en"
