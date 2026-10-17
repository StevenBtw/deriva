"""Call resolution: a call goes to the caller's own file first, then only to a method of a language the
caller may call, in a file it imports, else in its own scope (never by name alone across languages or scopes)."""

from __future__ import annotations

from deriva.adapters.treesitter.models import ExtractedCall
from deriva.modules.extraction.base import generate_method_node_id
from deriva.modules.extraction.edges import _extract_call_edges


def _call(callee, caller="main", caller_class=None, qualifier=None):
    return ExtractedCall(callee_name=callee, callee_qualifier=qualifier, caller_name=caller, caller_class=caller_class, is_method_call=qualifier is not None, line=1)


def _candidate(path, name, class_name=None):
    return {"node_id": generate_method_node_id("r", path, name, class_name), "file_path": path, "class_name": class_name}


def _targets(edges):
    return [e["to_node_id"] for e in edges]


def test_an_overload_in_the_callers_own_class_wins_over_a_function_of_another_language():
    # RiskComputationService.java calls its own private computeRiskFactor; a JS function has the same name
    java = "backend/RiskComputationService.java"
    lookup = {
        "computeRiskFactor": [
            {"class_name": "RiskComputationService", "line_start": 10, "line_end": 20},
            {"class_name": "RiskComputationService", "line_start": 30, "line_end": 40},
        ],
        "handle": [{"class_name": "RiskComputationService", "line_start": 1, "line_end": 9}],
    }
    global_lookup = {("computeRiskFactor", None): [_candidate("frontend/src/api.js", "computeRiskFactor")]}

    edges, _ = _extract_call_edges(
        calls=[_call("computeRiskFactor", caller="handle", caller_class="RiskComputationService")],
        method_lookup=lookup,
        file_path=java,
        repo_name="r",
        global_method_lookup=global_lookup,
    )

    assert _targets(edges) == [generate_method_node_id("r", java, "computeRiskFactor", "RiskComputationService")]


def test_a_call_never_resolves_into_a_language_the_caller_cannot_call():
    lookup = {"handle": [{"class_name": None, "line_start": 1, "line_end": 9}]}
    global_lookup = {("computeRiskFactor", None): [_candidate("frontend/src/api.js", "computeRiskFactor")]}

    edges, stats = _extract_call_edges(
        calls=[_call("computeRiskFactor", caller="handle")], method_lookup=lookup, file_path="backend/Risk.java", repo_name="r", global_method_lookup=global_lookup
    )

    assert edges == [] and stats["unresolved"] == 1


def test_an_imported_file_wins_over_other_files_with_the_same_function():
    lookup = {"main": [{"class_name": None, "line_start": 1, "line_end": 9}]}
    global_lookup = {("helper", None): [_candidate("a/helper.py", "helper"), _candidate("b/helper.py", "helper")]}

    edges, _ = _extract_call_edges(
        calls=[_call("helper")], method_lookup=lookup, file_path="main.py", repo_name="r", global_method_lookup=global_lookup, imported_files={"b/helper.py"}
    )

    assert _targets(edges) == [generate_method_node_id("r", "b/helper.py", "helper")]


def test_without_an_import_a_call_stays_in_the_callers_scope():
    # The checkStatus case: one frontend's helper is not parsed, another frontend defines the same name
    lookup = {"getJson": [{"class_name": None, "line_start": 1, "line_end": 9}]}
    global_lookup = {("checkStatus", None): [_candidate("policy-frontend/src/api.js", "checkStatus")]}
    scope = lambda path: path.split("/", 1)[0]  # noqa: E731 - the test's scopes: the top folder

    edges, stats = _extract_call_edges(
        calls=[_call("checkStatus", caller="getJson")],
        method_lookup=lookup,
        file_path="self-service-frontend/src/api/helpers.js",
        repo_name="r",
        global_method_lookup=global_lookup,
        scope_of=scope,
    )
    assert edges == [] and stats["unresolved"] == 1

    global_lookup[("checkStatus", None)].append(_candidate("self-service-frontend/src/api/status.js", "checkStatus"))
    edges, _ = _extract_call_edges(
        calls=[_call("checkStatus", caller="getJson")],
        method_lookup=lookup,
        file_path="self-service-frontend/src/api/helpers.js",
        repo_name="r",
        global_method_lookup=global_lookup,
        scope_of=scope,
    )
    assert _targets(edges) == [generate_method_node_id("r", "self-service-frontend/src/api/status.js", "checkStatus")]


def test_a_language_group_lets_a_job_step_run_a_program():
    lookup = {"STEP01": [{"class_name": None, "line_start": 1, "line_end": 9}]}
    global_lookup = {("CBACT01C", None): [_candidate("app/cbl/CBACT01C.cbl", "CBACT01C")]}

    edges, _ = _extract_call_edges(
        calls=[_call("CBACT01C", caller="STEP01")],
        method_lookup=lookup,
        file_path="app/jcl/READACCT.jcl",
        repo_name="r",
        global_method_lookup=global_lookup,
        call_languages={"jcl": frozenset({"jcl", "cobol"})},
    )

    assert _targets(edges) == [generate_method_node_id("r", "app/cbl/CBACT01C.cbl", "CBACT01C")]


def test_a_program_call_crosses_folders_within_the_module_root_but_not_into_another_module():
    lookup = {"MAIN": [{"class_name": None, "line_start": 1, "line_end": 9}]}
    global_lookup = {("COACTUPC", None): [_candidate("app/app-x/cbl/COACTUPC.cbl", "COACTUPC")]}
    roots = {"app/cbl/COMEN01C.cbl": "", "app/app-x/cbl/COACTUPC.cbl": ""}  # no manifest: the repository root

    edges, _ = _extract_call_edges(
        calls=[_call("COACTUPC", caller="MAIN")], method_lookup=lookup, file_path="app/cbl/COMEN01C.cbl", repo_name="r", global_method_lookup=global_lookup, scope_of=roots.get
    )
    assert _targets(edges) == [generate_method_node_id("r", "app/app-x/cbl/COACTUPC.cbl", "COACTUPC")]

    roots = {"svc-a/main.py": "svc-a", "svc-b/util.py": "svc-b"}
    global_lookup = {("helper", None): [_candidate("svc-b/util.py", "helper")]}
    edges, _ = _extract_call_edges(
        calls=[_call("helper", caller="MAIN")], method_lookup=lookup, file_path="svc-a/main.py", repo_name="r", global_method_lookup=global_lookup, scope_of=roots.get
    )
    assert edges == []
