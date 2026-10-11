"""The linked view: the intermediate graph and the output graph as two lanes, each element linked to its sources.

Structure only (no LLM): an element's sources are the ``sources`` list in its own properties map, or ``source``
without one (the rule of the trace service). Graph nodes are matched by their Deriva id, which the widget format keeps
as ``deriva_id``.
"""

from __future__ import annotations

from typing import Any

# Repositories stand in a narrow column on the left; their CONTAINS edges fan out into the intermediate graph
REPOSITORY_LANE = {"id": "repository", "arrange": "column", "width": 0.25}
LANES = [{"id": "intermediate", "title": "Intermediate graph"}, {"id": "output", "title": "Output graph"}]
# The model's action lane at the right end (the studio adds it, withModelLane); elements in the model link to it
MODEL_LANE = "model"


def element_sources(node: dict[str, Any]) -> list[str]:
    """The Deriva ids of the graph nodes an element was derived from.

    An older model (elements without their own properties map) has only the adapter's ``source_identifier``.
    """
    properties = node.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    sources = properties.get("sources") or ([properties["source"]] if properties.get("source") else [])
    if not sources and node.get("source_identifier"):
        sources = [node["source_identifier"]]
    return [source for source in sources if isinstance(source, str)]


def in_model(element: dict[str, Any]) -> bool:
    """Whether an element is part of the exported model (refine did not disable it)."""
    return element.get("enabled", True) is not False


def build_linked_view(model: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Both widget graphs as lanes (repositories in their own), plus one cross-lane edge per element source present in ``graph``.

    Each element in the model also links to the model lane; ``graph``'s ``totals`` (the sampled graph's counts) pass on.
    """
    widget_id = {str(node["deriva_id"]): node["id"] for node in graph["nodes"] if node.get("deriva_id")}
    graph_nodes = [{**node, "lane": "repository" if "Repository" in node.get("labels", []) else "intermediate"} for node in graph["nodes"]]
    repositories = sum(1 for node in graph_nodes if node["lane"] == "repository")
    lanes = [{**REPOSITORY_LANE, "title": "Repositories" if repositories > 1 else "Repository"}, *LANES]
    nodes = graph_nodes + [{**node, "lane": "output"} for node in model["nodes"]]
    edges = list(graph["edges"]) + list(model["edges"])
    missing = 0
    for element in model["nodes"]:
        for source in element_sources(element):
            target = widget_id.get(source)
            if target is None:
                missing += 1
                continue
            edges.append({"source": element["id"], "target": target, "label": "DERIVED_FROM", "cross": True})
    edges += [{"source": element["id"], "target": MODEL_LANE, "label": "IN_MODEL", "cross": True} for element in model["nodes"] if in_model(element)]
    view = {"lanes": lanes, "nodes": nodes, "edges": edges, "missing_links": missing}
    return {**view, "totals": graph["totals"]} if "totals" in graph else view
