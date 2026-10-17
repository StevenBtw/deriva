"""Abstraction levels from structure: the component hierarchy (system, module, unit by folder), the level of every
element (components by their place, other types by the versioned table), roll-up links and relationship levels."""

from __future__ import annotations

from deriva.modules.derivation.levels import Component, LevelRules, ancestors, assign_levels, component_parents, interface_owners, relationship_levels, rollups, service_lifts

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


def test_the_one_unit_at_a_module_folder_holds_the_module():
    """A unit and a build module share a folder (the module has modules inside): system, units, modules, libraries."""
    components = [_c("unit", "unit", "r/gui"), _c("mod", "module", "r/gui"), _c("src", "module", "r/gui/src")]
    elements = [{"identifier": c.identifier, "type": "ApplicationComponent"} for c in components]

    parents = component_parents(components)
    levels = assign_levels(elements, components, RULES)

    assert parents == {"unit": None, "mod": "unit", "src": "mod"}
    assert levels == {"unit": frozenset({"enterprise", "solution"}), "mod": frozenset({"solution"}), "src": frozenset({"solution"})}


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


def test_an_interface_moves_to_the_one_built_module_that_holds_all_its_member_files():
    # The unit builds the root system and a frontend module: the web interface lies in the frontend, the commands in the root
    builds = {"unit": ["sys", "web"], "solo": ["solo-module"]}
    kinds = {"unit": "unit", "sys": "system", "web": "module", "solo": "unit", "solo-module": "module"}
    own_files = {"sys": frozenset({"r/cli.py"}), "web": frozenset({"r/web/index.html", "r/web/app.js"}), "solo-module": frozenset({"s/index.html"})}
    interfaces = {
        "ai-web": ("unit", frozenset({"r/web/index.html"})),
        "ai-cli": ("unit", frozenset({"r/cli.py"})),  # in the system: a system is no solution component, the unit keeps it
        "ai-both": ("unit", frozenset({"r/cli.py", "r/web/app.js"})),  # in two modules: the unit keeps it
        "ai-none": ("unit", frozenset()),
        "ai-solo": ("solo", frozenset({"s/index.html"})),  # its unit builds one module only: nothing moves
    }

    assert interface_owners(interfaces, builds, kinds, own_files) == {"ai-web": "web"}


def test_the_units_at_a_folder_are_counted_from_structure_not_from_the_components():
    """Three units share the module's folder but one became a component: the module still holds it."""
    components = [_c("unit", "unit", "r/pkg"), _c("mod", "module", "r/pkg")]

    assert component_parents(components, units_at={"r/pkg": 3}) == {"unit": "mod", "mod": None}
    assert component_parents(components) == {"unit": None, "mod": "unit"}


def test_the_ancestors_of_a_component_follow_its_parents():
    parents = {"sys": None, "mod": "sys", "unit": "mod"}

    assert ancestors("unit", parents) == ["mod", "sys"] and ancestors("sys", parents) == []


def test_a_module_that_one_unit_builds_is_held_by_that_unit_not_by_the_system():
    """The root unit builds a frontend module in a subfolder: system, units, modules. A module nested in a module keeps it."""
    components = [_c("sys", "system", "r"), _c("cli", "unit", "r"), _c("web", "module", "r/web"), _c("lib", "module", "r/lib"), _c("part", "module", "r/web/part")]
    built_by = {"web": ["cli"], "part": ["cli"]}

    assert component_parents(components, built_by=built_by) == {"sys": None, "cli": "sys", "web": "cli", "lib": "sys", "part": "web"}


def test_a_role_can_place_an_element_type_on_its_own_levels():
    """The platform node stays enterprise; a service node (role service) is solution."""
    rules = LevelRules(types={"Node": ("enterprise",)}, roles={"Node": {"service": ("solution",)}})
    elements = [{"identifier": "env", "type": "Node", "role": "environment"}, {"identifier": "svc", "type": "Node", "role": "service"}, {"identifier": "x", "type": "Node"}]

    assert assign_levels(elements, [], rules) == {"env": frozenset({"enterprise"}), "svc": frozenset({"solution"}), "x": frozenset({"enterprise"})}
