"""The extraction graph and the ArchiMate model: stats, nodes, the model view, clear, export."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from deriva.studio.archimate_view import to_widget_model
from deriva.studio.deps import get_session

router = APIRouter(prefix="/api", tags=["graph", "model"])

# A node type is a graph label: the name goes into the query as one
NODE_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ExportRequest(BaseModel):
    path: str | None = None


@router.get("/graph/stats")
def graph_stats(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.get_graph_stats()


@router.get("/graph/nodes/{node_type}")
def graph_nodes(node_type: str, limit: int = Query(200, ge=0, le=10000), session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    if not NODE_TYPE.fullmatch(node_type):
        raise HTTPException(status_code=400, detail=f"Not a node type: {node_type!r}")
    return session.get_graph_nodes(node_type, limit=limit)


@router.delete("/graph")
def clear_graph(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.clear_graph()


@router.get("/model/stats")
def model_stats(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.get_archimate_stats()


@router.get("/model")
def model(level: str = Query("architect", pattern="^(architect|detail)$"), session: Any = Depends(get_session)) -> dict[str, Any]:
    """The model at one export level (detail: with the members of the architect elements), and the views of that level."""
    levels = session.get_model_levels()
    elements = [e for e in levels["elements"] if level == "detail" or e.get("level") == "architect"]
    views = [v for v in levels["views"] if level == "detail" or v.get("level") == "architect"]
    return {**to_widget_model(elements, levels["relationships"]), "views": views}


@router.delete("/model")
def clear_model(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.clear_model()


@router.post("/model/export")
def export_model(request: ExportRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    """Export the model as XML into the home folder's workspace/output (a request names the file, not a place)."""
    try:
        return session.export_model(output_path=request.path, confined=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
