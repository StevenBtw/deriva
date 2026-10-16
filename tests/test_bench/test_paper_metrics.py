"""The paper's numbers from the run snapshots and call logs: identities (C2), layers and origin (C24), J̄, the two-level table,
the out-of-candidate rate and agreement across LLMs (C42)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deriva.bench import paper_metrics as pm


def _element(identifier, type_, name, source, name_choice=False):
    return {"identifier": identifier, "type": type_, "name": name, "source": source, "name_choice": name_choice}


def _session(root: Path, name: str, model: str, runs: list[dict], calls: dict[int, list[dict]] | None = None, repo: str = "r") -> Path:
    session = root / name
    (session / "models").mkdir(parents=True)
    (session / "llm").mkdir()
    (session / "session_metadata.json").write_text(json.dumps({"config": {"repositories": [repo], "models": [model]}}), encoding="utf-8")
    for number, snapshot in enumerate(runs, 1):
        (session / "models" / f"{repo}_{model}_run{number}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    for number, run_calls in (calls or {}).items():
        lines = [json.dumps({"run_id": f"{name}:{repo}:{model}:{number}", **c}) for c in run_calls]
        (session / "llm" / f"{name}_{repo}_{model}_{number}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return session


SHOP = _element("ac_shop", "ApplicationComponent", "Shop", "unit::r::shop")
ORDER = _element("bo_order", "BusinessObject", "Order", "concept::r::order")  # its source is an LLM-created node
SERVICE = _element("as_ordering", "ApplicationService", "Ordering", "group::r::shop", name_choice=True)
SERVICE_2 = _element("as_ordering", "ApplicationService", "Order Handling", "group::r::shop", name_choice=True)
GRAPH = {"concepts": [["concept::r::order", ["entity"]]], "technologies": []}


def _run(*elements, relationships=(), decisions=None, candidates=()):
    return {
        "elements": list(elements),
        "relationships": [{"source": s, "target": t, "type": k, "derived_from": d} for s, t, k, d in relationships],
        "graph": GRAPH,
        "extraction_decisions": decisions,
        "candidates": list(candidates),
    }


class TestIdentities:
    def test_by_id_and_by_name_with_jaccard(self, tmp_path):
        rels = [("ac_shop", "as_ordering", "Realization", "listed_members")]
        session = _session(tmp_path, "s1", "m", [_run(SHOP, ORDER, SERVICE, relationships=rels), _run(SHOP, ORDER, SERVICE_2, relationships=rels)])

        (row,) = pm.consistency_rows([session])

        by_id, by_name = row["identities"]["id"], row["identities"]["name"]
        assert (by_id["elements"]["cons"], by_id["relationships"]["cons"]) == (1.0, 1.0)  # same ids, another name
        # By name the service differs: Shop and Order of 4 element names are in both runs
        assert (by_name["elements"]["cons"], by_name["elements"]["jbar"]) == (0.5, 0.5)
        assert by_name["relationships"]["cons"] == 0.0

    def test_layers_and_the_llm_dependent_part(self, tmp_path):
        session = _session(tmp_path, "s1", "m", [_run(SHOP, ORDER, SERVICE), _run(SHOP, SERVICE_2)])

        (row,) = pm.consistency_rows([session])

        by_id = row["identities"]["id"]
        assert by_id["layers"] == {"Application": 1.0, "Business": 0.0}
        # Order (an LLM-created source) and the service (name chosen by a call) depend on the LLM; Shop does not
        assert (by_id["origin"]["llm"]["elements"], by_id["origin"]["structural"]["elements"]) == (0.5, 1.0)
        assert by_id["origin"]["llm"]["count"] == 2

    def test_agreement_across_llms_pools_the_runs_of_every_session(self, tmp_path):
        a = _session(tmp_path, "s1", "m1", [_run(SHOP, ORDER), _run(SHOP, ORDER)])
        b = _session(tmp_path, "s2", "m2", [_run(SHOP), _run(SHOP)])

        rows = pm.consistency_rows([a, b])

        assert [(r["model"], r["runs"]) for r in rows] == [("m1", 2), ("m2", 2), ("all LLMs", 4)]
        assert rows[-1]["identities"]["id"]["elements"]["cons"] == 0.5


class TestTwoLevel:
    def test_answer_and_decision_stability_with_alpha_per_decision_type(self, tmp_path):
        calls = {
            1: [{"step": "BusinessConcept", "schema": "business_concept_classification", "cache_key": "k", "response": '{"labels": {"x": "entity"}}'}],
            2: [{"step": "BusinessConcept", "schema": "business_concept_classification", "cache_key": "k", "response": '{"labels": {"x": "process"}}'}],
        }
        decisions = [{"BusinessConcept": {"x": "entity", "y": "actor"}}, {"BusinessConcept": {"x": "process", "y": "actor"}}]
        runs = [_run(SHOP, SERVICE, decisions=decisions[0]), _run(SHOP, SERVICE_2, decisions=decisions[1])]
        session = _session(tmp_path, "s1", "m", runs, calls)

        rows = {r["decision"]: r for r in pm.two_level_rows([session])}

        concept = rows["BusinessConcept"]
        assert (concept["answers"], concept["decisions"]) == ({"identical": 0, "prompts": 1}, {"stable": 1, "items": 2})
        assert concept["alpha"] == pytest.approx(0.4)  # nominal: 1 - (n - 1) * 2 / 10 with x flipping and y stable
        names = rows["ApplicationService name choice"]
        assert names["decisions"] == {"stable": 0, "items": 1}


def test_krippendorff_alpha_nominal():
    assert pm.krippendorff_alpha([{"a": 1, "b": 2}, {"a": 1, "b": 2}]) == 1.0
    assert pm.krippendorff_alpha([{"a": 1}, {"a": 1}]) is None  # one value only: alpha is undefined
    assert pm.krippendorff_alpha([{"a": 1, "b": 2}, {"a": 2, "b": 1}]) < 0


class TestOutOfCandidates:
    def test_per_model_and_decision_type(self, tmp_path):
        prompt = 'C\n\n## Candidates\n- "Ordering"\n- "Order Handling"\n\nReturn {"name": "..."}'
        calls = {
            1: [
                {"step": "ApplicationService", "schema": "element_name_choice", "model": "x", "prompt": prompt, "response": '{"name": "Orders"}'},
                {"step": "ApplicationService", "schema": "element_name_choice", "model": "x", "prompt": prompt, "response": '{"name": "Ordering"}'},
            ]
        }
        session = _session(tmp_path, "s1", "m", [_run(SHOP)], calls)
        ocel = session / "ocel"
        ocel.mkdir()
        events = [
            {"activity": "LLMQuery", "attributes": {"config_id": "BusinessConcept", "requests": "2"}, "objects": {"Model": ["m"]}},
            {"activity": "LLMQuery", "attributes": {"config_id": "BusinessConcept", "requests": "1"}, "objects": {"Model": ["m"]}},
            {"activity": "ExtractConfig", "attributes": {"config_id": "BusinessConcept", "stats": str({"issues": {"unmatched": 1, "duplicates": 0, "missing": 2}})}, "objects": {}},
        ]
        (ocel / "benchmark_events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

        rows = {r["decision"]: r for r in pm.out_of_candidate_rows([session])}

        assert rows["ApplicationService name choice"] == {"model": "m", "decision": "ApplicationService name choice", "calls": 2, "re_asked": 0, "outside": 1}
        assert rows["BusinessConcept"] == {"model": "m", "decision": "BusinessConcept", "calls": 2, "re_asked": 1, "outside": 3}


class TestGolden:
    """Lineage-free golden comparison: name + type, plus the user's manual matches and derivable labels (C5)."""

    def _reference(self):
        from deriva.modules.analysis.types import ReferenceElement

        return [
            ReferenceElement(identifier="r1", name="Order Service", element_type="ApplicationComponent", layer="Application"),
            ReferenceElement(identifier="r2", name="Customer", element_type="BusinessActor", layer="Business"),
            ReferenceElement(identifier="r3", name="Billing Platform", element_type="Node", layer="Technology"),
            ReferenceElement(identifier="r4", name="Strategy", element_type="Capability", layer="Strategy"),
        ]

    def test_per_layer_with_manual_matches_and_the_derivable_subset(self):
        derived = [
            {"id": "a", "name": "Order Service", "type": "ApplicationComponent"},
            {"id": "b", "name": "Payments Host", "type": "Node"},  # matched only by the manual alias
            {"id": "c", "name": "Audit", "type": "ApplicationComponent"},
        ]
        aliases = {"r3": ["Payments Host"]}
        derivable = {"r1": {"derivable": True}, "r2": {"derivable": False, "reason": "not in the code"}, "r3": {"derivable": True}}

        result = pm.golden_comparison(derived, self._reference(), aliases=aliases, derivable=derivable)

        assert (result["recall"], result["precision"], result["reference_elements"]) == (0.5, round(2 / 3, 3), 4)
        assert result["layers"]["Application"] == {"recall": 1.0, "precision": 0.5, "reference": 1}
        assert result["layers"]["Business"]["recall"] == 0.0
        assert result["derivable_types_recall"] == round(2 / 3, 3)  # Capability is no derived type
        assert result["derivable_recall"] == 1.0 and result["derivable_labelled"] == 3
        assert result["manual_matches"] == 1

    def test_without_manual_files_the_name_match_alone(self):
        derived = [{"id": "a", "name": "Order Service", "type": "ApplicationComponent"}]

        result = pm.golden_comparison(derived, self._reference())

        assert result["recall"] == 0.25 and result["derivable_recall"] is None and result["manual_matches"] == 0


def test_an_element_without_a_structural_source_is_llm_generated(tmp_path):
    """A baseline's elements (B1) have no source node: all of them depend on the LLM."""
    free = _element("as_x", "ApplicationService", "Free", None)
    session = _session(tmp_path, "s1", "m", [_run(free), _run(free)])

    (row,) = pm.consistency_rows([session])

    assert row["identities"]["name"]["origin"]["llm"] == {"elements": 1.0, "relationships": None, "count": 1}
