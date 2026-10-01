"""Relationships from containment: the nearest enclosing component owns what lies in its directory."""

from __future__ import annotations

from typing import Any

import pytest

from deriva.modules.derivation.base import ContainmentRule, RelationshipRule, derive_consolidated_relationships, derive_containment_relationships, element_source_paths

RULES = [
    ContainmentRule(container="ApplicationComponent", contained="ApplicationComponent", relationship="Composition"),
    ContainmentRule(container="ApplicationComponent", contained="ApplicationInterface", relationship="Composition"),
    ContainmentRule(container="ApplicationComponent", contained="ApplicationService", relationship="Realization"),
    ContainmentRule(container="ApplicationComponent", contained="DataObject", relationship="Access"),
]


def _el(identifier: str, element_type: str, source: str, name: str = "") -> dict[str, Any]:
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": {"source": source}}


CORE = _el("ac_core", "ApplicationComponent", "dir::r::core")
CRUD = _el("ac_crud", "ApplicationComponent", "dir::r::core_crud")
CORE_API = _el("ac_core_api", "ApplicationComponent", "dir::r::core-api")
FIND = _el("ai_find", "ApplicationInterface", "file::r::core/crud/rest/Find.java")
ORDERS = _el("as_orders", "ApplicationService", "typedef::r::core/OrderService.java::OrderService")
ORDER_DATA = _el("do_order", "DataObject", "typedef::r::core/crud/model/Order.java::Order")
LOOSE = _el("ai_loose", "ApplicationInterface", "file::r::tools/Cli.java")
CONCEPT_SERVICE = _el("as_billing", "ApplicationService", "concept::r::billing")

PATHS = {
    "dir::r::core": "r/core",
    "dir::r::core_crud": "r/core/crud",
    "dir::r::core-api": "r/core-api",
    "file::r::core/crud/rest/Find.java": "r/core/crud/rest/Find.java",
    "typedef::r::core/OrderService.java::OrderService": "r/core/OrderService.java",
    "typedef::r::core/crud/model/Order.java::Order": "r/core/crud/model/Order.java",
    "file::r::tools/Cli.java": "r/tools/Cli.java",
}


def _pairs(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestContainment:
    def test_the_nearest_enclosing_component_owns_each_element(self):
        relationships = derive_containment_relationships([CORE, CRUD, CORE_API, FIND, ORDERS, ORDER_DATA], PATHS, RULES)

        assert _pairs(relationships) == {
            ("ac_core", "Composition", "ac_crud"),
            ("ac_crud", "Composition", "ai_find"),
            ("ac_core", "Realization", "as_orders"),
            ("ac_crud", "Access", "do_order"),
        }

    def test_composition_is_exclusive(self):
        relationships = derive_containment_relationships([CORE, CRUD, FIND], PATHS, RULES)

        wholes = [r["source"] for r in relationships if r["target"] == "ai_find"]
        assert wholes == ["ac_crud"]

    def test_a_sibling_with_a_longer_name_is_no_container(self):
        # r/core-api starts with r/core, but is not inside it
        relationships = derive_containment_relationships([CORE, CORE_API], PATHS, RULES)

        assert relationships == []

    def test_elements_outside_every_component_or_without_a_path_stay_unlinked(self):
        relationships = derive_containment_relationships([CORE, LOOSE, CONCEPT_SERVICE], PATHS, RULES)

        assert relationships == []

    def test_relationships_record_their_origin(self):
        (relationship,) = derive_containment_relationships([CRUD, FIND], PATHS, RULES)

        assert relationship["derived_from"] == "containment"

    def test_without_rules_nothing_is_derived(self):
        assert derive_containment_relationships([CORE, CRUD, FIND], PATHS, []) == []


class TestSourcePaths:
    """Directories carry a path, files, types and methods a file path, on a real graph."""

    @pytest.fixture
    def graph(self):
        from deriva.adapters.grafeo.manager import close_database
        from deriva.adapters.graph import GraphManager

        close_database()
        with GraphManager() as gm:
            yield gm
        close_database()

    def test_paths_of_directory_file_and_type_sources(self, graph):
        from deriva.adapters.graph.models import DirectoryNode, FileNode, TypeDefinitionNode

        graph.add_node(DirectoryNode(name="core", path="r/core", repository_name="r"), node_id="dir::r::core")
        graph.add_node(FileNode(name="Find.java", path="r/core/Find.java", repository_name="r", file_type="source"), node_id="file::r::core/Find.java")
        graph.add_node(TypeDefinitionNode(name="Order", type_category="class", file_path="r/core/Order.java", repository_name="r"), node_id="typedef::r::core/Order.java::Order")
        elements = [
            _el("ac_core", "ApplicationComponent", "dir::r::core"),
            _el("ai_find", "ApplicationInterface", "file::r::core/Find.java"),
            _el("do_order", "DataObject", "typedef::r::core/Order.java::Order"),
            _el("as_billing", "ApplicationService", "concept::r::billing"),
        ]

        paths = element_source_paths(graph, elements)

        assert paths == {"dir::r::core": "r/core", "file::r::core/Find.java": "r/core/Find.java", "typedef::r::core/Order.java::Order": "r/core/Order.java"}


class FakeGraph:
    """Answers the source-path query; every other query finds nothing."""

    def __init__(self, paths: dict[str, str]):
        self.paths = paths

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "file_path" in cypher:
            ids = set((params or {}).get("ids", []))
            return [{"id": i, "path": p, "file_path": None} for i, p in self.paths.items() if i in ids]
        return []


class TestConsolidatedPass:
    def test_containment_decides_its_type_pairs_and_name_overlap_does_not(self):
        # "Crud" in both names would make a name-overlap composition from the outer component
        crud = _el("ac_crud", "ApplicationComponent", "dir::r::core_crud", name="Crud")
        crud_tools = _el("ac_crud_tools", "ApplicationComponent", "dir::r::crud-tools", name="Crud Tools")
        find = _el("ai_find", "ApplicationInterface", "file::r::core/crud/rest/Find.java", name="Crud Find HTTP API")
        rules = {
            "ApplicationComponent": ([RelationshipRule(target_type="ApplicationInterface", rel_type="Composition", description="")], []),
            "ApplicationInterface": ([], [RelationshipRule(target_type="ApplicationComponent", rel_type="Composition", description="")]),
        }
        paths = {"dir::r::core_crud": "r/core/crud", "dir::r::crud-tools": "r/crud-tools", "file::r::core/crud/rest/Find.java": "r/core/crud/rest/Find.java"}

        relationships = derive_consolidated_relationships(
            all_elements=[crud, crud_tools, find], relationship_rules=rules, llm_query_fn=None, graph_manager=FakeGraph(paths), containment=RULES
        )

        assert _pairs(relationships) == {("ac_crud", "Composition", "ai_find")}

    def test_an_element_that_containment_cannot_place_stays_open_to_the_other_tiers(self):
        # A service from a concept has no source path: structure cannot decide its owner
        core = _el("ac_data", "ApplicationComponent", "dir::r::data", name="Data Management Core")
        service = _el("as_data", "ApplicationService", "concept::r::data_management", name="Data Management")
        rules = {"ApplicationComponent": ([RelationshipRule(target_type="ApplicationService", rel_type="Realization")], [])}

        relationships = derive_consolidated_relationships(
            all_elements=[core, service], relationship_rules=rules, llm_query_fn=None, graph_manager=FakeGraph({"dir::r::data": "r/data"}), containment=RULES
        )

        assert ("ac_data", "Realization", "as_data") in _pairs(relationships)

    def test_an_unplaced_element_gets_only_the_ownership_type_containment_uses(self):
        # Assignment and Realization would both match; containment relates component and service by Realization
        core = _el("ac_data", "ApplicationComponent", "dir::r::data", name="Data Management Core")
        service = _el("as_data", "ApplicationService", "concept::r::data_management", name="Data Management")
        rules = {
            "ApplicationComponent": (
                [RelationshipRule(target_type="ApplicationService", rel_type="Assignment"), RelationshipRule(target_type="ApplicationService", rel_type="Realization")],
                [],
            )
        }

        relationships = derive_consolidated_relationships(
            all_elements=[core, service], relationship_rules=rules, llm_query_fn=None, graph_manager=FakeGraph({"dir::r::data": "r/data"}), containment=RULES
        )

        assert {p for p in _pairs(relationships) if p[0] == "ac_data"} == {("ac_data", "Realization", "as_data")}

    def test_without_containment_the_open_tiers_keep_working(self):
        crud_tools = _el("ac_crud_tools", "ApplicationComponent", "dir::r::crud-tools", name="Crud Tools")
        find = _el("ai_find", "ApplicationInterface", "file::r::core/crud/rest/Find.java", name="Crud Find HTTP API")
        rules = {"ApplicationComponent": ([RelationshipRule(target_type="ApplicationInterface", rel_type="Composition", description="")], [])}

        relationships = derive_consolidated_relationships(all_elements=[crud_tools, find], relationship_rules=rules, llm_query_fn=None, graph_manager=None)

        assert ("ac_crud_tools", "Composition", "ai_find") in _pairs(relationships)


class TestLlmProposals:
    def test_a_proposal_must_match_an_open_rule_for_its_type_pair(self):
        """The LLM may not relate a type pair that containment decides, even with a relationship type other rules allow."""
        import json
        from types import SimpleNamespace

        from deriva.modules.derivation.base import RelationshipLLMConfig

        class Connected(FakeGraph):
            def query(self, cypher, params=None):
                if "*1.." in cypher:
                    return [{"id": "dir::r::core"}, {"id": "file::r::core/Api.java"}, {"id": "typedef::r::core/Orders.java::Orders"}]
                return super().query(cypher, params)

        core = _el("ac_core", "ApplicationComponent", "dir::r::core", name="Core")
        api = _el("ai_api", "ApplicationInterface", "file::r::core/Api.java", name="Api")
        orders = _el("as_orders", "ApplicationService", "typedef::r::core/Orders.java::Orders", name="Orders")
        rules = {
            "ApplicationInterface": (
                [RelationshipRule(target_type="ApplicationComponent", rel_type="Serving"), RelationshipRule(target_type="ApplicationService", rel_type="Serving")],
                [],
            )
        }
        proposals = [
            {"source": "ai_api", "target": "ac_core", "relationship_type": "Serving", "confidence": 0.9},
            {"source": "ai_api", "target": "as_orders", "relationship_type": "Serving", "confidence": 0.9},
        ]
        paths = {"dir::r::core": "r/core", "file::r::core/Api.java": "r/core/Api.java", "typedef::r::core/Orders.java::Orders": "r/core/Orders.java"}

        relationships = derive_consolidated_relationships(
            all_elements=[core, api, orders],
            relationship_rules=rules,
            llm_query_fn=lambda prompt, schema, **kw: SimpleNamespace(content=json.dumps({"relationships": proposals})),
            graph_manager=Connected(paths),
            llm_config=RelationshipLLMConfig(instruction="rules", min_confidence=0.5, persona="P"),
            containment=RULES,
        )

        assert ("ai_api", "Serving", "ac_core") not in _pairs(relationships)
        assert ("ai_api", "Serving", "as_orders") in _pairs(relationships)


class TestNoCoMentionAssignment:
    def test_an_actor_and_a_process_two_hops_apart_are_not_assigned(self):
        from deriva.modules.derivation.base import derive_neighbor_relationships

        class TwoHops:
            def query(self, cypher, params=None):
                # Both concepts are referenced by one document: two hops apart, no direct edge
                if "*1..2" in cypher:
                    return [{"id": "concept::r::approve_order"}]
                return []

        actor = _el("ba_clerk", "BusinessActor", "concept::r::clerk")
        process = _el("bp_approve", "BusinessProcess", "concept::r::approve_order")
        rules = [RelationshipRule(target_type="BusinessProcess", rel_type="Assignment", description="")]

        assert derive_neighbor_relationships([actor], [process], TwoHops(), rules, []) == []
