"""Dependencies between components from file imports, drawn between siblings."""

from __future__ import annotations

from typing import Any

from deriva.modules.derivation.base import DependencyRule, derive_consolidated_relationships, derive_dependency_relationships

RULES = [DependencyRule(provider="ApplicationComponent", consumer="ApplicationComponent", relationship="Serving")]


def _ac(identifier: str) -> dict[str, Any]:
    return {"identifier": identifier, "name": identifier, "element_type": "ApplicationComponent", "properties": {"source": f"dir::r::{identifier}"}}


# A layered application: cli -> services -> modules (extraction -> derivation) and adapters -> common
LAYOUT = {
    "cli": "r/app/cli",
    "services": "r/app/services",
    "modules": "r/app/modules",
    "extraction": "r/app/modules/extraction",
    "derivation": "r/app/modules/derivation",
    "adapters": "r/app/adapters",
    "graph": "r/app/adapters/graph",
    "common": "r/app/common",
}
ELEMENTS = [_ac(k) for k in LAYOUT]
PATHS = {f"dir::r::{k}": v for k, v in LAYOUT.items()}


def _pairs(relationships):
    return {(r["source"], r["relationship_type"], r["target"]) for r in relationships}


class TestDependencies:
    def test_the_provider_serves_the_component_that_imports_it(self):
        imports = [("r/app/cli/main.py", "r/app/services/run.py"), ("r/app/services/run.py", "r/app/common/util.py")]

        relationships = derive_dependency_relationships(ELEMENTS, PATHS, imports, RULES)

        assert _pairs(relationships) == {("services", "Serving", "cli"), ("common", "Serving", "services")}
        assert {r["derived_from"] for r in relationships} == {"dependency"}

    def test_a_dependency_is_drawn_between_the_siblings_below_the_shared_parent(self):
        imports = [
            # derivation (in modules) uses the graph adapter (in adapters): modules depends on adapters
            ("r/app/modules/derivation/base.py", "r/app/adapters/graph/manager.py"),
            # extraction and derivation share modules: the dependency stays between them
            ("r/app/modules/extraction/run.py", "r/app/modules/derivation/base.py"),
            # services uses derivation: services depends on modules
            ("r/app/services/run.py", "r/app/modules/derivation/base.py"),
        ]

        relationships = derive_dependency_relationships(ELEMENTS, PATHS, imports, RULES)

        assert _pairs(relationships) == {("adapters", "Serving", "modules"), ("derivation", "Serving", "extraction"), ("modules", "Serving", "services")}

    def test_imports_within_a_component_or_its_parts_and_outside_components_add_nothing(self):
        imports = [
            ("r/app/modules/extraction/a.py", "r/app/modules/extraction/b.py"),
            ("r/app/modules/base.py", "r/app/modules/derivation/base.py"),
            ("r/scripts/tool.py", "r/app/common/util.py"),
        ]

        assert derive_dependency_relationships(ELEMENTS, PATHS, imports, RULES) == []

    def test_many_imports_give_one_relationship(self):
        imports = [("r/app/cli/main.py", "r/app/services/run.py"), ("r/app/cli/other.py", "r/app/services/config.py")]

        assert len(derive_dependency_relationships(ELEMENTS, PATHS, imports, RULES)) == 1

    def test_an_element_from_a_file_owns_that_file(self):
        # A file outside every directory element is held only by the element derived from it
        elements = [*ELEMENTS, {"identifier": "gen", "name": "gen", "element_type": "ApplicationComponent", "properties": {"source": "file::r::gen"}}]
        paths = {**PATHS, "file::r::gen": "r/app/gen.py"}

        relationships = derive_dependency_relationships(elements, paths, [("r/app/cli/main.py", "r/app/gen.py"), ("r/app/gen.py", "r/app/common/util.py")], RULES)

        assert _pairs(relationships) == {("gen", "Serving", "cli"), ("common", "Serving", "gen")}


class FakeGraph:
    """Answers the source-path and import queries; every other query finds nothing."""

    def __init__(self, imports: list[tuple[str, str]]):
        self.imports = imports

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "file_path" in cypher and "IN $ids" in cypher:
            ids = set((params or {}).get("ids", []))
            return [{"id": i, "path": p, "file_path": None} for i, p in PATHS.items() if i in ids]
        if "IMPORTS" in cypher:
            return [{"a": a, "b": b} for a, b in self.imports]
        return []


class TestConsolidatedPass:
    def test_dependencies_come_from_the_import_edges(self):
        graph = FakeGraph([("r/app/cli/main.py", "r/app/services/run.py")])

        relationships = derive_consolidated_relationships(all_elements=ELEMENTS, relationship_rules={}, llm_query_fn=None, graph_manager=graph, dependency=RULES)

        assert _pairs(relationships) == {("services", "Serving", "cli")}
