"""The gate for a change: recall, precision and consistency per repository, a candidate against a baseline.

Per repository (read-only, from the sessions' run snapshots):

- **A development reference** (``<goldens>/<name>.json``, the reference format of ``reference_eval``): element and
  relationship recall and precision as ``reference_eval`` counts them, the mean over the runs.
- **A golden model** (``<reference>/<repository>.archimate``): recall on the derivable subset the user labelled
  (``<repository>.derivable.json``) with the user's accepted names (``<repository>.matches.json``), and precision.
  A golden relationship is found when a derived relationship of its type and direction joins the derived elements
  matched to its two ends; it is in the subset when both ends are. Without the user's files the ``.template.json``
  versions are read and the result is provisional: the subset is then the elements of the derived types and the
  relationships between two of them.
- **Consistency by id**: the share of elements and of relationships in every run (``session_metrics``).

A repository without either reference keeps its consistency and is left out of the count. The verdict: the change is
accepted when one of the four measures (element or relationship recall or precision) rises by at least the given
points on enough of the measured repositories, none of the four drops by more than the allowed points anywhere, and
consistency stays at the minimum everywhere.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deriva.bench import reference_eval, session_metrics
from deriva.common.naming import name_key
from deriva.modules.analysis.semantic_matching import match_elements, parse_archi_xml, parse_exchange_format_xml

MEASURES = ("recall", "precision", "relationship_recall", "relationship_precision")
GATE_LEVELS = ("enterprise", "solution", "union")  # Each is measured and judged; levels without a measure do not vote
LABELS = {"recall": "recall", "precision": "precision", "relationship_recall": "relationship recall", "relationship_precision": "relationship precision"}


@dataclass(frozen=True)
class GateRules:
    """The acceptance rule."""

    better_share: float = 2 / 3  # Of the measured repositories, at least this share better on one of the measures (6 of 9)
    min_rise: float = 1.0  # Points a measure must rise to count as better (a smaller move holds)
    max_drop: float = 2.0  # Points any measure may drop on any repository
    min_consistency: float = 0.95  # Element and relationship consistency by id on every repository


def _user_file(folder: Path, repository: str, kind: str) -> tuple[dict[str, Any], bool]:
    """The user's file (matches or derivable), else its template; True when the template was read."""
    for name, template in ((f"{repository}.{kind}.json", False), (f"{repository}.{kind}.template.json", True)):
        path = folder / name
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8")), template
            except ValueError:
                return {}, True
    return {}, True


def _golden_model(path: Path) -> tuple[list[Any], list[Any]]:
    elements, relationships = parse_archi_xml(path)
    return (elements, relationships) if elements else parse_exchange_format_xml(path)


def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 3) if known else None


def golden_relationships(
    derived: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    reference: list[Any],
    golden: list[Any],
    aliases: dict[str, Any],
    scope: set[str],
) -> dict[str, Any]:
    """Relationship recall over the golden relationships with both ends in ``scope``, and precision over all derived ones.

    A derived element maps to the golden element the element matcher gives it (same type, same or similar name) or
    whose accepted names (``aliases``) hold its name; a derived relationship is right when a golden relationship of
    its type joins the golden elements of its source and target, in that direction.
    """
    to_golden: dict[str, set[str]] = {}
    for m in match_elements(derived, reference):
        if m.match_type in session_metrics.NAME_MATCHES and m.derived_type == m.reference_type and m.reference_id:
            to_golden.setdefault(m.derived_id, set()).add(m.reference_id)
    by_key: dict[tuple[str, str], list[str]] = {}
    for d in derived:
        by_key.setdefault((d["type"], name_key(str(d.get("name") or ""))), []).append(d["id"])
    for r in reference:
        names = aliases.get(r.identifier)
        for alias in names if isinstance(names, list) else []:
            for derived_id in by_key.get((r.element_type, name_key(str(alias))), []):
                to_golden.setdefault(derived_id, set()).add(r.identifier)
    wanted = {(g.source, g.relationship_type, g.target) for g in golden}
    found: set[tuple[str, str, str]] = set()
    correct = 0
    for rel in relationships:
        kind = str(rel["type"]).removeprefix("Model:")
        pairs = {(a, kind, b) for a in to_golden.get(rel["source"], ()) for b in to_golden.get(rel["target"], ())} & wanted
        found |= pairs
        correct += bool(pairs)
    required = [g for g in golden if g.source in scope and g.target in scope]
    hits = sum(1 for g in required if (g.source, g.relationship_type, g.target) in found)
    return {
        "required": len(required),
        "matched": hits,
        "recall": round(hits / len(required), 3) if required else None,
        "derived": len(relationships),
        "correct": correct,
        "precision": round(correct / len(relationships), 3) if relationships else None,
    }


def _golden_row(path: Path, reference_dir: Path, repo: str, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    reference, golden_rels = _golden_model(path)
    aliases, alias_template = _user_file(reference_dir, repo, "matches")
    derivable, derivable_template = _user_file(reference_dir, repo, "derivable")
    provisional = alias_template or derivable_template
    if provisional:
        scope = {r.identifier for r in reference if r.element_type in session_metrics.DERIVED_TYPES}
    else:
        scope = {r.identifier for r in reference if isinstance(derivable.get(r.identifier), dict) and derivable[r.identifier].get("derivable")}
    elements, relationships = [], []
    for snapshot in snapshots:
        derived = [{"id": e["identifier"], "name": e.get("name"), "type": str(e["type"]).removeprefix("Model:")} for e in snapshot.get("elements", [])]
        elements.append(session_metrics.golden_comparison(derived, reference, aliases=aliases, derivable=derivable))
        relationships.append(golden_relationships(derived, snapshot.get("relationships", []), reference, golden_rels, aliases, scope))
    recall_key = "derivable_types_recall" if provisional else "derivable_recall"
    return {
        "source": "golden",
        "provisional": provisional,
        "recall": _mean([r[recall_key] for r in elements]),
        "precision": _mean([r["precision"] for r in elements]),
        "relationship_recall": _mean([r["recall"] for r in relationships]),
        "relationship_precision": _mean([r["precision"] for r in relationships]),
    }


def measure(sessions: list[Path], goldens_dir: Path, reference_dir: Path, model: str | None = None, *, level: str | None = None) -> dict[str, dict[str, Any]]:
    """Per repository of the sessions: its model, runs, source of the measure, the four measures and consistency by id.

    ``level`` (``enterprise``, ``solution`` or ``union``) measures one abstraction level; ``None`` measures everything,
    as before levels existed. A reference with no element at the level has no measure there; golden models carry no
    levels yet, so they have no solution measure.
    """
    sessions = [Path(s) for s in sessions]
    runs: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for session in sessions:
        for repo, run_model, _, snapshot in session_metrics.run_snapshots(session):
            runs.setdefault(repo, {}).setdefault(run_model, []).append(snapshot)
    references = reference_eval.load_references(goldens_dir) if Path(goldens_dir).is_dir() else {}
    consistency = {(r["repository"], r["model"]): r["identities"]["id"] for r in session_metrics.consistency_rows(sessions)}

    out: dict[str, dict[str, Any]] = {}
    for repo, by_model in sorted(runs.items()):
        if model is not None:
            snapshots = by_model.get(model, [])
            if not snapshots:
                continue
            chosen = model
        elif len(by_model) > 1:
            raise ValueError(f"{repo} has runs of several models ({', '.join(sorted(by_model))}): name one with --model")
        else:
            ((chosen, snapshots),) = by_model.items()
        row: dict[str, Any] = {"repository": repo, "model": chosen, "runs": len(snapshots), "source": None, "provisional": False} | dict.fromkeys(MEASURES)
        golden = Path(reference_dir) / f"{repo}.archimate"
        has_level = level in (None, "union") or (repo in references and any(level in e.levels for e in references[repo].elements))
        if repo in references and not has_level:
            pass  # no reference at this level
        elif repo in references:
            results = [reference_eval.evaluate(references[repo], s, level=level) for s in snapshots]
            row |= {
                "source": "reference",
                "recall": _mean([r["element_recall"] for r in results]),
                "precision": _mean([r["element_precision"] for r in results]),
                "relationship_recall": _mean([r["relationship_recall"] for r in results]),
                "relationship_precision": _mean([r["relationship_totals"]["precision"] for r in results]),
            }
        elif golden.is_file() and level != "solution":
            row |= _golden_row(golden, Path(reference_dir), repo, snapshots)
        ids = consistency.get((repo, chosen))
        row["consistency"] = {"elements": ids["elements"]["cons"], "relationships": ids["relationships"]["cons"]} if ids else None
        out[repo] = row
    return out


def _points(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else round((after - before) * 100, 1)


def _lowest(row: dict[str, Any]) -> float | None:
    values = [v for v in (row.get("consistency") or {}).values() if v is not None]
    return min(values) if values else None


def verdict(baseline: dict[str, dict[str, Any]], candidate: dict[str, dict[str, Any]], rules: GateRules | None = None) -> dict[str, Any]:
    """The candidate against the baseline, per repository and overall (PASS or FAIL, with the reasons)."""
    rules = rules or GateRules()
    rows, failures, unmeasured = [], [], []
    for repo in sorted(set(baseline) | set(candidate)):
        before, after = baseline.get(repo), candidate.get(repo)
        measured = bool(before and after and before["recall"] is not None and after["recall"] is not None)
        row: dict[str, Any] = {"repository": repo, "measured": measured, "baseline": before, "candidate": after, "better": False}
        if measured and before and after:
            row["points"] = {m: _points(before.get(m), after.get(m)) for m in MEASURES}
            changes = {m: p for m, p in row["points"].items() if p is not None}
            row["better"] = any(p >= rules.min_rise for p in changes.values())
            row["drop"] = max([0.0] + [-p for p in changes.values()])
            for m, p in changes.items():
                if -p > rules.max_drop:
                    failures.append(f"{repo} drops {-p:.1f} points on {LABELS[m]} (at most {rules.max_drop:.1f})")
        else:
            unmeasured.append(repo)
        lowest = _lowest(after) if after else None
        row["consistency"] = lowest
        if lowest is not None and lowest < rules.min_consistency:
            failures.append(f"{repo} consistency {lowest:.1%} (at least {rules.min_consistency:.0%})")
        rows.append(row)
    measured_rows = [r for r in rows if r["measured"]]
    better = sum(1 for r in measured_rows if r["better"])
    needed = math.ceil(rules.better_share * len(measured_rows) - 1e-9)
    if not measured_rows:
        failures.append("no repository has a measure in both the baseline and the candidate")
    elif better < needed:
        failures.append(f"{better} of {len(measured_rows)} measured repositories better (at least {needed})")
    consistencies = [r["consistency"] for r in rows if r["consistency"] is not None]
    return {
        "rows": rows,
        "measured": len(measured_rows),
        "better": better,
        "needed": needed,
        "max_drop": max((r["drop"] for r in measured_rows), default=0.0),
        "min_consistency": min(consistencies) if consistencies else None,
        "unmeasured": unmeasured,
        "failures": failures,
        "verdict": "FAIL" if failures else "PASS",
        "rules": {"better_share": rules.better_share, "min_rise": rules.min_rise, "max_drop": rules.max_drop, "min_consistency": rules.min_consistency},
    }


def overall_verdict(by_level: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    """PASS when every level with a measured repository passes; the levels that voted."""
    voting = [level for level, result in by_level.items() if result.get("measured")]
    passed = bool(voting) and all(by_level[level]["verdict"] == "PASS" for level in voting)
    return ("PASS" if passed else "FAIL"), voting


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _source(row: dict[str, Any] | None) -> str:
    if not row or row["source"] is None:
        return "no reference"
    return f"{row['source']} (provisional)" if row["provisional"] else row["source"]


def table_markdown(measures: dict[str, dict[str, Any]], title: str) -> list[str]:
    """One row per repository: source, runs, the four measures, consistency by id."""
    lines = [
        f"## {title}",
        "",
        "| Repository | Measure | Runs | Recall | Precision | Rel. recall | Rel. precision | Elements by id | Relationships by id |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for repo, row in sorted(measures.items()):
        cons = row.get("consistency") or {}
        values = " | ".join(_pct(row.get(m)) for m in MEASURES)
        lines.append(f"| {repo} | {_source(row)} | {row['runs']} | {values} | {_pct(cons.get('elements'))} | {_pct(cons.get('relationships'))} |")
    return [*lines, ""]


def verdict_markdown(result: dict[str, Any]) -> list[str]:
    """The comparison table (before -> after per measure) and the verdict with its reasons."""
    lines = [
        "## Verdict",
        "",
        "| Repository | Measure | Recall | Precision | Rel. recall | Rel. precision | Consistency | Better |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        before, after = r["baseline"] or {}, r["candidate"] or {}
        better = ("yes" if r["better"] else "held") if r["measured"] else "not measured"
        cells = " | ".join(f"{_pct(before.get(m))} -> {_pct(after.get(m))}" for m in MEASURES)
        lines.append(f"| {r['repository']} | {_source(r['candidate'] or r['baseline'])} | {cells} | {_pct(r['consistency'])} | {better} |")
    rules = result["rules"]
    lines += [
        "",
        f"**{result['verdict']}**: {result['better']}/{result['measured']} measured repositories better by {rules['min_rise']:.1f} points or more "
        f"(at least {result['needed']}), largest drop {result['max_drop']:.1f} points, lowest consistency {_pct(result['min_consistency'])}.",
    ]
    if result["unmeasured"]:
        lines.append(f"Counted out of the {result['measured']} repositories with a measure; not measured: {', '.join(result['unmeasured'])}.")
    lines += [f"- {f}" for f in result["failures"]]
    return [*lines, ""]


def write(out_dir: Path, payload: dict[str, Any], lines: list[str]) -> dict[str, str]:
    """gate.json and gate.md in a folder."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gate.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    (out_dir / "gate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(out_dir / "gate.json"), "markdown": str(out_dir / "gate.md")}
