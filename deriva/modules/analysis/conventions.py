"""ArchiMate convention checklist for derived models.

Checks one model snapshot (elements with type, name and source id; relationships with
type) against modelling conventions: size bands per type, names that are no
architecture element (files, artifacts, code suffixes, placeholder nodes, languages as
system software), technology services, unconnected elements, duplicates, one interface
per component and channel, data objects that realize a business object, nodes made from
a deployment unit, and the evidence behind business behaviour. Pure functions: the
caller passes the snapshots and the conventions (thresholds and pattern lists).
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

from deriva.common.naming import name_key

LAYERS: list[tuple[str, list[str]]] = [
    ("Business", ["BusinessActor", "BusinessProcess", "BusinessFunction", "BusinessEvent", "BusinessObject"]),
    ("Application", ["ApplicationComponent", "ApplicationInterface", "ApplicationService", "ApplicationFunction", "DataObject"]),
    ("Technology", ["Node", "Device", "SystemSoftware", "TechnologyService", "Artifact"]),
]
BEHAVIOUR = ("BusinessProcess", "BusinessFunction", "BusinessEvent")
STATUS_ORDER = {"fail": 3, "warn": 2, "info": 1, "pass": 0}


def _words(name: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)]


def _source_kind(source: str) -> str:
    prefix = source.split("::", 1)[0]
    return {"tech": "technology item", "file": "file", "dir": "directory", "concept": "concept", "typedef": "type", "method": "method"}.get(prefix, prefix or "none")


def _check(name: str, items: list[str], fail: bool = True, value: Any = None, target: str = "") -> dict[str, Any]:
    status = ("fail" if fail else "warn") if items else "pass"
    return {"check": name, "status": status, "value": len(items) if value is None else value, "target": target, "items": items}


def check_model(snapshot: dict[str, Any], conventions: dict[str, Any]) -> dict[str, Any]:
    """The checklist for one model: per check its status, value, target and the items behind it."""
    elements = [e for e in snapshot.get("elements", []) if e.get("identifier")]
    by_id = {e["identifier"]: e for e in elements}
    rels = [r for r in snapshot.get("relationships", []) if r.get("source") in by_id and r.get("target") in by_id]
    flags: dict[str, list[str]] = defaultdict(list)
    label = {e["identifier"]: f"{e['name']} ({e['type']})" for e in elements}

    def flag(identifier: str, check: str) -> None:
        if check not in flags[identifier]:
            flags[identifier].append(check)

    counts: dict[str, int] = defaultdict(int)
    for e in elements:
        counts[e["type"]] += 1
    checks: list[dict[str, Any]] = []

    # Size bands (warn only)
    bands = conventions.get("bands", {})
    for key, (low, high) in bands.items():
        value = len(elements) if key == "total" else counts.get(key, 0)
        checks.append({"check": f"size: {key}", "status": "pass" if low <= value <= high else "warn", "value": value, "target": f"{low}-{high}", "items": []})

    # Technology services: none
    forbidden_types = set(conventions.get("forbidden_types", []))
    hits = [e for e in elements if e["type"] in forbidden_types]
    for e in hits:
        flag(e["identifier"], "technology services")
    checks.append(_check("technology services", sorted(e["name"] for e in hits), target="0"))

    # Names that are no architecture element
    extensions = "|".join(re.escape(x) for x in conventions.get("file_extensions", []))
    ext_pattern = re.compile(rf"\.({extensions})$", re.IGNORECASE) if extensions else None
    artifacts = [a.lower() for a in conventions.get("artifact_names", [])]
    suffixes = {s.lower() for s in conventions.get("suffixes", [])}
    placeholders = {p.lower() for p in conventions.get("placeholder_names", [])}
    languages = {name_key(x) for x in conventions.get("languages", [])}
    technology_types = set(conventions.get("technology_types", []))
    forbidden: list[str] = []
    for e in sorted(elements, key=lambda x: (x["type"], x["name"])):
        name, low, source = e["name"], e["name"].lower().strip(), str(e.get("source") or "")
        reasons = []
        if ext_pattern and ext_pattern.search(low) and source.startswith("file::"):
            reasons.append("file name")
        if any(a in low for a in artifacts):
            reasons.append("build or container artifact")
        if e["type"] in technology_types and source.startswith("file::") and "file name" not in reasons:
            reasons.append("file as a technology element")
        words = _words(name)
        if words and words[-1] in suffixes:
            reasons.append(f"code suffix '{words[-1]}'")
        if low in placeholders:
            reasons.append("placeholder name")
        if e["type"] == "SystemSoftware" and name_key(name) in languages:
            reasons.append("language as system software")
        if reasons:
            forbidden.append(f"{name} ({e['type']}): {', '.join(reasons)}")
            flag(e["identifier"], "forbidden patterns")
    checks.append(_check("forbidden patterns", forbidden, target="0"))

    # Every element in at least one relationship
    linked = {r["source"] for r in rels} | {r["target"] for r in rels}
    orphans = sorted(label[e["identifier"]] for e in elements if e["identifier"] not in linked)
    for e in elements:
        if e["identifier"] not in linked:
            flag(e["identifier"], "unconnected elements")
    checks.append(_check("unconnected elements", orphans, target="0"))

    # Exact duplicates: within a type, and one name across two types
    realized = {(r["source"], r["target"]) for r in rels if r["type"] == "Realization"}
    exact: list[str] = []
    by_type_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in elements:
        by_type_key[(e["type"], name_key(e["name"]))].append(e)
    for (kind, _), group in sorted(by_type_key.items()):
        if len(group) > 1:
            exact.append(f"{kind}: {' = '.join(sorted(g['name'] for g in group))}")
            for g in group:
                flag(g["identifier"], "exact duplicates")
    # Across any two types one name is a duplicate, except a data object that realizes its business object
    types_by_key: dict[str, list[str]] = defaultdict(list)
    for kind, key in sorted(by_type_key):
        if key:
            types_by_key[key].append(kind)
    for key, kinds in sorted(types_by_key.items()):
        for i, first in enumerate(kinds):
            for second in kinds[i + 1 :]:
                needs_link = (first, second) == ("BusinessObject", "DataObject")
                for a in by_type_key[(first, key)]:
                    for b in by_type_key[(second, key)]:
                        if needs_link and ((b["identifier"], a["identifier"]) in realized or (a["identifier"], b["identifier"]) in realized):
                            continue
                        note = ", no Realization" if needs_link else ""
                        exact.append(f"{a['name']}: {first} and {second}{note}")
                        flag(a["identifier"], "exact duplicates")
                        flag(b["identifier"], "exact duplicates")
    checks.append(_check("exact duplicates", exact, target="0"))

    # Spelling variants within a type (warn only: pairs such as a backend and its frontend look alike)
    ratio = float(conventions.get("fuzzy_ratio", 0.85))
    variants: list[str] = []
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in elements:
        by_type[e["type"]].append(e)
    for kind, group in sorted(by_type.items()):
        ordered = sorted(group, key=lambda x: x["name"])
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                ka, kb = name_key(a["name"]), name_key(b["name"])
                if ka == kb:
                    continue
                wa, wb = set(_words(a["name"])), set(_words(b["name"]))
                if (wa and wb and (wa < wb or wb < wa)) or SequenceMatcher(None, ka, kb).ratio() >= ratio:
                    variants.append(f"{kind}: {a['name']} ~ {b['name']}")
    checks.append(_check("spelling variants", variants, fail=False, target="0"))

    # One interface per component and channel
    channels = sorted(((pattern.lower(), channel) for channel, patterns in conventions.get("channels", {}).items() for pattern in patterns), key=lambda x: -len(x[0]))

    def channel_of(name: str) -> str:
        low = name.lower().strip()
        # The pattern ends the name as whole words ("interest" is no "rest")
        return next((channel for pattern, channel in channels if re.search(rf"\b{re.escape(pattern)}$", low)), "other")

    owners: dict[str, set[str]] = defaultdict(set)
    for r in rels:
        s, t = by_id[r["source"]], by_id[r["target"]]
        if s["type"] == "ApplicationComponent" and t["type"] == "ApplicationInterface":
            owners[t["identifier"]].add(s["name"])
        elif t["type"] == "ApplicationComponent" and s["type"] == "ApplicationInterface":
            owners[s["identifier"]].add(t["name"])
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    # Interfaces without a component share no owner: they are not grouped
    for e in by_type.get("ApplicationInterface", []):
        for owner in sorted(owners.get(e["identifier"], set())):
            groups[(owner, channel_of(e["name"]))].append(e)
    per_channel = []
    for (owner, channel), group in sorted(groups.items()):
        if len(group) > 1:
            per_channel.append(f"{owner} · {channel}: {', '.join(sorted(g['name'] for g in group))}")
            for g in group:
                flag(g["identifier"], "interfaces per component and channel")
    checks.append(_check("interfaces per component and channel", per_channel, target="1 each"))

    # Every data object realizes a business object
    business = {e["identifier"] for e in by_type.get("BusinessObject", [])}
    loose = [e for e in by_type.get("DataObject", []) if not any(src == e["identifier"] and tgt in business for src, tgt in realized)]
    for e in loose:
        flag(e["identifier"], "data objects without a business object")
    checks.append(_check("data objects without a business object", sorted(e["name"] for e in loose), target="0"))

    # Every node is made from a deployment unit
    units = tuple(conventions.get("deployment_unit_prefixes", []))
    nodes = [e for e in by_type.get("Node", []) if not (units and str(e.get("source") or "").startswith(units))]
    for e in nodes:
        flag(e["identifier"], "nodes without a deployment unit")
    checks.append(_check("nodes without a deployment unit", sorted(f"{e['name']} ({_source_kind(str(e.get('source') or ''))})" for e in nodes), target="0"))

    # Business behaviour and its evidence (reported, not judged)
    behaviour = sorted(
        f"{e['name']} ({e['type']}, {'concept' if str(e.get('source') or '').startswith('concept::') else 'structural'})" for e in elements if e["type"] in BEHAVIOUR
    )
    checks.append({"check": "business behaviour evidence", "status": "info", "value": len(behaviour), "target": "", "items": behaviour})

    return {"total": len(elements), "counts": dict(counts), "checks": checks, "flags": dict(flags)}


def check_runs(runs: dict[str, dict[str, Any]], conventions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The checklist per run label (one snapshot each)."""
    return {run: check_model(snapshot, conventions) for run, snapshot in runs.items()}


def _cell(check: dict[str, Any]) -> str:
    return check["status"] if check["status"] in ("pass", "info") and not check["value"] else f"{check['status']} {check['value']}"


def render_review(repository: str, model: str, results: dict[str, dict[str, Any]], runs: dict[str, dict[str, Any]]) -> str:
    """A review page for one repository: the checklist per run, what failed, and the elements by layer with their source."""
    labels = list(results)
    first = results[labels[0]] if labels else {"checks": []}
    lines = [f"# Convention review: {repository}", "", f"Model {model}, runs {', '.join(labels)}.", "", "## Checklist", ""]
    lines.append("| check | " + " | ".join(labels) + " | target |")
    lines.append("|---|" + "---|" * len(labels) + "---|")
    for i, check in enumerate(first["checks"]):
        cells = [_cell(results[label]["checks"][i]) for label in labels]
        lines.append(f"| {check['check']} | " + " | ".join(cells) + f" | {check['target']} |")

    lines += ["", "## Findings", ""]
    any_finding = False
    for i, check in enumerate(first["checks"]):
        seen: dict[str, int] = defaultdict(int)
        for label in labels:
            for item in results[label]["checks"][i]["items"]:
                seen[item] += 1
        if not seen:
            continue
        any_finding = True
        status = max((results[label]["checks"][i]["status"] for label in labels), key=lambda s: STATUS_ORDER[s])
        lines.append(f"### {check['check']} ({status})")
        lines.append("")
        lines += [f"- {item}" + (f" ({n}/{len(labels)} runs)" if n != len(labels) else "") for item, n in sorted(seen.items())]
        lines.append("")
    if not any_finding:
        lines += ["Nothing to report.", ""]

    # Elements by layer and type, keyed by type and source over the runs
    present: dict[tuple[str, str], dict[str, Any]] = {}
    runs_of: dict[tuple[str, str], int] = defaultdict(int)
    for label in labels:
        snapshot = runs[label]
        degree: dict[str, int] = defaultdict(int)
        for r in snapshot.get("relationships", []):
            degree[r.get("source")] += 1
            degree[r.get("target")] += 1
        for e in snapshot.get("elements", []):
            key = (e["type"], str(e.get("source") or e["identifier"]))
            runs_of[key] += 1
            if key not in present:
                present[key] = {"element": e, "degree": degree.get(e["identifier"], 0), "flags": results[label]["flags"].get(e["identifier"], [])}
    lines += ["## Elements", ""]
    known = [t for _, types in LAYERS for t in types]
    layers = [*LAYERS, ("Other", sorted({t for t, _ in present} - set(known)))]
    for layer, types in layers:
        rows = [(key, value) for key, value in present.items() if key[0] in types]
        if not rows:
            continue
        lines += [f"### {layer}", ""]
        for kind in types:
            of_type = sorted((value for key, value in rows if key[0] == kind), key=lambda v: v["element"]["name"].lower())
            if not of_type:
                continue
            lines += [f"**{kind}** ({len(of_type)})", "", "| name | source | relationships | runs | flags |", "|---|---|---|---|---|"]
            for value in of_type:
                e = value["element"]
                key = (e["type"], str(e.get("source") or e["identifier"]))
                lines.append(f"| {e['name']} | {key[1]} | {value['degree']} | {runs_of[key]}/{len(labels)} | {', '.join(value['flags'])} |")
            lines.append("")
    return "\n".join(lines)


def render_summary(results_by_repository: dict[str, dict[str, dict[str, Any]]]) -> str:
    """One row per repository: elements per run and, per check, the worst status over the runs with its largest value."""
    names: list[str] = []
    for results in results_by_repository.values():
        for result in results.values():
            names = [c["check"] for c in result["checks"]]
            break
        if names:
            break
    lines = ["| repository | elements | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    for repository, results in sorted(results_by_repository.items()):
        totals = "/".join(str(r["total"]) for r in results.values())
        cells = []
        for i in range(len(names)):
            checks = [r["checks"][i] for r in results.values()]
            worst = max(checks, key=lambda c: (STATUS_ORDER[c["status"]], c["value"] if isinstance(c["value"], int) else 0))
            cells.append(_cell(worst))
        lines.append(f"| {repository} | {totals} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
