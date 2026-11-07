"""Ontology views for the studio: what the graph holds and what the model may hold.

The intermediate ontology lists every node type of the graph metamodel in its group (structure,
code, business, deployment) with what the graph holds of it, the extraction steps that wrote its
nodes and the derivation steps whose candidate query reads it; the edge types and the types they
connect are read from the graph itself. The output ontology is ArchiMate as Deriva
derives it: the element types per layer and aspect with the derivation steps that make them
(what the studio selects the derived part of the metamodel with), the relationship types with
their counts in the model, and the allowed relationships per pair of types (direct or derived)
from the ArchiMate 3.2 table.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from deriva.adapters.archimate.models import DERIVABLE_RELATIONSHIP_TYPES, ELEMENT_TYPES, RELATIONSHIP_TABLE, layer_of, relationship_tier
from deriva.adapters.database import DATA_DIR
from deriva.adapters.graph.metamodel import GROUP_ORDER, get_all_node_classes, get_node_properties, node_description, node_group

NAMESPACES = ("Graph", "Model")
SAMPLE_TEXT = 200
# Steps that make elements of a type besides the type's own step: a type's switch covers them too
TYPE_EXTRA_STEPS = {"BusinessActor": ("DocumentationActors",), "ApplicationComponent": ("ApplicationGrouping",), "BusinessFunction": ("BusinessFunctionModel",)}
# The types whose elements another type's are built on: with one of these off, the type comes out empty or partly so
TYPE_NEEDS = {
    "ApplicationInterface": ("ApplicationComponent",),
    "ApplicationFunction": ("ApplicationComponent",),
    "ApplicationService": ("ApplicationComponent", "ApplicationInterface"),
    "Artifact": ("ApplicationComponent",),
    "BusinessActor": ("ApplicationComponent", "ApplicationService"),  # Its Serving link at the enterprise level
    "BusinessObject": ("DataObject",),  # Its Access link at the enterprise level
}


def _short(value: Any) -> Any:
    return value[:SAMPLE_TEXT] + "…" if isinstance(value, str) and len(value) > SAMPLE_TEXT else value


def _types(labels: list[str]) -> list[str]:
    return [label for label in labels if label not in NAMESPACES]


def _step(config: dict[str, Any], versions: dict[str, int]) -> dict[str, Any]:
    name = config["node_type"]
    return {"name": name, "enabled": config["enabled"], "version": versions.get(name), "method": config.get("extraction_method")}


def intermediate_ontology(session: Any) -> dict[str, Any]:
    """Every node type of the graph metamodel (and any other label the graph holds) in its group: count, sample or
    properties, producing extraction steps (from the steps that wrote its nodes, else the step of its name), consuming
    derivation steps; the edge types with their endpoints, and the extraction steps that produce no node type."""
    run = session.query_graph_read_only
    counts: Counter[str] = Counter()
    writers: dict[str, set[str]] = {}
    for row in run("MATCH (n:Graph) RETURN labels(n) AS labels, n.extractSteps AS steps", None):
        for label in _types(row["labels"]):
            counts[label] += 1
            writers.setdefault(label, set()).update(str(s) for s in row.get("steps") or [])
    extraction = session.get_extraction_configs()
    derivation = session.get_derivation_configs()
    versions = session.get_config_versions().get("extraction", {})
    steps = {c["node_type"]: c for c in extraction}
    classes = get_all_node_classes()
    order = {group: i for i, group in enumerate(GROUP_ORDER)}

    node_types: list[dict[str, Any]] = []
    for label in sorted(set(classes) | set(counts), key=lambda name: (order.get(node_group(name), len(order)), name)):
        rows = run(f"MATCH (n:Graph:`{label}`) RETURN n LIMIT 1", None) if counts[label] else []
        sample = {k: _short(v) for k, v in rows[0]["n"].items() if not k.startswith("_")} if rows else {}
        # A query reads a type by matching it (n:Graph:Label) or by testing its labels ("Label" IN labels(n))
        pattern = re.compile(rf":`?(Graph:)?{re.escape(label)}\b|[\"']{re.escape(label)}[\"']\s+IN\s+labels\(")
        producers = sorted(writers.get(label) or ({label} if label in steps else set()))
        node_types.append(
            {
                "name": label,
                "group": node_group(label),
                "description": node_description(classes[label]) if label in classes else "",
                "count": counts[label],
                "properties": sorted(sample) if sample else (get_node_properties(classes[label]) if label in classes else []),
                "sample": sample,
                "producers": [_step(steps[name], versions) for name in producers if name in steps],
                "consumers": sorted(c["element_type"] for c in derivation if c.get("input_graph_query") and pattern.search(c["input_graph_query"])),
            }
        )

    edge_types = []
    for edge in sorted(run("MATCH (:Graph)-[r]->(:Graph) RETURN type(r) AS type, count(r) AS count", None), key=lambda r: r["type"]):
        pairs = run("MATCH (a:Graph)-[r]->(b:Graph) WHERE type(r) = $type RETURN DISTINCT labels(a) AS source, labels(b) AS target", {"type": edge["type"]})
        seen = sorted({(t[0], u[0]) for p in pairs if (t := _types(p["source"])) and (u := _types(p["target"]))})
        edge_types.append({"name": edge["type"].split(":", 1)[-1], "count": edge["count"], "pairs": [list(pair) for pair in seen]})

    produced = {p["name"] for t in node_types for p in t["producers"]}
    other_steps = [_step(c, versions) for c in extraction if c["node_type"] not in produced]
    return {"groups": list(GROUP_ORDER), "node_types": node_types, "edge_types": edge_types, "other_steps": other_steps}


def _shipped_steps() -> set[str]:
    """The derivation steps the release switches on: a layer switched back on gets these, not every step it has."""
    rows = json.loads((DATA_DIR / "derivation_config.json").read_text(encoding="utf-8"))
    return {row["step_name"] for row in rows if row.get("enabled")}


def output_ontology(session: Any) -> dict[str, Any]:
    """Element types per layer and aspect (count, the steps that make them, the types they need), relationship types
    (count) and the allowed relationships per pair of types."""
    counts = session.get_archimate_stats().get("by_type", {})
    # A step switched off keeps its version
    versions = session.get_config_versions(include_disabled=True).get("derivation", {})
    steps = {c["element_type"]: c for c in session.get_derivation_configs()}
    shipped = _shipped_steps()
    element_types = []
    for name in sorted({source for source, _ in RELATIONSHIP_TABLE}):
        step = steps.get(name)
        makers = [n for n in (name, *TYPE_EXTRA_STEPS.get(name, ())) if n in steps]
        element_types.append(
            {
                "name": name,
                "layer": layer_of(name),
                "aspect": ELEMENT_TYPES[name].aspect,
                "count": counts.get(name, 0),
                "step": {"enabled": step["enabled"], "version": versions.get(name)} if step else None,
                "steps": [{"name": n, "enabled": steps[n]["enabled"], "version": versions.get(n), "shipped": n in shipped} for n in makers],
                "needs": list(TYPE_NEEDS.get(name, ())),
            }
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
