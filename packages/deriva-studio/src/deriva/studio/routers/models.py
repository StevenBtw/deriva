"""LLM model configs in .env: listed with masked keys; keys are accepted on write and never returned."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/models", tags=["models"])

# Each change reads .env, edits it and writes it back: one at a time, or two edits would overwrite each other
_ENV_WRITES = threading.Lock()


def get_env_session(request: Request) -> Any:
    """Model configs live in .env: a session that is not connected, so they work while another process holds the database."""
    return request.app.state.provider.detached()


class ModelConfig(BaseModel):
    provider: str
    model: str
    url: str | None = None
    key: str | None = None
    key_env: str | None = None
    sampling: str | None = None
    reasoning: str | None = None


@router.get("")
def list_models(session: Any = Depends(get_env_session)) -> list[dict[str, Any]]:
    return session.list_model_configs()


@router.put("/{name}")
def save_model(name: str, body: ModelConfig, session: Any = Depends(get_env_session)) -> dict[str, Any]:
    try:
        with _ENV_WRITES:
            session.save_model_config(name, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": name, "saved": True}


@router.delete("/{name}", status_code=204)
def delete_model(name: str, session: Any = Depends(get_env_session)) -> Response:
    try:
        with _ENV_WRITES:
            session.delete_model_config(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No model config named {name!r}") from exc
    return Response(status_code=204)
