"""Relationships from links the graph holds between source nodes (relationship config params.graph_links),
elements named as their source is written, and services whose interfaces and objects come through such links."""

from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from deriva.modules.derivation.base import Candidate, GraphLinkRule, RelationshipRule, derive_consolidated_relationships, derive_graph_link_relationships
from deriva.modules.derivation.component_services import ComponentServicesConfig, derive_component_services
from tests.test_modules.derivation.test_roles import TestRoleNameTemplate, TestStructuralRoles


def _el(identifier: str, element_type: str, source: str, name: str = "") -> dict[str, Any]:
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": {"source": source}}


PROG_A = _el("ac_proga", "ApplicationComponent", "typedef::r::src/PROGA.cbl::PROGA", "PROGA")
PROG_B = _el("ac_progb", "ApplicationComponent", "typedef::r::src/PROGB.cbl::PROGB", "PROGB")
PROG_C = _el("ac_progc", "ApplicationComponent", "typedef::r::src/PROGC.cbl::PROGC", "PROGC")
SCREEN_A = _el("ai_mapa", "ApplicationInterface", "typedef::r::maps/MAPA.bms::MAPA", "MAPA Web UI")
JOB_C = _el("ai_jobc", "ApplicationInterface", "typedef::r::jcl/JOBC.jcl::JOBC", "JOBC Batch Job")
LEDGER = _el("do_ledger", "DataObject", "typedef::r::cpy/LEDGER.cpy::LEDGER-RECORD", "Ledger Record")
PARCEL = _el("do_parcel", "DataObject", "typedef::r::cpy/PARCEL.cpy::PARCEL-RECORD", "Parcel Record")
ELEMENTS = [PROG_A, PROG_B, PROG_C, SCREEN_A, JOB_C, LEDGER, PARCEL]
SCREEN_LINKS = [(PROG_A["properties"]["source"], SCREEN_A["properties"]["source"]), (PROG_C["properties"]["source"], JOB_C["properties"]["source"])]
RECORD_LINKS = [
    (PROG_A["properties"]["source"], LEDGER["properties"]["source"]),
    (PROG_B["properties"]["source"], LEDGER["properties"]["source"]),
    (PROG_C["properties"]["source"], PARCEL["properties"]["source"]),
]


def _triples(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestGraphLinks:
    RULES = [GraphLinkRule(source="ApplicationComponent", target="ApplicationInterface", relationship="Composition", query="Q1")]

    def test_linked_sources_relate_their_elements(self):
        relationships = derive_graph_link_relationships(ELEMENTS, self.RULES, {"Q1": SCREEN_LINKS + [("typedef::r::none", "typedef::r::other")]})

        assert _triples(relationships) == {("ac_proga", "Composition", "ai_mapa"), ("ac_progc", "Composition", "ai_jobc")}
        assert {r["derived_from"] for r in relationships} == {"graph_link"}

    def test_the_consolidated_pass_runs_each_query_once(self):
        asked: list[str] = []

        def query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            asked.append(cypher)
            return [{"a": a, "b": b} for a, b in SCREEN_LINKS] if cypher == "Q1" else []

        relationships = derive_consolidated_relationships(
            all_elements=ELEMENTS, relationship_rules={}, llm_query_fn=None, graph_manager=cast(Any, SimpleNamespace(query=query)), graph_links=self.RULES
        )

        assert ("ac_proga", "Composition", "ai_mapa") in _triples(relationships) and asked.count("Q1") == 1


class TestNamedAsWritten:
    def test_an_element_with_a_structural_role_can_keep_its_source_name_and_is_not_renamed(self):
        """A program is known by its real name: no template, no naming call."""
        roles = dataclasses.replace(TestStructuralRoles.ROLES, structural=(("category", r"^program$", "http"),), structural_as_written=True, naming_call=True)
        program = Candidate(
            node_id="typedef::r::src/PROGA01C.cbl::PROGA01C",
            name="PROGA01C",
            labels=["Graph", "TypeDefinition"],
            properties={"filePath": "shop/src/PROGA01C.cbl", "category": "program"},
        )
        with patch.object(TestRoleNameTemplate, "ROLES", roles):
            elements, prompts = TestRoleNameTemplate._generate([program], {}, [("dir::r::shop", "shop", "Shop")])

        assert prompts == [] and [e["name"] for e in elements.values()] == ["PROGA01C"]


class TestServicesThroughLinks:
    CONFIG = ComponentServicesConfig(min_names=2, share=0.5, overlap=0.75, max_doc_lines=0)

    def test_interfaces_and_objects_reached_through_links_make_and_group_the_services(self):
        prompts: list[str] = []

        def llm(prompt: str, schema: dict[str, Any], **kwargs: Any) -> SimpleNamespace:
            prompts.append(prompt)
            return SimpleNamespace(content=json.dumps({"name": "Parcel Handling" if "PROGC" in prompt else "Ledger Keeping", "documentation": "x"}))

        services = derive_component_services(ELEMENTS, {}, [], {}, self.CONFIG, "NAME", llm, interface_links=SCREEN_LINKS, object_links=RECORD_LINKS)

        by_name = {s["name"]: s["properties"] for s in services}
        # PROGA has a screen and shares its record with PROGB (no interface of its own): one service of both
        assert by_name["Ledger Keeping"]["sources"] == [PROG_A["properties"]["source"], PROG_B["properties"]["source"]]
        assert by_name["Ledger Keeping"]["interfaces"] == ["ai_mapa"] and by_name["Ledger Keeping"]["objects"] == ["do_ledger"]
        assert by_name["Parcel Handling"]["interfaces"] == ["ai_jobc"]
        assert len(prompts) == 2 and "Ledger Record" in prompts[0] + prompts[1]

    def test_a_group_without_any_interface_is_no_service(self):
        services = derive_component_services(
            [PROG_B, LEDGER], {}, [], {}, self.CONFIG, "NAME", lambda *a, **k: SimpleNamespace(content="{}"), interface_links=[], object_links=RECORD_LINKS
        )

        assert services == []

    def test_a_link_to_something_that_is_no_element_changes_nothing(self):
        links = [*RECORD_LINKS, (PROG_B["properties"]["source"], "typedef::r::cpy/OTHER.cpy::OTHER"), ("typedef::r::none", LEDGER["properties"]["source"])]
        services = derive_component_services(
            [PROG_A, PROG_B, SCREEN_A], {}, [], {}, self.CONFIG, "NAME", lambda *a, **k: SimpleNamespace(content="{}"), interface_links=SCREEN_LINKS, object_links=links
        )

        assert [s["properties"]["sources"] for s in services] == [[PROG_A["properties"]["source"]]]


class TestCodesStayWhole:
    def test_a_word_of_capitals_and_digits_is_a_code_and_is_not_split(self):
        from deriva.modules.derivation.base import name_from_source

        assert name_from_source("PROGA01C") == "PROGA01C"
        assert name_from_source("LEDGER-A01-RECORD") == "Ledger A01 Record"
        assert name_from_source("ledgerReader") == "Ledger Reader"


def test_a_service_name_in_a_fenced_answer_is_read():
    answer = '```json\n{"name": "Ledger Keeping", "documentation": "x"}\n```'
    services = derive_component_services(
        [PROG_A, SCREEN_A], {}, [], {}, TestServicesThroughLinks.CONFIG, "NAME", lambda *a, **k: SimpleNamespace(content=answer), interface_links=SCREEN_LINKS
    )

    assert [s["name"] for s in services] == ["Ledger Keeping"]


class TestGraphLinksOnAChannel:
    """A rule with source_channel ends on the source element whose role is the link's channel (a unit has an interface per channel)."""

    RULE = GraphLinkRule(source="ApplicationInterface", target="ApplicationComponent", relationship="Serving", query="Q", source_channel=True)
    REST = {**_el("ai_core__rest", "ApplicationInterface", "unit::r::core", "Core REST API"), "properties": {"source": "unit::r::core", "role": "rest"}}
    WEB = {**_el("ai_core__web", "ApplicationInterface", "unit::r::core", "Core Web UI"), "properties": {"source": "unit::r::core", "role": "web"}}
    BILLING = _el("ac_billing", "ApplicationComponent", "unit::r::billing", "Billing")

    def test_the_providers_interface_of_the_channel_serves_the_consumer(self):
        relationships = derive_graph_link_relationships([self.REST, self.WEB, self.BILLING], [self.RULE], {"Q": [("unit::r::core", "unit::r::billing", "rest")]})

        assert _triples(relationships) == {("ai_core__rest", "Serving", "ac_billing")}

    def test_a_provider_without_an_interface_of_the_channel_gets_no_line(self):
        assert derive_graph_link_relationships([self.REST, self.WEB, self.BILLING], [self.RULE], {"Q": [("unit::r::core", "unit::r::billing", "rpc")]}) == []

    def test_the_query_rows_carry_the_channel(self):
        from deriva.modules.derivation.base import graph_link_pairs

        rows = [{"a": "unit::r::core", "b": "unit::r::billing", "channel": "rest"}, {"a": "x", "b": "y"}]
        assert graph_link_pairs(cast(Any, SimpleNamespace(query=lambda q: rows)), "Q") == [("unit::r::core", "unit::r::billing", "rest"), ("x", "y")]


class TestExclusiveGraphLinks:
    """An exclusive rule lets only the graph relate its two types by its relationship type, in either direction."""

    LIFE = _el("bp_lease", "BusinessProcess", "lifecycle::r::lease", "Lease Lifecycle")
    SENT = _el("be_sent", "BusinessEvent", "event::r::lease::SENT", "Lease Sent")
    DONE = _el("be_done", "BusinessEvent", "event::r::lease::DONE", "Lease Done")
    LINKS = {"Q1": [("lifecycle::r::lease", "event::r::lease::SENT")], "Q2": [("event::r::lease::SENT", "event::r::lease::DONE")]}
    METAMODEL = {
        "BusinessEvent": (
            [RelationshipRule(target_type="BusinessProcess", rel_type="Triggering")],
            [RelationshipRule(target_type="BusinessProcess", rel_type="Triggering")],
        ),
        "BusinessProcess": ([RelationshipRule(target_type="BusinessEvent", rel_type="Triggering")], [RelationshipRule(target_type="BusinessEvent", rel_type="Triggering")]),
    }

    def _derive(self, exclusive: bool):
        rules = [
            GraphLinkRule(source="BusinessProcess", target="BusinessEvent", relationship="Triggering", query="Q1", exclusive=exclusive),
            GraphLinkRule(source="BusinessEvent", target="BusinessEvent", relationship="Triggering", query="Q2", exclusive=exclusive),
        ]

        def query(cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            return [{"a": a, "b": b} for a, b in self.LINKS.get(cypher, [])]

        return derive_consolidated_relationships(
            all_elements=[self.LIFE, self.SENT, self.DONE],
            relationship_rules=self.METAMODEL,
            llm_query_fn=None,
            graph_manager=cast(Any, SimpleNamespace(query=query)),
            graph_links=rules,
        )

    def test_without_exclusive_other_tiers_add_more_of_the_type(self):
        assert _triples(self._derive(False)) > {("bp_lease", "Triggering", "be_sent"), ("be_sent", "Triggering", "be_done")}

    def test_with_exclusive_only_the_graph_links_remain(self):
        assert _triples(self._derive(True)) == {("bp_lease", "Triggering", "be_sent"), ("be_sent", "Triggering", "be_done")}
