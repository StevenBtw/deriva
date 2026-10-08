"""Ontology views for the studio: what the graph holds and what the model may hold.

The intermediate ontology is read from the graph itself (node labels, edge types and the
types they connect) and joined with the extraction steps that produce a node type and the
derivation steps whose candidate query reads it. The output ontology is ArchiMate as Deriva
derives it: the 13 element types per layer with their derivation step, the relationship
types with their counts in the model, and the allowed relationships per pair of types
(direct or derived) from the ArchiMate 3.2 table.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from deriva.adapters.archimate.models import DERIVABLE_RELATIONSHIP_TYPES, RELATIONSHIP_TABLE, relationship_tier
from deriva.services.benchmark_views import layer_of

NAMESPACES = ("Graph", "Model")
SAMPLE_TEXT = 200


def _short(value: Any) -> Any:
    return value[:SAMPLE_TEXT] + "…" if isinstance(value, str) and len(value) > SAMPLE_TEXT else value


def _types(labels: list[str]) -> list[str]:
    return [label for label in labels if label not in NAMESPACES]


def _step(config: dict[str, Any], versions: dict[str, int]) -> dict[str, Any]:
    name = config["node_type"]
    return {"name": name, "enabled": config["enabled"], "version": versions.get(name), "method": config.get("extraction_method")}


def intermediate_ontology(session: Any) -> dict[str, Any]:
    """Node types (count, sample, producing extraction steps, consuming derivation steps), edge types with their endpoints, and other extraction steps."""
    run = session.query_graph_read_only
    counts: Counter[str] = Counter()
    for row in run("MATCH (n:Graph) RETURN labels(n) AS labels", None):
        counts.update(_types(row["labels"]))
    extraction = session.get_extraction_configs()
    derivation = session.get_derivation_configs()
    versions = session.get_config_versions().get("extraction", {})

    node_types = []
    for label in sorted(counts):
        rows = run(f"MATCH (n:Graph:`{label}`) RETURN n LIMIT 1", None)
        sample = {k: _short(v) for k, v in rows[0]["n"].items() if not k.startswith("_")} if rows else {}
        pattern = re.compile(rf":`?(Graph:)?{re.escape(label)}\b")
        node_types.append(
            {
                "name": label,
                "count": counts[label],
                "properties": sorted(sample),
                "sample": sample,
                "producers": [_step(c, versions) for c in extraction if c["node_type"] == label],
                "consumers": sorted(c["element_type"] for c in derivation if c.get("input_graph_query") and pattern.search(c["input_graph_query"])),
            }
        )

    edge_types = []
    for row in sorted(run("MATCH (:Graph)-[r]->(:Graph) RETURN type(r) AS type, count(r) AS count", None), key=lambda r: r["type"]):
        pairs = run("MATCH (a:Graph)-[r]->(b:Graph) WHERE type(r) = $type RETURN labels(a) AS source, labels(b) AS target LIMIT 200", {"type": row["type"]})
        seen = sorted({(t[0], u[0]) for p in pairs if (t := _types(p["source"])) and (u := _types(p["target"]))})
        edge_types.append({"name": row["type"].split(":", 1)[-1], "count": row["count"], "pairs": [list(pair) for pair in seen]})

    other_steps = [_step(c, versions) for c in extraction if c["node_type"] not in counts]
    return {"node_types": node_types, "edge_types": edge_types, "other_steps": other_steps}


def output_ontology(session: Any) -> dict[str, Any]:
    """Element types per layer (count, derivation step), relationship types (count) and the allowed relationships per pair of types."""
    counts = session.get_archimate_stats().get("by_type", {})
    versions = session.get_config_versions().get("derivation", {})
    steps = {c["element_type"]: c for c in session.get_derivation_configs()}
    element_types = []
    for name in sorted({source for source, _ in RELATIONSHIP_TABLE}):
        step = steps.get(name)
        element_types.append(
            {"name": name, "layer": layer_of(name), "count": counts.get(name, 0), "step": {"enabled": step["enabled"], "version": versions.get(name)} if step else None}
        )
    relationship_counts = Counter(r.get("relationship_type") for r in session.get_archimate_relationships())
    rules = []
    for source, target in sorted(RELATIONSHIP_TABLE):
        tiers = {kind: relationship_tier(source, kind, target) for kind in DERIVABLE_RELATIONSHIP_TYPES}
        rules.append(
            {
                "source": source,
                "target": target,
                "direct": [k for k, tier in tiers.items() if tier == "direct"],
                "derived": [k for k, tier in tiers.items() if tier == "derived"],
            }
        )
    return {
        "element_types": element_types,
        "relationship_types": [{"name": kind, "count": relationship_counts.get(kind, 0)} for kind in DERIVABLE_RELATIONSHIP_TYPES],
        "rules": rules,
    }
