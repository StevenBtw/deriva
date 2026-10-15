"""Re-runnable extraction steps: which step owns a node or edge, and what a step's sweep removes."""

from __future__ import annotations

from deriva.modules.extraction.step_tags import edge_step, node_step, plan_sweep


def test_nodes_are_owned_by_the_step_that_writes_their_kind():
    assert node_step(["Graph", "File"], {"extractionMethod": "structural"}) == "File"
    assert node_step(["Graph", "TypeDefinition"], {"extractionMethod": "structural"}) == "TypeDefinition"  # placeholders too
    assert node_step(["Graph", "BusinessConcept"], {"extractionMethod": "llm"}) == "BusinessConcept"
    assert node_step(["Graph", "BusinessConcept"], {"extractionMethod": "llm-directory"}) == "DirectoryClassification"
    assert node_step(["Graph", "Technology"], {"extractionMethod": "llm-directory"}) == "DirectoryClassification"
    assert node_step(["Graph", "ExternalDependency"], {"description": "External package discovered via import"}) == "Imports"
    assert node_step(["Graph", "ExternalDependency"], {"extractionMethod": "llm"}) == "ExternalDependency"
    assert node_step(["Graph", "Mystery"], {}) is None  # no rule: left untagged, never swept


def test_edges_are_owned_by_their_type_and_endpoints():
    assert edge_step("CONTAINS", "Directory", "File") == "File"
    assert edge_step("CONTAINS", "Repository", "Directory") == "Directory"
    assert edge_step("CONTAINS", "File", "TypeDefinition") == "TypeDefinition"
    assert edge_step("CONTAINS", "TypeDefinition", "Method") == "Method"
    assert edge_step("REFERENCES", "Method", "TypeDefinition") == "References"
    assert edge_step("REFERENCES", "File", "BusinessConcept") == "BusinessConcept"
    assert edge_step("INCLUDES", "DataEntity", "TypeDefinition") == "DataEntity"
    assert edge_step("INHERITS", "TypeDefinition", "TypeDefinition") == "TypeDefinition"
    assert edge_step("USES", "File", "ExternalDependency") == "Imports"
    assert edge_step("CONTAINS", "Method", "File") is None


def test_a_step_sweeps_what_it_no_longer_produces_and_keeps_what_another_step_shares():
    prior_nodes = {"a": ["DataEntity"], "b": ["DataEntity"], "c": ["BusinessConcept", "DirectoryClassification"], "d": ["File"]}
    prior_edges = {("a", "INCLUDES", "t1"), ("b", "INCLUDES", "t2")}

    plan = plan_sweep("DataEntity", prior_nodes, {"a"}, prior_edges, {("a", "INCLUDES", "t1")})

    assert plan.delete_nodes == ["b"]  # no longer produced, owned by nobody else
    assert plan.delete_edges == []  # b's edges go with b
    assert plan.set_steps == {"a": ["DataEntity"]}

    moved = plan_sweep("DataEntity", prior_nodes, {"a", "b"}, prior_edges, {("a", "INCLUDES", "t1")})
    assert moved.delete_edges == [("b", "INCLUDES", "t2")]  # both ends stay, the edge is no longer produced

    shared = plan_sweep("DirectoryClassification", prior_nodes, set(), set(), set())
    assert shared.delete_nodes == [] and shared.set_steps == {"c": ["BusinessConcept"]}  # still produced by BusinessConcept


def test_a_node_another_step_also_produces_keeps_both_steps():
    plan = plan_sweep("DirectoryClassification", {"c": ["BusinessConcept"]}, {"c"}, set(), set())

    assert plan.set_steps == {"c": ["BusinessConcept", "DirectoryClassification"]} and plan.delete_nodes == []
