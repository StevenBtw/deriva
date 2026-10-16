"""Application services per component (gap 3): the members of a component's interfaces grouped by member
family and by the data domain they reach; business functions where cooperating components share a domain."""

from __future__ import annotations

import json
from typing import Any

from deriva.modules.derivation.base import UnitScopes
from deriva.modules.derivation.component_services import ComponentServicesConfig, derive_unit_services

CONFIG = ComponentServicesConfig(
    group_by="unit",
    min_members=2,
    max_per_component=3,
    min_family=3,
    kind_words=("Information Holder", "Holder", "Resource", "Controller", "Endpoint", "Servlet", "Consumer", "Abstract", "Service"),
    generic_names=("routes", "index", "main", "api"),
    service_templates=("{object} Management",),
    function_templates=("{object} Management", "{object} Handling"),
)


def _component(unit: str, name: str) -> dict[str, Any]:
    return {"identifier": f"ac_{unit}", "name": name, "element_type": "ApplicationComponent", "properties": {"source": f"unit::{unit}"}}


def _interface(unit: str, role: str, members: list[str]) -> dict[str, Any]:
    return {
        "identifier": f"ai_{unit}__{role}",
        "name": f"{unit} {role}",
        "element_type": "ApplicationInterface",
        "properties": {"source": f"unit::{unit}", "role": role, "members": [{"name": m, "source": f"n::{m}"} for m in members]},
    }


def _data(key: str, name: str) -> dict[str, Any]:
    return {"identifier": f"do_{key}", "name": name, "element_type": "DataObject", "properties": {"source": f"domain::{key}"}}


def _run(elements, reach, *, bases=None, lines=(), objects=None, deciding=None, llm=None, documents=None, files=None):
    """reach: member -> domain keys its file holds; each member lives in its own file."""
    node_paths = {f"n::{m}": f"{m}.java" for m in reach} | {f"n::{m}": f"{m}.java" for e in elements for m in [x["name"] for x in (e["properties"].get("members") or [])]}
    entity_files: dict[str, set[str]] = {}
    for member, domains in reach.items():
        for d in domains:
            entity_files.setdefault(f"domain::{d}", set()).add(f"{member}.java")
    scopes = UnitScopes(files=files or {}, nodes={}, entity_files={k: frozenset(v) for k, v in entity_files.items()}, entity_nodes={})
    calls: list[str] = []

    def query(prompt, schema, **kwargs):
        calls.append(prompt)
        choice = (llm or (lambda options: options[0]))(schema["schema"]["properties"]["name"]["enum"])
        return {"content": json.dumps({"name": choice})}

    services, functions = derive_unit_services(
        elements,
        node_paths,
        [],
        CONFIG,
        "Choose the name.",
        query,
        scopes=scopes,
        deciding=set(deciding if deciding is not None else {f"domain::{d}" for ds in reach.values() for d in ds}),
        business_objects=objects or {},
        bases={f"n::{m}": set(b) for m, b in (bases or {}).items()},
        lines=set(lines),
        documents=documents or {},
    )
    return services, functions, calls


def _groups(services):
    return sorted(sorted(m["name"] for m in s["properties"]["members"]) for s in services)


def test_a_component_offers_one_service_per_domain_its_members_reach_when_each_holds_enough_members():
    elements = [
        _component("pm", "Policy Management"),
        _interface("pm", "rest", ["PolicyHolder", "PolicyRepository", "QuoteResource", "QuoteConsumer"]),
        _data("policy", "Policy Data"),
        _data("quote", "Quote Data"),
    ]
    reach = {"PolicyHolder": ["policy"], "PolicyRepository": ["policy"], "QuoteResource": ["quote"], "QuoteConsumer": ["quote"]}

    services, _, _ = _run(elements, reach)

    assert _groups(services) == [["PolicyHolder", "PolicyRepository"], ["QuoteConsumer", "QuoteResource"]]
    by_objects = {tuple(s["properties"]["objects"]): s for s in services}
    assert set(by_objects) == {("do_policy",), ("do_quote",)}
    assert all(s["properties"]["sources"] == ["unit::pm"] and s["properties"]["interfaces"] == ["ai_pm__rest"] for s in services)
    assert by_objects[("do_policy",)]["identifier"] != by_objects[("do_quote",)]["identifier"]


def test_one_service_when_only_one_group_holds_enough_members():
    elements = [
        _component("pm", "Policy Management"),
        _interface("pm", "rest", ["PolicyHolder", "PolicyRepository", "QuoteResource"]),
        _data("policy", "Policy Data"),
        _data("quote", "Quote Data"),
    ]

    services, _, _ = _run(elements, {"PolicyHolder": ["policy"], "PolicyRepository": ["policy"], "QuoteResource": ["quote"]})

    assert _groups(services) == [["PolicyHolder", "PolicyRepository", "QuoteResource"]]


def test_members_of_one_family_are_one_service_and_pages_join_it():
    elements = [
        _component("store", "Store"),
        _interface("store", "rest", ["CategoryEndpoint", "OrderEndpoint", "UserEndpoint"]),
        _interface("store", "web", ["index.jsp", "cart.jsp"]),
        _data("category", "Category Data"),
        _data("order", "Order Data"),
        _data("user", "User Data"),
    ]
    reach = {"CategoryEndpoint": ["category"], "OrderEndpoint": ["order"], "UserEndpoint": ["user"]}
    bases = {"CategoryEndpoint": ["AbstractCRUDEndpoint"], "OrderEndpoint": ["AbstractCRUDEndpoint"], "UserEndpoint": ["AbstractCRUDEndpoint"]}

    services, _, _ = _run(elements, reach, bases=bases)

    assert _groups(services) == [["CategoryEndpoint", "OrderEndpoint", "UserEndpoint", "cart.jsp", "index.jsp"]]
    assert services[0]["properties"]["interfaces"] == ["ai_store__rest", "ai_store__web"]


def test_a_pure_frontend_offers_no_service_of_its_own():
    elements = [_component("web", "Shop Frontend"), _interface("web", "web", ["index.html", "app.js"]), _component("api", "Shop API"), _interface("api", "rest", ["OrderResource"])]

    services, _, _ = _run(elements, {"OrderResource": []}, lines={("unit::web", "unit::api")}, deciding=set())

    assert [s["properties"]["sources"] for s in services] == [["unit::api"]]


def test_names_are_a_closed_set_and_one_candidate_needs_no_call():
    elements = [_component("loan", "Loan Service"), _interface("loan", "rest", ["routes.py"]), _data("loan", "Loan Data")]

    services, _, calls = _run(elements, {"routes.py": ["loan"]}, objects={"domain::loan": "Loan"})

    assert [s["name"] for s in services] == ["Loan Management"]  # the route file is a generic name; the template on the object remains
    assert calls == []

    elements = [_component("pm", "Policy Management"), _interface("pm", "rest", ["PolicyInformationHolder", "PolicyAdministrationController"]), _data("policy", "Policy Data")]
    services, _, calls = _run(
        elements, {"PolicyInformationHolder": ["policy"], "PolicyAdministrationController": ["policy"]}, objects={"domain::policy": "Policy"}, llm=lambda options: options[-1]
    )

    assert len(calls) == 1 and '"Policy"' in calls[0] and '"Policy Administration"' in calls[0]
    assert '- "Policy Management"' not in calls[0]  # the component's own name is no service name candidate
    assert services[0]["name"] == "Policy Administration"  # the choice, one of the candidates


def test_a_business_function_is_a_shared_business_domain_of_cooperating_components():
    elements = [
        _component("ss", "Self Service"),
        _interface("ss", "rest", ["QuoteRequestResource", "QuoteRequestHolder", "CustomerHolder", "CustomerResource"]),
        _component("pm", "Policy Management"),
        _interface("pm", "rest", ["QuoteProcessingResource", "QuoteConsumer"]),
        _component("core", "Customer Core"),
        _interface("core", "rest", ["CoreCustomerHolder", "CoreCustomerResource"]),
        _data("quote", "Quote Data"),
        _data("customer", "Customer Data"),
    ]
    reach = {
        "QuoteRequestResource": ["quote"],
        "QuoteRequestHolder": ["quote"],
        "CustomerHolder": ["customer"],
        "CustomerResource": ["customer"],
        "QuoteProcessingResource": ["quote"],
        "QuoteConsumer": ["quote"],
        "CoreCustomerHolder": ["customer"],
        "CoreCustomerResource": ["customer"],
    }
    objects = {"domain::quote": "Insurance Quote", "domain::customer": "Customer"}
    docs = {"README.md": "Insurance quote handling spans both backends."}

    services, functions, _ = _run(elements, reach, objects=objects, lines={("unit::ss", "unit::pm")}, documents=docs)

    [function] = functions  # Customer is shared by ss and core, but no line connects them
    assert function["element_type"] == "BusinessFunction" and function["properties"]["source"] == "domain::quote"
    quote_services = sorted(s["identifier"] for s in services if s["properties"]["objects"] == ["do_quote"])
    assert sorted(function["properties"]["services"]) == quote_services and len(quote_services) == 2
    assert function["properties"]["name_candidates"] == ["Insurance Quote Management", "Insurance Quote Handling"]


def _run2(elements, imports, *, files_of=None, type_names=None, domain_names=None, endpoints=None, objects=None, members_reach=None):
    """Like _run, with explicit imports, type names per file, domain entity names and endpoint types."""
    node_paths = {f"n::{m}": f"{m}.java" for e in elements for m in [x["name"] for x in (e["properties"].get("members") or [])]}
    for unit_members in (endpoints or {}).values():
        node_paths |= {node: f"{name}.java" for node, name in unit_members}
    scopes = UnitScopes(files={}, nodes={}, entity_files={k: frozenset(v) for k, v in (files_of or {}).items()}, entity_nodes={})
    return derive_unit_services(
        elements,
        node_paths,
        imports,
        CONFIG,
        "Choose.",
        lambda prompt, schema, **k: {"content": json.dumps({"name": schema["schema"]["properties"]["name"]["enum"][0]})},
        scopes=scopes,
        deciding=set((files_of or {}) | (domain_names or {})),
        business_objects=objects or {},
        bases={},
        lines=set(),
        documents={},
        type_names=type_names or {},
        domain_names=domain_names or {},
        endpoints=endpoints or {},
    )


def test_a_member_reaches_a_domain_over_two_import_hops_or_by_the_name_of_an_entity_it_uses():
    elements = [
        _component("loan", "Loan Service"),
        _interface("loan", "rest", ["routes"]),
        _data("loan", "Loan Data"),
        _component("shop", "Shop"),
        _interface("shop", "rest", ["CategoryEndpoint"]),
        _data("category", "Category Data"),
    ]
    imports = [("routes.java", "services.java"), ("services.java", "models.java"), ("CategoryEndpoint.java", "entities/Category.java")]

    services, _ = _run2(
        elements,
        imports,
        files_of={"domain::loan": {"models.java"}},
        type_names={"entities/Category.java": {"category"}},
        domain_names={"domain::category": {"category", "product"}},
        objects={"domain::loan": "Loan", "domain::category": "Category"},
    )

    assert sorted(tuple(s["properties"]["objects"]) for s in services) == [("do_category",), ("do_loan",)]


def test_endpoint_types_join_the_members_and_a_group_without_a_domain_joins_the_largest():
    elements = [_component("pm", "Policy Backend"), _interface("pm", "rest", ["PolicyHolder"]), _data("policy", "Policy Data"), _data("quote", "Quote Data")]
    endpoints = {
        "unit::pm": [
            ("n::QuoteResource", "QuoteResource"),
            ("n::QuoteConsumer", "QuoteConsumer"),
            ("n::PolicyRepository", "PolicyRepository"),
            ("n::RiskService", "RiskService"),
            ("n::StatusResource", "StatusResource"),
        ]
    }
    files_of = {"domain::policy": {"PolicyHolder.java", "PolicyRepository.java"}, "domain::quote": {"QuoteResource.java", "QuoteConsumer.java"}}

    services, _ = _run2(elements, [], files_of=files_of, endpoints=endpoints)

    groups = sorted(sorted(m["name"] for m in s["properties"]["members"]) for s in services)
    # Risk and Status reach no domain: they join the largest group instead of forming a service of their own
    assert len(groups) == 2 and ["QuoteConsumer", "QuoteResource"] in groups
    assert all(s["properties"]["interfaces"] == ["ai_pm__rest"] for s in services)


def test_a_code_identifier_is_no_name_candidate():
    from deriva.modules.derivation.component_services import clean_member_name

    assert clean_member_name("CBPAUP0J", CONFIG.kind_words, CONFIG.generic_names) is None
    assert clean_member_name("COACTUPC.cbl", CONFIG.kind_words, CONFIG.generic_names) is None
    assert clean_member_name("PolicyInformationHolder", CONFIG.kind_words, CONFIG.generic_names) == "Policy"


def test_templates_cover_every_business_domain_reached_by_weight_and_the_component_stem_is_the_fallback():
    elements = [
        _component("loan", "Loan Service"),
        _interface("loan", "rest", ["routes"]),
        _data("loan", "Loan Data"),
        _data("eligibility", "Eligibility Result Data"),
        _component("audit", "Audit Service"),
        _interface("audit", "rest", ["app/routes.py"]),
    ]
    files_of = {"domain::loan": {"routes.java", "models.java"}, "domain::eligibility": {"models.java"}}
    domain_names = {"domain::loan": {"loan", "loanapplication", "loanproduct"}, "domain::eligibility": {"eligibilityresult"}}

    services, _ = _run2(
        elements,
        [("routes.java", "models.java")],
        files_of=files_of,
        domain_names=domain_names,
        objects={"domain::loan": "Loan", "domain::eligibility": "Eligibility Result"},
    )

    by_component = {s["properties"]["sources"][0]: s["properties"]["name_candidates"] for s in services}
    assert by_component["unit::loan"] == ["Loan Management", "Eligibility Result Management"]  # the domain reached most comes first
    assert by_component["unit::audit"] == ["Audit Management"]  # no name from the members: the template on the component's stem


def test_a_function_never_takes_a_services_name():
    elements = [
        _component("ss", "Self Service"),
        _interface("ss", "rest", ["ss/routes.py"]),
        _component("pm", "Policy Backend"),
        _interface("pm", "rest", ["pm/routes.py"]),
        _data("quote", "Quote Data"),
    ]
    reach = {"ss/routes.py": ["quote"], "pm/routes.py": ["quote"]}  # both services fall back to the template "Quote Management"

    services, functions, _ = _run(elements, reach, objects={"domain::quote": "Quote"}, lines={("unit::ss", "unit::pm")})

    service_names = {s["name"] for s in services}
    assert functions and not ({f["name"] for f in functions} & service_names)
    assert "Quote Management" in service_names and functions[0]["name"] == "Quote Handling"
