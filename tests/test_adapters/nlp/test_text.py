"""Text preparation: cleanup, segments, binary and prose filters, near-duplicate removal."""

from __future__ import annotations

from deriva.adapters.nlp.settings import Settings
from deriva.adapters.nlp.text import clean, duplicate_segments, is_binary, is_prose, segments

SETTINGS = Settings()


class TestBinary:
    def test_text_is_not_binary(self):
        assert not is_binary("A plain sentence.\nAnother line.\t", SETTINGS)

    def test_control_characters_mark_binary(self):
        assert is_binary("PNG\x00\x01\x02\x03 header" + "x" * 100, SETTINGS)


class TestClean:
    def test_markdown_code_links_and_tags_go(self):
        text = "See [the guide](http://x.org/a) and `code()`.\n```\nblock\n```\n<b>bold</b> mail@x.org"

        assert clean(text).split() == ["See", "the", "guide", "and", ".", "bold"]

    def test_line_end_hyphenation_is_repaired(self):
        assert "registration" in clean("regis-\ntration of users")

    def test_rtf_control_words_go(self):
        assert clean("{\\rtf1\\ansi Hello {\\b world}}").split() == ["Hello", "world"]


class TestSegments:
    def test_blank_lines_headings_list_items_and_cells_start_segments(self):
        text = "# Title\nfirst line\nsoft wrap\n\n- item one\n- item two\n| a | b |"

        assert segments(text) == ["Title", "first line soft wrap", "item one", "item two", "a", "b"]


class TestProse:
    def test_a_sentence_is_prose(self):
        assert is_prose("Users register their accounts here.", SETTINGS)

    def test_code_like_text_is_not(self):
        assert not is_prose('{"id": 1, "x": [2, 3]}', SETTINGS)


class TestDuplicates:
    """Segments repeated from an earlier document (path order) are dropped, at every length."""

    def test_near_duplicate_long_segment_is_dropped(self):
        docs = {
            "a.md": ["the platform stores every order for later review by the team"],
            "b.md": ["the platform stores every order for later review by the team today", "something new here"],
        }

        assert duplicate_segments(docs, SETTINGS) == {("b.md", 0)}

    def test_short_repeated_segments_are_dropped_by_exact_match(self):
        docs = {"a.md": ["Contributing", "How to build"], "b.md": ["contributing", "Other heading"]}

        assert duplicate_segments(docs, SETTINGS) == {("b.md", 0)}

    def test_repeats_within_one_document_are_kept(self):
        docs = {"a.md": ["Contributing", "contributing"]}

        assert duplicate_segments(docs, SETTINGS) == set()
