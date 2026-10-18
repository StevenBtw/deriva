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


def _on_level(value: str | None, level: str) -> bool:
    """Whether an exported ``level`` value (``enterprise solution``, ``cross-level``, ``detail``, ``architect`` in a model
    from before the levels) belongs to the studio level: enterprise, solution, detail (the solution level and the
    members, as the exchange file's detail views) or architect (every level but detail)."""
    levels = set(str(value or "architect").split())
    if level == "architect":
        return "detail" not in levels
    if level == "detail":
        return bool(levels & {"solution", "detail", "architect"})
    return level in levels or "architect" in levels


@router.get("/model")
def model(level: str = Query("architect", pattern="^(architect|enterprise|solution|detail)$"), session: Any = Depends(get_session)) -> dict[str, Any]:
    """The model at one abstraction level with the views of that level: enterprise, solution, detail (the solution level
    with the members of its elements) or architect (every level but detail, the whole model of earlier studios). A
    relationship shows on the level it is on, so a cross-level link shows on architect only."""
    levels = session.get_model_levels()
    elements = [e for e in levels["elements"] if _on_level(e.get("level"), level)]
    shown = {e["identifier"] for e in elements}
    relationships = [
        r for r in levels["relationships"] if r["source"] in shown and r["target"] in shown and ("level" not in r or level == "architect" or _on_level(r["level"], level))
    ]
    # A view of an earlier model ("architect") is an enterprise view
    views = [v for v in levels["views"] if (v.get("level") != "detail" if level == "architect" else (v.get("level") or "architect").replace("architect", "enterprise") == level)]
    return {**to_widget_model(elements, relationships), "views": views}


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
