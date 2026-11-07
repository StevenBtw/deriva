"""The shipped candidate queries of the experimental BusinessCollaboration and Path steps, run on a real in-memory
graph: what they return for the structures they read, the edge cases included."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deriva.adapters.grafeo.manager import close_database
from deriva.adapters.graph import GraphManager

SEED = Path(__file__).parents[3] / "deriva" / "adapters" / "database" / "data" / "derivation_config.json"


def _query(step: str) -> str:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("rows") or data.get("data") or []
    return next(r["input_graph_query"] for r in rows if r["step_name"] == step and r.get("is_active"))


@pytest.fixture
def graph():
    manager = GraphManager()
    manager.connect()
    try:
        yield manager
    finally:
        manager.disconnect()
        close_database()


def _node(graph, label: str, node_id: str, active: bool = True, **properties) -> None:
    assert graph.db is not None
    fields = ", ".join([f"id: '{node_id}'", f"active: {str(active).lower()}", *(f"{k}: '{v}'" for k, v in properties.items())])
    graph.db.execute(f"INSERT (:Graph:{label} {{{fields}}})")


def _ids(graph, step: str) -> list[str]:
    return sorted(row["id"] for row in graph.query(_query(step)))


class TestCollaborationCandidates:
    def test_a_lifecycle_two_roles_take_part_in_is_a_candidate_and_one_role_is_not(self, graph):
        _node(graph, "Lifecycle", "life::loan", entity="Loan")
        _node(graph, "Lifecycle", "life::bill", entity="Bill")
        for role in ("role::clerk", "role::officer", "role::payer"):
            _node(graph, "Role", role)
        graph.add_edge("role::clerk", "life::loan", "ASSIGNED")
        graph.add_edge("role::officer", "life::loan", "ASSIGNED")
        graph.add_edge("role::payer", "life::bill", "ASSIGNED")

        assert _ids(graph, "BusinessCollaboration") == ["life::loan"]

    def test_a_role_written_twice_is_one_participant(self, graph):
        _node(graph, "Lifecycle", "life::loan", entity="Loan")
        _node(graph, "Role", "role::clerk")
        graph.add_edge("role::clerk", "life::loan", "ASSIGNED")
        graph.add_edge("role::clerk", "life::loan", "ASSIGNED")  # a second run writes the same edge

        assert _ids(graph, "BusinessCollaboration") == []

    def test_a_role_an_earlier_run_left_inactive_is_no_participant(self, graph):
        _node(graph, "Lifecycle", "life::loan", entity="Loan")
        _node(graph, "Role", "role::clerk")
        _node(graph, "Role", "role::gone", active=False)
        graph.add_edge("role::clerk", "life::loan", "ASSIGNED")
        graph.add_edge("role::gone", "life::loan", "ASSIGNED")

        assert _ids(graph, "BusinessCollaboration") == []

    def test_an_inactive_lifecycle_is_no_candidate(self, graph):
        _node(graph, "Lifecycle", "life::loan", active=False, entity="Loan")
        for role in ("role::clerk", "role::officer"):
            _node(graph, "Role", role)
            graph.add_edge(role, "life::loan", "ASSIGNED")

        assert _ids(graph, "BusinessCollaboration") == []


class TestPathCandidates:
    def test_one_candidate_per_connection_between_two_active_units(self, graph):
        for unit in ("unit::web", "unit::api", "unit::db", "unit::old"):
            _node(graph, "DeployableUnit", unit, active=unit != "unit::old", name=unit.split("::")[1])
        graph.add_edge("unit::web", "unit::api", "CONSUMES")
        graph.add_edge("unit::api", "unit::db", "CONSUMES")
        graph.add_edge("unit::web", "unit::old", "CONSUMES")

        rows = {row["id"]: row["name"] for row in graph.query(_query("Path"))}
        assert rows == {"unit::web>unit::api": "web to api", "unit::api>unit::db": "api to db"}

    def test_a_connection_written_twice_is_one_candidate(self, graph):
        for unit in ("unit::web", "unit::api"):
            _node(graph, "DeployableUnit", unit, name=unit.split("::")[1])
        graph.add_edge("unit::web", "unit::api", "CONSUMES")
        graph.add_edge("unit::web", "unit::api", "CONSUMES")

        assert _ids(graph, "Path") == ["unit::web>unit::api"]

    def test_a_unit_that_consumes_itself_is_no_path(self, graph):
        _node(graph, "DeployableUnit", "unit::web", name="web")
        graph.add_edge("unit::web", "unit::web", "CONSUMES")

        assert _ids(graph, "Path") == []

    def test_two_units_that_consume_each_other_are_one_path_named_in_id_order(self, graph):
        for unit in ("unit::web", "unit::api"):
            _node(graph, "DeployableUnit", unit, name=unit.split("::")[1])
        graph.add_edge("unit::web", "unit::api", "CONSUMES")
        graph.add_edge("unit::api", "unit::web", "CONSUMES")

        rows = {row["id"]: row["name"] for row in graph.query(_query("Path"))}
        assert rows == {"unit::api>unit::web": "api to web"}

    def test_a_one_way_connection_keeps_its_direction_whatever_the_id_order(self, graph):
        for unit in ("unit::web", "unit::api"):
            _node(graph, "DeployableUnit", unit, name=unit.split("::")[1])
        graph.add_edge("unit::web", "unit::api", "CONSUMES")

        assert _ids(graph, "Path") == ["unit::web>unit::api"]

    def test_a_reverse_connection_from_an_inactive_unit_is_no_pair(self, graph):
        _node(graph, "DeployableUnit", "unit::web", name="web")
        _node(graph, "DeployableUnit", "unit::api", name="api")
        _node(graph, "DeployableUnit", "unit::old", active=False, name="old")
        graph.add_edge("unit::web", "unit::api", "CONSUMES")
        graph.add_edge("unit::old", "unit::web", "CONSUMES")

        assert _ids(graph, "Path") == ["unit::web>unit::api"]
