"""Relationships between an element and the members it lists (relationship config params.listed_members)."""

from __future__ import annotations

from typing import Any

from deriva.modules.derivation.base import ListedMembersRule, derive_consolidated_relationships, derive_listed_member_relationships

RULES = [
    ListedMembersRule(holder="ApplicationService", list_property="sources", member="ApplicationComponent", relationship="Realization", by="source", from_holder=False),
    ListedMembersRule(holder="ApplicationService", list_property="interfaces", member="ApplicationInterface", relationship="Assignment", by="identifier", from_holder=False),
    ListedMembersRule(holder="ApplicationService", list_property="objects", member="BusinessObject", relationship="Access", by="identifier", from_holder=True),
]


def _el(identifier: str, element_type: str, source: str, **properties: Any) -> dict[str, Any]:
    return {"identifier": identifier, "name": identifier, "element_type": element_type, "properties": {"source": source, **properties}}


SERVICE = _el("as_billing", "ApplicationService", "dir::r::billing", sources=["dir::r::billing", "dir::r::ledgers"], interfaces=["ai_billing"], objects=["bo_ledger"])
ELEMENTS = [
    SERVICE,
    _el("ac_billing", "ApplicationComponent", "dir::r::billing"),
    _el("ac_ledgers", "ApplicationComponent", "dir::r::ledgers"),
    _el("ac_other", "ApplicationComponent", "dir::r::other"),
    _el("ai_billing", "ApplicationInterface", "file::r::billing_routes.py"),
    _el("ai_other", "ApplicationInterface", "file::r::other_routes.py"),
    _el("bo_ledger", "BusinessObject", "concept::r::ledger"),
    _el("bo_parcel", "BusinessObject", "concept::r::parcel"),
]


def _triples(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


def test_listed_members_relate_to_their_holder_in_the_configured_direction():
    relationships = derive_listed_member_relationships(ELEMENTS, RULES)

    assert _triples(relationships) == {
        ("ac_billing", "Realization", "as_billing"),
        ("ac_ledgers", "Realization", "as_billing"),
        ("ai_billing", "Assignment", "as_billing"),
        ("as_billing", "Access", "bo_ledger"),
    }
    assert {r["derived_from"] for r in relationships} == {"listed_members"}


def test_an_element_without_the_list_relates_to_nothing():
    plain = _el("as_plain", "ApplicationService", "typedef::r::x")

    assert derive_listed_member_relationships([plain, *ELEMENTS[1:]], RULES) == []


def test_the_consolidated_pass_adds_them():
    relationships = derive_consolidated_relationships(all_elements=ELEMENTS, relationship_rules={}, llm_query_fn=None, listed_members=RULES)

    assert ("ac_billing", "Realization", "as_billing") in _triples(relationships)
