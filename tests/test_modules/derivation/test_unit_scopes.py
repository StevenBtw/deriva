"""Relationships lifted to deployable units: an element whose source is a unit owns what the unit includes."""

from __future__ import annotations

from deriva.modules.derivation.base import (
    ConfigurationRule,
    ContainmentRule,
    DependencyRule,
    GraphLinkRule,
    NamedInCodeRule,
    UnitScopes,
    derive_configuration_relationships,
    derive_containment_relationships,
    derive_dependency_relationships,
    derive_graph_link_relationships,
    derive_named_in_code_relationships,
    unit_owners,
)

# Two units in one folder (two project scripts) and a mainframe-style unit that includes program nodes
SCOPES = UnitScopes(
    files={
        "unit::r::r::cli": frozenset({"r/pkg/cli.py", "r/pkg/core/orders.py"}),
        "unit::r::r::app": frozenset({"r/pkg/app.py", "r/pkg/core/orders.py", "r/pkg/core/ledger.py"}),
        "unit::r::batch": frozenset({"r/cbl/BAT1.cbl"}),
    },
    nodes={"unit::r::batch": frozenset({"typedef::r::BAT1"})},
)
PATHS = {
    "unit::r::r::cli": "r",
    "unit::r::r::app": "r",
    "unit::r::batch": "r/cbl",
    "typedef::r::pkg/core/orders.py::Order": "r/pkg/core/orders.py",
    "typedef::r::pkg/core/ledger.py::Ledger": "r/pkg/core/ledger.py",
    "file::r::pkg_cli.py": "r/pkg/cli.py",
    "typedef::r::REC": "r/cpy/REC.cpy",
}


def _el(identifier: str, element_type: str, source: str, name: str = "") -> dict:
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": {"source": source}}


CLI = _el("ac_cli", "ApplicationComponent", "unit::r::r::cli", "Cli")
APP = _el("ac_app", "ApplicationComponent", "unit::r::r::app", "App")
BATCH = _el("ac_batch", "ApplicationComponent", "unit::r::batch", "Batch")
COMPONENTS = [CLI, APP, BATCH]


def _triples(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


def test_the_owner_of_a_unit_sourced_element_is_the_component_of_that_unit_then_the_units_that_include_it():
    owners = [("unit::r::r::cli", "ac_cli"), ("unit::r::r::app", "ac_app"), ("unit::r::batch", "ac_batch")]

    assert unit_owners(owners, SCOPES, "unit::r::r::cli", "r") == ["ac_cli"]
    assert unit_owners(owners, SCOPES, "typedef::r::x", "r/pkg/core/orders.py") == ["ac_app", "ac_cli"]
    assert unit_owners(owners, SCOPES, "typedef::r::BAT1", None) == ["ac_batch"]
    assert unit_owners(owners, SCOPES, "typedef::r::y", "r/elsewhere.py") == []


def test_containment_composes_a_units_interface_into_its_component_and_one_owner_per_data_object():
    interface = _el("ai_cli", "ApplicationInterface", "unit::r::r::cli", "Cli CLI")
    order = _el("do_order", "DataObject", "typedef::r::pkg/core/orders.py::Order")
    ledger = _el("do_ledger", "DataObject", "typedef::r::pkg/core/ledger.py::Ledger")
    rules = [
        ContainmentRule(container="ApplicationComponent", contained="ApplicationInterface", relationship="Composition"),
        ContainmentRule(container="ApplicationComponent", contained="DataObject", relationship="Access"),
    ]

    triples = _triples(derive_containment_relationships([*COMPONENTS, interface, order, ledger], PATHS, rules, scopes=SCOPES))

    assert ("ac_cli", "Composition", "ai_cli") in triples and ("ac_app", "Composition", "ai_cli") not in triples
    # A shared file has one owner (the smaller unit); a file of one unit belongs to it
    assert ("ac_cli", "Access", "do_order") in triples and ("ac_app", "Access", "do_ledger") in triples
    assert len([t for t in triples if t[2] == "do_order"]) == 1


def test_named_in_code_counts_the_code_names_in_a_units_files():
    order = _el("bo_order", "BusinessObject", "concept::r::order", "Order")
    names = [("OrderService", "r/pkg/core/orders.py"), ("OrderStore", "r/pkg/core/orders.py"), ("OrderLine", "r/pkg/core/orders.py")]

    triples = _triples(
        derive_named_in_code_relationships([*COMPONENTS, order], PATHS, names, [NamedInCodeRule("ApplicationComponent", "BusinessObject", "Access", min_names=3)], scopes=SCOPES)
    )

    assert triples == {("ac_app", "Access", "bo_order"), ("ac_cli", "Access", "bo_order")}


def test_dependencies_and_configuration_are_drawn_between_units():
    scopes = UnitScopes(files={"unit::r::a": frozenset({"r/a/x.py"}), "unit::r::b": frozenset({"r/b/y.py", "r/b/Dockerfile"})}, nodes={})
    a, b = _el("ac_a", "ApplicationComponent", "unit::r::a"), _el("ac_b", "ApplicationComponent", "unit::r::b")
    tech = {"identifier": "ts_db", "name": "Db", "element_type": "TechnologyService", "properties": {"source": "tech::r::db", "sources": ["tech::r::db"]}}
    paths = {"unit::r::a": "r/a", "unit::r::b": "r/b"}

    deps = derive_dependency_relationships([a, b], paths, [("r/a/x.py", "r/b/y.py")], [DependencyRule("ApplicationComponent", "ApplicationComponent", "Serving")], scopes=scopes)
    conf = derive_configuration_relationships(
        [a, b, tech], paths, {"r/b/Dockerfile": {"tech::r::db"}}, [ConfigurationRule("TechnologyService", "ApplicationComponent", "Serving")], scopes=scopes
    )

    assert _triples(deps) == {("ac_b", "Serving", "ac_a")}
    assert _triples(conf) == {("ts_db", "Serving", "ac_b")}


def test_a_graph_link_from_a_member_node_is_lifted_to_its_unit():
    record = _el("do_rec", "DataObject", "typedef::r::REC", "Record")
    rule = GraphLinkRule(source="ApplicationComponent", target="DataObject", relationship="Access", query="Q")

    triples = _triples(derive_graph_link_relationships([*COMPONENTS, record], [rule], {"Q": [("typedef::r::BAT1", "typedef::r::REC")]}, scopes=SCOPES))

    assert triples == {("ac_batch", "Access", "do_rec")}


def test_without_unit_sourced_owners_the_rules_work_by_path_as_before():
    component = _el("ac_shop", "ApplicationComponent", "dir::r::shop")
    order = _el("do_order", "DataObject", "typedef::r::shop/Order.java::Order")
    paths = {"dir::r::shop": "r/shop", "typedef::r::shop/Order.java::Order": "r/shop/Order.java"}
    rule = ContainmentRule(container="ApplicationComponent", contained="DataObject", relationship="Access")

    assert _triples(derive_containment_relationships([component, order], paths, [rule], scopes=SCOPES)) == {("ac_shop", "Access", "do_order")}


def test_a_unit_inside_another_units_folder_is_not_its_part():
    """A mainframe module lies in the core application's folder, but it is a deployable unit of its own."""
    scopes = UnitScopes(files={"unit::r::app::online": frozenset({"r/app/cbl/A.cbl"}), "unit::r::app_mod": frozenset({"r/app/mod/cbl/B.cbl"})}, nodes={})
    core = _el("ac_core", "ApplicationComponent", "unit::r::app::online")
    module = _el("ac_mod", "ApplicationComponent", "unit::r::app_mod")
    rule = ContainmentRule(container="ApplicationComponent", contained="ApplicationComponent", relationship="Composition")

    assert derive_containment_relationships([core, module], {"unit::r::app::online": "r/app", "unit::r::app_mod": "r/app/mod"}, [rule], scopes=scopes) == []


def test_without_the_interface_service_name_rule_the_listed_assignment_stays():
    """The consolidated pass skips the configured name-match pairs; the service's interface list still assigns."""
    from unittest.mock import MagicMock

    from deriva.modules.derivation.base import ListedMembersRule, RelationshipRule, derive_consolidated_relationships

    elements = [
        {
            "identifier": "ai_pay",
            "name": "Payment REST API",
            "element_type": "ApplicationInterface",
            "properties": {"source": "unit::r::pay", "structure_name": "Payment REST API"},
        },
        {
            "identifier": "as_pay",
            "name": "Payment Handling",
            "element_type": "ApplicationService",
            "properties": {"source": "typedef::r::a", "structure_name": "PaymentRest", "interfaces": ["ai_pay"]},
        },
    ]
    rules = {"ApplicationService": ([], [RelationshipRule(target_type="ApplicationInterface", rel_type="Serving")])}
    listed = [ListedMembersRule(holder="ApplicationService", list_property="interfaces", member="ApplicationInterface", relationship="Assignment", by="identifier")]

    result = derive_consolidated_relationships(elements, rules, MagicMock(), listed_members=listed, name_match_skip={("ApplicationInterface", "ApplicationService")})

    assert [(r["source"], r["relationship_type"], r["target"]) for r in result] == [("ai_pay", "Assignment", "as_pay")]


# A data entity merges the same concept's types across units: its element relates through all of them
ENTITY_SCOPES = UnitScopes(
    files=dict(SCOPES.files),
    nodes=dict(SCOPES.nodes),
    entity_files={"entity::r::order": frozenset({"r/pkg/core/orders.py", "r/cbl/BAT1.cbl"})},
    entity_nodes={"entity::r::order": frozenset({"typedef::r::pkg/core/orders.py::Order", "typedef::r::REC"})},
)


def test_a_data_entity_is_accessed_by_every_unit_that_holds_one_of_its_types():
    order = _el("do_order", "DataObject", "entity::r::order", "Order")

    result = derive_containment_relationships(
        [*COMPONENTS, order], PATHS, [ContainmentRule(container="ApplicationComponent", contained="DataObject", relationship="Access")], scopes=ENTITY_SCOPES
    )

    assert _triples(result) == {("ac_cli", "Access", "do_order"), ("ac_app", "Access", "do_order"), ("ac_batch", "Access", "do_order")}


def test_a_graph_link_to_one_of_an_entities_types_reaches_the_entities_element():
    order = _el("do_order", "DataObject", "entity::r::order", "Order")
    rule = GraphLinkRule(source="ApplicationComponent", target="DataObject", relationship="Access", query="Q")

    result = derive_graph_link_relationships([*COMPONENTS, order], [rule], {"Q": [("typedef::r::BAT1", "typedef::r::REC")]}, scopes=ENTITY_SCOPES)

    assert _triples(result) == {("ac_batch", "Access", "do_order")}
