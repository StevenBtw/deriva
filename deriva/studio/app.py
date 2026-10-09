"""Deriva Studio FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from deriva.studio.provider import DatabaseHeld, SessionBusy, SessionProvider
from deriva.studio.routers import benchmarks, configs, grafeo, graph, models, ontology, repositories, session, settings, status, trace, widgets
from deriva.studio.routers import runs as runs_router
from deriva.studio.runs import RUNS_DIR, RunManager

STATIC_DIR = Path(__file__).parent / "static"

NOT_BUILT = (
    "<!doctype html><title>Deriva Studio</title><p>The studio front end is not built yet. "
    "Run <code>npm install</code> and <code>npm run build</code> in <code>studio/</code>, then reload. "
    "The API is available under <a href='/docs'>/docs</a>.</p>"
)
API_PREFIXES = ("api/", "grafeo/", "widgets/", "docs", "openapi.json", "redoc")


def create_app(provider: SessionProvider | None = None, static_dir: Path | None = STATIC_DIR, runs_dir: Path = RUNS_DIR) -> FastAPI:
    """Build the studio app; tests pass a provider with a fake session, ``static_dir=None`` and a temporary ``runs_dir``."""
    session_provider = provider or SessionProvider()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        session_provider.close()

    app = FastAPI(title="Deriva Studio", version=version("Deriva"), lifespan=lifespan)
    app.state.provider = session_provider
    app.state.runs = RunManager(session_provider, runs_dir)

    @app.exception_handler(DatabaseHeld)
    async def database_held(request: Request, exc: DatabaseHeld) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "The databases are held by another process", "held_by": exc.pid})

    @app.exception_handler(SessionBusy)
    async def session_busy(request: Request, exc: SessionBusy) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc), "busy": True})

    app.include_router(status.router)
    app.include_router(repositories.router)
    app.include_router(settings.router)
    app.include_router(configs.router)
    app.include_router(graph.router)
    app.include_router(grafeo.router)
    app.include_router(widgets.router)
    app.include_router(runs_router.router)
    app.include_router(session.router)
    app.include_router(trace.router)
    app.include_router(benchmarks.router)
    app.include_router(models.router)
    app.include_router(ontology.router)
    _mount_front_end(app, static_dir)
    return app


def _mount_front_end(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the built front end (index.html for every non-API path), or a page explaining how to build it."""
    index = static_dir / "index.html" if static_dir is not None else None
    if static_dir is None or index is None or not index.exists():

        @app.get("/", include_in_schema=False)
        def not_built() -> HTMLResponse:
            return HTMLResponse(NOT_BUILT)

        return
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def front_end(path: str) -> FileResponse:
        if path.startswith(API_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index)
