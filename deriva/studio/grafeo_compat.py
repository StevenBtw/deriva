"""Translate between Deriva's embedded grafeo results and anywidget-graph's grafeo server mode."""

from __future__ import annotations

import re
from typing import Any

NAMESPACES = ("Graph", "Model")
# Property that names a node when it has no "name" (the widget labels nodes by name, title or first label)
DISPLAY_KEYS = ("name", "techName", "conceptName", "typeName", "methodName", "fileName", "repositoryName", "path", "id")

_QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`")
_WRITE = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|INSERT|LOAD)\b", re.IGNORECASE)


def is_write_query(query: str) -> bool:
    """True when the query uses a write clause outside string literals and backticked names."""
    return _WRITE.search(_QUOTED.sub("", query)) is not None


def _strip_namespace(name: str) -> str:
    for ns in NAMESPACES:
        if name.startswith(f"{ns}:"):
            return name[len(ns) + 1 :]
    return name


def to_widget_value(value: Any) -> Any:
    """A grafeo node or edge in the shape anywidget-graph's server client parses; other values unchanged."""
    if isinstance(value, list):
        return [to_widget_value(v) for v in value]
    if isinstance(value, dict) and "_labels" in value:
        properties = {k: v for k, v in value.items() if not k.startswith("_")}
        if "name" not in properties:
            display = next((properties[k] for k in DISPLAY_KEYS if properties.get(k)), None)
            if display is not None:
                properties["name"] = display
        # The widget spreads properties over its node, so Deriva's own "id" would replace the graph id edges point at
        if "id" in properties:
            properties = {("deriva_id" if k == "id" else k): v for k, v in properties.items()}
        labels = [label for label in value["_labels"] if label not in NAMESPACES] or list(value["_labels"])
        return {"id": str(value["_id"]), "labels": labels, "properties": properties}
    if isinstance(value, dict) and "_type" in value and "_source" in value:
        properties = {k: v for k, v in value.items() if not k.startswith("_")}
        return {"id": str(value["_id"]), "type": _strip_namespace(value["_type"]), "start": str(value["_source"]), "end": str(value["_target"]), "properties": properties}
    return value


def to_widget_graph(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Unique nodes and the edges of every row, in the widget's ``nodes``/``edges`` format (as its result parser builds them)."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        converted = to_widget_value(value)
        if not isinstance(converted, dict):
            return
        if "labels" in converted and converted["id"] not in nodes:
            props = converted["properties"]
            nodes[converted["id"]] = {"id": converted["id"], "label": props.get("name", converted["id"]), "labels": converted["labels"], **props}
        elif "start" in converted:
            props = {("edge_id" if k == "id" else k): v for k, v in converted["properties"].items()}
            edges.append({"source": converted["start"], "target": converted["end"], "label": converted["type"], **props})

    for row in rows:
        for value in row.values():
            visit(value)
    return {"nodes": list(nodes.values()), "edges": edges}


def to_widget_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rows as ``{"columns", "rows"}`` with every value converted."""
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": [[to_widget_value(row.get(c)) for c in columns] for row in rows]}
