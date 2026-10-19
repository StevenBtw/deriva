"""What the workspace keeps on disk (graph databases, runs, LLM cache, exports, benchmark sessions) and clearing it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from deriva.studio.deps import get_session
from deriva.studio.runs import RunBusy

router = APIRouter(prefix="/api/storage", tags=["storage"])


def _idle(request: Request, action: Callable[[], Any]) -> Any:
    """Under the lock that starts runs: a run reads the cache and writes its graph and exports."""
    try:
        return request.app.state.runs.while_idle(action)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail="A run is in progress; try again when it has finished") from exc


@router.get("")
def overview(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    return {**session.storage_overview(), "runs": request.app.state.runs.storage()}


@router.delete("/llm-cache")
def clear_llm_cache(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    """Every cached LLM answer: the next runs call the LLM again."""
    return _idle(request, session.clear_llm_cache)


@router.delete("/exports")
def delete_exports(request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    return _idle(request, session.delete_exports)


@router.delete("/graphs/{key}")
def delete_graph(key: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    """A graph database without a repository (a repository's goes with the repository)."""
    try:
        return _idle(request, lambda: session.delete_graph(key))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No graph database: {key}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
