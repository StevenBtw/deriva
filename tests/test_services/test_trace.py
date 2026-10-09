"""Element trace: the element, its source graph nodes, its relationships and the LLM calls that mention its sources."""

from __future__ import annotations

from typing import Any

from deriva.services.trace import trace_element

SOURCE = {
    "_id": 5,
    "_labels": ["Graph", "Technology"],
    "id": "tech::r::queue",
    "techName": "Queue",
    "techCategory": "infrastructure",
    "extractionMethod": "llm-directory",
}


def element(identifier: str, name: str, element_type: str, **properties: Any) -> dict[str, Any]:
    return {"identifier": identifier, "name": name, "element_type": element_type, "documentation": "", "properties": properties, "enabled": True}


def relationship(identifier: str, source: str, target: str, relationship_type: str, **properties: Any) -> dict[str, Any]:
    return {"identifier": identifier, "source": source, "target": target, "relationship_type": relationship_type, "name": None, "documentation": None, "properties": properties}


ELEMENTS = [
    element("node_queue", "Queue Server", "Node", source="tech::r::queue", role="server"),
    element("svc_msg", "Messaging Service", "TechnologyService"),
    element("comp_worker", "Worker", "ApplicationComponent"),
]
RELATIONSHIPS = [
    relationship("r1", "node_queue", "svc_msg", "Realization", derived_from="metamodel"),
    relationship("r2", "comp_worker", "node_queue", "Serving"),
    relationship("r3", "comp_worker", "svc_msg", "Serving"),
]


def call(seq: int, step: str, prompt: str) -> dict[str, Any]:
    return {"call_id": f"c{seq}", "run_id": "run1", "seq": seq, "step": step, "prompt": prompt, "response": "{}", "schema": None, "cache_hit": False, "error": None}


CALLS = [
    call(1, "DirectoryClassification", "Classify these directories:\n- queue/\n- docs/"),
    call(2, "Node", "Candidates:\n- tech::r::queue (Queue)\n- tech::r::cache (Cache)"),
    call(3, "Node", "Candidates:\n- tech::r::cache (Cache)"),
    call(4, "SystemSoftware", "Candidates:\n- Queuetastic"),
]


class FakeSession:
    def __init__(self, elements=ELEMENTS, relationships=RELATIONSHIPS, nodes=(SOURCE,)):
        self.elements, self.relationships, self.nodes = list(elements), list(relationships), list(nodes)
        self.queries: list[tuple[str, dict | None]] = []

    def get_archimate_elements(self):
        return self.elements

    def get_archimate_relationships(self):
        return self.relationships

    def query_graph_read_only(self, cypher, params=None):
        self.queries.append((cypher, params))
        return [{"n": n} for n in self.nodes if n["id"] in (params or {}).get("ids", [])]


def test_trace_names_the_element_its_sources_and_relationships():
    trace = trace_element(FakeSession(), "node_queue", [])

    assert trace is not None
    assert trace["element"]["name"] == "Queue Server"
    (source,) = trace["sources"]
    assert (source["id"], source["type"], source["name"]) == ("tech::r::queue", "Technology", "Queue")
    assert source["properties"]["techCategory"] == "infrastructure"
    assert "_labels" not in source["properties"]
    assert [(r["identifier"], r["direction"], r["type"], r["other"]["name"], r["derived_from"]) for r in trace["relationships"]] == [
        ("r1", "out", "Realization", "Messaging Service", "metamodel"),
        ("r2", "in", "Serving", "Worker", None),
    ]


def test_trace_lists_the_calls_that_mention_a_source_decision_calls_by_step():
    trace = trace_element(FakeSession(), "node_queue", CALLS)

    assert trace is not None
    assert [(c["call_id"], c["role"], c["matched"]) for c in trace["calls"]] == [
        ("c1", "upstream", "Queue"),
        ("c2", "decision", "tech::r::queue"),
    ]
    assert "prompt" not in trace["calls"][0]


def test_role_elements_trace_every_source_of_the_group():
    second = {**SOURCE, "_id": 6, "id": "tech::r::bus", "techName": "Bus"}
    elements = [{**ELEMENTS[0], "properties": {"source": "tech::r::queue", "sources": ["tech::r::queue", "tech::r::bus"]}}]

    trace = trace_element(FakeSession(elements=elements, relationships=[], nodes=(SOURCE, second)), "node_queue", [])

    assert trace is not None
    assert [s["id"] for s in trace["sources"]] == ["tech::r::queue", "tech::r::bus"]


def test_unknown_element_and_element_without_source():
    session = FakeSession(elements=[{**ELEMENTS[1]}], relationships=[])

    assert trace_element(session, "missing", CALLS) is None
    trace = trace_element(session, "svc_msg", CALLS)
    assert trace is not None
    assert (trace["sources"], trace["calls"]) == ([], [])
    assert session.queries == []
