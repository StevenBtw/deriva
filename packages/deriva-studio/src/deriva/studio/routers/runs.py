"""Start, follow and cancel pipeline runs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from deriva.services.llm_log import LlmCallLog, summarize_call
from deriva.studio.runs import RunBusy

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunRequest(BaseModel):
    kind: Literal["all", "extraction", "derivation"]
    repository: str | None = None
    no_llm: bool = False


@router.post("", status_code=202)
def start_run(body: RunRequest, request: Request) -> Any:
    try:
        run_id = request.app.state.runs.start(body.kind, body.repository, body.no_llm)
    except RunBusy as busy:
        return JSONResponse(status_code=409, content={"detail": "A run is in progress", "run_id": busy.run_id})
    return {"run_id": run_id}


@router.get("/current")
def current_run(request: Request) -> dict[str, Any] | None:
    return request.app.state.runs.current()


@router.get("/history")
def run_history(request: Request, limit: int = 10) -> list[dict[str, Any]]:
    """The studio's own runs, newest first (kept in each run's folder)."""
    return request.app.state.runs.history(limit)


@router.post("/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
    if not request.app.state.runs.cancel(run_id):
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return {"run_id": run_id, "cancel_requested": True}


@router.get("/{run_id}/events")
def run_events(run_id: str, request: Request, after: int = 0, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    runs = request.app.state.runs
    # A run of this process, or one of an earlier process whose folder kept its events
    if not runs.events_kept(run_id):
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    def stream() -> Iterator[str]:
        for event in runs.events(run_id, after=start):
            payload = json.dumps({**event["data"], "ts": event["ts"]})
            yield f"id: {event['seq']}\nevent: {event['event']}\ndata: {payload}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _log_path(request: Request, run_id: str) -> str | None:
    runs = request.app.state.runs
    path = runs.log_path(run_id)
    # A known run without a call log made no LLM call (a structural run): no calls, not an unknown run
    if path is None and not runs.known(run_id):
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return path


@router.get("/{run_id}/calls")
def run_calls(run_id: str, request: Request) -> list[dict[str, Any]]:
    """The run's LLM calls without prompt and answer (fetch one call for those)."""
    path = _log_path(request, run_id)
    return [summarize_call(call) for call in LlmCallLog.read(path)] if path else []


@router.get("/{run_id}/calls/{call_id}")
def run_call(run_id: str, call_id: str, request: Request) -> dict[str, Any]:
    path = _log_path(request, run_id)
    call = LlmCallLog.find(path, call_id) if path else None
    if call is None:
        raise HTTPException(status_code=404, detail=f"Unknown call: {call_id}")
    return call
