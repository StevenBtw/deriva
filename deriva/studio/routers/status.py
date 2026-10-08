"""Health and status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deriva.studio.provider import DatabaseHeld, SessionBusy

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "version": request.app.version}


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    provider = request.app.state.provider
    try:
        with provider.session(wait=0.5):
            pass
    except DatabaseHeld:
        pass
    except SessionBusy:
        return {"version": request.app.version, "db": {**provider.status(), "busy": True}}
    return {"version": request.app.version, "db": provider.status()}
