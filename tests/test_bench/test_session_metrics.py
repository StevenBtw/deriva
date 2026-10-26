"""Session measures from the run snapshots and call logs: identities, layers and origin, J̄, the two-level table,
the out-of-candidate rate and agreement across LLMs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deriva.bench import session_metrics as pm


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

    def test_an_across_llm_row_pools_every_models_runs(self, tmp_path):
        """Each model agrees with itself; across the models the same prompt is answered and the item decided otherwise."""

        def call(key, label):
            return [{"step": "BusinessConcept", "schema": "business_concept_classification", "cache_key": key, "prompt": "p", "response": f'{{"labels": {{"x": "{label}"}}}}'}]

        def session(name, model, label):
            runs = [_run(SHOP, decisions={"BusinessConcept": {"x": label}}) for _ in range(2)]
            return _session(tmp_path, name, model, runs, {1: call(f"k_{model}", label), 2: call(f"k_{model}", label)})

        rows = pm.two_level_rows([session("s1", "m1", "entity"), session("s2", "m2", "process")])

        concept = {r["model"]: r for r in rows if r["decision"] == "BusinessConcept"}
        assert list(concept) == ["m1", "m2", "all LLMs"]
        assert concept["m1"]["answers"] == {"identical": 1, "prompts": 1} and concept["m1"]["decisions"] == {"stable": 1, "items": 1}
        # Across the LLMs: the prompt (not the per-model cache key) is the same, its answers differ; x flips
        assert concept["all LLMs"]["answers"] == {"identical": 0, "prompts": 1}
        assert concept["all LLMs"]["decisions"] == {"stable": 0, "items": 1}

    def test_a_classification_is_decided_per_candidate_and_one_run_has_no_rows(self, tmp_path):
        """A role classification's decision per candidate is its stage (created or rejected); a single run has nothing
        to compare."""
        calls = {n: [{"step": "ApplicationInterface", "schema": "role_classification", "cache_key": "k", "response": '{"items": []}'}] for n in (1, 2)}
        candidates = [
            [{"type": "ApplicationInterface", "source": "file::r::a", "stage": "created"}],
            [{"type": "ApplicationInterface", "source": "file::r::a", "stage": "llm_rejected"}],
        ]
        session = _session(tmp_path, "s1", "m", [_run(SHOP, candidates=c) for c in candidates], calls)
        single = _session(tmp_path, "s2", "m", [_run(SHOP)], {1: calls[1]})

        (row,) = [r for r in pm.two_level_rows([session]) if r["decision"] == "ApplicationInterface classification"]

        assert row["answers"] == {"identical": 1, "prompts": 1} and row["decisions"] == {"stable": 0, "items": 1}
        assert pm.two_level_rows([single]) == []


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
    """Lineage-free golden comparison: name + type, plus the user's manual matches and derivable labels."""

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

    def test_a_names_only_matches_file_gives_the_same_numbers_in_either_form(self):
        """A list of names (today's form) and {"names": [...]} score alike, and as before structure refs existed."""
        derived = [
            {"id": "a", "name": "Order Service", "type": "ApplicationComponent"},
            {"id": "b", "name": "Payments Host", "type": "Node"},
            {"id": "c", "name": "Audit", "type": "ApplicationComponent"},
        ]

        listed = pm.golden_comparison(derived, self._reference(), aliases={"r3": ["Payments Host"]})
        objects = pm.golden_comparison(derived, self._reference(), aliases={"r3": {"names": ["Payments Host"], "structure_refs": []}})

        assert listed == objects
        assert (listed["recall"], listed["precision"], listed["manual_matches"], listed["structure_matches"]) == (0.5, round(2 / 3, 3), 1, 0)

    def test_a_structure_ref_matches_the_derived_element_of_that_folder_or_id(self):
        """A golden element the user tied to a folder (path:) or a structural id is found by the element derived from it."""
        from deriva.modules.analysis.types import ReferenceElement

        reference = [
            ReferenceElement(identifier="g1", name="Alert Hook", element_type="ApplicationComponent", layer="Application"),
            ReferenceElement(identifier="g2", name="Ledger", element_type="ApplicationComponent", layer="Application"),
            ReferenceElement(identifier="g3", name="Publisher", element_type="ApplicationComponent", layer="Application"),
        ]
        derived = [
            {"id": "x", "name": "Hook Module", "type": "ApplicationComponent", "source": "module::r::libs/alert-hook"},
            {"id": "y", "name": "Accounts", "type": "ApplicationComponent", "source": "unit::r::services/ledger"},
            {"id": "z", "name": "Notifier", "type": "ApplicationComponent", "source": "unit::r::libs/publish/notify"},
        ]
        aliases = {
            "g1": {"names": [], "structure_refs": ["path:./libs/alert-hook/"]},  # the folder itself
            "g2": {"structure_refs": ["unit::r::services/ledger"]},  # a structural id
            "g3": {"structure_refs": ["path:libs/publish"]},  # a parent folder of z: no match
        }

        result = pm.golden_comparison(derived, reference, aliases=aliases)

        assert (result["recall"], result["structure_matches"]) == (round(2 / 3, 3), 2)

    def test_one_derived_element_matches_one_golden_element_and_names_come_first(self):
        from deriva.modules.analysis.types import ReferenceElement

        reference = [
            ReferenceElement(identifier="g1", name="Core", element_type="ApplicationComponent", layer="Application"),
            ReferenceElement(identifier="g2", name="Core Runtime", element_type="ApplicationComponent", layer="Application"),
            ReferenceElement(identifier="g3", name="Engine", element_type="ApplicationComponent", layer="Application"),
        ]
        derived = [{"id": "x", "name": "Core", "type": "ApplicationComponent", "source": "unit::r::core"}]
        # g1 is found by name; g2 and g3 point at the same folder, but x is already taken
        aliases = {"g2": {"structure_refs": ["path:core"]}, "g3": {"structure_refs": ["path:core"]}}

        result = pm.golden_comparison(derived, reference, aliases=aliases)

        assert (result["recall"], result["structure_matches"]) == (round(1 / 3, 3), 0)
        # Without the name match, the first golden element (by id) that points at x takes it
        alone = pm.golden_comparison([{**derived[0], "name": "Something Else"}], reference, aliases=aliases)
        assert (alone["recall"], alone["structure_matches"]) == (round(1 / 3, 3), 1)
        assert pm.golden_mapping([{**derived[0], "name": "Something Else"}], reference, aliases=aliases) == {"x": {"g2"}}

    def test_internal_behaviour_matches_across_its_types_within_a_layer(self):
        """A function found for a reference process counts (user, 2026-10-19); across layers and for services it does not."""
        from deriva.modules.analysis.types import ReferenceElement

        reference = [
            ReferenceElement(identifier="g1", name="Order Goods", element_type="BusinessProcess", layer="Business"),
            ReferenceElement(identifier="g2", name="Post Transactions", element_type="ApplicationProcess", layer="Application"),
            ReferenceElement(identifier="g3", name="Catalogue", element_type="ApplicationService", layer="Application"),
        ]
        derived = [
            {"id": "a", "name": "Order Goods", "type": "BusinessFunction"},
            {"id": "b", "name": "Post Transactions", "type": "ApplicationFunction"},
            {"id": "c", "name": "Catalogue", "type": "ApplicationFunction"},  # a function is no service
        ]

        assert pm.golden_mapping(derived, reference) == {"a": {"g1"}, "b": {"g2"}}
        assert pm.golden_comparison(derived, reference)["recall"] == round(2 / 3, 3)

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


def test_consistency_by_id_per_level(tmp_path):
    """A level counts the elements tagged with it (no tag: enterprise) and the relationships on it; the union counts all."""
    sys_ = {**_element("ac_sys", "ApplicationComponent", "Shop", "module::r::r"), "levels": ["enterprise"]}
    orders = {**_element("ac_orders", "ApplicationComponent", "Orders", "unit::r::orders"), "levels": ["solution"]}
    lib = {**_element("ac_lib", "ApplicationComponent", "Lib", "module::r::lib"), "levels": ["solution"]}
    one = _run(sys_, orders, lib)
    two = _run(sys_, orders)  # the library is missing in run 2: only the solution level differs
    session = _session(tmp_path, "s1", "m", [one, two])

    (enterprise,) = pm.consistency_rows([session], level="enterprise")
    (solution,) = pm.consistency_rows([session], level="solution")
    (union,) = pm.consistency_rows([session], level="union")

    assert enterprise["identities"]["id"]["elements"]["cons"] == 1.0
    assert solution["identities"]["id"]["elements"]["cons"] == 0.5
    assert union["identities"]["id"]["elements"]["cons"] == round(2 / 3, 3)
    assert pm.consistency_rows([session]) == pm.consistency_rows([session], level="union")  # None: as before levels
