"""Refine step wrapper: evidence collection, metamodel injection, dry-run report, apply."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from deriva.adapters.archimate.models import ArchiMateMetamodel, Element, Relationship
from deriva.modules.derivation.refine.joint_consistency import JointConsistencyStep, merge_candidates, origin_tiers


def element(identifier, name, source=None, element_type="ApplicationComponent", pagerank=0.0, role=None):
    props = {"source": source, "source_pagerank": pagerank}
    if role is not None:
        props["role"] = role
    return Element(name=name, element_type=element_type, identifier=identifier, properties=props)


class TestMergeCandidates:
    """Merges only on structural identity: the same type, source node and role; names never."""

    def test_the_same_source_and_role_is_tier_1(self):
        (m,) = merge_candidates([element("a", "Ledger", "n1"), element("b", "Payouts", "n1")])
        assert (m.first, m.second, m.tier, m.evidence) == ("a", "b", 1, "same_source_node")

    def test_interfaces_of_one_unit_on_different_channels_are_no_candidates(self):
        pair = [
            element("a", "Core REST API", "unit::r::core", "ApplicationInterface", role="rest"),
            element("b", "Core Web UI", "unit::r::core", "ApplicationInterface", role="web"),
        ]
        assert merge_candidates(pair) == []

    def test_equal_or_similar_names_are_no_candidates(self):
        assert merge_candidates([element("a", "Ledger", "n1"), element("b", "Ledger", "n2")]) == []
        assert merge_candidates([element("a", "Ledger Keeping", "n1"), element("b", "Ledger Keepings", "n2")]) == []

    def test_no_source_is_no_evidence(self):
        assert merge_candidates([element("a", "Ledger"), element("b", "Ledger")]) == []

    def test_different_types_never_candidates(self):
        assert merge_candidates([element("a", "Ledger", "n1"), element("b", "Ledger", "n1", element_type="ApplicationService")]) == []


class TestOriginTiers:
    def test_the_table_comes_from_params(self):
        assert origin_tiers({})["graph_link"] == 1
        assert origin_tiers({"origin_tiers": {"graph_link": 2}}) == {"graph_link": 2}

    @pytest.mark.parametrize("table", [{"graph_link": 4}, {"graph_link": "1"}, ["graph_link"]])
    def test_an_invalid_table_is_an_error(self, table):
        with pytest.raises(ValueError, match="origin_tiers"):
            origin_tiers({"origin_tiers": table})


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
        elements = [element("a", "Ledger", "n1", pagerank=0.9), element("b", "Ledger Core", "n1"), element("x", "Portal", "n2")]
        rels = [Relationship(source="b", target="x", relationship_type="Serving", identifier="r1", properties={"derived_from": "graph_link"})]
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
        elements = [element("a", "Ledger", "n1", pagerank=0.9), element("b", "Ledger Core", "n1"), element("x", "Portal", "n2")]
        rels = [
            Relationship(source="b", target="x", relationship_type="Serving", identifier="r1", properties={"derived_from": "rule"}),
            Relationship(source="a", target="a", relationship_type="Serving", identifier="loop", properties={}),
        ]
        am, gm = managers(elements, rels)

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.disable_element.assert_called_once_with("b", reason="duplicate_of:a:joint:same_source_node")
        am.redirect_relationship.assert_called_once_with("r1", "a", "x")
        am.delete_relationship.assert_called_once_with("loop")
        assert result.elements_merged == 1 and result.relationships_deleted == 2 and result.relationships_created == 1

    def test_the_tier_table_from_params_decides_a_conflict(self):
        elements = [element("a", "A", "n1"), element("b", "B", "n2")]
        rels = [
            Relationship(source="a", target="b", relationship_type="Serving", identifier="named", properties={"derived_from": "named_in_code"}),
            Relationship(source="a", target="b", relationship_type="Flow", identifier="words", properties={"derived_from": "rule"}),
        ]
        am, gm = managers(elements, rels)

        JointConsistencyStep().run(am, gm, params={"dry_run": False})
        am.delete_relationship.assert_called_once_with("words")  # tier 2 beats tier 3

        am, gm = managers(elements, rels)
        JointConsistencyStep().run(am, gm, params={"dry_run": False, "origin_tiers": {"rule": 1, "named_in_code": 3}})
        am.delete_relationship.assert_called_once_with("named")

    @staticmethod
    def _with_disabled_duplicate(dup):
        dup.enabled = False
        elements = [element("a", "Ledger", "n1", pagerank=0.9), dup]
        am, gm = managers(elements, [])
        am.query.return_value = [{"id": dup.identifier}]
        return am, gm

    def test_apply_plans_over_the_same_elements_as_the_dry_run(self):
        am, gm = self._with_disabled_duplicate(element("b", "Ledger Core", "n1"))

        JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.disable_element.assert_called_once_with("b", reason="duplicate_of:a:joint:same_source_node")

    def test_apply_re_enables_a_disabled_duplicate_it_keeps_separate(self):
        am, gm = self._with_disabled_duplicate(element("y", "Portal", "n9"))

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        am.enable_element.assert_called_once_with("y")
        assert result.success

    def test_solver_failure_applies_nothing_and_reports_error(self, monkeypatch):
        from deriva.modules.derivation.refine import joint_consistency
        from deriva.modules.derivation.refine.joint import JointDecision

        monkeypatch.setattr(joint_consistency, "solve", lambda *a, **k: JointDecision(status="solver_failed"))
        am, gm = managers([element("a", "Ledger", "n1"), element("b", "Ledger Core", "n1")], [])

        result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

        assert not result.success
        assert result.errors == ["joint solve failed: solver_failed"]
        am.disable_element.assert_not_called()

    def test_is_registered(self):
        from deriva.modules.derivation.refine import REFINE_STEPS

        assert "joint_consistency" in REFINE_STEPS


def test_the_step_reports_the_solve_with_its_time():
    elements = [element("a", "A", "n1"), element("b", "B", "n2")]
    rels = [
        Relationship(source="a", target="b", relationship_type="Serving", identifier="named", properties={"derived_from": "named_in_code"}),
        Relationship(source="a", target="b", relationship_type="Flow", identifier="words", properties={"derived_from": "rule"}),
    ]
    am, gm = managers(elements, rels)

    result = JointConsistencyStep().run(am, gm, params={"dry_run": False})

    report = result.report
    assert report["status"] == "optimal" and report["rows"] == {"H1": 1} and report["dropped"] == 1 and report["kept"] == 1
    assert isinstance(report["seconds"], float) and report["seconds"] >= 0
    assert result.to_dict()["report"] == report
