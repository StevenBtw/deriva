"""Relationships from the code that names a concept (relationship config params.named_in_code).

A business element whose words appear in the names of types and directories below a component's
directory is related to that component: the graph says where the concept lives in the code.
"""

from __future__ import annotations

from typing import Any

from deriva.modules.derivation.base import NamedInCodeRule, code_names_with_paths, derive_consolidated_relationships, derive_named_in_code_relationships

RULES = [NamedInCodeRule(owner="ApplicationComponent", named="BusinessObject", relationship="Access", min_names=2)]


def _el(identifier: str, element_type: str, source: str, name: str = "") -> dict[str, Any]:
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": {"source": source}}


BILLING = _el("ac_billing", "ApplicationComponent", "dir::r::services/billing")
SHIPPING = _el("ac_shipping", "ApplicationComponent", "dir::r::services/shipping")
LEDGER = _el("bo_ledger", "BusinessObject", "concept::r::ledger", name="Ledger")
VOUCHER = _el("bo_voucher", "BusinessObject", "concept::r::voucher", name="Voucher")
PATHS = {"dir::r::services/billing": "services/billing", "dir::r::services/shipping": "services/shipping"}
CODE = [
    ("LedgerEntry", "services/billing/model/LedgerEntry.java"),
    ("LedgerService", "services/billing/LedgerService.java"),
    ("ledgers", "services/billing/ledgers"),
    ("VoucherPrinter", "services/billing/VoucherPrinter.java"),
    ("LedgerExport", "services/shipping/LedgerExport.java"),
    ("Parcel", "services/shipping/Parcel.java"),
]


def _pairs(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestNamedInCode:
    def test_the_component_whose_code_names_the_concept_accesses_it(self):
        relationships = derive_named_in_code_relationships([BILLING, SHIPPING, LEDGER, VOUCHER], PATHS, CODE, RULES)

        # Ledger: three names below billing (a plural directory counts), one below shipping; Voucher: one name, under the minimum
        assert _pairs(relationships) == {("ac_billing", "Access", "bo_ledger")}
        assert {r["derived_from"] for r in relationships} == {"named_in_code"}

    def test_components_with_the_same_number_of_names_both_relate(self):
        code = [*CODE, ("LedgerLabel", "services/shipping/LedgerLabel.java"), ("LedgerRoute", "services/shipping/LedgerRoute.java")]

        relationships = derive_named_in_code_relationships([BILLING, SHIPPING, LEDGER], PATHS, code, RULES)

        assert _pairs(relationships) == {("ac_billing", "Access", "bo_ledger"), ("ac_shipping", "Access", "bo_ledger")}

    def test_a_component_with_at_least_the_share_of_the_strongest_relates_too(self):
        """A concept can live in two components; one stray mention next to many is no home."""
        code = [*CODE, ("LedgerLabel", "services/shipping/LedgerLabel.java")]
        half = [NamedInCodeRule(owner="ApplicationComponent", named="BusinessObject", relationship="Access", min_names=2, share=0.5)]
        all_of_it = [NamedInCodeRule(owner="ApplicationComponent", named="BusinessObject", relationship="Access", min_names=2, share=1.0)]

        # billing has three names, shipping two: two of three passes a share of one half, not a share of one
        assert _pairs(derive_named_in_code_relationships([BILLING, SHIPPING, LEDGER], PATHS, code, half)) == {
            ("ac_billing", "Access", "bo_ledger"),
            ("ac_shipping", "Access", "bo_ledger"),
        }
        assert _pairs(derive_named_in_code_relationships([BILLING, SHIPPING, LEDGER], PATHS, code, all_of_it)) == {("ac_billing", "Access", "bo_ledger")}

    def test_a_name_counts_for_the_nearest_component_only(self):
        """A component inside another one owns its code: the outer one is not credited with it."""
        outer = _el("ac_services", "ApplicationComponent", "dir::r::services")
        paths = {**PATHS, "dir::r::services": "services"}

        relationships = derive_named_in_code_relationships([outer, BILLING, LEDGER], paths, CODE, RULES)

        assert _pairs(relationships) == {("ac_billing", "Access", "bo_ledger")}

    def test_the_words_of_a_longer_name_must_stand_in_a_row(self):
        note = _el("bo_note", "BusinessObject", "concept::r::creditnote", name="Credit Note")
        code = [
            ("CreditNote", "services/billing/CreditNote.java"),
            ("CreditNoteLine", "services/billing/CreditNoteLine.java"),
            ("NoteOfCredit", "services/shipping/NoteOfCredit.java"),
            ("CreditLimitNote", "services/shipping/CreditLimitNote.java"),
        ]

        relationships = derive_named_in_code_relationships([BILLING, SHIPPING, note], PATHS, code, RULES)

        assert _pairs(relationships) == {("ac_billing", "Access", "bo_note")}

    def test_the_concept_is_matched_by_its_own_name_when_the_graph_gives_one(self):
        """The element's display name may be reworded; the concept's name in the graph is what the code is searched for."""
        renamed = _el("bo_ledger", "BusinessObject", "concept::r::ledger", name="General Book")

        relationships = derive_named_in_code_relationships([BILLING, renamed], PATHS, CODE, RULES, concept_names={"concept::r::ledger": "Ledger"})

        assert _pairs(relationships) == {("ac_billing", "Access", "bo_ledger")}

    def test_no_rule_no_relationship(self):
        assert derive_named_in_code_relationships([BILLING, LEDGER], PATHS, CODE, []) == []


class FakeGraph:
    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "TypeDefinition" in cypher and "typeName" in cypher:
            return [{"name": name, "path": path} for name, path in CODE if path.endswith(".java")]
        if "Graph:Directory" in cypher and "d.name" in cypher:
            return [{"name": "ledgers", "path": "services\\billing\\ledgers"}]
        if "conceptName" in cypher:
            return [{"id": "concept::r::ledger", "name": "Ledger"}]
        if "n.path AS path" in cypher:
            return [{"id": source, "path": path, "file_path": None} for source, path in PATHS.items()]
        return []


class TestFromTheGraph:
    def test_code_names_are_the_repositories_own_types_and_directories_with_their_paths(self):
        names = code_names_with_paths(FakeGraph())  # type: ignore[arg-type]

        assert ("LedgerEntry", "services/billing/model/LedgerEntry.java") in names
        assert ("ledgers", "services/billing/ledgers") in names

    def test_the_consolidated_pass_adds_them(self):
        relationships = derive_consolidated_relationships(
            all_elements=[BILLING, SHIPPING, LEDGER], relationship_rules={}, llm_query_fn=None, graph_manager=FakeGraph(), named_in_code=RULES
        )  # type: ignore[arg-type]

        assert ("ac_billing", "Access", "bo_ledger") in _pairs(relationships)
