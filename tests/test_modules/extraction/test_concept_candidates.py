"""Business concepts from candidate terms: merge, evidence, selection, batches, closed classification."""

from __future__ import annotations

import json

import pytest

from deriva.modules.extraction import concept_candidates as cc


def _tool_candidate(term, language, english, occurrences, kind="noun"):
    return {
        "term": term,
        "language": language,
        "kind": kind,
        "english": english,
        "count": len(occurrences),
        "occurrences": [{"path": p, "segment": s, "start": 0, "snippet": text} for p, s, text in occurrences],
    }


class TestMerge:
    def test_one_candidate_per_english_identity(self):
        tool = [
            _tool_candidate("Hauptbuch", "de", "ledger", [("b.md", 0, "Das Hauptbuch wird geführt.")]),
            _tool_candidate("Ledger", "en", "ledger", [("a.md", 0, "The ledger is closed."), ("a.md", 1, "Each ledger has entries.")]),
        ]

        (ledger,) = cc.merge_candidates(tool, "repo")

        assert (ledger.key, ledger.name, ledger.count) == ("ledger", "Ledger", 3)
        assert ledger.documents == {"a.md": 2, "b.md": 1}
        assert [(o["term"], o["language"]) for o in ledger.originals] == [("Ledger", "en"), ("Hauptbuch", "de")]

    def test_a_translated_name_is_title_case_with_a_singular_head(self):
        (candidate,) = cc.merge_candidates([_tool_candidate("Hauptbücher", "de", "ledgers", [("b.md", 0, "x")])], "repo")

        assert candidate.name == "Ledger"

    def test_the_repository_name_is_not_a_candidate(self):
        assert cc.merge_candidates([_tool_candidate("Shop", "en", "shop", [("a.md", 0, "x")])], "shop") == []

    def test_snippets_come_from_the_documents_that_mention_it_most(self):
        tool = [
            _tool_candidate("Ledger", "en", "ledger", [("a.md", 0, "first a"), ("b.md", 0, "first b"), ("b.md", 2, "second b")]),
        ]

        (candidate,) = cc.merge_candidates(tool, "repo")

        assert candidate.snippets == ["first b", "first a"]
        assert candidate.snippet_paths == ["b.md", "a.md"]

    def test_with_one_document_the_second_snippet_is_a_different_sentence(self):
        tool = [_tool_candidate("Ledger", "en", "ledger", [("a.md", 0, "same"), ("a.md", 0, "same"), ("a.md", 3, "other")])]

        (candidate,) = cc.merge_candidates(tool, "repo")

        assert candidate.snippets == ["same", "other"]
        assert candidate.snippet_paths == ["a.md", "a.md"]


class TestPhrases:
    """A translated clause or phrase (its English name holds a stop word) is no term."""

    @staticmethod
    def _candidates():
        tool = [
            _tool_candidate("Buch gliedern", "de", "books are divided", [("a.md", 0, "x")]),
            _tool_candidate("Austausch", "de", "exchange of information", [("a.md", 0, "x")]),
            _tool_candidate("Überblick bieten", "de", "provide an overview", [("a.md", 0, "x")]),
            _tool_candidate("Ledger", "en", "ledger", [("a.md", 0, "x")]),
        ]
        return cc.merge_candidates(tool, "repo")

    def test_candidates_with_a_stop_word_are_left_out(self):
        kept, dropped = cc.without_phrases(self._candidates(), frozenset({"are", "an", "the"}))

        assert [c.name for c in kept] == ["Exchange Of Information", "Ledger"]
        assert dropped == 2

    def test_no_stop_words_keep_everything(self):
        candidates = self._candidates()

        assert cc.without_phrases(candidates, frozenset()) == (candidates, 0)


class TestSupport:
    def test_code_names_that_contain_the_words(self):
        candidates = cc.merge_candidates(
            [
                _tool_candidate("Ledger", "en", "ledger", [("a.md", 0, "x")]),
                _tool_candidate("Payment Plan", "en", "payment plan", [("a.md", 0, "x")]),
                _tool_candidate("Plan Payment", "en", "plan payment", [("a.md", 0, "x")]),
            ],
            "repo",
        )

        supported = cc.add_support(candidates, ["LedgerController", "PaymentService", "payment_plans"])

        # Contiguous words of a type or directory name, in their order
        assert {c.key: c.code_support for c in supported} == {"ledger": True, "paymentplan": True, "planpayment": False}


class TestSelect:
    @staticmethod
    def _candidate(key, count, documents=1, code=False):
        docs = {f"d{i}.md": 1 for i in range(documents)}
        return cc.ConceptCandidate(key=key, name=key.title(), kind="noun", count=count, documents=docs, originals=[], snippets=[], code_support=code)

    def test_single_mentions_without_structural_support_are_left_out(self):
        candidates = [self._candidate("once", 1), self._candidate("twice", 2), self._candidate("coded", 1, code=True)]

        selected, _ = cc.select_candidates(candidates, evidence_min_count=2, evidence_share=1.0, max_candidates=100, support_factor=1.5)

        assert {c.key for c in selected} == {"twice", "coded"}

    def test_the_list_holds_the_evidence_share(self):
        candidates = [self._candidate("big", 50, documents=5), self._candidate("mid", 5, documents=2), self._candidate("small", 2)]

        selected, stats = cc.select_candidates(candidates, evidence_min_count=2, evidence_share=0.8, max_candidates=100, support_factor=1.5)

        assert [c.key for c in selected] == ["big", "mid"]
        assert (stats["qualified"], stats["selected"], stats["capped"]) == (3, 2, False)

    def test_the_budget_cap_is_reported_when_it_binds(self):
        candidates = [self._candidate(f"k{i}", 2) for i in range(5)]

        selected, stats = cc.select_candidates(candidates, evidence_min_count=2, evidence_share=1.0, max_candidates=3, support_factor=1.5)

        assert (len(selected), stats["capped"]) == (3, True)

    def test_code_support_multiplies_the_score_by_the_support_factor(self):
        # Equal evidence: a factor of 1 leaves the tie to the key order, a larger one ranks the supported term first
        candidates = [self._candidate("alpha", 2), self._candidate("zeta", 2, code=True)]

        neutral, _ = cc.select_candidates(candidates, evidence_min_count=2, evidence_share=1.0, max_candidates=100, support_factor=1.0)
        boosted, _ = cc.select_candidates(candidates, evidence_min_count=2, evidence_share=1.0, max_candidates=100, support_factor=2.0)

        assert [c.key for c in neutral] == ["alpha", "zeta"]
        assert [c.key for c in boosted] == ["zeta", "alpha"]
        assert boosted[0].score == pytest.approx(2 * boosted[1].score)

    def _tied(self):
        # "big" alone holds less than the share; the prefix ends on the first of three equal candidates
        return [self._candidate("big", 20, documents=2), self._candidate("tie_c", 2), self._candidate("tie_a", 2), self._candidate("tie_b", 2)]

    def test_without_keeping_ties_the_cut_splits_equal_evidence_by_key(self):
        """The behaviour of config versions without the switch: the key order decides inside the tie."""
        selected, stats = cc.select_candidates(self._tied(), evidence_min_count=2, evidence_share=0.65, max_candidates=100, support_factor=1.5)

        assert [c.key for c in selected] == ["big", "tie_a"]
        assert stats["ties_added"] == 0

    def test_keeping_ties_the_cut_takes_its_whole_tie_group(self):
        """Equal evidence, same decision: the prefix runs to the end of the tie group at the cut."""
        selected, stats = cc.select_candidates(self._tied(), evidence_min_count=2, evidence_share=0.65, max_candidates=100, support_factor=1.5, keep_ties=True)

        assert [c.key for c in selected] == ["big", "tie_a", "tie_b", "tie_c"]
        assert (stats["share_size"], stats["ties_added"], stats["selected"]) == (2, 2, 4)

    def test_the_budget_cap_still_binds_over_a_kept_tie(self):
        selected, stats = cc.select_candidates(self._tied(), evidence_min_count=2, evidence_share=0.65, max_candidates=3, support_factor=1.5, keep_ties=True)

        assert (len(selected), stats["capped"]) == (3, True)


class TestBatches:
    @staticmethod
    def _candidates(n):
        return [cc.ConceptCandidate(key=f"term{i}", name=f"Term {i}", kind="noun", count=2, documents={}, originals=[], snippets=[]) for i in range(n)]

    def test_every_candidate_lands_in_one_batch(self):
        batches = cc.classification_batches(self._candidates(130), batch_size=50)

        keys = [c.key for batch in batches for c in batch]
        assert sorted(keys) == sorted(c.key for c in self._candidates(130))
        assert all(batch for batch in batches)

    def test_a_candidate_keeps_its_neighbours_when_the_list_grows_within_the_bucket_count(self):
        small = {c.key: frozenset(n.key for n in batch) for batch in cc.classification_batches(self._candidates(70), 50) for c in batch}
        grown = {c.key: frozenset(n.key for n in batch) for batch in cc.classification_batches(self._candidates(90), 50) for c in batch}

        # Both lists use 2 buckets; old candidates keep their bucket, only new ones join
        assert all(small[k] <= grown[k] for k in small)

    @pytest.mark.parametrize("batch_size", [0, -1])
    def test_a_nonpositive_batch_size_is_a_config_error(self, batch_size):
        with pytest.raises(ValueError, match="batch_size"):
            cc.classification_batches(self._candidates(3), batch_size=batch_size)


class TestPrompt:
    def test_terms_with_originals_and_context_lines(self):
        candidate = cc.ConceptCandidate(
            key="ledger",
            name="Ledger",
            kind="noun",
            count=2,
            documents={},
            originals=[{"term": "Ledger", "language": "en", "count": 1}, {"term": "Hauptbuch", "language": "de", "count": 1}],
            snippets=["The ledger is closed.", "Das Hauptbuch wird geführt."],
        )

        prompt = cc.build_classification_prompt("Classify.", [candidate])

        assert prompt == ('Classify.\n\nTerms:\n1. "Ledger" (original: "Hauptbuch", German)\n   context: "The ledger is closed."\n   context: "Das Hauptbuch wird geführt."\n')

    LEDGER = cc.ConceptCandidate(key="ledger", name="Ledger", kind="noun", count=2, documents={}, originals=[], snippets=["The ledger is closed."], snippet_paths=["docs/a.md"])

    def test_the_system_description_comes_before_the_terms(self):
        prompt = cc.build_classification_prompt("Classify.", [self.LEDGER], system_description="A service that keeps ledgers.")

        assert prompt == 'Classify.\n\nSystem description:\nA service that keeps ledgers.\n\nTerms:\n1. "Ledger"\n   context: "The ledger is closed."\n'

    def test_context_lines_can_name_their_document(self):
        prompt = cc.build_classification_prompt("Classify.", [self.LEDGER], show_sources=True)

        assert prompt == 'Classify.\n\nTerms:\n1. "Ledger"\n   context (docs/a.md): "The ledger is closed."\n'


class TestSystemDescription:
    README = (
        "[![Build](https://ci/badge.svg)](https://ci)\n"
        "# Ledger\n\n"
        "A service that keeps [ledgers](docs/ledger.md) for small shops.\n"
        "![diagram](d.png)\n"
        "```bash\npip install ledger\n```\n"
        "| Column | Meaning |\n"
        "Module | Coverage ![badge](b.svg)\n"
        "<p align=center>logo</p>\n"
        "**Shop owners** close their `books` every month.\n"
    )

    def test_the_prose_of_the_opening_without_markup(self):
        assert cc.system_description(self.README, 500) == "A service that keeps ledgers for small shops. Shop owners close their books every month."

    def test_cut_at_a_word_boundary(self):
        assert cc.system_description(self.README, 30) == "A service that keeps ledgers"

    def test_zero_characters_means_no_description(self):
        assert cc.system_description(self.README, 0) == ""


class TestParse:
    BATCH = [
        cc.ConceptCandidate(key="ledger", name="Ledger", kind="noun", count=2, documents={}, originals=[], snippets=[]),
        cc.ConceptCandidate(key="approveledger", name="Approve Ledger", kind="verb", count=2, documents={}, originals=[], snippets=[]),
    ]

    def test_labels_are_matched_by_exact_then_folded_term(self):
        content = json.dumps({"classifications": [{"term": "Ledger", "label": "business_object"}, {"term": "approve ledger", "label": "business_process"}]})

        labels, issues = cc.parse_labels(content, self.BATCH)

        assert labels == {"ledger": "business_object", "approveledger": "business_process"}
        assert issues == {"unmatched": [], "duplicates": [], "missing": []}

    def test_unknown_and_missing_terms_are_reported(self):
        content = json.dumps({"classifications": [{"term": "Other", "label": "technical"}]})

        labels, issues = cc.parse_labels(content, self.BATCH)

        assert labels == {}
        assert issues == {"unmatched": ["Other"], "duplicates": [], "missing": ["Ledger", "Approve Ledger"]}

    def test_a_label_outside_the_closed_set_is_an_error(self):
        with pytest.raises(ValueError, match="label"):
            cc.parse_labels(json.dumps({"classifications": [{"term": "Ledger", "label": "thing"}]}), self.BATCH)


class TestNodes:
    def test_business_labels_become_concepts_with_references(self):
        ledger = cc.ConceptCandidate(
            key="ledger",
            name="Ledger",
            kind="noun",
            count=3,
            documents={"docs/a.md": 2, "docs/b.md": 1},
            originals=[{"term": "Ledger", "language": "en", "count": 2}, {"term": "Hauptbuch", "language": "de", "count": 1}],
            snippets=[],
        )
        noise = cc.ConceptCandidate(key="data", name="Data", kind="noun", count=9, documents={"docs/a.md": 9}, originals=[], snippets=[])

        nodes, edges = cc.concept_nodes_and_edges([(ledger, "business_object"), (noise, "generic")], "repo", confidence=0.9)

        (node,) = nodes
        assert node["node_id"] == "concept::repo::ledger"
        props = node["properties"]
        assert (props["conceptName"], props["conceptType"], props["confidence"], props["originSource"]) == ("Ledger", "entity", 0.9, "docs/a.md")
        assert props["sourceTerms"] == ["Ledger (en)", "Hauptbuch (de)"]
        assert sorted(e["from_node_id"] for e in edges) == ["file::repo::docs_a.md", "file::repo::docs_b.md"]
        assert {e["relationship_type"] for e in edges} == {"REFERENCES"}

    def test_labels_map_to_the_concept_types_derivation_reads(self):
        assert cc.LABEL_TYPES == {
            "business_object": "entity",
            "business_process": "process",
            "business_function": "capability",
            "business_actor": "actor",
            "business_role": "actor",
            "business_event": "event",
            "business_service": "service",
        }


class TestOutcome:
    def test_labels_with_the_same_effect_share_an_outcome(self):
        """What a label does to the graph: the concept type it creates, or nothing (every reject label alike)."""
        assert [cc.outcome(label) for label in ("business_actor", "business_role", "business_object")] == ["actor", "actor", "entity"]
        assert {cc.outcome(label) for label in cc.REJECT_LABELS} == {"rejected"}
        assert cc.outcome(None) is None
