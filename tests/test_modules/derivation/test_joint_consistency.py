"""Refine step wrapper: evidence collection, metamodel injection, dry-run report, apply."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from deriva.adapters.archimate.models import ArchiMateMetamodel, Element, Relationship
from deriva.modules.derivation.refine.joint_consistency import JointConsistencyStep, merge_candidates
from deriva.modules.derivation.refine.normalization import RepoContext


def element(identifier, name, source=None, community=None, element_type="ApplicationComponent", pagerank=0.0):
    props = {"source": source, "source_pagerank": pagerank}
    if community is not None:
        props["source_louvain_community"] = community
    return Element(name=name, element_type=element_type, identifier=identifier, properties=props)


class TestMergeCandidates:
    ctx = RepoContext(repo_name="")

    def test_normalized_name_is_tier_1(self):
        (m,) = merge_candidates([element("a", "Claims"), element("b", "Claims Component")], self.ctx, set(), 0.85)
        assert (m.first, m.second, m.tier, m.evidence) == ("a", "b", 1, "normalized_name")

    def test_same_source_node_is_tier_1(self):
        (m,) = merge_candidates([element("a", "Claims", "n1"), element("b", "Payouts", "n1")], self.ctx, set(), 0.85)
        assert (m.tier, m.evidence) == (1, "same_source_node")

    def test_fuzzy_with_graph_proximity_is_tier_2_else_tier_3(self):
        pair = [element("a", "Claim Registration", "n1"), element("b", "Claim Registrations", "n2")]
        near = merge_candidates(pair, self.ctx, {frozenset(("n1", "n2"))}, 0.85)
        far = merge_candidates(pair, self.ctx, set(), 0.85)
        assert near[0].tier == 2 and far[0].tier == 3

    def test_empty_names_are_never_candidates(self):
        assert merge_candidates([element("a", ""), element("b", "")], self.ctx, set(), 0.85) == []

    def test_different_types_never_candidates(self):
        assert merge_candidates([element("a", "Claims"), element("b", "Claims", element_type="ApplicationService")], self.ctx, set(), 0.85) == []


def managers(elements, relationships):
    am = MagicMock()
    am.namespace = "Model"
    am.metamodel = ArchiMateMetamodel()
    am.get_elements.return_value = elements
    am.get_relationships.return_value = relationships
    am.query.return_value = []
    gm = MagicMock()
    gm.query.return_value = []
    return am, gm


class TestStep:
    def test_dry_run_reports_without_writing(self, tmp_path):
        elements = [element("a", "Claims", pagerank=0.9), element("b", "Claims Component"), element("x", "Portal")]
        rels = [Relationship(source="b", target="x", relationship_type="Serving", identifier="r1", properties={"derived_from": "llm"})]
        am, gm = managers(elements, rels)
        report = tmp_path / "joint.json"

        result = JointConsistencyStep().run(am, gm, params={"dry_run": True, "report_path": str(report)})

        assert result.success
        am.disable_element.assert_not_called()
        am.delete_relationship.assert_not_called()
        am.redirect_relationship.assert_not_called()
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["merges"] == {"b": "a"}
        assert data["redirects"] == {"r1": ["a", "x"]}

    def test_apply_merges_redirects_and_drops(self):
        elements = [element("a", "Claims", pagerank=0.9), element("b", "Claims Component"), element("x", "Portal")]
        rels = [
            Relationship(source="b", target="x", relationship_type="Serving", identifier="r1", properties={"derived_from": "rule"}),
            Relationship(source="a", target="a", relationship_type="Serving", identifier="loop", properties={}),
        ]
        am, gm = managers(elements, rels)

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.disable_element.assert_called_once_with("b", reason="duplicate_of:a:joint:normalized_name")
        am.redirect_relationship.assert_called_once_with("r1", "a", "x")
        am.delete_relationship.assert_called_once_with("loop")
        assert result.elements_merged == 1 and result.relationships_deleted == 2 and result.relationships_created == 1

    @staticmethod
    def _with_disabled_duplicate(dup):
        dup.enabled = False
        elements = [element("a", "Claims", pagerank=0.9), dup]
        am, gm = managers(elements, [])
        am.query.return_value = [{"id": dup.identifier}]
        return am, gm

    def test_apply_plans_over_the_same_elements_as_the_dry_run(self):
        am, gm = self._with_disabled_duplicate(element("b", "Claims Component"))

        JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.disable_element.assert_called_once_with("b", reason="duplicate_of:a:joint:normalized_name")

    def test_apply_re_enables_a_disabled_duplicate_it_keeps_separate(self):
        am, gm = self._with_disabled_duplicate(element("y", "Portal"))

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.enable_element.assert_called_once_with("y")
        assert result.success

    def test_solver_failure_applies_nothing_and_reports_error(self, monkeypatch):
        from deriva.modules.derivation.refine import joint_consistency
        from deriva.modules.derivation.refine.joint import JointDecision

        monkeypatch.setattr(joint_consistency, "solve", lambda *a, **k: JointDecision(status="solver_failed"))
        am, gm = managers([element("a", "Claims"), element("b", "Claims Component")], [])

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        assert not result.success
        assert result.errors == ["joint solve failed: solver_failed"]
        am.disable_element.assert_not_called()

    def test_is_registered(self):
        from deriva.modules.derivation.refine import REFINE_STEPS

        assert "joint_consistency" in REFINE_STEPS
