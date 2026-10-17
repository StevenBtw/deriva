"""The nine-repo gate: recall and precision per repository (a development reference, or a golden model on its
derivable subset), consistency by id, and the acceptance verdict of a candidate against a baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deriva.bench.gate import GateRules, measure, verdict

MODEL = "anthropic-haiku55"
REFERENCE = {
    "repository": "shop",
    "elements": [
        {"key": "core", "type": "ApplicationComponent", "name": "Customer Core"},
        {"key": "web", "type": "ApplicationComponent", "name": "Web Shop"},
    ],
}
GOLDEN = """<?xml version="1.0" encoding="UTF-8"?>
<archimate:model xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:archimate="http://www.archimatetool.com/archimate" name="m" id="m">
  <folder name="Application" id="f1" type="application">
    <element xsi:type="archimate:ApplicationComponent" name="Ledger" id="g-ledger"/>
    <element xsi:type="archimate:ApplicationComponent" name="Reporting" id="g-reporting"/>
    <element xsi:type="archimate:ApplicationComponent" name="Target Platform" id="g-target"/>
  </folder>
  <folder name="Other" id="f2" type="other">
    <element xsi:type="archimate:Grouping" name="Everything" id="g-group"/>
  </folder>
</archimate:model>
"""


def _snapshot(elements, relationships=()):
    return {
        "elements": [{"identifier": i, "type": t, "name": n, "source": f"unit::{i}"} for i, t, n in elements],
        "relationships": [{"source": a, "type": t, "target": b, "derived_from": "rule"} for a, t, b in relationships],
    }


def _session(root: Path, name: str, repo: str, runs: list[dict], model: str = MODEL) -> Path:
    session = root / name
    (session / "models").mkdir(parents=True)
    (session / "session_metadata.json").write_text(json.dumps({"config": {"repositories": [repo], "models": [model]}}), encoding="utf-8")
    for number, snapshot in enumerate(runs, start=1):
        (session / "models" / f"{repo}_{model}_run{number}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return session


@pytest.fixture
def folders(tmp_path):
    goldens, references = tmp_path / "goldens", tmp_path / "reference"
    goldens.mkdir()
    references.mkdir()
    (goldens / "shop.json").write_text(json.dumps(REFERENCE), encoding="utf-8")
    (references / "ledger.archimate").write_text(GOLDEN, encoding="utf-8")
    return goldens, references


def test_a_repository_with_a_development_reference_is_measured_against_it_with_its_consistency(tmp_path, folders):
    one = _snapshot([("a", "ApplicationComponent", "Customer Core"), ("b", "ApplicationComponent", "Admin")], [("a", "Serving", "b")])
    two = _snapshot([("a", "ApplicationComponent", "Customer Core"), ("c", "ApplicationComponent", "Web Shop")], [("a", "Serving", "c")])
    session = _session(tmp_path, "s1", "shop", [one, two])

    (shop,) = measure([session], *folders).values()

    assert (shop["source"], shop["provisional"], shop["runs"]) == ("reference", False, 2)
    assert (shop["recall"], shop["precision"]) == (0.75, 0.75)  # run 1: R 1/2 P 1/2, run 2: R 2/2 P 2/2
    assert shop["consistency"] == {"elements": pytest.approx(1 / 3, abs=0.001), "relationships": 0.0}


def test_a_golden_repository_is_measured_on_its_derivable_subset(tmp_path, folders):
    _, references = folders
    (references / "ledger.derivable.json").write_text(
        json.dumps({"g-ledger": {"derivable": True}, "g-reporting": {"derivable": True}, "g-target": {"derivable": False}, "g-group": {"derivable": False}}), encoding="utf-8"
    )
    (references / "ledger.matches.json").write_text(json.dumps({"g-reporting": ["Report Generation"]}), encoding="utf-8")
    run = _snapshot([("l", "ApplicationComponent", "Ledger"), ("r", "ApplicationComponent", "Report Generation"), ("x", "ApplicationComponent", "Batch")])
    session = _session(tmp_path, "s1", "ledger", [run, run])

    ledger = measure([session], *folders)["ledger"]

    assert (ledger["source"], ledger["provisional"]) == ("golden", False)
    assert ledger["recall"] == 1.0  # both derivable elements, one through the user's accepted name
    assert ledger["precision"] == pytest.approx(0.667, abs=0.001)
    assert ledger["consistency"]["elements"] == 1.0


def test_without_the_users_files_a_golden_repository_falls_back_to_the_templates_and_is_provisional(tmp_path, folders):
    _, references = folders
    (references / "ledger.derivable.template.json").write_text(json.dumps({"_help": "x", "g-ledger": {"derivable": None}}), encoding="utf-8")
    (references / "ledger.matches.template.json").write_text(json.dumps({"_help": "x", "_elements": {}, "g-ledger": []}), encoding="utf-8")
    run = _snapshot([("l", "ApplicationComponent", "Ledger")])

    ledger = measure([_session(tmp_path, "s1", "ledger", [run, run])], *folders)["ledger"]

    # Unlabelled: recall over the reference elements of the derived types (3 components, not the grouping)
    assert (ledger["source"], ledger["provisional"]) == ("golden", True)
    assert ledger["recall"] == pytest.approx(0.333, abs=0.001) and ledger["precision"] == 1.0


def test_a_repository_without_a_reference_has_consistency_but_no_measure(tmp_path, folders):
    run = _snapshot([("a", "ApplicationComponent", "Anything")])

    other = measure([_session(tmp_path, "s1", "other", [run, run])], *folders)["other"]

    assert (other["source"], other["recall"], other["precision"]) == (None, None, None)
    assert other["consistency"]["elements"] == 1.0


def test_a_repository_with_several_models_needs_the_model_named(tmp_path, folders):
    run = _snapshot([("a", "ApplicationComponent", "Customer Core")])
    sessions = [_session(tmp_path, "s1", "shop", [run, run]), _session(tmp_path, "s2", "shop", [run, run], model="other-model")]

    with pytest.raises(ValueError, match="shop has runs of several models"):
        measure(sessions, *folders)
    assert measure(sessions, *folders, model="other-model")["shop"]["model"] == "other-model"


def _row(repo, recall, precision, consistency=1.0, source="reference"):
    return {
        "repository": repo,
        "model": MODEL,
        "runs": 3,
        "source": source,
        "provisional": False,
        "recall": recall,
        "precision": precision,
        "consistency": {"elements": consistency, "relationships": consistency},
    }


def test_the_verdict_counts_better_repositories_the_largest_drop_and_the_lowest_consistency():
    baseline = {r: _row(r, 0.50, 0.50) for r in ("a", "b", "c", "d", "e", "f", "g", "h", "i")}
    candidate = {r: _row(r, 0.52, 0.50) for r in ("a", "b", "c", "d", "e", "f")}  # 6 better on recall
    candidate |= {"g": _row("g", 0.50, 0.49), "h": _row("h", 0.50, 0.50), "i": _row("i", 0.50, 0.50, consistency=0.96)}

    result = verdict(baseline, candidate)

    assert (result["better"], result["measured"], result["needed"]) == (6, 9, 6)
    assert result["max_drop"] == pytest.approx(1.0) and result["min_consistency"] == 0.96
    assert result["verdict"] == "PASS"
    assert {r["repository"]: r["better"] for r in result["rows"]}["g"] is False


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"a": _row("a", 0.47, 0.60)}, "a drops 3.0 points"),  # more than 2 points down on recall, despite the precision
        ({"b": _row("b", 0.52, 0.50, consistency=0.94)}, "consistency 94.0%"),
    ],
)
def test_a_drop_beyond_two_points_or_consistency_below_95_fails(change, reason):
    baseline = {r: _row(r, 0.50, 0.50) for r in "abcdefghi"}
    candidate = {r: _row(r, 0.52, 0.50) for r in "abcdefghi"} | change

    result = verdict(baseline, candidate)

    assert result["verdict"] == "FAIL" and any(reason in f for f in result["failures"])


def test_repositories_without_a_measure_are_left_out_of_the_count_and_named():
    baseline = {r: _row(r, 0.50, 0.50) for r in "abcdef"} | {"x": _row("x", None, None, source=None)}
    candidate = {r: _row(r, 0.52, 0.50) for r in "abcd"} | {"e": _row("e", 0.50, 0.50), "f": _row("f", 0.50, 0.50), "x": _row("x", None, None, source=None)}

    result = verdict(baseline, candidate, GateRules())

    # 6 measured: two thirds of them (4) must be better
    assert (result["better"], result["measured"], result["needed"]) == (4, 6, 4)
    assert result["unmeasured"] == ["x"] and result["verdict"] == "PASS"
