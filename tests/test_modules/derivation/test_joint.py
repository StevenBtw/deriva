"""Pure joint-consistency core: tiered exact selection of relationships and merges."""

from __future__ import annotations

import random

from deriva.adapters.archimate.models import ArchiMateMetamodel
from deriva.modules.derivation.refine.joint import (
    JointElement,
    MergeCandidate,
    Metamodel,
    Proposal,
    origin_tier,
    solve,
)

AC = "ApplicationComponent"
_ARCHIMATE = ArchiMateMetamodel()
ARCHIMATE = Metamodel(
    is_valid=lambda s, r, t: _ARCHIMATE.can_relate(s, r, t)[0],
    single_parent_types=_ARCHIMATE.single_parent_relationship_types,
    acyclic_types=_ARCHIMATE.acyclic_relationship_types,
)


def run(elements, proposals, merges):
    return solve(elements, proposals, merges, ARCHIMATE)


def el(identifier: str, element_type: str = AC, pagerank: float = 0.0, doc_length: int = 0) -> JointElement:
    return JointElement(identifier, element_type, pagerank, doc_length)


def rel(identifier: str, source: str, target: str, rel_type: str = "Serving", tier: int = 3, confidence: float = 0.5) -> Proposal:
    return Proposal(identifier, source, target, rel_type, tier, confidence)


class TestOriginTier:
    def test_graph_edges_are_tier_1(self):
        assert origin_tier("Graph:CALLS") == 1
        assert origin_tier("calls_edge") == 1

    def test_structural_rules_are_tier_2(self):
        for origin in ("graph_neighbor", "graph_neighbor_2hop", "community", "rule"):
            assert origin_tier(origin) == 2

    def test_llm_and_unknown_are_tier_3(self):
        assert origin_tier("llm") == 3
        assert origin_tier(None) == 3
        assert origin_tier("something_else") == 3


class TestPrefilter:
    def test_self_loop_is_dropped(self):
        decision = run([el("a")], [rel("r1", "a", "a")], [])
        assert decision.dropped == {"r1": "self_loop"}
        assert decision.kept == []

    def test_invalid_metamodel_is_dropped(self):
        decision = run([el("a"), el("d", "DataObject")], [rel("r1", "a", "d", "Composition")], [])
        assert decision.dropped == {"r1": "invalid_metamodel"}

    def test_empty_input_is_optimal(self):
        decision = run([], [], [])
        assert decision.ok
        assert decision.kept == [] and decision.merges == {}

    def test_core_has_no_archimate_knowledge(self):
        permissive = Metamodel(is_valid=lambda s, r, t: True)
        decision = solve([el("a"), el("d", "DataObject")], [rel("r1", "a", "d", "Composition", tier=2)], [], permissive)
        assert decision.kept == ["r1"]


class TestRelationshipConstraints:
    def test_h1_keeps_one_relationship_per_pair_highest_tier(self):
        decision = run(
            [el("a"), el("b")],
            [rel("llm", "a", "b", "Serving", tier=3), rel("edge", "a", "b", "Flow", tier=1)],
            [],
        )
        assert decision.kept == ["edge"]
        assert decision.dropped["llm"] == "H1:edge"

    def test_h2_single_composition_parent(self):
        decision = run(
            [el("a"), el("b"), el("c")],
            [rel("from_a", "a", "c", "Composition", tier=2), rel("from_b", "b", "c", "Composition", tier=3)],
            [],
        )
        assert decision.kept == ["from_a"]
        assert decision.dropped["from_b"] == "H2:from_a"

    def test_pair_falls_back_to_weaker_type_when_composition_is_taken(self):
        decision = run(
            [el("a"), el("b"), el("c")],
            [
                rel("c_comp", "c", "b", "Composition", tier=1),
                rel("a_comp", "a", "b", "Composition", tier=2),
                rel("a_agg", "a", "b", "Aggregation", tier=3),
            ],
            [],
        )
        assert sorted(decision.kept) == ["a_agg", "c_comp"]
        # Both H1 (a_agg holds the pair) and H2 (c_comp holds the parent slot) bind; the first row is reported.
        assert decision.dropped["a_comp"].split(":")[0] in {"H1", "H2"}

    def test_one_tier1_item_beats_several_tier3_items(self):
        decision = run(
            [el("a"), el("b")],
            [rel("ab", "a", "b", tier=3), rel("ba", "b", "a", tier=3)],
            [MergeCandidate("a", "b", tier=1, score=1.0, evidence="normalized_name")],
        )
        assert decision.merges == {"b": "a"}
        assert decision.kept == []
        assert decision.dropped["ab"].startswith("H4") and decision.dropped["ba"].startswith("H4")

    def test_deterministic_under_input_order(self):
        elements = [el(x) for x in "abcd"]
        proposals = [
            rel("r1", "a", "b", "Composition", 2, 0.9),
            rel("r2", "c", "b", "Composition", 2, 0.9),
            rel("r3", "a", "b", "Serving", 3, 0.7),
            rel("r4", "d", "c", "Flow", 3, 0.6),
        ]
        merges = [MergeCandidate("c", "d", 3, 0.9)]
        baseline = run(elements, proposals, merges)
        for seed in range(5):
            rnd = random.Random(seed)
            shuffled = proposals[:]
            rnd.shuffle(shuffled)
            again = run(list(reversed(elements)), shuffled, merges)
            assert (sorted(again.kept), again.dropped, again.merges) == (sorted(baseline.kept), baseline.dropped, baseline.merges)


class TestMerges:
    def test_merge_redirects_relationships_to_survivor(self):
        decision = run(
            [el("s", pagerank=0.9), el("d", pagerank=0.1), el("x")],
            [rel("d_to_x", "d", "x", "Serving", tier=2)],
            [MergeCandidate("s", "d", tier=1, score=1.0)],
        )
        assert decision.merges == {"d": "s"}
        assert decision.kept == ["d_to_x"]
        assert decision.redirects == {"d_to_x": ("s", "x")}

    def test_survivor_tie_breaks_on_documentation_then_identifier(self):
        decision = run(
            [el("a", doc_length=5), el("b", doc_length=50)],
            [],
            [MergeCandidate("a", "b", tier=1, score=1.0)],
        )
        assert decision.merges == {"a": "b"}

    def test_h5_merge_keeps_one_of_two_colliding_relationships(self):
        decision = run(
            [el("s", pagerank=0.9), el("d"), el("x")],
            [rel("s_to_x", "s", "x", "Serving", tier=2), rel("d_to_x", "d", "x", "Serving", tier=3)],
            [MergeCandidate("s", "d", tier=1, score=1.0)],
        )
        assert decision.merges == {"d": "s"}
        assert decision.kept == ["s_to_x"]
        assert decision.dropped["d_to_x"].startswith("H5")

    def test_h6_no_chain_without_direct_evidence(self):
        decision = run(
            [el("a"), el("b"), el("c")],
            [],
            [MergeCandidate("a", "b", tier=3, score=0.9), MergeCandidate("b", "c", tier=3, score=0.9)],
        )
        assert len(decision.merges) == 1

    def test_h6_triangle_merges_all_three(self):
        decision = run(
            [el("a", pagerank=0.9), el("b"), el("c")],
            [],
            [
                MergeCandidate("a", "b", tier=3, score=0.9),
                MergeCandidate("b", "c", tier=3, score=0.9),
                MergeCandidate("a", "c", tier=3, score=0.9),
            ],
        )
        assert decision.merges == {"b": "a", "c": "a"}

    def test_merge_requires_same_element_type(self):
        decision = run(
            [el("a"), el("s", "ApplicationService")],
            [],
            [MergeCandidate("a", "s", tier=1, score=1.0)],
        )
        assert decision.merges == {}


class TestCyclesAndFailures:
    def test_h3_breaks_composition_cycle(self):
        decision = run(
            [el("a"), el("b"), el("c")],
            [
                rel("ab", "a", "b", "Composition", tier=2, confidence=0.9),
                rel("bc", "b", "c", "Composition", tier=2, confidence=0.8),
                rel("ca", "c", "a", "Composition", tier=2, confidence=0.7),
            ],
            [],
        )
        assert sorted(decision.kept) == ["ab", "bc"]
        assert decision.dropped["ca"] == "H3:ab,bc"

    def test_cycle_created_by_a_merge_is_prevented(self):
        decision = run(
            [el("a", pagerank=0.9), el("b"), el("c")],
            [rel("ab", "a", "b", "Composition", tier=2), rel("bc", "b", "c", "Composition", tier=2)],
            [MergeCandidate("a", "c", tier=3, score=0.9)],
        )
        assert sorted(decision.kept) == ["ab", "bc"]
        assert decision.merges == {}

    def test_types_outside_acyclic_set_may_cycle(self):
        decision = run(
            [el("a"), el("b")],
            [rel("ab", "a", "b", "Flow", tier=2), rel("ba", "b", "a", "Flow", tier=2)],
            [],
        )
        assert sorted(decision.kept) == ["ab", "ba"]

    def test_solver_failure_changes_nothing(self, monkeypatch):
        from solvor.types import Result, Status

        from deriva.modules.derivation.refine import joint

        monkeypatch.setattr(joint, "solve_milp", lambda *a, **k: Result(None, 0.0, status=Status.MAX_ITER))
        decision = run([el("a"), el("b")], [rel("ab", "a", "b", tier=2)], [])
        assert not decision.ok
        assert decision.kept == [] and decision.merges == {}
