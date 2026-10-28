"""Translate between Deriva's embedded grafeo results and anywidget-graph's grafeo server mode."""

from __future__ import annotations

import re
from typing import Any

NAMESPACES = ("Graph", "Model")
# Property that names a node when it has no "name" (the widget labels nodes by name, title or first label); methodName
# before typeName, since a method also carries its class's typeName
DISPLAY_KEYS = ("name", "techName", "conceptName", "methodName", "typeName", "fileName", "repoName", "repositoryName", "dependencyName", "path", "id")

# String literals, backticked names and comments: write words there are no clauses (scanned left to right,
# so a // inside a string stays part of the string)
_SKIPPED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`|//[^\n]*|/\*.*?\*/", re.DOTALL)
_WRITE = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|INSERT|LOAD)\b", re.IGNORECASE)


def is_write_query(query: str) -> bool:
    """True when the query uses a write clause outside string literals, backticked names and comments."""
    return _WRITE.search(_SKIPPED.sub(" ", query)) is not None


def _strip_namespace(name: str) -> str:
    for ns in NAMESPACES:
        if name.startswith(f"{ns}:"):
            return name[len(ns) + 1 :]
    return name


def to_widget_value(value: Any) -> Any:
    """A grafeo node or edge in the shape anywidget-graph's server client parses; other values unchanged."""
    if isinstance(value, list):
        return [to_widget_value(v) for v in value]
    if isinstance(value, dict) and "_labels" in value and "_id" in value:
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


def to_server_value(value: Any) -> Any:
    """A grafeo node or edge in grafeo-server's own result shape, which the widget's server client parses: ``_id`` and
    ``_labels`` (nodes) or ``_id``, ``_type``, ``_source`` and ``_target`` (edges), properties flat on the item.
    Namespaces are stripped, a node without a name gets a display name, and Deriva's own ``id`` stays visible as
    ``deriva_id`` (the widget keys nodes by ``_id`` and drops a property named ``id``)."""
    if isinstance(value, list):
        return [to_server_value(v) for v in value]
    if isinstance(value, dict) and "_labels" in value and "_id" in value:
        properties = {("deriva_id" if k == "id" else k): v for k, v in value.items() if not k.startswith("_")}
        if "name" not in properties:
            display = next((value[k] for k in DISPLAY_KEYS if value.get(k)), None)
            if display is not None:
                properties["name"] = display
        labels = [label for label in value["_labels"] if label not in NAMESPACES] or list(value["_labels"])
        return {"_id": value["_id"], "_labels": labels, **properties}
    if isinstance(value, dict) and "_type" in value and "_source" in value:
        properties = {("deriva_id" if k == "id" else k): v for k, v in value.items() if not k.startswith("_")}
        return {"_id": value.get("_id"), "_type": _strip_namespace(value["_type"]), "_source": value["_source"], "_target": value["_target"], **properties}
    return value


def to_widget_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Rows as ``{"columns", "rows"}`` with every node and edge in grafeo-server's shape (the widget's query box)."""
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "rows": [[to_server_value(row.get(c)) for c in columns] for row in rows]}
