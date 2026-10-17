"""Convention checklist over benchmark sessions: reads the run snapshots, writes a review page per repository.

The checks live in ``deriva.modules.analysis.conventions``; their thresholds and pattern lists in
``data/conventions.json`` next to this module (a measuring instrument: it never changes a model).
"""

from __future__ import annotations

import json
from collections import defaultdict
from importlib import resources
from pathlib import Path
from typing import Any

from deriva.common.paths import workspace
from deriva.modules.analysis.conventions import check_runs, render_review, render_summary


def load_conventions() -> dict[str, Any]:
    """The shipped thresholds and pattern lists."""
    return json.loads(resources.files("deriva.bench").joinpath("data/conventions.json").read_text(encoding="utf-8"))


def _snapshots(session_ids: list[str], benchmarks_dir: Path, run: int | None) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """(repository, model) -> run label -> snapshot; the label names the session when there are several."""
    found: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for session_id in session_ids:
        models = benchmarks_dir / session_id / "models"
        if not models.is_dir():
            raise FileNotFoundError(f"No model snapshots in {models}")
        for path in sorted(models.glob("*_run*.json")):
            stem, _, number = path.stem.rpartition("_run")
            if not number.isdigit() or (run is not None and int(number) != run):
                continue
            repository, _, model = stem.rpartition("_")
            label = f"{session_id}/run{number}" if len(session_ids) > 1 else f"run{number}"
            found[(repository, model)][label] = json.loads(path.read_text(encoding="utf-8"))
    return dict(found)


def write_reports(session_ids: list[str], out_dir: str | Path, run: int | None = None, benchmarks_dir: str | Path | None = None) -> dict[str, Any]:
    """Check every repository's runs of the sessions; write ``<repository>_<model>.md``, ``summary.md`` and ``conventions.json``.

    Raises LookupError when no run snapshot matches (nothing is written then, so an earlier report stays).
    """
    conventions = load_conventions()
    folder = Path(benchmarks_dir) if benchmarks_dir is not None else workspace() / "benchmarks"
    found = _snapshots(session_ids, folder, run)
    if not found:
        raise LookupError("no run snapshots matched the selected sessions and run")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, dict[str, Any]]] = {}
    pages: dict[str, str] = {}
    models_of: dict[str, set[str]] = defaultdict(set)
    for repository, model in found:
        models_of[repository].add(model)
    for (repository, model), runs in sorted(found.items()):
        # A repository benchmarked with several models gets one row per model
        name = f"{repository} ({model})" if len(models_of[repository]) > 1 else repository
        checked = check_runs(runs, conventions)
        results[name] = checked
        page = out / f"{repository}_{model}.md"
        page.write_text(render_review(repository, model, checked, runs) + "\n", encoding="utf-8")
        pages[name] = str(page)
    header = [
        "# Convention checklist",
        "",
        f"Sessions: {', '.join(session_ids)}. Conventions version {conventions.get('version')}: bands warn; the other checks fail, "
        "except spelling variants (warn) and business behaviour evidence (reported).",
        "",
        "Each cell is the worst status over the runs, with its largest count (elements per run in the second column).",
        "",
        "",
    ]
    (out / "summary.md").write_text("\n".join(header) + render_summary(results) + "\n", encoding="utf-8")
    payload = {"sessions": session_ids, "conventions_version": conventions.get("version"), "results": results, "pages": pages}
    (out / "conventions.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return payload
