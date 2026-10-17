"""The gate for a change: recall, precision and consistency per repository, a candidate against a baseline.

Per repository (read-only, from the sessions' run snapshots):

- **A development reference** (``<goldens>/<name>.json``, the reference format of ``reference_eval``): element
  recall and precision, the mean over the runs.
- **A golden model** (``<reference>/<repository>.archimate``): recall on the derivable subset the user labelled
  (``<repository>.derivable.json``) with the user's accepted names (``<repository>.matches.json``), and precision.
  Without those files the ``.template.json`` versions are read and the result is provisional: recall then counts the
  reference elements of the derived types.
- **Consistency by id**: the share of elements and of relationships in every run (``session_metrics``).

A repository without either reference keeps its consistency and is left out of the count. The verdict: the change is
accepted when recall or precision rises on enough of the measured repositories, none drops by more than the allowed
points on either, and consistency stays at the minimum everywhere.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deriva.bench import reference_eval, session_metrics
from deriva.modules.analysis.semantic_matching import parse_archi_xml, parse_exchange_format_xml


@dataclass(frozen=True)
class GateRules:
    """The acceptance rule."""

    better_share: float = 2 / 3  # Of the measured repositories, at least this share better on recall or precision (6 of 9)
    max_drop: float = 2.0  # Points either may drop on any repository
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


def _golden_elements(path: Path) -> list[Any]:
    elements, _ = parse_archi_xml(path)
    return elements or parse_exchange_format_xml(path)[0]


def _mean(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 3) if known else None


def measure(sessions: list[Path], goldens_dir: Path, reference_dir: Path, model: str | None = None) -> dict[str, dict[str, Any]]:
    """Per repository of the sessions: its model, runs, source of the measure, recall, precision and consistency by id."""
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
        row: dict[str, Any] = {"repository": repo, "model": chosen, "runs": len(snapshots), "source": None, "provisional": False, "recall": None, "precision": None}
        golden = Path(reference_dir) / f"{repo}.archimate"
        if repo in references:
            results = [reference_eval.evaluate(references[repo], s) for s in snapshots]
            row |= {"source": "reference", "recall": _mean([r["element_recall"] for r in results]), "precision": _mean([r["element_precision"] for r in results])}
        elif golden.is_file():
            reference = _golden_elements(golden)
            aliases, alias_template = _user_file(Path(reference_dir), repo, "matches")
            derivable, derivable_template = _user_file(Path(reference_dir), repo, "derivable")
            provisional = alias_template or derivable_template
            results = []
            for snapshot in snapshots:
                derived = [{"id": e["identifier"], "name": e.get("name"), "type": str(e["type"]).removeprefix("Model:")} for e in snapshot.get("elements", [])]
                results.append(session_metrics.golden_comparison(derived, reference, aliases=aliases, derivable=derivable))
            recall_key = "derivable_types_recall" if provisional else "derivable_recall"
            row |= {
                "source": "golden",
                "provisional": provisional,
                "recall": _mean([r[recall_key] for r in results]),
                "precision": _mean([r["precision"] for r in results]),
            }
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
            row["recall_points"] = _points(before["recall"], after["recall"])
            row["precision_points"] = _points(before["precision"], after["precision"])
            changes = [p for p in (row["recall_points"], row["precision_points"]) if p is not None]
            row["better"] = any(p > 0 for p in changes)
            row["drop"] = max([0.0] + [-p for p in changes])
            if row["drop"] > rules.max_drop:
                worst = "recall" if (row["recall_points"] or 0) <= (row["precision_points"] or 0) else "precision"
                failures.append(f"{repo} drops {row['drop']:.1f} points on {worst} (at most {rules.max_drop:.1f})")
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
        "rules": {"better_share": rules.better_share, "max_drop": rules.max_drop, "min_consistency": rules.min_consistency},
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def _source(row: dict[str, Any] | None) -> str:
    if not row or row["source"] is None:
        return "no reference"
    return f"{row['source']} (provisional)" if row["provisional"] else row["source"]


def table_markdown(measures: dict[str, dict[str, Any]], title: str) -> list[str]:
    """One row per repository: source, runs, recall, precision, consistency by id."""
    lines = [f"## {title}", "", "| Repository | Measure | Runs | Recall | Precision | Elements by id | Relationships by id |", "|---|---|---|---|---|---|---|"]
    for repo, row in sorted(measures.items()):
        cons = row.get("consistency") or {}
        lines.append(
            f"| {repo} | {_source(row)} | {row['runs']} | {_pct(row['recall'])} | {_pct(row['precision'])} | {_pct(cons.get('elements'))} | {_pct(cons.get('relationships'))} |"
        )
    return [*lines, ""]


def verdict_markdown(result: dict[str, Any]) -> list[str]:
    """The comparison table and the verdict with its reasons."""
    lines = [
        "## Verdict",
        "",
        "| Repository | Measure | Recall before | Recall after | Precision before | Precision after | Consistency | Better |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        before, after = r["baseline"] or {}, r["candidate"] or {}
        better = ("yes" if r["better"] else "no") if r["measured"] else "not measured"
        lines.append(
            f"| {r['repository']} | {_source(r['candidate'] or r['baseline'])} | {_pct(before.get('recall'))} | {_pct(after.get('recall'))} | "
            f"{_pct(before.get('precision'))} | {_pct(after.get('precision'))} | {_pct(r['consistency'])} | {better} |"
        )
    lines += [
        "",
        f"**{result['verdict']}**: {result['better']}/{result['measured']} measured repositories better (at least {result['needed']}), "
        f"largest drop {result['max_drop']:.1f} points, lowest consistency {_pct(result['min_consistency'])}.",
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
