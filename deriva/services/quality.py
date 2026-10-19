"""Model quality: the verdict on a repository's model from its structure (see ``modules.derivation.quality``).

A report: it reads the model, the graph and the thresholds in system_settings, and writes nothing.
"""

from __future__ import annotations

from typing import Any

from deriva.adapters.archimate.models import ELEMENT_TYPES
from deriva.modules.derivation.quality import model_quality as _verdict
from deriva.services import config

__all__ = ["model_quality"]

# Located graph nodes that are evidence themselves; a folder-like node needs a source file under it
ARTIFACTS = frozenset({"File", "TypeDefinition", "Method"})


def _sources(properties: dict[str, Any]) -> list[str]:
    """An element's graph sources: its listed ``sources``, else its ``source``."""
    return [str(s) for s in properties.get("sources") or ([properties["source"]] if properties.get("source") else [])]


def model_quality(engine: Any, graph_manager: Any, archimate_manager: Any) -> dict[str, Any]:
    """The quality verdict of the model in the open graph database, with what it is based on."""
    elements = [
        {
            "id": e.identifier,
            "name": e.name,
            "type": e.element_type,
            "layer": ELEMENT_TYPES[e.element_type].layer if e.element_type in ELEMENT_TYPES else "",
            "sources": _sources(e.properties or {}),
        }
        for e in archimate_manager.get_elements()
        if e.enabled
    ]
    relationships = [{"source": r.source, "target": r.target, "type": r.relationship_type} for r in archimate_manager.get_relationships()]

    located = {r["id"]: r["p"] for r in graph_manager.query("MATCH (n:Graph) WHERE n.path IS NOT NULL RETURN n.id AS id, n.path AS p")}
    artifacts = set()
    for r in graph_manager.query("MATCH (n:Graph) WHERE n.filePath IS NOT NULL RETURN n.id AS id, n.filePath AS p, labels(n) AS l"):
        located[r["id"]] = r["p"]
        if ARTIFACTS & set(r.get("l") or []):
            artifacts.add(r["id"])
    source_files = [r["p"] for r in graph_manager.query("MATCH (f:Graph:File) WHERE f.fileType = 'source' RETURN f.filePath AS p") if r.get("p")]
    return _verdict(elements, relationships, located, artifacts, source_files, config.get_quality_thresholds(engine))
