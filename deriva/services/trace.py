"""Element trace: where a model element comes from and which LLM calls decided on it.

Joins the element, the graph nodes it was derived from (``source`` / ``sources``), its
relationships and the run's LLM calls that mention a source by id or name. Calls of the
element's own derivation step are the deciding calls; calls of other steps are upstream
(for example the classification that made the source node a candidate).
"""

from __future__ import annotations

from typing import Any

from deriva.modules.analysis.run_consistency import mentions
from deriva.services.llm_log import summarize_call

DISPLAY_KEYS = ("name", "techName", "conceptName", "typeName", "methodName", "fileName", "repositoryName", "path", "id")
MIN_NAME_LENGTH = 3


def _node(value: dict[str, Any]) -> dict[str, Any]:
    properties = {k: v for k, v in value.items() if not k.startswith("_")}
    labels = [label for label in value.get("_labels", []) if label != "Graph"]
    name = next((properties[k] for k in DISPLAY_KEYS if properties.get(k)), None)
    return {"id": properties.get("id"), "type": labels[0] if labels else None, "name": name, "properties": properties}


def _source_ids(element: dict[str, Any]) -> list[str]:
    properties = element.get("properties") or {}
    sources = properties.get("sources") or ([properties["source"]] if properties.get("source") else [])
    return [s for s in sources if isinstance(s, str)]


def _matching_calls(element_type: str, sources: list[dict[str, Any]], calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = [s["id"] for s in sources if s["id"]] + [s["name"] for s in sources if isinstance(s["name"], str) and len(s["name"]) >= MIN_NAME_LENGTH]
    matched = []
    for call in calls:
        prompt = call.get("prompt") or ""
        term = next((t for t in terms if mentions(prompt, t)), None)
        if term is not None:
            role = "decision" if call.get("step") == element_type else "upstream"
            matched.append({**summarize_call(call), "role": role, "matched": term})
    return matched


def trace_element(session: Any, element_id: str, calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The element with its sources, relationships and matching calls; None for an unknown element."""
    elements = session.get_archimate_elements()
    element = next((e for e in elements if e.get("identifier") == element_id), None)
    if element is None:
        return None
    by_id = {e.get("identifier"): e for e in elements}

    ids = _source_ids(element)
    rows = session.query_graph_read_only("MATCH (n:Graph) WHERE n.id IN $ids RETURN n", {"ids": ids}) if ids else []
    found = {node["id"]: node for node in (_node(row["n"]) for row in rows)}
    sources = [found.get(i) or {"id": i, "type": None, "name": None, "properties": {}} for i in ids]

    relationships = []
    for rel in session.get_archimate_relationships():
        if element_id not in (rel.get("source"), rel.get("target")):
            continue
        outgoing = rel.get("source") == element_id
        other = by_id.get(rel.get("target") if outgoing else rel.get("source")) or {}
        relationships.append(
            {
                "identifier": rel.get("identifier"),
                "direction": "out" if outgoing else "in",
                "type": rel.get("relationship_type"),
                "other": {"identifier": other.get("identifier"), "name": other.get("name"), "type": other.get("element_type")},
                "derived_from": (rel.get("properties") or {}).get("derived_from"),
            }
        )

    return {
        "element": element,
        "sources": sources,
        "relationships": relationships,
        "calls": _matching_calls(element.get("element_type", ""), sources, calls),
    }
