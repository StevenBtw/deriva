"""Relationships between elements whose structural sources carry the same name (relationship config params.same_name)."""

from __future__ import annotations

from typing import Any

from deriva.modules.derivation.base import SameNameRule, derive_consolidated_relationships, derive_same_name_relationships

RULES = [SameNameRule(source="DataObject", target="BusinessObject", relationship="Realization", strip_suffixes=("Impl",))]


def _el(identifier: str, element_type: str, source: str, name: str = "") -> dict[str, Any]:
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": {"source": source}}


ORDER_DATA = _el("do_order", "DataObject", "typedef::r::store/OrderImpl.java::OrderImpl", name="Order Record")
LEDGER_DATA = _el("do_ledger", "DataObject", "typedef::r::store/LedgerEntry.java::LedgerEntry")
ORDER = _el("bo_order", "BusinessObject", "concept::r::order", name="Order")
INVOICE = _el("bo_invoice", "BusinessObject", "concept::r::invoice")


def _pairs(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestSameName:
    def test_the_data_object_realizes_the_business_object_its_type_names(self):
        relationships = derive_same_name_relationships([ORDER_DATA, LEDGER_DATA, ORDER, INVOICE], RULES)

        # Matched on the sources (type name without the suffix, concept key), whatever the display names say
        assert _pairs(relationships) == {("do_order", "Realization", "bo_order")}
        assert {r["derived_from"] for r in relationships} == {"same_name"}

    def test_without_the_suffix_rule_the_implementation_name_does_not_match(self):
        rules = [SameNameRule(source="DataObject", target="BusinessObject", relationship="Realization", strip_suffixes=())]

        assert derive_same_name_relationships([ORDER_DATA, ORDER], rules) == []

    def test_the_consolidated_pass_adds_them(self):
        relationships = derive_consolidated_relationships(all_elements=[ORDER_DATA, ORDER], relationship_rules={}, llm_query_fn=None, same_name=RULES)

        assert _pairs(relationships) == {("do_order", "Realization", "bo_order")}
