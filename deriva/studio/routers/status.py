"""Health and status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from deriva.studio.provider import DatabaseHeld

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "version": request.app.version}


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    provider = request.app.state.provider
    try:
        with provider.session():
            pass
    except DatabaseHeld:
        pass
    return {"version": request.app.version, "db": provider.status()}
