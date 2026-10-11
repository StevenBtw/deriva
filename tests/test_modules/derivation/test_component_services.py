"""Application services from structure: what each component with an interface offers, grouped by shared business objects."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from deriva.modules.derivation.component_services import (
    ComponentServicesConfig,
    build_service_prompt,
    derive_component_services,
    documentation_lines,
    group_by_shared_objects,
    offering_components,
)

CONFIG = ComponentServicesConfig(min_names=2, share=0.5, overlap=0.5, max_doc_lines=3)


def _el(identifier: str, element_type: str, source: str, name: str) -> dict[str, Any]:
    return {"identifier": identifier, "name": name, "element_type": element_type, "properties": {"source": source}}


BILLING = _el("ac_billing", "ApplicationComponent", "dir::r::services/billing", "Billing")
LEDGERS = _el("ac_ledgers", "ApplicationComponent", "dir::r::services/ledgers", "Ledgers")
SHIPPING = _el("ac_shipping", "ApplicationComponent", "dir::r::services/shipping", "Shipping")
TOOLS = _el("ac_tools", "ApplicationComponent", "dir::r::tools", "Tools")
BILLING_API = _el("ai_billing", "ApplicationInterface", "file::r::services_billing_routes.py", "Billing Routes HTTP API")
LEDGERS_API = _el("ai_ledgers", "ApplicationInterface", "file::r::services_ledgers_routes.py", "Ledgers Routes HTTP API")
SHIPPING_API = _el("ai_shipping", "ApplicationInterface", "file::r::services_shipping_routes.py", "Shipping Routes HTTP API")
LEDGER = _el("bo_ledger", "BusinessObject", "concept::r::ledger", "Ledger")
PARCEL = _el("bo_parcel", "BusinessObject", "concept::r::parcel", "Parcel")
ELEMENTS = [BILLING, LEDGERS, SHIPPING, TOOLS, BILLING_API, LEDGERS_API, SHIPPING_API, LEDGER, PARCEL]
PATHS = {
    "dir::r::services/billing": "services/billing",
    "dir::r::services/ledgers": "services/ledgers",
    "dir::r::services/shipping": "services/shipping",
    "dir::r::tools": "tools",
    "file::r::services_billing_routes.py": "services/billing/routes.py",
    "file::r::services_ledgers_routes.py": "services/ledgers/routes.py",
    "file::r::services_shipping_routes.py": "services/shipping/routes.py",
}
CODE = [
    ("LedgerEntry", "services/billing/LedgerEntry.py"),
    ("LedgerTotals", "services/billing/LedgerTotals.py"),
    ("Ledger", "services/ledgers/Ledger.py"),
    ("LedgerStore", "services/ledgers/LedgerStore.py"),
    ("Parcel", "services/shipping/Parcel.py"),
    ("ParcelLabel", "services/shipping/ParcelLabel.py"),
    ("LedgerTool", "tools/LedgerTool.py"),
    ("LedgerCheck", "tools/LedgerCheck.py"),
]
DOCS = {
    "services/billing/README.md": "# Billing\nCharges customers and keeps the ledger entries.\n\nRun with make.",
    "README.md": "# Shop\nThe billing module charges customers.\nThe shipping module sends parcels.\nLicense: open.",
}


def _llm(answers: dict[str, str], prompts: list[str]):
    def query(prompt: str, schema: dict[str, Any], **kwargs: Any) -> SimpleNamespace:
        prompts.append(prompt)
        name = next((n for key, n in answers.items() if key in prompt), "")
        return SimpleNamespace(content=json.dumps({"name": name, "documentation": f"Offers {name.lower()}."}))

    return query


class TestStructure:
    def test_a_component_offers_something_when_an_interface_lies_in_it(self):
        offering = offering_components(ELEMENTS, PATHS, CONFIG)

        assert {c: [i["identifier"] for i in interfaces] for c, interfaces in offering.items()} == {
            "ac_billing": ["ai_billing"],
            "ac_ledgers": ["ai_ledgers"],
            "ac_shipping": ["ai_shipping"],
        }

    def test_components_that_work_on_the_same_business_objects_are_one_service(self):
        groups = group_by_shared_objects(
            {"ac_billing": {"bo_ledger"}, "ac_ledgers": {"bo_ledger"}, "ac_shipping": {"bo_parcel"}, "ac_tools": set(), "ac_other": set()}, overlap=0.5
        )

        # No objects, no grouping: a component without them stays on its own
        assert groups == [["ac_billing", "ac_ledgers"], ["ac_other"], ["ac_shipping"], ["ac_tools"]]

    def test_a_small_overlap_keeps_components_apart(self):
        objects = {"ac_a": {"bo_1", "bo_2", "bo_3"}, "ac_b": {"bo_3", "bo_4", "bo_5"}}

        assert group_by_shared_objects(objects, overlap=0.5) == [["ac_a"], ["ac_b"]]
        assert group_by_shared_objects(objects, overlap=0.2) == [["ac_a", "ac_b"]]


class TestDocumentation:
    def test_lines_come_from_the_components_own_documents_then_from_lines_that_name_it(self):
        lines = documentation_lines("services/billing", DOCS, max_lines=3)

        assert lines == ["Billing", "Charges customers and keeps the ledger entries.", "Run with make."]
        assert documentation_lines("services/shipping", DOCS, max_lines=3) == ["The shipping module sends parcels."]
        assert documentation_lines("tools", DOCS, max_lines=3) == []


class TestServices:
    def test_one_service_per_group_named_by_the_answer_with_structure_as_identity(self):
        prompts: list[str] = []

        services = derive_component_services(
            ELEMENTS, PATHS, CODE, DOCS, CONFIG, "NAME THE CAPABILITY", _llm({"Shipping": "Parcel Dispatch", "Billing": "Ledger Keeping"}, prompts)
        )

        by_name = {s["name"]: s for s in services}
        assert set(by_name) == {"Ledger Keeping", "Parcel Dispatch"}
        ledger = by_name["Ledger Keeping"]
        assert ledger["element_type"] == "ApplicationService"
        assert ledger["properties"]["source"] == "dir::r::services/billing"
        assert ledger["properties"]["sources"] == ["dir::r::services/billing", "dir::r::services/ledgers"]
        assert ledger["properties"]["interfaces"] == ["ai_billing", "ai_ledgers"] and ledger["properties"]["objects"] == ["bo_ledger"]
        assert ledger["documentation"] == "Offers ledger keeping."
        assert len(prompts) == 2 and all("NAME THE CAPABILITY" in p for p in prompts)

    def test_the_prompt_shows_structure_and_documentation_only(self):
        prompt = build_service_prompt(
            {
                "components": [{"name": "Billing", "path": "services/billing"}],
                "interfaces": ["Billing Routes HTTP API"],
                "business_objects": ["Ledger"],
                "documentation": ["Charges customers."],
            },
            "NAME THE CAPABILITY",
        )

        assert "NAME THE CAPABILITY" in prompt and '"Billing Routes HTTP API"' in prompt and "Charges customers." in prompt

    def test_without_an_answer_the_service_keeps_the_components_name(self):
        def failing(prompt: str, schema: dict[str, Any], **kwargs: Any) -> SimpleNamespace:
            raise RuntimeError("provider down")

        services = derive_component_services([SHIPPING, SHIPPING_API, PARCEL], PATHS, CODE, DOCS, CONFIG, "NAME", failing)

        assert [s["name"] for s in services] == ["Shipping"]

    def test_the_same_identifier_every_run(self):
        first = derive_component_services(ELEMENTS, PATHS, CODE, DOCS, CONFIG, "NAME", _llm({"Shipping": "A", "Billing": "B"}, []))
        second = derive_component_services(list(reversed(ELEMENTS)), PATHS, CODE, DOCS, CONFIG, "NAME", _llm({"Shipping": "C", "Billing": "D"}, []))

        assert [s["identifier"] for s in first] == [s["identifier"] for s in second]
