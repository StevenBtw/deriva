"""Run-to-run consistency of benchmark model snapshots, and the flips behind it.

Consistency = objects present in every run / objects in any run, reported for elements and
relationships by name identity (type + name) and by source identity (type + source graph
node), per element type, per relationship provenance (``derived_from``), and for the
LLM-created graph nodes (concepts, technologies, per extraction route).

A flip is an element (by source identity) that is not in every run. Each run that misses
it gets a cause from its own snapshot: the candidate's stage, no candidate at all, or a
source node the run never extracted. When the run's LLM calls are known, the deciding
calls of a run with the element and a run without it are compared: the same prompt with
a different answer points at the LLM, a different prompt points upstream.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

HEADLINE = ("graph_concepts", "graph_concept_types", "graph_technologies", "el_name", "el_source", "rel_name", "rel_source")
BREAKDOWN_PREFIXES = ("route:", "type:", "prov:")


def run_sets(snapshot: dict[str, Any]) -> dict[str, set]:
    """The identity sets of one run's snapshot (elements, relationships, graph nodes and their breakdowns)."""
    by_id = {e["identifier"]: e for e in snapshot.get("elements", [])}
    out: dict[str, set] = defaultdict(set)
    for e in snapshot.get("elements", []):
        out["el_name"].add((e["type"], e["name"].strip().lower()))
        out["el_source"].add((e["type"], e["source"]))
        out[f"type:{e['type']}"].add(e["name"].strip().lower())
    for r in snapshot.get("relationships", []):
        s, t = by_id.get(r["source"], {}), by_id.get(r["target"], {})
        out["rel_name"].add((r["type"], s.get("name", "").strip().lower(), t.get("name", "").strip().lower()))
        out["rel_source"].add((r["type"], s.get("source"), t.get("source")))
        out[f"prov:{r.get('derived_from') or 'unknown'}"].add((r["type"], s.get("source"), t.get("source")))
    graph = snapshot.get("graph") or {}
    out["graph_concepts"] = {c[0] for c in graph.get("concepts", [])}
    out["graph_concept_types"] = {(c[0], tuple(c[1])) for c in graph.get("concepts", [])}
    out["graph_technologies"] = set(graph.get("technologies", []))
    # Per extraction route (directory, document, structural, llm); a node from two routes counts in both
    for kind in ("concept", "technology"):
        for node, routes in graph.get(f"{kind}_routes", {}).items():
            for route in routes:
                out[f"route:{kind}:{route}"].add(node)
    return dict(out)


def _score(runs: list[set]) -> tuple[int, int, float]:
    union = set().union(*runs)
    common = set.intersection(*runs) if runs else set()
    return len(common), len(union), (len(common) / len(union) if union else 1.0)


def consistency_rows(runs: list[dict[str, set]]) -> list[dict[str, Any]]:
    """Consistency per identity: the headline rows first, then the breakdowns (route, type, provenance) by key."""
    breakdown = sorted({k for r in runs for k in r if k.startswith(BREAKDOWN_PREFIXES)})
    rows = []
    for key in (*HEADLINE, *breakdown):
        common, union, score = _score([r.get(key, set()) for r in runs])
        rows.append({"key": key, "common": common, "union": union, "score": score})
    return rows


def mentions(prompt: str, term: str) -> bool:
    """Whether ``term`` occurs in ``prompt`` as a whole word (case-insensitive)."""
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", prompt, re.IGNORECASE) is not None


def _missing_cause(snapshot: dict[str, Any], element_type: str, source: str) -> str:
    candidates = [c for c in snapshot.get("candidates", []) if c.get("type") == element_type and c.get("source") == source]
    if candidates and candidates[-1].get("refine"):
        return f"disabled in refine ({candidates[-1]['refine']})"
    if candidates:
        return f"candidate {candidates[-1].get('stage')}"
    graph = snapshot.get("graph") or {}
    if source.startswith("tech::") and "technologies" in graph and source not in graph["technologies"]:
        return "source not extracted"
    if source.startswith("concept::") and "concepts" in graph and source not in {c[0] for c in graph["concepts"]}:
        return "source not extracted"
    return "not a candidate"


def _deciding_call(calls: list[dict[str, Any]], element_type: str, source: str) -> dict[str, Any] | None:
    return next((c for c in calls if c.get("step") == element_type and mentions(c.get("prompt") or "", source)), None)


def _llm_verdict(present: list[str], missing: list[str], calls: dict[str, list[dict[str, Any]]], element_type: str, source: str) -> str | None:
    def first(labels: list[str]) -> dict[str, Any] | None:
        return next((call for label in labels if (call := _deciding_call(calls.get(label, []), element_type, source))), None)

    kept, dropped = first(present), first(missing)
    if kept is None or dropped is None:
        return None
    if kept.get("cache_key") != dropped.get("cache_key"):
        return "different prompt"
    return "same prompt, different answer" if kept.get("response") != dropped.get("response") else "same prompt, same answer"


def element_flips(runs: dict[str, dict[str, Any]], calls: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Elements (by type and source) that are not in every run, each with the cause per missing run."""
    labels = list(runs)
    names: dict[str, dict[tuple[str, str], str]] = {label: {(e["type"], e["source"]): e["name"] for e in runs[label].get("elements", [])} for label in labels}
    sources_by_name: dict[str, dict[tuple[str, str], set[str]]] = {label: _sources_by_name(runs[label].get("elements", [])) for label in labels}
    flips = []
    for key in sorted(set().union(*(set(n) for n in names.values()))):
        present = [label for label in labels if key in names[label]]
        if len(present) == len(labels):
            continue
        element_type, source = key
        missing = {label: _missing_cause(runs[label], element_type, source) for label in labels if label not in present}
        element_names = {label: names[label][key] for label in present}
        also_from = {}
        for label in missing:
            other = sources_by_name[label].get((element_type, next(iter(element_names.values())).strip().lower()), set()) - {source}
            if other:
                also_from[label] = sorted(other)[0]
        llm = _llm_verdict(present, list(missing), calls, element_type, source)
        by_cause: dict[str, list[str]] = defaultdict(list)
        for label, cause in missing.items():
            by_cause[cause].append(label)
        line = f"{element_type}: " + "; ".join(f"{cause} in {', '.join(ls)}" for cause, ls in by_cause.items()) + (f" ({llm})" if llm else "")
        flips.append(
            {
                "type": element_type,
                "source": source,
                "names": element_names,
                "present": present,
                "missing": missing,
                "also_from": also_from,
                "llm": llm,
                "cause": line,
            }
        )
    return flips


def _sources_by_name(elements: list[dict[str, Any]]) -> dict[tuple[str, str], set[str]]:
    out: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in elements:
        out[(e["type"], e["name"].strip().lower())].add(e["source"])
    return out
