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


CONTAINED = ("Directory", "File")


def repository_links(graph_nodes: list[dict[str, Any]], graph_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-lane CONTAINS edges from each repository to the roots of its sampled containment tree.

    The sample rarely holds a repository's own CONTAINS edges (they reach only its top folders), so the repository
    links to every sampled folder or file that no sampled folder contains: the flow from repository to graph stays
    visible without a line to every node. With one repository every root is its own; with more, a root needs a
    ``repository_name`` to be linked.
    """
    repositories = {node.get("repository_name"): node["id"] for node in graph_nodes if node["lane"] == "repository"}
    only = next(iter(repositories.values())) if len(repositories) == 1 else None
    contained = {edge["target"] for edge in graph_edges if edge.get("label") == "CONTAINS"}
    links = []
    for node in graph_nodes:
        if node["lane"] != "intermediate" or node["id"] in contained or not set(node.get("labels", [])) & set(CONTAINED):
            continue
        repository = repositories.get(node.get("repository_name")) or only
        if repository is not None:
            links.append({"source": repository, "target": node["id"], "label": "CONTAINS", "cross": True})
    return links


def above_rank(graph: dict[str, Any], min_rank: float, keep: set[str]) -> dict[str, Any]:
    """``graph`` without the nodes ranked below ``min_rank`` (their PageRank percentile) and the edges touching them.

    Repositories, nodes without a rank, and the Deriva ids in ``keep`` (the elements' sources) always stay.
    """

    def stays(node: dict[str, Any]) -> bool:
        rank = node.get("pagerank_percentile")
        return "Repository" in node.get("labels", []) or rank is None or rank >= min_rank or str(node.get("deriva_id")) in keep

    nodes = [node for node in graph["nodes"] if stays(node)]
    ids = {node["id"] for node in nodes}
    edges = [edge for edge in graph["edges"] if edge["source"] in ids and edge["target"] in ids]
    return {**graph, "nodes": nodes, "edges": edges}


def build_linked_view(model: dict[str, Any], graph: dict[str, Any], min_rank: float | None = None) -> dict[str, Any]:
    """Both widget graphs as lanes (repositories in their own), plus one cross-lane edge per element source present in ``graph``.

    Each element in the model also links to the model lane; ``graph``'s ``totals`` (the sampled graph's counts) pass on.
    ``min_rank`` hides the graph nodes ranked below it (see ``above_rank``); the repository links follow what stays.
    """
    if min_rank is not None:
        graph = above_rank(graph, min_rank, {source for element in model["nodes"] for source in element_sources(element)})
    widget_id = {str(node["deriva_id"]): node["id"] for node in graph["nodes"] if node.get("deriva_id")}
    graph_nodes = [{**node, "lane": "repository" if "Repository" in node.get("labels", []) else "intermediate"} for node in graph["nodes"]]
    repositories = sum(1 for node in graph_nodes if node["lane"] == "repository")
    lanes = [{**REPOSITORY_LANE, "title": "Repositories" if repositories > 1 else "Repository"}, *LANES]
    nodes = graph_nodes + [{**node, "lane": "output"} for node in model["nodes"]]
    edges = list(graph["edges"]) + list(model["edges"]) + repository_links(graph_nodes, graph["edges"])
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
