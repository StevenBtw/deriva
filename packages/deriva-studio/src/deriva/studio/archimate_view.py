"""The model in anywidget-archimate's element and relationship format."""

from __future__ import annotations

from typing import Any

from anywidget_archimate.parser import LAYER_MAP


def to_widget_model(elements: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Enabled elements and the relationships between them, keyed as the widget's parser produces them."""
    shown = [e for e in elements if e.get("enabled", True)]
    ids = {e["identifier"] for e in shown}
    return {
        "elements": [
            {
                "id": e["identifier"],
                "name": e.get("name") or e["identifier"],
                "type": e["element_type"],
                "layer": LAYER_MAP.get(e["element_type"], "Other"),
                "documentation": e.get("documentation") or "",
                "source": (e.get("properties") or {}).get("source"),
            }
            for e in shown
        ],
        "relationships": [
            {"id": r["identifier"], "source": r["source"], "target": r["target"], "type": r["relationship_type"], "name": r.get("name") or ""}
            for r in relationships
            if r["source"] in ids and r["target"] in ids
        ],
    }
