"""The extraction graph and the ArchiMate model: stats, nodes, the model view, clear, export."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deriva.studio.archimate_view import to_widget_model
from deriva.studio.deps import get_session
from deriva.studio.runs import RunBusy

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


def _when_idle(request: Request, action: Any) -> dict[str, Any]:
    """Clears wait for the run to end: a step would go on writing into what was cleared."""
    try:
        return request.app.state.runs.while_idle(action)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail="A run is in progress; try again when it has finished") from exc


@router.delete("/graph")
def clear_graph(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    return _when_idle(request, session.clear_graph)


@router.get("/model/stats")
def model_stats(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.get_archimate_stats()


@router.get("/model/quality")
def model_quality(session: Any = Depends(get_session)) -> dict[str, Any]:
    """The verdict on the model from its structure, with what it is based on (a report; nothing changes)."""
    return session.model_quality()


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
def clear_model(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    return _when_idle(request, session.clear_model)


@router.get("/model/download")
def download_model(session: Any = Depends(get_session)) -> FileResponse:
    """The model as an exchange file for the browser to save, named after its repository and the time; the copy in
    workspace/output keeps that name, so exports no longer overwrite each other."""
    repository = session.repository if isinstance(getattr(session, "repository", None), str) else "model"
    name = f"{repository}-{datetime.now():%Y%m%d-%H%M%S}.xml"
    try:
        result = session.export_model(output_path=f"workspace/output/{name}", confined=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Export failed"))
    return FileResponse(result["output_path"], media_type="application/xml", filename=name)


@router.post("/model/export")
def export_model(request: ExportRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    """Export the model as XML into the home folder's workspace/output (a request names the file, not a place)."""
    try:
        return session.export_model(output_path=request.path, confined=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
