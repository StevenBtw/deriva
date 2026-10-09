"""Ontology views: the intermediate graph's types and the output model's ArchiMate types and rules."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from deriva.studio.deps import get_session

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/intermediate")
def intermediate(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.intermediate_ontology()


@router.get("/output")
def output(session: Any = Depends(get_session)) -> dict[str, Any]:
    return session.output_ontology()
