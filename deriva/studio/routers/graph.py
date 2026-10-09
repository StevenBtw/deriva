"""The extraction graph and the ArchiMate model: stats, nodes, the model view, clear, export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deriva.studio.archimate_view import to_widget_model
from deriva.studio.deps import get_session

router = APIRouter(prefix="/api", tags=["graph", "model"])


class ExportRequest(BaseModel):
    path: str = "workspace/output/model.xml"


@router.get("/graph/stats")
def graph_stats(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.get_graph_stats()


@router.get("/graph/nodes/{node_type}")
def graph_nodes(node_type: str, limit: int = 200, session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    return session.get_graph_nodes(node_type)[:limit]


@router.delete("/graph")
def clear_graph(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.clear_graph()


@router.get("/model/stats")
def model_stats(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.get_archimate_stats()


@router.get("/model")
def model(session: Any = Depends(get_session)) -> dict[str, Any]:
    return to_widget_model(session.get_archimate_elements(), session.get_archimate_relationships())


@router.delete("/model")
def clear_model(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.clear_model()


@router.post("/model/export")
def export_model(request: ExportRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.export_model(output_path=request.path)
