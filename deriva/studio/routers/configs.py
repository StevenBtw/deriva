"""Extraction and derivation configs: list with active versions, versioned saves, enable/disable."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deriva.studio.deps import get_session

router = APIRouter(prefix="/api/configs", tags=["configs"])

NAME_KEY = {"extraction": "node_type", "derivation": "element_type"}


class ConfigChange(BaseModel):
    instruction: str | None = None
    example: str | None = None
    enabled: bool | None = None
    params: str | None = None
    input_graph_query: str | None = None
    batch_size: int | None = Field(default=None, ge=1)


class ScanRequest(BaseModel):
    texts: dict[str, str]


class DryRun(BaseModel):
    query: str | None = None


class Enabled(BaseModel):
    enabled: bool


def _name_key(step_type: str) -> str:
    if step_type not in NAME_KEY:
        raise HTTPException(status_code=404, detail=f"Unknown step type: {step_type}")
    return NAME_KEY[step_type]


@router.get("/{step_type}")
def list_configs(step_type: str, session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    key = _name_key(step_type)
    rows = session.get_extraction_configs() if step_type == "extraction" else session.get_derivation_configs()
    versions = session.get_config_versions().get(step_type, {})
    return [{"name": row[key], **row, "version": versions.get(row[key])} for row in rows]


@router.put("/{step_type}/{name}")
def save_config(step_type: str, name: str, change: ConfigChange, session: Any = Depends(get_session)) -> dict[str, Any]:
    _name_key(step_type)
    fields = change.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Nothing to change")
    if step_type == "extraction" and "input_graph_query" in fields:
        raise HTTPException(status_code=400, detail="Extraction steps have no candidate query")
    save = session.save_extraction_config if step_type == "extraction" else session.save_derivation_config
    try:
        result = save(
            name,
            **{k: getattr(change, k) for k in ("instruction", "example", "enabled", "params", "batch_size")},
            **({"input_graph_query": change.input_graph_query} if step_type == "derivation" else {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", f"Config not found: {name}"))
    return {"name": name, "old_version": result.get("old_version"), "new_version": result.get("new_version")}


@router.put("/{step_type}/{name}/enabled")
def set_enabled(step_type: str, name: str, body: Enabled, session: Any = Depends(get_session)) -> dict[str, Any]:
    _name_key(step_type)
    changed = session.enable_step(step_type, name) if body.enabled else session.disable_step(step_type, name)
    if not changed:
        raise HTTPException(status_code=404, detail=f"Step not found: {name}")
    return {"name": name, "enabled": body.enabled}


@router.get("/{step_type}/{name}/versions")
def config_versions(step_type: str, name: str, session: Any = Depends(get_session)) -> list[dict[str, Any]]:
    """Every version of the step, newest first."""
    _name_key(step_type)
    return session.get_config_history(step_type, name)


@router.post("/scan")
def scan(body: ScanRequest, session: Any = Depends(get_session)) -> dict[str, Any]:
    """Overfit scan of draft texts; ``available`` is false where the local scanner is missing."""
    return session.scan_prompt_texts(body.texts)


@router.post("/derivation/{name}/dry-run")
def dry_run(name: str, body: DryRun, session: Any = Depends(get_session)) -> dict[str, Any]:
    """The step's candidate query (or a draft of it) read-only, without LLM: row count and first rows."""
    query = body.query
    if query is None:
        row = next((r for r in session.get_derivation_configs() if r.get("element_type") == name), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Config not found: {name}")
        query = row.get("input_graph_query")
    if not query:
        raise HTTPException(status_code=400, detail=f"{name} has no candidate query")
    try:
        return session.dry_run_graph_query(query)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
