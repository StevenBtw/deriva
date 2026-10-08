"""The BusinessConcept step: documents -> candidate terms (NLP tool) -> evidence selection -> closed classification -> concepts."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deriva.adapters.grafeo.manager import close_database
from deriva.adapters.graph import GraphManager
from deriva.adapters.graph.models import BusinessConceptNode, DirectoryNode, FileNode, TypeDefinitionNode
from deriva.common.naming import UNCOUNTABLE_WORDS
from deriva.services import extraction as service

PARAMS = {
    "confidence": 0.9,
    "evidence_min_count": 2,
    "evidence_share": 1.0,
    "max_candidates": 100,
    "missing_retries": 1,
    "nlp": {"snippet_chars": 120},
    "stop_words": ["the", "are"],
    "support_factor": 1.5,
}
DOCS = ("a.md", "b.md")


def _tool_candidate(term, language, english, paths):
    return {
        "term": term,
        "language": language,
        "kind": "noun",
        "english": english,
        "count": len(paths),
        "occurrences": [{"path": p, "segment": i, "start": 0, "snippet": f"{term} in {p}"} for i, p in enumerate(paths)],
    }


class FakeNlpTool:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []
        self.models_ensured = False

    def ensure_models(self):
        self.models_ensured = True

    def extract(self, documents, settings, keep_surface):
        self.calls.append({"documents": documents, "settings": settings, "keep_surface": keep_surface})
        return {"tool": {"spacy": "3.8.16"}, "settings": settings, "documents": [], "candidates": self.candidates}


class FakeLlm:
    """Labels the prompted terms from a table; `response` replaces the answer when given."""

    def __init__(self, labels, response=None):
        self.labels = labels
        self.response = response
        self.calls = []

    def __call__(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        if self.response is not None:
            return self.response
        terms = re.findall(r'^\d+\. "([^"]+)"', prompt, re.MULTILINE)
        return SimpleNamespace(content=json.dumps({"classifications": [{"term": t, "label": self.labels[t]} for t in terms if t in self.labels]}))

    def prompted_terms(self):
        """The terms the classifier saw (once each, retries included)."""
        return sorted({t for call in self.calls for t in re.findall(r'^\d+\. "([^"]+)"', call["prompt"], re.MULTILINE)})


class SkippingLlm(FakeLlm):
    """Leaves the given terms out of its first answer, as the model sometimes does."""

    def __init__(self, labels, skip):
        super().__init__(labels)
        self.skip = set(skip)

    def __call__(self, prompt, schema, **kwargs):
        response = super().__call__(prompt, schema, **kwargs)
        if len(self.calls) > 1:
            return response
        answer = json.loads(response.content)
        answer["classifications"] = [item for item in answer["classifications"] if item["term"] not in self.skip]
        return SimpleNamespace(content=json.dumps(answer))


@pytest.fixture
def graph():
    close_database()
    with GraphManager() as gm:
        yield gm
    close_database()


def _cfg(params=None, batch_size=50):
    return SimpleNamespace(
        node_type="BusinessConcept",
        input_sources=json.dumps({"files": [{"type": "docs", "subtype": "*"}], "nodes": ["File"]}),
        instruction="Classify every term.",
        example="",
        params=json.dumps(PARAMS if params is None else params),
        batch_size=batch_size,
        temperature=0.0,
        max_tokens=None,
    )


def _run(tmp_path, graph, tool, llm, cfg=None, readme=None):
    (tmp_path / "docs").mkdir(exist_ok=True)
    for name in DOCS:
        (tmp_path / "docs" / name).write_text(f"text of {name}", encoding="utf-8")
        graph.add_node(FileNode(name=name, path=f"docs/{name}", repository_name="r", file_type="docs", subtype="markdown"), node_id=f"file::r::docs_{name}")
    files = [{"path": f"docs/{name}", "file_type": "docs", "subtype": "markdown"} for name in DOCS]
    if readme is not None:
        (tmp_path / "README.md").write_text(readme, encoding="utf-8")
        files.append({"path": "README.md", "file_type": "docs", "subtype": "markdown"})
    with patch.object(service, "NlpTool", lambda: tool):
        return service._extract_business_concepts(cfg or _cfg(), SimpleNamespace(name="r"), tmp_path, files, graph, llm)


def _ledger_tool():
    return FakeNlpTool(
        [
            _tool_candidate("Ledger", "en", "ledger", ["docs/a.md", "docs/a.md", "docs/b.md"]),
            _tool_candidate("Hauptbuch", "de", "ledger", ["docs/b.md"]),
            _tool_candidate("Data", "en", "data", ["docs/a.md", "docs/a.md"]),
        ]
    )


class TestBusinessConceptStep:
    def test_business_labels_become_concepts_referenced_by_every_document(self, tmp_path, graph):
        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({"Ledger": "business_object", "Data": "generic"}))

        assert (result["nodes_created"], result["edges_created"], result["errors"]) == (1, 2, [])
        props = graph.get_node("concept::r::ledger")["properties"]
        assert (props["conceptName"], props["conceptType"], props["confidence"]) == ("Ledger", "entity", 0.9)
        assert props["sourceTerms"] == ["Hauptbuch (de)", "Ledger (en)"]
        assert graph.get_node("concept::r::data") is None
        rows = graph.query("MATCH (n:Graph:BusinessConcept)<-[r]-(f) RETURN f.id AS src, type(r) AS rel")
        assert sorted((row["src"], row["rel"]) for row in rows) == [("file::r::docs_a.md", "Graph:REFERENCES"), ("file::r::docs_b.md", "Graph:REFERENCES")]

    def test_the_ids_of_the_created_edges_are_reported_for_the_run_log(self, tmp_path, graph):
        from deriva.common.ocel import create_edge_id

        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({"Ledger": "business_object", "Data": "generic"}))

        assert sorted(result["edge_ids"]) == sorted(create_edge_id(f"file::r::docs_{name}", "REFERENCES", "concept::r::ledger") for name in ("a.md", "b.md"))

    def test_the_classifier_gets_the_configured_instruction_and_the_closed_schema(self, tmp_path, graph):
        llm = FakeLlm({"Ledger": "business_object", "Data": "generic"})

        _run(tmp_path, graph, _ledger_tool(), llm)

        (call,) = llm.calls
        assert call["prompt"].startswith("Classify every term.\n\nTerms:\n")
        assert call["schema"]["name"] == "business_concept_classification"
        assert call["temperature"] == 0.0

    def test_the_tool_gets_the_documents_the_settings_and_the_uncountable_words(self, tmp_path, graph):
        tool = _ledger_tool()

        _run(tmp_path, graph, tool, FakeLlm({}))

        assert tool.models_ensured
        (call,) = tool.calls
        assert call["documents"] == [{"path": "docs/a.md", "text": "text of a.md"}, {"path": "docs/b.md", "text": "text of b.md"}]
        assert call["settings"] == {"snippet_chars": 120}
        assert call["keep_surface"] == sorted(UNCOUNTABLE_WORDS)

    def test_code_and_directory_names_let_a_single_mention_qualify(self, tmp_path, graph):
        graph.add_node(DirectoryNode(name="shipments", path="src/shipments", repository_name="r"), node_id="dir::r::src/shipments")
        graph.add_node(TypeDefinitionNode(name="ParcelLabel", type_category="class", file_path="src/p.py", repository_name="r"), node_id="typedef::r::src_p.py::parcellabel")
        graph.add_node(TypeDefinitionNode(name="Voucher", type_category="external_reference", file_path="external", repository_name="r"), node_id="typedef::r::external::voucher")
        tool = FakeNlpTool([_tool_candidate(term, "en", term.lower(), ["docs/a.md"]) for term in ("Shipment", "Parcel", "Voucher", "Coupon")])
        llm = FakeLlm({})

        _run(tmp_path, graph, tool, llm)

        assert llm.prompted_terms() == ["Parcel", "Shipment"]

    def test_the_list_does_not_depend_on_directory_classification(self, tmp_path):
        """Only structure decides which terms reach the classifier: a concept that DirectoryClassification
        (an LLM decision) made for a directory changes nothing, so an upstream flip cannot cascade (rule 6d)."""
        prompted = []
        for with_directory_concept in (False, True):
            close_database()
            with GraphManager() as graph:
                graph.add_node(DirectoryNode(name="src", path="src", repository_name="r"), node_id="dir::r::src")
                if with_directory_concept:
                    graph.add_node(BusinessConceptNode("Ledger", "entity", "", "src", "r", 0.9, "llm-directory"), node_id="concept::r::ledger")
                    graph.add_edge("dir::r::src", "concept::r::ledger", "REPRESENTS")
                tool = FakeNlpTool([_tool_candidate(term, "en", term.lower(), ["docs/a.md"] * 3) for term in ("Journal", "Ledger")])
                llm = FakeLlm({})
                # Equal evidence; half of it keeps one term
                _run(tmp_path, graph, tool, llm, cfg=_cfg(params={**PARAMS, "evidence_share": 0.5}))
                prompted.append(llm.prompted_terms())
            close_database()

        assert prompted == [["Journal"], ["Journal"]]

    def test_the_support_factor_comes_from_the_config(self, tmp_path):
        """Equal evidence, one term named in the code: the configured factor decides which term holds half of the evidence."""
        prompted = []
        for factor in (1.0, 2.0):
            close_database()
            with GraphManager() as graph:
                graph.add_node(DirectoryNode(name="ledgers", path="src/ledgers", repository_name="r"), node_id="dir::r::src/ledgers")
                tool = FakeNlpTool([_tool_candidate(term, "en", term.lower(), ["docs/a.md"] * 3) for term in ("Journal", "Ledger")])
                llm = FakeLlm({})
                _run(tmp_path, graph, tool, llm, cfg=_cfg(params={**PARAMS, "evidence_share": 0.5, "support_factor": factor}))
                prompted.append(llm.prompted_terms())
            close_database()

        assert prompted == [["Journal"], ["Ledger"]]

    def test_stats_report_the_selection_the_labels_and_the_tool(self, tmp_path, graph):
        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({"Ledger": "business_object", "Data": "generic"}))

        stats = result["stats"]
        assert stats["selection"] == {"candidates": 2, "qualified": 2, "share_size": 2, "ties_added": 0, "selected": 2, "capped": False}
        assert (stats["batches"], stats["labels"]) == (1, {"business_object": 1, "generic": 1})
        assert stats["issues"] == {"unmatched": 0, "duplicates": 0, "missing": 0}
        assert stats["tool"] == {"spacy": "3.8.16"}
        assert stats["decisions"] == {"data": "generic", "ledger": "business_object"}
        assert stats["retries"] == {"calls": 0, "recovered": 0}
        assert stats["phrases"] == 0

    def test_a_term_no_answer_labels_has_no_decision(self, tmp_path, graph):
        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({"Ledger": "business_object"}))

        assert result["stats"]["decisions"] == {"data": None, "ledger": "business_object"}
        assert result["stats"]["issues"]["missing"] == 1

    def test_terms_left_out_of_an_answer_are_asked_again_on_their_own(self, tmp_path, graph):
        llm = SkippingLlm({"Ledger": "business_object", "Data": "generic"}, skip={"Data"})

        result = _run(tmp_path, graph, _ledger_tool(), llm)

        assert [re.findall(r'^\d+\. "([^"]+)"', call["prompt"], re.MULTILINE) for call in llm.calls] == [["Data", "Ledger"], ["Data"]]
        assert llm.calls[1]["prompt"].startswith("Classify every term.\n\nTerms:\n")
        assert result["stats"]["decisions"] == {"data": "generic", "ledger": "business_object"}
        assert (result["stats"]["issues"]["missing"], result["stats"]["retries"]) == (0, {"calls": 1, "recovered": 1})

    @pytest.mark.parametrize("retries, calls", [(0, 1), (2, 3)])
    def test_the_number_of_retries_comes_from_the_config(self, tmp_path, graph, retries, calls):
        llm = FakeLlm({"Ledger": "business_object"})  # never labels Data

        result = _run(tmp_path, graph, _ledger_tool(), llm, cfg=_cfg(params={**PARAMS, "missing_retries": retries}))

        assert len(llm.calls) == calls
        assert (result["stats"]["decisions"]["data"], result["stats"]["issues"]["missing"]) == (None, 1)
        assert result["stats"]["retries"] == {"calls": calls - 1, "recovered": 0}

    def test_a_failed_retry_is_an_error_and_keeps_the_first_answer(self, tmp_path, graph):
        first = SimpleNamespace(content=json.dumps({"classifications": [{"term": "Ledger", "label": "business_object"}]}))
        answers = iter([first, SimpleNamespace(content="", error="rate limited")])

        result = _run(tmp_path, graph, _ledger_tool(), lambda prompt, schema, **kwargs: next(answers))

        assert result["errors"] == ["LLM error in batch 1, retry 1: rate limited"]
        assert result["nodes_created"] == 1
        assert result["stats"]["decisions"] == {"data": None, "ledger": "business_object"}

    def test_missing_params_are_an_error_before_any_work(self, tmp_path, graph):
        tool, llm = _ledger_tool(), FakeLlm({})

        result = _run(tmp_path, graph, tool, llm, cfg=_cfg(params={"confidence": 0.9}))

        assert result["errors"] == ["BusinessConcept params missing: evidence_min_count, evidence_share, max_candidates, missing_retries, nlp, stop_words, support_factor"]
        assert (tool.calls, llm.calls) == ([], [])

    def test_translated_phrases_never_reach_the_classifier(self, tmp_path, graph):
        tool = _ledger_tool()
        tool.candidates.append(_tool_candidate("Buch gliedern", "de", "books are divided", ["docs/a.md", "docs/b.md"]))
        llm = FakeLlm({})

        result = _run(tmp_path, graph, tool, llm)

        assert llm.prompted_terms() == ["Data", "Ledger"]
        assert result["stats"]["phrases"] == 1

    def test_leaving_phrases_out_does_not_move_the_evidence_cut(self, tmp_path, graph):
        """A phrase is a real source term with a bad English form: its evidence still counts, so the
        classifier sees the same terms as without the filter, less the phrases. Leaving the phrase out
        before the selection would lower the total and cut Ledger."""
        tool = FakeNlpTool(
            [
                _tool_candidate("Journal", "en", "journal", ["docs/a.md"] * 3 + ["docs/b.md"] * 3 + ["docs/c.md"] * 3),
                _tool_candidate("Ledger", "en", "ledger", ["docs/a.md"] * 2),
                _tool_candidate("Buch gliedern", "de", "books are divided", ["docs/b.md"]),
            ]
        )
        llm = FakeLlm({})

        _run(tmp_path, graph, tool, llm, cfg=_cfg(params={**PARAMS, "evidence_min_count": 1, "evidence_share": 0.8}))

        assert llm.prompted_terms() == ["Journal", "Ledger"]

    README = "# Ledger\n\nLedger keeps the books of small shops and their owners.\n"

    def test_the_classifier_sees_the_opening_of_the_root_readme(self, tmp_path, graph):
        llm = FakeLlm({})

        _run(tmp_path, graph, _ledger_tool(), llm, cfg=_cfg(params={**PARAMS, "system_description_chars": 30}), readme=self.README)

        assert llm.calls[0]["prompt"].startswith("Classify every term.\n\nSystem description:\nLedger keeps the books of\n\nTerms:\n")

    def test_without_a_root_readme_there_is_no_description(self, tmp_path, graph):
        llm = FakeLlm({})

        _run(tmp_path, graph, _ledger_tool(), llm, cfg=_cfg(params={**PARAMS, "system_description_chars": 30}))

        assert llm.calls[0]["prompt"].startswith("Classify every term.\n\nTerms:\n")

    def test_context_lines_name_their_document_when_configured(self, tmp_path, graph):
        llm = FakeLlm({})

        _run(tmp_path, graph, _ledger_tool(), llm, cfg=_cfg(params={**PARAMS, "context_sources": True}))

        assert '   context (docs/a.md): "Ledger in docs/a.md"' in llm.calls[0]["prompt"]

    def test_the_evidence_cut_keeps_its_tie_group_when_configured(self, tmp_path, graph):
        """Three terms with equal evidence sit at the cut: all of them or (older versions) the first by key."""
        tool = FakeNlpTool(
            [_tool_candidate("Journal", "en", "journal", ["docs/a.md"] * 3 + ["docs/b.md"] * 3 + ["docs/c.md"] * 3)]
            + [_tool_candidate(term, "en", term.lower(), ["docs/a.md"] * 2) for term in ("Ledger", "Account", "Booking")]
        )
        params = {**PARAMS, "evidence_share": 0.65}
        older, kept = FakeLlm({}), FakeLlm({})

        _run(tmp_path, graph, tool, older, cfg=_cfg(params=params))
        _run(tmp_path, graph, tool, kept, cfg=_cfg(params={**params, "evidence_keep_ties": True}))

        assert older.prompted_terms() == ["Account", "Journal"]
        assert kept.prompted_terms() == ["Account", "Booking", "Journal", "Ledger"]

    @pytest.mark.parametrize("option", [{"system_description_chars": -1}, {"system_description_chars": "many"}, {"context_sources": "yes"}, {"evidence_keep_ties": "yes"}])
    def test_invalid_prompt_options_are_an_error_before_any_work(self, tmp_path, graph, option):
        tool, llm = _ledger_tool(), FakeLlm({})

        result = _run(tmp_path, graph, tool, llm, cfg=_cfg(params={**PARAMS, **option}))

        assert len(result["errors"]) == 1 and next(iter(option)) in result["errors"][0]
        assert (tool.calls, llm.calls) == ([], [])

    def test_a_failed_call_is_an_error_and_creates_nothing(self, tmp_path, graph):
        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({}, response=SimpleNamespace(content="", error="rate limited")))

        assert result["nodes_created"] == 0
        assert result["errors"] == ["LLM error in batch 1: rate limited"]

    def test_an_unreadable_answer_is_an_error(self, tmp_path, graph):
        result = _run(tmp_path, graph, _ledger_tool(), FakeLlm({}, response=SimpleNamespace(content="not json")))

        assert result["nodes_created"] == 0
        assert len(result["errors"]) == 1 and result["errors"][0].startswith("Unreadable answer in batch 1:")


def test_the_step_runs_the_candidate_flow(tmp_path):
    cfg = SimpleNamespace(node_type="BusinessConcept", extraction_method="llm")

    with patch.object(service, "_extract_business_concepts", return_value={"nodes_created": 3, "edges_created": 0, "errors": []}) as step:
        result = service._run_extraction_step(cfg, SimpleNamespace(name="r"), tmp_path, [], [], None, lambda *a, **k: None, None)

    assert result["nodes_created"] == 3
    step.assert_called_once()
