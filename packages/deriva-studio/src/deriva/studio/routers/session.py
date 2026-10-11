"""The repository the studio session reads: its graph file holds the extraction graph and the model shown in the views."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from deriva.studio.deps import get_session
from deriva.studio.runs import RunBusy

router = APIRouter(prefix="/api/session", tags=["session"])


class RepositoryChoice(BaseModel):
    repository: str


@router.get("")
def current(session: Any = Depends(get_session)) -> dict[str, Any]:
    return {"repository": getattr(session, "repository", None)}


@router.put("/repository")
def use_repository(choice: RepositoryChoice, request: Request) -> dict[str, Any]:
    def switch() -> None:
        with request.app.state.provider.session() as session:
            if choice.repository not in {r["name"] for r in session.get_repositories(detailed=False)}:
                raise HTTPException(status_code=404, detail=f"Repository not found: {choice.repository}")
            session.use_repository(choice.repository)

    # Checked and switched under the lock that starts runs: no run can start in between and read the old repository
    try:
        request.app.state.runs.while_idle(switch)
    except RunBusy as exc:
        raise HTTPException(status_code=409, detail="A run is in progress; switch repositories when it has finished") from exc
    return {"repository": choice.repository}
