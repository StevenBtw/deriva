"""LLM model configs in .env: listed with masked keys; keys are accepted on write and never returned."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from deriva.studio.deps import get_session

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelConfig(BaseModel):
    provider: str
    model: str
    url: str | None = None
    key: str | None = None
    key_env: str | None = None
    structured_output: str | None = None


@router.get("")
def list_models(session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    return session.list_model_configs()


@router.put("/{name}")
def save_model(name: str, body: ModelConfig, session: Any = Depends(get_session)) -> dict[str, Any]:
    try:
        session.save_model_config(name, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": name, "saved": True}


@router.delete("/{name}", status_code=204)
def delete_model(name: str, session: Any = Depends(get_session)) -> Response:
    try:
        session.delete_model_config(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No model config named {name!r}") from exc
    return Response(status_code=204)
