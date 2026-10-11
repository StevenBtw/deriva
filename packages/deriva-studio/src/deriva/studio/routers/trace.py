"""Element trace: sources, relationships and the LLM calls of a run that mention the element's sources."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from deriva.services.llm_log import LlmCallLog
from deriva.studio.deps import get_session

router = APIRouter(prefix="/api/trace", tags=["trace"])


@router.get("/{element_id:path}")
def element_trace(element_id: str, request: Request, run_id: str | None = None, session: Any = Depends(get_session)) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    if run_id:
        runs = request.app.state.runs
        # A run of this process, or one an earlier process left in its folder (its saved calls)
        path = runs.log_path(run_id)
        if path is None and runs.get(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
        calls = LlmCallLog.read(path) if path else []
    trace = session.trace_element(element_id, calls)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Unknown element: {element_id}")
    return trace
