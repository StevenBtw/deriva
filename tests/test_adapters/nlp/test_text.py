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

    def test_rtf_paragraphs_stay_separate_segments(self):
        text = "{\\rtf1\\ansi\\pard First paragraph here.\\par\nSecond paragraph here.\\par\n}"

        assert [s for s in segments(clean(text)) if s] == ["First paragraph here.", "Second paragraph here."]

    def test_an_rtf_line_break_is_a_soft_wrap(self):
        assert segments(clean("{\\rtf1 One line\\line and the next.}")) == ["One line and the next."]

    def test_rtf_unicode_escapes_are_decoded_without_their_fallback(self):
        assert clean("{\\rtf1 Gr\\u252\\'fc\\u223?e aus M\\u252?nchen}").split() == ["Grüße", "aus", "München"]

    def test_comparisons_are_not_tags(self):
        assert clean("keep a < b > c here").split() == ["keep", "a", "<", "b", ">", "c", "here"]

    def test_tags_comments_and_declarations_go(self):
        assert clean("<?xml version='1.0'?><!-- note --><p class='x'>Text</p>").split() == ["Text"]

    def test_a_tag_whose_attribute_holds_a_comparison_goes_whole(self):
        assert clean('<div show="items.length < 1 && size > 2">Text</div>').split() == ["Text"]

    def test_a_tag_with_a_url_in_an_attribute_goes_whole(self):
        assert clean('Host <input placeholder="http://host:8080/path" required> here').split() == ["Host", "here"]

    def test_template_directives_go(self):
        assert clean("<#if flag??>Text</#if><@macro/>").split() == ["Text"]


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
