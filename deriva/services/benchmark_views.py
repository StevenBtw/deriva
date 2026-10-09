"""Benchmark views over session files: runs, results per repository, flips and the inspector's occurrences.

Reads the model snapshots a benchmark writes (``models/{repo}_{model}_run{n}.json``) and the
runs' LLM call logs (``llm/<run>.jsonl``), for one or more sessions: end-to-end measurements
are separate one-run sessions (rule 7), so a view may combine several. The set logic lives
in ``deriva.modules.analysis.run_consistency``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deriva.adapters.archimate.models import APPLICATION_LAYER, BUSINESS_LAYER, TECHNOLOGY_LAYER
from deriva.common.ocel import create_run_id
from deriva.modules.analysis.run_consistency import consistency_rows, element_flips, run_sets
from deriva.modules.analysis.run_consistency import element_trace as run_element_trace
from deriva.services.llm_log import LlmCallLog, run_log_path


@dataclass(frozen=True)
class RunFiles:
    """One benchmark run's files."""

    session: str
    repository: str
    model: str
    iteration: int
    snapshot: Path
    calls: Path

    @property
    def label(self) -> str:
        return f"{self.session}/{self.iteration}"


def layer_of(element_type: str) -> str:
    if element_type in BUSINESS_LAYER:
        return "Business"
    if element_type in APPLICATION_LAYER:
        return "Application"
    if element_type in TECHNOLOGY_LAYER:
        return "Technology"
    return "Other"


def session_runs(benchmarks_dir: str | Path, session_ids: list[str], models: list[str]) -> list[RunFiles]:
    """The runs of the sessions in order (session, then file name); file names are matched against the known model names."""
    root = Path(benchmarks_dir)
    names = "|".join(re.escape(m) for m in sorted(models, key=lambda name: len(name), reverse=True)) or r"[^_]+"
    pattern = re.compile(rf"^(?P<repo>.+)_(?P<model>{names})_run(?P<n>\d+)\.json$")
    runs = []
    for session in session_ids:
        folder = root / session
        if not folder.is_dir():
            raise FileNotFoundError(f"Benchmark session not found: {session}")
        found = []
        for path in (folder / "models").glob("*.json"):
            match = pattern.match(path.name)
            if match:
                repo, model, n = match["repo"], match["model"], int(match["n"])
                found.append(RunFiles(session, repo, model, n, path, run_log_path(folder / "llm", create_run_id(session, repo, model, n))))
        runs += sorted(found, key=lambda r: (r.repository, r.model, r.iteration))
    return runs


def _snapshot(run: RunFiles) -> dict[str, Any]:
    return json.loads(run.snapshot.read_text(encoding="utf-8"))


def _of(runs: list[RunFiles], repository: str, model: str | None) -> list[RunFiles]:
    return [r for r in runs if r.repository == repository and (model is None or r.model == model)]


def results(benchmarks_dir: str | Path, session_ids: list[str], models: list[str]) -> list[dict[str, Any]]:
    """Per repository and model: the runs, their element and relationship counts, and the consistency rows."""
    runs = session_runs(benchmarks_dir, session_ids, models)
    groups = []
    for repository, model in sorted({(r.repository, r.model) for r in runs}):
        group = _of(runs, repository, model)
        snapshots = [_snapshot(r) for r in group]
        groups.append(
            {
                "repository": repository,
                "model": model,
                "runs": [r.label for r in group],
                "counts": [
                    {"label": r.label, "elements": len(s.get("elements", [])), "relationships": len(s.get("relationships", []))} for r, s in zip(group, snapshots, strict=True)
                ],
                "rows": consistency_rows([run_sets(s) for s in snapshots]),
            }
        )
    return groups


def flips(benchmarks_dir: str | Path, session_ids: list[str], models: list[str], repository: str, model: str | None = None) -> list[dict[str, Any]]:
    """Elements of the repository that are not in every run, with their causes (call logs where recorded)."""
    group = _of(session_runs(benchmarks_dir, session_ids, models), repository, model)
    return element_flips({r.label: _snapshot(r) for r in group}, {r.label: LlmCallLog.read(r.calls) for r in group})


def element_trace(
    benchmarks_dir: str | Path, session_ids: list[str], models: list[str], repository: str, element_type: str, source: str, model: str | None = None
) -> list[dict[str, Any]]:
    """Per run of the sessions, why an element (by type and source) is or is not in the model, with its deciding calls."""
    group = _of(session_runs(benchmarks_dir, session_ids, models), repository, model)
    return run_element_trace({r.label: _snapshot(r) for r in group}, {r.label: LlmCallLog.read(r.calls) for r in group}, element_type, source)


def inspector(benchmarks_dir: str | Path, session_ids: list[str], models: list[str], repository: str, model: str | None = None) -> dict[str, Any]:
    """Every element and relationship occurrence per run, with both identity keys, the layer and the flip causes by source key."""
    group = _of(session_runs(benchmarks_dir, session_ids, models), repository, model)
    snapshots = {r.label: _snapshot(r) for r in group}
    elements, relationships = [], []
    for label, snapshot in snapshots.items():
        keys = {}
        for e in snapshot.get("elements", []):
            by_source, by_name = f"{e['type']}|{e['source']}", f"{e['type']}|{e['name'].strip().lower()}"
            keys[e["identifier"]] = (by_source, by_name)
            elements.append(
                {
                    "run": label,
                    "identifier": e["identifier"],
                    "name": e["name"],
                    "type": e["type"],
                    "layer": layer_of(e["type"]),
                    "source": e["source"],
                    "by_source": by_source,
                    "by_name": by_name,
                }
            )
        for r in snapshot.get("relationships", []):
            if r["source"] in keys and r["target"] in keys:
                relationships.append(
                    {
                        "run": label,
                        "type": r["type"],
                        "source_by_source": keys[r["source"]][0],
                        "target_by_source": keys[r["target"]][0],
                        "source_by_name": keys[r["source"]][1],
                        "target_by_name": keys[r["target"]][1],
                        "derived_from": r.get("derived_from"),
                    }
                )
    calls = {r.label: LlmCallLog.read(r.calls) for r in group}
    causes = {f"{f['type']}|{f['source']}": f["cause"] for f in element_flips(snapshots, calls)}
    return {"repository": repository, "runs": list(snapshots), "elements": elements, "relationships": relationships, "causes": causes}
