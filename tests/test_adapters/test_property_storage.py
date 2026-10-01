"""Stored properties come back exactly as written (real in-memory grafeo, both namespaces).

These pin the read contract independently of how properties are stored: every reader returns what the
last write gave it, nested values and None included.
"""

from __future__ import annotations

import pytest

from deriva.adapters.archimate import ArchimateManager
from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.grafeo.manager import close_database
from deriva.adapters.graph import GraphManager
from deriva.adapters.graph.models import BusinessConceptNode, FileNode, TypeDefinitionNode
from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep
from deriva.modules.derivation.refine.structural_consistency import StructuralConsistencyStep
from deriva.services.step_benchmark import graph_outputs


@pytest.fixture
def managers():
    """A graph and an ArchiMate manager on one fresh in-memory database."""
    close_database()
    gm, am = GraphManager(), ArchimateManager()
    gm.connect()
    am.connect()
    yield gm, am
    am.disconnect()
    gm.disconnect()
    close_database()


def _concept():
    return BusinessConceptNode("Ledger", "entity", "", "docs/a.md", "r", 0.9, concept_types=["actor", "entity"], source_terms=["Hauptbuch (de)", "Ledger (en)"])


def _type_definition():
    return TypeDefinitionNode(
        name="LedgerService", type_category="class", file_path="src/ledger.py", repository_name="r", description=None, code_snippet="class LedgerService: ..."
    )


def _file(path):
    return FileNode(name=path.rsplit("/", 1)[-1], path=path, repository_name="r", file_type="docs")


NESTED = {"route": "document", "confidence": 0.9, "meta": {"terms": ["a", "b"], "note": None}}


class TestGraphNodes:
    @pytest.mark.parametrize(
        "node_id, make, label",
        [("concept::r::ledger", _concept, "BusinessConcept"), ("typedef::r::src_ledger.py::ledgerservice", _type_definition, "TypeDefinition")],
    )
    def test_a_node_reads_back_as_its_model_dict(self, managers, node_id, make, label):
        gm, _ = managers
        node = make()
        gm.add_node(node, node_id=node_id)

        assert gm.get_node(node_id) == {"id": node_id, "label": label, "properties": node.to_dict()}
        assert gm.get_nodes_by_type(label) == [{"id": node_id, "label": label, "properties": node.to_dict()}]

    def test_a_rewrite_replaces_what_was_stored(self, managers):
        gm, _ = managers
        node = _concept()
        gm.add_node(node, node_id="concept::r::ledger")
        gm.batch_update_properties({"concept::r::ledger": {"pagerank": 0.5}})

        gm.add_node(node, node_id="concept::r::ledger")

        assert gm.get_node("concept::r::ledger")["properties"] == node.to_dict()


class TestGraphEdges:
    def _two_nodes(self, gm):
        gm.add_node(_file("docs/a.md"), node_id="file::r::docs_a.md")
        gm.add_node(_concept(), node_id="concept::r::ledger")
        return "file::r::docs_a.md", "concept::r::ledger"

    def test_edge_properties_read_back_with_nested_values(self, managers):
        gm, _ = managers
        src, dst = self._two_nodes(gm)

        gm.add_edge(src, dst, "REFERENCES", properties=NESTED)

        assert graph_outputs(gm)[("REFERENCES", f"{src} -> {dst}")] == NESTED

    def test_a_readded_edge_carries_only_its_new_properties(self, managers):
        gm, _ = managers
        src, dst = self._two_nodes(gm)
        gm.add_edge(src, dst, "REFERENCES", properties=NESTED)

        gm.add_edge(src, dst, "REFERENCES", properties={"route": "llm"})
        assert graph_outputs(gm)[("REFERENCES", f"{src} -> {dst}")] == {"route": "llm"}

        gm.add_edge(src, dst, "REFERENCES")
        assert graph_outputs(gm)[("REFERENCES", f"{src} -> {dst}")] == {}


class TestModelElements:
    PROPS = {"source": "typedef::r::src_a.py::a", "confidence": 0.9, "tags": ["x", "y"], "evidence": {"pagerank": 0.2, "note": None}}

    def test_element_properties_read_back_unchanged(self, managers):
        _, am = managers
        am.add_element(Element(name="Ledger", element_type="ApplicationComponent", identifier="ac_ledger", properties=self.PROPS))

        assert am.get_element("ac_ledger").properties == self.PROPS
        assert [e.properties for e in am.get_elements()] == [self.PROPS]
        assert [e.properties for e in am.get_elements("ApplicationComponent")] == [self.PROPS]

    def test_relationship_properties_read_back_unchanged(self, managers):
        _, am = managers
        for identifier in ("ac_a", "ac_b"):
            am.add_element(Element(name=identifier, element_type="ApplicationComponent", identifier=identifier))

        am.add_relationship(Relationship(source="ac_a", target="ac_b", relationship_type="Serving", identifier="rel_1", properties=self.PROPS))

        (relationship,) = am.get_relationships()
        assert (relationship.identifier, relationship.properties) == ("rel_1", self.PROPS)

    def test_a_redirected_relationship_keeps_its_properties(self, managers):
        _, am = managers
        for identifier in ("ac_a", "ac_b", "ac_c"):
            am.add_element(Element(name=identifier, element_type="ApplicationComponent", identifier=identifier))
        am.add_relationship(Relationship(source="ac_a", target="ac_b", relationship_type="Serving", identifier="rel_1", name="uses", properties=self.PROPS))

        new_id = am.redirect_relationship("rel_1", "ac_a", "ac_c")

        (relationship,) = am.get_relationships()
        assert (relationship.identifier, relationship.target, relationship.name) == (new_id, "ac_c", "uses")
        assert relationship.properties == {**self.PROPS, "redirected_from": "rel_1"}


class TestRefineReadsElementProperties:
    def test_orphan_importance_comes_from_the_element_properties(self, managers):
        _, am = managers
        am.add_element(Element(name="Ledger", element_type="ApplicationComponent", identifier="ac_ledger", properties={"source_pagerank": 0.9}))

        result = OrphanElementsStep().run(am, None, None, {})

        (detail,) = [d for d in result.details if d.get("identifier") == "ac_ledger"]
        assert detail["importance"] == 0.9

    def test_orphan_proposals_follow_the_element_source(self, managers):
        gm, am = managers
        gm.add_node(_file("src/a.py"), node_id="file::r::src_a.py")
        gm.add_node(_file("src/b.py"), node_id="file::r::src_b.py")
        gm.add_edge("file::r::src_a.py", "file::r::src_b.py", "USES")
        am.add_element(Element(name="A", element_type="ApplicationComponent", identifier="ac_a", properties={"source": "file::r::src_a.py"}))

        result = OrphanElementsStep().run(am, gm, None, {})

        (detail,) = [d for d in result.details if d.get("identifier") == "ac_a"]
        assert [(p["source_graph_rel"], p["proposed_archimate_rel"], p["target_graph_id"]) for p in detail["proposed_relationships"]] == [("USES", "Serving", "file::r::src_b.py")]

    def test_a_flow_to_a_passive_element_becomes_access_and_keeps_its_data(self, managers):
        _, am = managers
        am.add_element(Element(name="Process", element_type="ApplicationService", identifier="ap_1"))
        am.add_element(Element(name="Data", element_type="DataObject", identifier="do_1"))
        flow = Relationship(
            source="ap_1", target="do_1", relationship_type="Flow", identifier="rel_flow", name="writes", documentation="d", properties={"confidence": 0.8, "origin": "rule"}
        )
        am.add_relationship(flow, validate=False)

        StructuralConsistencyStep()._fix_flow_to_access(am, "rel_flow")

        (relationship,) = am.get_relationships()
        assert (relationship.identifier, relationship.relationship_type, relationship.source, relationship.target) == ("rel_flow", "Access", "ap_1", "do_1")
        assert (relationship.name, relationship.documentation, relationship.properties) == ("writes", "d", {"confidence": 0.8, "origin": "rule"})
