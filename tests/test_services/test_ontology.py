"""Ontology views: graph node and edge types with their producing and consuming steps; ArchiMate types and rules."""

from __future__ import annotations

from deriva.services.ontology import intermediate_ontology, output_ontology

DIRECTORY = {"_id": 1, "_labels": ["Graph", "Directory"], "id": "dir::r::src", "name": "src", "path": "src", "content": "x" * 500}
TECH = {"_id": 2, "_labels": ["Graph", "Technology"], "id": "tech::r::queue", "techName": "Queue"}


class FakeSession:
    def __init__(self):
        self.queries: list[str] = []

    def query_graph_read_only(self, cypher, params=None):
        self.queries.append(cypher)
        if "RETURN labels(n) AS labels" in cypher:
            return [{"labels": ["Graph", "Directory"]}, {"labels": ["Graph", "Directory"]}, {"labels": ["Graph", "Technology"]}]
        if "count(r) AS count" in cypher:
            return [{"type": "Graph:CONTAINS", "count": 4}]
        if "RETURN labels(a) AS source, labels(b) AS target" in cypher:
            return [{"source": ["Graph", "Directory"], "target": ["Graph", "Directory"]}, {"source": ["Graph", "Directory"], "target": ["Graph", "Technology"]}]
        if ":`Directory`" in cypher:
            return [{"n": DIRECTORY}]
        if ":`Technology`" in cypher:
            return [{"n": TECH}]
        return []

    def get_extraction_configs(self):
        return [
            {"node_type": "Directory", "enabled": True, "extraction_method": "structural"},
            {"node_type": "Technology", "enabled": True, "extraction_method": "llm"},
            {"node_type": "DirectoryClassification", "enabled": True, "extraction_method": "llm"},
        ]

    def get_derivation_configs(self):
        return [
            {"element_type": "Node", "enabled": True, "phase": "generate", "input_graph_query": "MATCH (t:Graph:Technology) RETURN t"},
            {"element_type": "ApplicationComponent", "enabled": False, "phase": "generate", "input_graph_query": "MATCH (d:`Graph:Directory`) RETURN d"},
            {"element_type": "pagerank", "enabled": True, "phase": "prep", "input_graph_query": None},
        ]

    def get_config_versions(self):
        return {"extraction": {"Directory": 2, "Technology": 7, "DirectoryClassification": 9}, "derivation": {"Node": 4}}

    def get_archimate_stats(self):
        return {"total_elements": 3, "total_relationships": 2, "by_type": {"Node": 2, "ApplicationComponent": 1}}

    def get_archimate_relationships(self):
        return [{"relationship_type": "Serving"}, {"relationship_type": "Serving"}]


def test_node_types_carry_counts_samples_producers_and_consumers():
    view = intermediate_ontology(FakeSession())

    types = {t["name"]: t for t in view["node_types"]}
    assert (types["Directory"]["count"], types["Technology"]["count"]) == (2, 1)
    assert types["Directory"]["properties"] == ["content", "id", "name", "path"]
    assert len(types["Directory"]["sample"]["content"]) < 500
    assert types["Technology"]["producers"] == [{"name": "Technology", "enabled": True, "version": 7, "method": "llm"}]
    assert types["Technology"]["consumers"] == ["Node"]
    assert types["Directory"]["consumers"] == ["ApplicationComponent"]
    assert view["other_steps"] == [{"name": "DirectoryClassification", "enabled": True, "version": 9, "method": "llm"}]


def test_edge_types_name_their_endpoint_types():
    view = intermediate_ontology(FakeSession())

    assert view["edge_types"] == [{"name": "CONTAINS", "count": 4, "pairs": [["Directory", "Directory"], ["Directory", "Technology"]]}]


def test_output_ontology_lists_types_per_layer_with_their_step_and_the_rules():
    view = output_ontology(FakeSession())

    types = {t["name"]: t for t in view["element_types"]}
    assert len(types) == 13
    assert (types["Node"]["layer"], types["Node"]["count"], types["Node"]["step"]) == ("Technology", 2, {"enabled": True, "version": 4})
    assert types["BusinessActor"]["step"] is None
    assert {r["name"]: r["count"] for r in view["relationship_types"]}["Serving"] == 2
    rules = {(r["source"], r["target"]): r for r in view["rules"]}
    assert "Serving" in rules[("ApplicationService", "ApplicationComponent")]["direct"]
    assert "Realization" in rules[("ApplicationComponent", "ApplicationService")]["derived"]
    assert "Realization" not in rules[("ApplicationComponent", "ApplicationService")]["direct"]
