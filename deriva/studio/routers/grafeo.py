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

router = APIRouter(prefix="/grafeo", tags=["grafeo"])

DATABASES = {"graph": "Graph", "default": "Graph", "model": "Model"}
# Node types of the extraction graph that derivation reads (files and methods are left out of the overview)
VIEW_TYPES = ("Repository", "Directory", "Technology", "BusinessConcept", "TypeDefinition")


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
    return to_widget_result(rows)


@router.get("/view/{database}")
def view(database: str, limit: int = 300, session: Any = Depends(get_session)) -> dict[str, Any]:
    """An overview graph for the studio's graph panes: up to ``limit`` nodes and the edges between them."""
    if database not in ("graph", "model"):
        raise HTTPException(status_code=404, detail=f"Unknown database: {database} (graph or model)")
    if database == "model":
        # Disabled elements (refine) are not part of the model, as in /api/model
        run = session.query_model_read_only
        nodes = run(f"MATCH (n:Model) WHERE coalesce(n.enabled, true) = true RETURN n LIMIT {limit}", None)
        edges = run(f"MATCH (a:Model)-[r]->(b:Model) WHERE coalesce(a.enabled, true) = true AND coalesce(b.enabled, true) = true RETURN a, r, b LIMIT {limit * 3}", None)
        return to_widget_graph(nodes + edges)
    run = session.query_graph_read_only
    rows: list[dict[str, Any]] = []
    for node_type in VIEW_TYPES:
        remaining = limit - len(rows)
        if remaining <= 0:
            break
        rows += run(f"MATCH (n:Graph:{node_type}) RETURN n LIMIT {remaining}", None)
    ids = [row["n"]["id"] for row in rows if isinstance(row.get("n"), dict) and "id" in row["n"]]
    edges = run("MATCH (a:Graph)-[r]->(b:Graph) WHERE a.id IN $ids AND b.id IN $ids RETURN a, r, b", {"ids": ids}) if ids else []
    return to_widget_graph(rows + edges)


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
