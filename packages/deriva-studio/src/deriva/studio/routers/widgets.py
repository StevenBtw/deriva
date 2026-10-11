"""Front-end code of the two widgets the studio mounts, taken from the installed Python packages."""

from __future__ import annotations

from collections.abc import Callable
from functools import cache

import anywidget_archimate.ui as archimate_ui
import anywidget_graph.ui as graph_ui
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/widgets", tags=["widgets"])

WIDGETS: dict[str, tuple[Callable[[], str], Callable[[], str]]] = {
    "anywidget-graph": (graph_ui.get_esm, graph_ui.get_css),
    "anywidget-archimate": (archimate_ui.get_esm, archimate_ui.get_css),
}


@cache
def _asset(name: str, kind: str) -> str:
    esm, css = WIDGETS[name]
    return esm() if kind == "js" else css()


def _known(name: str) -> None:
    if name not in WIDGETS:
        raise HTTPException(status_code=404, detail=f"Unknown widget: {name}")


@router.get("/{name}/index.js")
def widget_module(name: str) -> Response:
    _known(name)
    return Response(_asset(name, "js"), media_type="text/javascript")


@router.get("/{name}/styles.css")
def widget_styles(name: str) -> Response:
    _known(name)
    return Response(_asset(name, "css"), media_type="text/css")
