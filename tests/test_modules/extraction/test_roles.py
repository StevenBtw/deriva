"""Actors and roles from structure: role constants in authorization checks, and the persons the README of a
component with a Web UI names, each assigned to the lifecycles it works on."""

from __future__ import annotations

from deriva.modules.extraction.roles import RoleRules, detect_roles

RULES = RoleRules(
    markers=(r"require_role\(([^)]*)\)", r"hasRole\(([^)]*)\)", r"@RolesAllowed\(([^)]*)\)"),
    generic_roles=("admin", "user"),
    generic_actors=("user", "client", "server"),
)
UNITS = [
    {"id": "unit::lease", "path": "r/lease", "web": False},
    {"id": "unit::uw", "path": "r/uw", "web": False},
    {"id": "unit::web", "path": "r/web", "web": True},
]
LIFECYCLES = {"life::app": ["unit::lease", "unit::uw"], "life::kyc": ["unit::customer"]}  # lifecycle -> units that reach its states


def test_roles_in_authorization_checks_are_named_and_assigned_to_the_lifecycles_of_their_unit():
    files = {
        "r/lease/routes.py": '@router.post("/x", dependencies=[Depends(require_role("ADMIN", "LEASE_OFFICER"))])\ndef x(): ...',
        "r/uw/routes.py": 'require_role("ADMIN", "UPKEEPER")\nrequire_role(*STAFF)',
    }

    result = detect_roles(files, [], UNITS, LIFECYCLES, [], RULES)

    assert [(r.name, r.kind, r.lifecycles) for r in result] == [("Lease Officer", "role", ["life::app"]), ("Upkeeper", "role", ["life::app"])]


def test_a_person_the_readme_of_a_web_ui_component_names_is_an_actor_of_the_lifecycles_it_uses():
    concepts = [
        {"id": "c::customer", "name": "Customer", "files": ["r/web/README.md", "r/README.md"]},
        {"id": "c::employee", "name": "Employee", "files": ["r/README.md"]},  # no Web UI component's README
        {"id": "c::user", "name": "User", "files": ["r/web/README.md"]},  # a generic word
    ]
    consumes = [("unit::web", "unit::lease")]

    result = detect_roles({}, concepts, UNITS, LIFECYCLES, consumes, RULES)

    assert [(r.name, r.kind, r.lifecycles, r.source) for r in result] == [("Customer", "actor", ["life::app"], "c::customer")]
