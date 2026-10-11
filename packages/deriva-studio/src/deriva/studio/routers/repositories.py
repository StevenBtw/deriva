"""Repositories: list, details, clone, delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deriva.studio.deps import get_session

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


class CloneRequest(BaseModel):
    url: str
    name: str | None = None
    branch: str | None = None


@router.get("")
def list_repositories(session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    return session.get_repositories(detailed=True)


@router.get("/{name}")
def repository_info(name: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    info = session.get_repository_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {name}")
    return info


@router.post("", status_code=201)
def clone_repository(request: CloneRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    result = session.clone_repository(url=request.url, name=request.name, branch=request.branch)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Clone failed"))
    return result


@router.delete("/{name}")
def delete_repository(name: str, force: bool = False, session: Any = Depends(get_session)) -> dict[str, Any]:
    result = session.delete_repository(name, force=force)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
    return result
