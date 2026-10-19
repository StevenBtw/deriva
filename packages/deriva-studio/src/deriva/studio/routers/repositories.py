"""Repositories: list, details, clone, register, update, delete, and each repository's graph database (counts, clear)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from deriva.studio.deps import get_session
from deriva.studio.runs import RunBusy

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


class CloneRequest(BaseModel):
    url: str
    name: str | None = None
    branch: str | None = None


@router.get("")
def list_repositories(session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    return session.get_repositories(detailed=True)


@router.get("/unregistered")
def unregistered_repositories(request: Request) -> list[str]:
    """Git folders in the workspace without a record: they can be registered instead of cloned again."""
    return request.app.state.provider.detached().unregistered_repositories()


@router.post("/{name}/register", status_code=201)
def register_repository(name: str, request: Request) -> dict[str, Any]:
    session = request.app.state.provider.detached()
    return _idle(request, lambda: session.register_repository(name), "Register failed")


@router.get("/{name}")
def repository_info(name: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    info = session.get_repository_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {name}")
    return info


@router.post("", status_code=201)
def clone_repository(body: CloneRequest, request: Request) -> dict[str, Any]:
    """A clone needs no database and can take minutes: it holds no session (reads go on), only the lock that starts runs."""
    session = request.app.state.provider.detached()
    return _idle(request, lambda: session.clone_repository(url=body.url, name=body.name, branch=body.branch), "Clone failed")


def _idle(request: Request, action: Callable[[], dict[str, Any]], failed: str) -> dict[str, Any]:
    """Run an action under the lock that starts runs (a run would lose its input, or go on in another repository)."""
    try:
        result = request.app.state.runs.while_idle(action)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail="A run is in progress; try again when it has finished") from exc
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", failed))
    return result


def _known(session: Any, name: str) -> None:
    if name not in {r["name"] for r in session.get_repositories(detailed=False)}:
        raise HTTPException(status_code=404, detail=f"Repository not found: {name}")


@router.delete("/{name}")
def delete_repository(name: str, request: Request, force: bool = False, with_data: bool = False, session: Any = Depends(get_session)) -> dict[str, Any]:
    return _idle(request, lambda: session.delete_repository(name, force=force, with_data=with_data), "Delete failed")


@router.get("/{name}/data")
def repository_data(name: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    """Counts of the repository's graph and model, its database size, and its last extraction and derivation run."""
    _known(session, name)
    # Another repository's database is opened for the count: never while a run works in the session's one
    if name == session.repository:
        data = session.repository_data(name)
    else:
        data = _idle(request, lambda: {"success": True, **session.repository_data(name)}, "Reading the data failed")
        data.pop("success", None)
    runs = [r for r in request.app.state.runs.history(limit=None) if r.get("repository") == name]
    last = {kind: next((r for r in runs if r.get("kind") in (kind, "all")), None) for kind in ("extraction", "derivation")}
    return {**data, "last_runs": last}


@router.get("/{name}/coverage")
def extraction_coverage(name: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    """What of the checkout reached the graph, files per extension, and whether the extraction is complete."""
    _known(session, name)
    if name == session.repository:
        return session.extraction_coverage(name)
    # Another repository's database is opened for it: never while a run works in the session's one
    report = _idle(request, lambda: {"success": True, **session.extraction_coverage(name)}, "Reading the coverage failed")
    report.pop("success", None)
    return report


@router.delete("/{name}/model")
def clear_repository_model(name: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    _known(session, name)
    return _idle(request, lambda: session.clear_repository_model(name), "Clearing the model failed")


@router.delete("/{name}/graph")
def clear_repository_data(name: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    """The graph and the model: a model without its graph would point at nodes that are gone."""
    _known(session, name)
    return _idle(request, lambda: session.clear_repository_data(name), "Clearing the graph failed")


@router.post("/{name}/update")
def update_repository(name: str, request: Request, session: Any = Depends(get_session)) -> dict[str, Any]:
    _known(session, name)
    return _idle(request, lambda: session.update_repository(name), "Update failed")
