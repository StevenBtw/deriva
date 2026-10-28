"""The three grafeo server requests anywidget-graph sends in server mode, answered read-only from the embedded databases.

Point the widget at it with grafeo_connection_mode="server" and grafeo_server_url="/grafeo";
connection_database is "graph" (extraction graph) or "model" (ArchiMate model).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deriva.studio.deps import get_session
from deriva.studio.grafeo_compat import NAMESPACES, is_write_query, to_widget_graph, to_widget_result
from deriva.studio.linked_view import build_linked_view, element_sources
from deriva.studio.sampling import sample_nodes

router = APIRouter(prefix="/grafeo", tags=["grafeo"])

DATABASES = {"graph": "Graph", "default": "Graph", "model": "Model"}
# Shown in full in every view of the extraction graph; the sample fills the rest of the limit
ALWAYS_SHOWN = "Repository"


class QueryRequest(BaseModel):
    query: str
    language: str = "cypher"
    database: str = "graph"


def _runner(session: Any, database: str):
    if database not in DATABASES:
        raise HTTPException(status_code=404, detail=f"Unknown database: {database} (graph or model)")
    return session.query_graph_read_only if DATABASES[database] == "Graph" else session.query_model_read_only


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "grafeo-embedded"}


@router.post("/query")
def query(request: QueryRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    if request.language.lower() not in ("cypher", "gql"):
        raise HTTPException(status_code=400, detail="The studio answers Cypher queries")
    run = _runner(session, request.database)
    if is_write_query(request.query):
        raise HTTPException(status_code=400, detail="The studio graph view is read-only")
    try:
        rows = run(request.query, None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Both namespaces share one graph file: rows with the other namespace's nodes or edges are left out
    namespace = DATABASES[request.database]
    return to_widget_result([row for row in rows if all(_in_namespace(value, namespace) for value in row.values())])


def _in_namespace(value: Any, namespace: str) -> bool:
    """False for a node or edge of another namespace (lists: every item); other values belong anywhere."""
    if isinstance(value, list):
        return all(_in_namespace(item, namespace) for item in value)
    if isinstance(value, dict) and "_labels" in value:
        return namespace in value["_labels"] or not any(ns in value["_labels"] for ns in NAMESPACES)
    if isinstance(value, dict) and "_type" in value and "_source" in value:
        kind = str(value["_type"])
        return kind.startswith(f"{namespace}:") or not any(kind.startswith(f"{ns}:") for ns in NAMESPACES)
    return True


def _model_view(session: Any, rejected: bool = False) -> dict[str, Any]:
    """The whole output graph: the model's elements (with ``rejected``, also those refine disabled) and its relationships."""
    run = session.query_model_read_only
    valid_only = "" if rejected else " WHERE coalesce(n.enabled, true) = true"
    nodes = run(f"MATCH (n:Model){valid_only} RETURN n", None)
    # Relationships as exported: only between elements that are part of the model
    edges = run("MATCH (a:Model)-[r]->(b:Model) WHERE coalesce(a.enabled, true) = true AND coalesce(b.enabled, true) = true RETURN a, r, b", None)
    return to_widget_graph(nodes + edges)


def _node_type(labels: list[str]) -> str:
    return next((label for label in labels if label not in NAMESPACES), labels[0] if labels else "")


def _graph_view(session: Any, budget: int, first_ids: list[str] | None = None, keep_first: int = 0) -> dict[str, Any]:
    """A realistic sample of the extraction graph in ``budget`` nodes (repositories and ``first_ids`` first), with its edges.

    The repositories always fit, and up to ``keep_first`` of ``first_ids`` too, also when the budget is smaller.
    ``totals`` counts the whole graph's nodes and edges per type.
    """
    run = session.query_graph_read_only
    types = {str(row["id"]): _node_type(row["labels"]) for row in run("MATCH (n:Graph) RETURN n.id AS id, labels(n) AS labels", None) if row.get("id") is not None}
    structure = run("MATCH (a:Graph)-[r]->(b:Graph) RETURN a.id AS source, b.id AS target, type(r) AS type", None)
    edges = [(str(row["source"]), str(row["target"])) for row in structure]
    always = sorted(node for node, kind in types.items() if kind == ALWAYS_SHOWN)
    first = [node for node in dict.fromkeys(first_ids or []) if node in types and node not in always]
    ids = sample_nodes(types, edges, max(budget, len(always) + min(len(first), keep_first)), first=always + first)
    order = {node: i for i, node in enumerate(ids)}
    rows = run("MATCH (n:Graph) WHERE n.id IN $ids RETURN n", {"ids": ids}) if ids else []
    rows.sort(key=lambda row: order.get(row["n"].get("id"), len(order)))
    links = run("MATCH (a:Graph)-[r]->(b:Graph) WHERE a.id IN $ids AND b.id IN $ids RETURN a, r, b", {"ids": ids}) if ids else []
    totals = {
        "nodes": dict(Counter(types.values())),
        "edges": dict(Counter(row["type"].split(":", 1)[-1] for row in structure)),
    }
    return {**to_widget_graph(rows + links), "totals": totals}


@router.get("/view/linked")
def linked_view(limit: int | None = None, session: Any = Depends(get_session)) -> dict[str, Any]:
    """The intermediate graph and the output graph as two lanes, with each element linked to its source nodes.

    The output graph (rejected elements too) and the repositories are always shown; the rest of ``limit`` (the
    graph_view_nodes setting when not given) samples the intermediate graph, starting from the elements' sources. A
    model larger than the limit still gets its sources (up to the limit), so its links stay.
    """
    limit = limit if limit is not None else session.graph_view_nodes()
    model = _model_view(session, rejected=True)
    sources = sorted({source for node in model["nodes"] for source in element_sources(node)})
    return build_linked_view(model, _graph_view(session, limit - len(model["nodes"]), first_ids=sources, keep_first=limit))


@router.get("/view/{database}")
def view(database: str, limit: int | None = None, session: Any = Depends(get_session)) -> dict[str, Any]:
    """An overview graph for the studio's graph panes: the whole model, or a realistic sample of ``limit`` graph nodes
    (the graph_view_nodes setting when not given)."""
    if database not in ("graph", "model"):
        raise HTTPException(status_code=404, detail=f"Unknown database: {database} (graph or model)")
    if database == "model":
        return _model_view(session)
    return _graph_view(session, limit if limit is not None else session.graph_view_nodes())


@router.get("/db/{database}/schema")  # the path anywidget-graph's grafeo client asks
@router.get("/databases/{database}/schema")
def schema(database: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    run = _runner(session, database)
    namespace = DATABASES[database]
    label_counts: Counter[str] = Counter()
    for row in run(f"MATCH (n:{namespace}) RETURN labels(n) AS labels", None):
        for label in row["labels"]:
            if label not in NAMESPACES:
                label_counts[label] += 1
    edges = run(f"MATCH (:{namespace})-[r]->(:{namespace}) RETURN type(r) AS type, count(r) AS count", None)
    return {
        "labels": [{"name": name, "count": count} for name, count in sorted(label_counts.items())],
        "edge_types": sorted(({"name": r["type"].split(":", 1)[-1], "count": r["count"]} for r in edges), key=lambda e: e["name"]),
    }
