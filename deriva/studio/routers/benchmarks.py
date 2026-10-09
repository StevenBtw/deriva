"""Benchmark sessions: start one, read their results, steps, flips and inspector views, download one as a verifiable bundle."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from deriva.studio.deps import get_session
from deriva.studio.runs import RunBusy

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


class BenchmarkRequest(BaseModel):
    repositories: list[str] = Field(min_length=1)
    model: str
    runs: int = Field(default=3, ge=1, le=20)
    stages: list[Literal["extraction", "derivation"]] | None = None
    use_cache: bool = False
    per_repo: bool = True
    separate_sessions: bool = False
    no_cache_extraction: bool = False
    description: str = ""


def _sessions(sessions: str) -> list[str]:
    ids = [s for s in sessions.split(",") if s]
    if not ids:
        raise HTTPException(status_code=400, detail="Name at least one benchmark session")
    return ids


def _view(read: Any) -> Any:
    try:
        return read()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_sessions(limit: int = 20, session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    return session.list_benchmarks(limit)


@router.get("/models")
def models(session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    """The configured benchmark models (name, provider, model; never keys)."""
    return [{"name": name, "provider": cfg.provider, "model": cfg.model} for name, cfg in sorted(session.list_benchmark_models().items())]


@router.post("", status_code=202)
def start_benchmark(body: BenchmarkRequest, request: Request) -> Any:
    """Start a benchmark; it holds the databases until it ends (data views answer busy meanwhile). Samples per call stay 1."""
    try:
        run_id = request.app.state.runs.start_benchmark(body.model_dump())
    except RunBusy as busy:
        return JSONResponse(status_code=409, content={"detail": str(busy), "run_id": busy.run_id})
    return {"run_id": run_id}


@router.get("/results")
def results(sessions: str, session: Any = Depends(get_session)) -> Any:
    """Consistency per repository and model over the runs of the sessions (comma-separated ids)."""
    ids = _sessions(sessions)
    return _view(lambda: session.benchmark_results(ids))


@router.get("/steps")
def steps(sessions: str, session: Any = Depends(get_session)) -> Any:
    ids = _sessions(sessions)
    return _view(lambda: session.benchmark_steps(ids))


@router.get("/flips")
def flips(sessions: str, repo: str, session: Any = Depends(get_session)) -> Any:
    ids = _sessions(sessions)
    return _view(lambda: session.benchmark_flips(ids, repo))


@router.get("/inspector")
def inspector(sessions: str, repo: str, session: Any = Depends(get_session)) -> Any:
    ids = _sessions(sessions)
    return _view(lambda: session.benchmark_inspector(ids, repo))


@router.get("/trace")
def trace(sessions: str, repo: str, type: str, source: str, session: Any = Depends(get_session)) -> Any:  # noqa: A002 - the query parameter is named type
    """Per run, why an element (by type and source) is or is not in the model, with the calls that decided it."""
    ids = _sessions(sessions)
    return _view(lambda: session.benchmark_trace(ids, repo, type, source))


@router.get("/{session_id}/export")
def export_benchmark(session_id: str, session: Any = Depends(get_session)) -> FileResponse:
    """The session as one zip (logs, LLM calls, models, config texts, environment, sha256 manifest)."""
    folder = Path(tempfile.mkdtemp(prefix="deriva-export-"))
    out = folder / f"{session_id}.zip"
    try:
        session.export_benchmark(session_id, out)
    except FileNotFoundError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(out, media_type="application/zip", filename=f"{session_id}.zip", background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True))
