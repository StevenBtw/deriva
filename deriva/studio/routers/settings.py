"""System settings and the file type registry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deriva.studio.deps import get_session

router = APIRouter(prefix="/api", tags=["settings"])


class SettingValue(BaseModel):
    value: str


class FileTypeIn(BaseModel):
    extension: str
    file_type: str
    subtype: str


class FileTypeUpdate(BaseModel):
    file_type: str
    subtype: str


@router.get("/settings/{key}")
def get_setting(key: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    return {"key": key, "value": session.get_setting(key)}


@router.put("/settings/{key}")
def set_setting(key: str, body: SettingValue, session: Any = Depends(get_session)) -> dict[str, Any]:
    session.set_setting(key, body.value)
    return {"key": key, "value": body.value}


@router.get("/filetypes")
def list_file_types(session: Any = Depends(get_session)) -> dict[str, Any]:
    return {"file_types": session.get_file_types(), "stats": session.get_file_type_stats()}


@router.post("/filetypes", status_code=201)
def add_file_type(body: FileTypeIn, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.add_file_type(body.extension, body.file_type, body.subtype):
        raise HTTPException(status_code=409, detail=f"File type exists: {body.extension}")
    return body.model_dump()


@router.put("/filetypes/{extension}")
def update_file_type(extension: str, body: FileTypeUpdate, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.update_file_type(extension, body.file_type, body.subtype):
        raise HTTPException(status_code=404, detail=f"File type not found: {extension}")
    return {"extension": extension, **body.model_dump()}


@router.delete("/filetypes/{extension}")
def delete_file_type(extension: str, session: Any = Depends(get_session)) -> dict[str, Any]:
    if not session.delete_file_type(extension):
        raise HTTPException(status_code=404, detail=f"File type not found: {extension}")
    return {"extension": extension, "deleted": True}
