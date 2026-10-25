"""Derivation of relationships from chains of direct ones (pure engine): the rules are data, so these tests use
synthetic rules, not the specification's."""

from __future__ import annotations

from deriva.modules.derivation.derivation_rules import Rule, derive

STRENGTH = ("Realization", "Assignment", "Aggregation", "Composition")  # weakest first
STRUCTURAL = frozenset(STRENGTH)
CHAIN = Rule(number="T1", first=STRUCTURAL, second=STRUCTURAL, join="chain", result="weakest")
THEN_SERVING = Rule(number="T2", first=STRUCTURAL, second=frozenset({"Serving"}), join="chain", result="second")
SERVING_INTO = Rule(number="T3", first=frozenset({"Serving"}), second=STRUCTURAL, join="into", result="first")


def _always(source_type: str, relationship_type: str, target_type: str) -> bool:
    return True


def test_a_chain_of_structural_relationships_derives_the_weakest_with_its_chain_and_rule():
    rels = [("r1", "sys", "Composition", "unit"), ("r2", "unit", "Assignment", "fn"), ("r3", "fn", "Realization", "svc")]

    derived = derive(rels, {}, [CHAIN], STRENGTH, _always)

    assert derived[("sys", "Assignment", "fn")].chain == ("r1", "r2")
    assert derived[("sys", "Realization", "svc")].chain == ("r1", "r2", "r3")
    assert derived[("sys", "Realization", "svc")].rules == ("T1", "T1")
    assert ("sys", "Composition", "unit") not in derived  # a direct relationship is no derivation


def test_the_second_relationship_type_and_the_into_join():
    rels = [("r1", "node", "Composition", "sw"), ("r2", "sw", "Serving", "app"), ("r3", "tool", "Serving", "part"), ("r4", "whole", "Composition", "part")]

    derived = derive(rels, {}, [THEN_SERVING, SERVING_INTO], STRENGTH, _always)

    assert derived[("node", "Serving", "app")].chain == ("r1", "r2")
    assert derived[("tool", "Serving", "whole")].chain == ("r3", "r4")  # p(a,b), q(c,b) -> r(a,c)


def test_the_metamodel_decides_whether_a_derived_triple_exists():
    rels = [("r1", "a", "Composition", "b"), ("r2", "b", "Assignment", "c")]
    types = {"a": "Node", "b": "SystemSoftware", "c": "TechnologyFunction"}

    derived = derive(rels, types, [CHAIN], STRENGTH, lambda s, r, t: (s, t) != ("Node", "TechnologyFunction"))

    assert derived == {}


def test_chains_are_bounded_and_the_shortest_chain_wins_deterministically():
    rels = [("r1", "a", "Composition", "b"), ("r2", "b", "Composition", "c"), ("r3", "c", "Composition", "d"), ("r4", "a", "Composition", "c")]

    derived = derive(rels, {}, [CHAIN], STRENGTH, _always, max_length=2)

    assert derived[("a", "Composition", "d")].chain == ("r4", "r3")  # length 2 through the direct shortcut, not r1 r2 r3
    assert derive(list(reversed(rels)), {}, [CHAIN], STRENGTH, _always, max_length=2) == derived


def test_no_self_loop_and_no_unknown_relationship_type_is_derived():
    rels = [("r1", "a", "Composition", "b"), ("r2", "b", "Composition", "a"), ("r3", "b", "Triggering", "c")]

    derived = derive(rels, {}, [CHAIN], STRENGTH, _always)

    assert derived == {}


def test_the_valid_rules_of_the_specification_derive_its_examples():
    """ArchiMate 3.2 Appendix B.2 (DR 1-8): Example 39 (DR 2), Example 40 (DR 3), Example 41 (DR 4), Example 43 (DR 6)."""
    from deriva.adapters.archimate.models import STRUCTURAL_STRENGTH, VALID_DERIVATION_RULES
    from deriva.modules.derivation.derivation_rules import rules_from

    def run(rels):
        return derive(rels, {}, rules_from(VALID_DERIVATION_RULES), STRUCTURAL_STRENGTH, _always)

    # DR 2: assignment - composition - realization gives realization (the weakest)
    ex39 = run([("p", "app", "Assignment", "processing"), ("q", "processing", "Composition", "payment"), ("r", "payment", "Realization", "service")])
    assert ex39[("app", "Realization", "service")].rules == ("DR 2", "DR 2")
    # DR 3: a function realizes a service that serves a process: the function serves the process
    assert ("fn", "Serving", "process") in run([("p", "fn", "Realization", "svc"), ("q", "svc", "Serving", "process")])
    # DR 4: a component assigned to a function that a service serves: the service serves the component
    assert ("svc", "Serving", "component") in run([("p", "component", "Assignment", "fn"), ("q", "svc", "Serving", "fn")])
    # DR 6: an actor assigned to a process that a flow reaches: the flow reaches the actor
    assert ("source", "Flow", "actor") in run([("p", "actor", "Assignment", "process"), ("q", "source", "Flow", "process")])
    # A dependency followed by a structural relationship in line is no valid derivation (access to a data object that realizes a business object)
    assert ("svc", "Access", "bo") not in run([("p", "svc", "Access", "do"), ("q", "do", "Realization", "bo")])
