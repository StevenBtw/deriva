"""Technology relationships from structure: membership of role elements and configuration files."""

from __future__ import annotations

from typing import Any

from deriva.modules.derivation.base import (
    ConfigurationRule,
    ContainmentRule,
    MembershipRule,
    RelationshipRule,
    derive_configuration_relationships,
    derive_consolidated_relationships,
    derive_membership_relationships,
)


def _el(identifier: str, element_type: str, source: str, sources: list[str] | None = None, name: str = "") -> dict[str, Any]:
    properties: dict[str, Any] = {"source": source}
    if sources is not None:
        properties["sources"] = sources
    return {"identifier": identifier, "name": name or identifier, "element_type": element_type, "properties": properties}


MEMBERSHIP = [
    MembershipRule(group="Node", member="SystemSoftware", relationship="Composition", from_group=True),
    MembershipRule(group="TechnologyService", member="SystemSoftware", relationship="Realization", from_group=False),
]
CONFIGURATION = [ConfigurationRule(provider="TechnologyService", consumer="ApplicationComponent", relationship="Serving")]

APP_SERVER = _el("n_app_server", "Node", "tech::r::jboss", sources=["tech::r::jboss", "tech::r::wildfly"])
DOCKERFILE = _el("n_dockerfile", "Node", "file::r::Dockerfile")
JBOSS = _el("ss_jboss", "SystemSoftware", "tech::r::jboss")
WILDFLY = _el("ss_wildfly", "SystemSoftware", "tech::r::wildfly")
HOSTING = _el("ts_hosting", "TechnologyService", "tech::r::jboss", sources=["tech::r::jboss", "tech::r::wildfly"])
RUNTIME = _el("ts_runtime", "TechnologyService", "tech::r::java", sources=["tech::r::java"])
STORAGE = _el("ts_storage", "TechnologyService", "tech::r::mongodb", sources=["tech::r::mongodb"])
CACHING = _el("ts_caching", "TechnologyService", "tech::r::ehcache", sources=["tech::r::ehcache"])
CORE = _el("ac_core", "ApplicationComponent", "dir::r::core")
CRUD = _el("ac_crud", "ApplicationComponent", "dir::r::core_crud_src_crud")


def _pairs(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestMembership:
    def test_a_role_element_relates_to_the_elements_of_its_member_technologies(self):
        relationships = derive_membership_relationships([APP_SERVER, DOCKERFILE, JBOSS, WILDFLY, HOSTING], MEMBERSHIP)

        assert _pairs(relationships) == {
            ("n_app_server", "Composition", "ss_jboss"),
            ("n_app_server", "Composition", "ss_wildfly"),
            ("ss_jboss", "Realization", "ts_hosting"),
            ("ss_wildfly", "Realization", "ts_hosting"),
        }
        assert {r["derived_from"] for r in relationships} == {"membership"}

    def test_an_element_without_member_technologies_groups_nothing(self):
        # A node made from a container file lists no technologies
        assert derive_membership_relationships([DOCKERFILE, JBOSS], MEMBERSHIP) == []


class TestConfiguration:
    PATHS = {"dir::r::core": "r/core", "dir::r::core_crud_src_crud": "r/core/crud/src/crud"}

    def test_a_service_serves_the_component_whose_files_configure_its_technologies(self):
        configured = {"r/core/pom.xml": {"tech::r::java", "tech::r::mongodb"}, "r/pom.xml": {"tech::r::ehcache"}}

        relationships = derive_configuration_relationships([CORE, RUNTIME, STORAGE, CACHING], self.PATHS, configured, CONFIGURATION)

        # The root manifest lies in no component
        assert _pairs(relationships) == {("ts_runtime", "Serving", "ac_core"), ("ts_storage", "Serving", "ac_core")}
        assert {r["derived_from"] for r in relationships} == {"configuration"}

    def test_a_file_belongs_to_its_nearest_enclosing_component(self):
        configured = {"r/core/crud/pom.xml": {"tech::r::java"}, "r/core/crud/src/crud/package.json": {"tech::r::mongodb"}}

        relationships = derive_configuration_relationships([CORE, CRUD, RUNTIME, STORAGE], self.PATHS, configured, CONFIGURATION)

        assert _pairs(relationships) == {("ts_runtime", "Serving", "ac_core"), ("ts_storage", "Serving", "ac_crud")}


class FakeGraph:
    """Answers the source-path and configuration queries; every other query finds nothing."""

    def __init__(self, paths: dict[str, str], configured: list[tuple[str, str]], connected: list[str] | None = None):
        self.paths, self.configured, self.connected = paths, configured, connected or []

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "file_path" in cypher and "IN $ids" in cypher:
            ids = set((params or {}).get("ids", []))
            return [{"id": i, "path": p, "file_path": None} for i, p in self.paths.items() if i in ids]
        if "CONFIGURES" in cypher:
            return [{"file": f, "tech": t} for f, t in self.configured]
        if "*1.." in cypher:
            return [{"id": i} for i in self.connected]
        return []


class TestConsolidatedPass:
    def test_structure_decides_and_other_tiers_add_no_second_owner(self):
        import json
        from types import SimpleNamespace

        from deriva.modules.derivation.base import RelationshipLLMConfig

        # The LLM proposes that the container-file node composes the system software as well
        docker_node = _el("n_container_host", "Node", "tech::r::docker", sources=["tech::r::docker"])
        compose = _el("n_compose", "Node", "file::r::docker-compose.yml")
        docker = _el("ss_docker", "SystemSoftware", "tech::r::docker")
        rules = {"Node": ([RelationshipRule(target_type="SystemSoftware", rel_type="Composition"), RelationshipRule(target_type="ApplicationComponent", rel_type="Serving")], [])}
        proposals = [
            {"source": "n_compose", "target": "ss_docker", "relationship_type": "Composition", "confidence": 0.9},
            {"source": "n_compose", "target": "ac_core", "relationship_type": "Serving", "confidence": 0.9},
        ]
        graph = FakeGraph({"dir::r::core": "r/core"}, [], connected=["tech::r::docker", "file::r::docker-compose.yml", "dir::r::core"])

        relationships = derive_consolidated_relationships(
            all_elements=[docker_node, compose, docker, CORE],
            relationship_rules=rules,
            llm_query_fn=lambda prompt, schema, **kw: SimpleNamespace(content=json.dumps({"relationships": proposals})),
            graph_manager=graph,
            llm_config=RelationshipLLMConfig(instruction="rules", min_confidence=0.5, persona="P"),
            membership=MEMBERSHIP,
        )

        pairs = _pairs(relationships)
        assert ("n_container_host", "Composition", "ss_docker") in pairs
        assert ("n_compose", "Composition", "ss_docker") not in pairs
        # Usage from the file node stays
        assert ("n_compose", "Serving", "ac_core") in pairs

    def test_a_node_without_member_technologies_never_owns_system_software(self):
        # MySQL is in no role: no structural owner, but a container-file node may still not compose it
        compose = _el("n_compose", "Node", "file::r::docker-compose.yml", name="Docker Compose")
        mysql = _el("ss_mysql", "SystemSoftware", "tech::r::mysql", name="Docker Compose MySQL")
        rules = {"Node": ([RelationshipRule(target_type="SystemSoftware", rel_type="Composition"), RelationshipRule(target_type="SystemSoftware", rel_type="Serving")], [])}

        relationships = derive_consolidated_relationships(
            all_elements=[compose, mysql], relationship_rules=rules, llm_query_fn=None, graph_manager=FakeGraph({}, []), membership=MEMBERSHIP
        )

        pairs = _pairs(relationships)
        assert ("n_compose", "Composition", "ss_mysql") not in pairs
        assert ("n_compose", "Serving", "ss_mysql") in pairs

    def test_configuration_reads_the_configures_edges(self):
        graph = FakeGraph({"dir::r::core": "r/core"}, [("r/core/pom.xml", "tech::r::java")])

        relationships = derive_consolidated_relationships(all_elements=[CORE, RUNTIME], relationship_rules={}, llm_query_fn=None, graph_manager=graph, configuration=CONFIGURATION)

        assert _pairs(relationships) == {("ts_runtime", "Serving", "ac_core")}

    def test_containment_and_membership_together(self):
        graph = FakeGraph({"dir::r::core": "r/core", "dir::r::core_crud_src_crud": "r/core/crud/src/crud"}, [])
        containment = [ContainmentRule(container="ApplicationComponent", contained="ApplicationComponent", relationship="Composition")]

        relationships = derive_consolidated_relationships(
            all_elements=[CORE, CRUD, APP_SERVER, JBOSS, HOSTING], relationship_rules={}, llm_query_fn=None, graph_manager=graph, containment=containment, membership=MEMBERSHIP
        )

        assert _pairs(relationships) == {
            ("ac_core", "Composition", "ac_crud"),
            ("n_app_server", "Composition", "ss_jboss"),
            ("ss_jboss", "Realization", "ts_hosting"),
        }
