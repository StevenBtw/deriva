"""System settings and the file type registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deriva.services import config
from deriva.studio.deps import get_session

router = APIRouter(prefix="/api", tags=["settings"])


class SettingValue(BaseModel):
    value: str


class FileTypeIn(BaseModel):
    extension: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    subtype: str


class FileTypeUpdate(BaseModel):
    file_type: str = Field(min_length=1)
    subtype: str


@router.get("/settings/{key}")
def get_setting(key: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    # With the value that applies while it is not set (excluded directories have a built-in list)
    return {"key": key, "value": session.get_setting(key), "default": config.setting_default(key)}


@router.put("/settings/{key}")
def set_setting(key: str, body: SettingValue, session: Any = Depends(get_session)) -> dict[str, Any]:
    try:
        session.set_setting(key, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"key": key, "value": body.value}


@router.get("/filetypes")
def list_file_types(session: Any = Depends(get_session)) -> dict[str, Any]:
    return {"file_types": session.get_file_types(), "stats": session.get_file_type_stats()}


@router.post("/filetypes", status_code=201)
def add_file_type(body: FileTypeIn, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.add_file_type(body.extension, body.file_type, body.subtype):
        raise HTTPException(status_code=409, detail=f"File type exists: {body.extension}")
    return body.model_dump()


# Keys are extensions or path patterns (path:**/tests/**), so the key may hold slashes
@router.put("/filetypes/{extension:path}")
def update_file_type(extension: str, body: FileTypeUpdate, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.update_file_type(extension, body.file_type, body.subtype):
        raise HTTPException(status_code=404, detail=f"File type not found: {extension}")
    return {"extension": extension, **body.model_dump()}


@router.delete("/filetypes/{extension:path}")
def delete_file_type(extension: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.delete_file_type(extension):
        raise HTTPException(status_code=404, detail=f"File type not found: {extension}")
    return {"extension": extension, "deleted": True}
