"""Deriva Studio FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from deriva.studio.provider import DatabaseHeld, SessionBusy, SessionProvider
from deriva.studio.routers import repositories, status

STATIC_DIR = Path(__file__).parent / "static"


def create_app(provider: SessionProvider | None = None, static_dir: Path | None = None) -> FastAPI:
    """Build the studio app; tests pass a provider with a fake session and ``static_dir=None``."""
    session_provider = provider or SessionProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        session_provider.close()

    app = FastAPI(title="Deriva Studio", version=version("Deriva"), lifespan=lifespan)
    app.state.provider = session_provider

    @app.exception_handler(DatabaseHeld)
    async def database_held(request: Request, exc: DatabaseHeld) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "The databases are held by another process", "held_by": exc.pid})

    @app.exception_handler(SessionBusy)
    async def session_busy(request: Request, exc: SessionBusy) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc), "busy": True})

    app.include_router(status.router)
    app.include_router(repositories.router)
    return app
