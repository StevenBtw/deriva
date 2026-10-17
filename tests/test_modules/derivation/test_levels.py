"""Abstraction levels from structure: the component hierarchy (system, module, unit by folder), the level of every
element (components by their place, other types by the versioned table), roll-up links and relationship levels."""

from __future__ import annotations

from deriva.modules.derivation.levels import Component, LevelRules, assign_levels, component_parents, relationship_levels, rollups, service_lifts

RULES = LevelRules(
    types={
        "ApplicationInterface": ("solution",),
        "DataObject": ("solution",),
        "SystemSoftware": ("solution",),
        "ApplicationService": ("enterprise",),
        "BusinessObject": ("enterprise",),
        "Node": ("enterprise",),
    }
)


def _c(identifier: str, kind: str, folder: str) -> Component:
    return Component(identifier=identifier, kind=kind, folder=folder)


def test_the_nearest_holding_folder_is_the_parent_and_at_one_folder_the_system_holds_the_rest():
    components = [
        _c("sys", "system", "r"),
        _c("cli", "unit", "r"),  # the root unit, in the system's own folder
        _c("orders", "unit", "r/orders"),
        _c("lib", "module", "r/libs/pricing"),
        _c("plugin", "module", "r/libs/pricing/plugins/x"),
        _c("pkg", "module", "r/pkg"),
        _c("pkg-a", "unit", "r/pkg"),  # two entry points in one module folder: the module holds them
        _c("pkg-b", "unit", "r/pkg"),
    ]

    parents = component_parents(components)

    assert parents == {"sys": None, "cli": "sys", "orders": "sys", "lib": "sys", "plugin": "lib", "pkg": "sys", "pkg-a": "pkg", "pkg-b": "pkg"}


def test_a_top_level_unit_is_on_both_levels_a_top_level_system_on_enterprise_and_the_rest_on_solution():
    components = [_c("sys", "system", "r"), _c("orders", "unit", "r/orders"), _c("lib", "module", "r/lib"), _c("solo", "unit", "s")]
    elements = [
        {"identifier": "sys", "type": "ApplicationComponent"},
        {"identifier": "orders", "type": "ApplicationComponent"},
        {"identifier": "lib", "type": "ApplicationComponent"},
        {"identifier": "solo", "type": "ApplicationComponent"},
        {"identifier": "api", "type": "ApplicationInterface"},
        {"identifier": "svc", "type": "ApplicationService"},
        {"identifier": "proc", "type": "BusinessProcess"},  # not in the table: enterprise
    ]

    levels = assign_levels(elements, components, RULES)

    assert levels == {
        "sys": frozenset({"enterprise"}),
        "orders": frozenset({"solution"}),
        "lib": frozenset({"solution"}),
        "solo": frozenset({"enterprise", "solution"}),
        "api": frozenset({"solution"}),
        "svc": frozenset({"enterprise"}),
        "proc": frozenset({"enterprise"}),
    }


def test_roll_ups_join_parent_and_child_on_their_shared_levels_or_across_levels():
    components = [_c("sys", "system", "r"), _c("orders", "unit", "r/orders"), _c("plugin", "module", "r/orders/plugin")]
    levels = {"sys": frozenset({"enterprise"}), "orders": frozenset({"solution"}), "plugin": frozenset({"solution"})}

    assert rollups(components, levels) == [("orders", "plugin", frozenset({"solution"}), False), ("sys", "orders", frozenset(), True)]


def test_a_relationship_is_on_the_levels_both_ends_share_else_across_levels():
    both, solution, enterprise = frozenset({"enterprise", "solution"}), frozenset({"solution"}), frozenset({"enterprise"})

    assert relationship_levels(both, solution) == (frozenset({"solution"}), False)
    assert relationship_levels(both, both) == (both, False)
    assert relationship_levels(solution, enterprise) == (frozenset(), True)


def test_a_service_a_solution_unit_realizes_is_also_realized_by_its_top_level_component():
    components = [_c("sys", "system", "r"), _c("orders", "unit", "r/orders"), _c("solo", "unit", "s")]
    levels = {"sys": frozenset({"enterprise"}), "orders": frozenset({"solution"}), "solo": frozenset({"enterprise", "solution"})}
    realizations = [("orders", "svc-orders"), ("solo", "svc-solo")]

    # solo is on the enterprise level itself; orders is not: its system realizes the service there
    assert service_lifts(components, levels, realizations) == [("sys", "svc-orders")]
