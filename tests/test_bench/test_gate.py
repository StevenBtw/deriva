"""The nine-repo gate: recall and precision per repository (a development reference, or a golden model on its
derivable subset), consistency by id, and the acceptance verdict of a candidate against a baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deriva.bench.gate import GateRules, measure, verdict, verdict_markdown

MODEL = "anthropic-haiku55"
REFERENCE = {
    "repository": "shop",
    "elements": [
        {"key": "core", "type": "ApplicationComponent", "name": "Customer Core"},
        {"key": "web", "type": "ApplicationComponent", "name": "Web Shop"},
    ],
    "relationships": [{"source": "core", "target": "web", "type": "Serving", "kind": "cooperation"}],
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
  <folder name="Relations" id="f3" type="relations">
    <element xsi:type="archimate:ServingRelationship" id="r1" source="g-ledger" target="g-reporting"/>
    <element xsi:type="archimate:CompositionRelationship" id="r2" source="g-ledger" target="g-target"/>
    <element xsi:type="archimate:AggregationRelationship" id="r3" source="g-group" target="g-ledger"/>
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
    # Relationships as reference_eval counts them: run 1 misses it (no precision: no end pair maps), run 2 has it
    assert (shop["relationship_recall"], shop["relationship_precision"]) == (0.5, 1.0)
    assert shop["consistency"] == {"elements": pytest.approx(1 / 3, abs=0.001), "relationships": 0.0}


def test_a_golden_repository_is_measured_on_its_derivable_subset(tmp_path, folders):
    _, references = folders
    (references / "ledger.derivable.json").write_text(
        json.dumps({"g-ledger": {"derivable": True}, "g-reporting": {"derivable": True}, "g-target": {"derivable": False}, "g-group": {"derivable": False}}), encoding="utf-8"
    )
    (references / "ledger.matches.json").write_text(json.dumps({"g-reporting": ["Report Generation"]}), encoding="utf-8")
    run = _snapshot(
        [("l", "ApplicationComponent", "Ledger"), ("r", "ApplicationComponent", "Report Generation"), ("x", "ApplicationComponent", "Batch")],
        [("l", "Serving", "r"), ("l", "Composition", "x"), ("r", "Serving", "l")],  # one right, one wrong end, one reversed
    )
    session = _session(tmp_path, "s1", "ledger", [run, run])

    ledger = measure([session], *folders)["ledger"]

    assert (ledger["source"], ledger["provisional"]) == ("golden", False)
    assert ledger["recall"] == 1.0  # both derivable elements, one through the user's accepted name
    assert ledger["precision"] == pytest.approx(0.667, abs=0.001)
    assert ledger["consistency"]["elements"] == 1.0
    # A golden relationship counts when both ends are derivable (only Ledger -> Reporting); type and direction must agree
    assert (ledger["relationship_recall"], ledger["relationship_precision"]) == (1.0, pytest.approx(0.333, abs=0.001))


def test_final_derivable_labels_set_the_scope_while_the_accepted_names_are_still_a_template(tmp_path, folders):
    """The scope comes from the derivable file once it is final; the accepted names (matches) can follow later: only
    names and structure match until then, and the row says the matches are provisional, not the scope."""
    _, references = folders
    (references / "ledger.derivable.json").write_text(
        json.dumps({"g-ledger": {"derivable": True}, "g-reporting": {"derivable": True}, "g-target": {"derivable": False}, "g-group": {"derivable": False}}), encoding="utf-8"
    )
    (references / "ledger.matches.template.json").write_text(json.dumps({"_help": "x", "_elements": {}, "g-reporting": []}), encoding="utf-8")
    run = _snapshot([("l", "ApplicationComponent", "Ledger"), ("r", "ApplicationComponent", "Report Generation")], [("l", "Serving", "r")])

    ledger = measure([_session(tmp_path, "s1", "ledger", [run, run])], *folders)["ledger"]

    assert (ledger["source"], ledger["provisional"], ledger["matches_provisional"]) == ("golden", False, True)
    # Over the 2 derivable elements (not the derived types' 3): Ledger by name; Reporting needs an accepted name
    assert ledger["recall"] == 0.5


def test_without_the_users_files_a_golden_repository_falls_back_to_the_templates_and_is_provisional(tmp_path, folders):
    _, references = folders
    (references / "ledger.derivable.template.json").write_text(json.dumps({"_help": "x", "g-ledger": {"derivable": None}}), encoding="utf-8")
    (references / "ledger.matches.template.json").write_text(json.dumps({"_help": "x", "_elements": {}, "g-ledger": []}), encoding="utf-8")
    run = _snapshot([("l", "ApplicationComponent", "Ledger")])

    ledger = measure([_session(tmp_path, "s1", "ledger", [run, run])], *folders)["ledger"]

    # Unlabelled: recall over the reference elements of the derived types (3 components, not the grouping)
    assert (ledger["source"], ledger["provisional"]) == ("golden", True)
    assert ledger["recall"] == pytest.approx(0.333, abs=0.001) and ledger["precision"] == 1.0
    # Relationships between two elements of the derived types (not the grouping's): 2, none derived
    assert (ledger["relationship_recall"], ledger["relationship_precision"]) == (0.0, None)


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


def _row(repo, recall, precision, consistency=1.0, source="reference", rel_recall=0.5, rel_precision=0.5):
    return {
        "repository": repo,
        "model": MODEL,
        "runs": 3,
        "source": source,
        "provisional": False,
        "recall": recall,
        "precision": precision,
        "relationship_recall": rel_recall if source else None,
        "relationship_precision": rel_precision if source else None,
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


def test_a_rise_below_one_point_is_held_and_a_relationship_rise_counts():
    baseline = {r: _row(r, 0.50, 0.50) for r in "abc"}
    candidate = {"a": _row("a", 0.505, 0.50), "b": _row("b", 0.50, 0.50, rel_recall=0.52), "c": _row("c", 0.50, 0.50, rel_precision=0.53)}

    result = verdict(baseline, candidate)

    assert {r["repository"]: r["better"] for r in result["rows"]} == {"a": False, "b": True, "c": True}
    assert (result["better"], result["needed"], result["verdict"]) == (2, 2, "PASS")


def test_a_level_that_only_holds_is_held_not_failed():
    """Too few repositories better but nothing dropping and consistency kept: the change holds this level (a change aimed
    at another level, such as one rule of the solution level, leaves the enterprise level held)."""
    baseline = {r: _row(r, 0.50, 0.50) for r in "abcdef"}
    candidate = {r: _row(r, 0.50, 0.50) for r in "bcdef"} | {"a": _row("a", 0.50, 0.50, rel_precision=0.535)}

    result = verdict(baseline, candidate)

    assert (result["better"], result["needed"], result["verdict"], result["failures"]) == (1, 4, "HELD", [])
    assert result["held"] == ["1 of 6 measured repositories better (at least 4)"]
    assert "**HELD**" in "\n".join(verdict_markdown(result)) and "- 1 of 6 measured repositories better (at least 4)" in "\n".join(verdict_markdown(result))


def test_a_relationship_drop_beyond_two_points_fails():
    baseline = {r: _row(r, 0.50, 0.50) for r in "abc"}
    candidate = {r: _row(r, 0.52, 0.52) for r in "ab"} | {"c": _row("c", 0.52, 0.52, rel_precision=0.47)}

    result = verdict(baseline, candidate)

    assert result["verdict"] == "FAIL" and any("c drops 3.0 points on relationship precision" in f for f in result["failures"])


def test_a_level_measures_that_level_and_a_reference_without_it_has_no_measure(tmp_path, folders):
    goldens, references = folders
    leveled = {
        "repository": "shop",
        "elements": [
            {"key": "core", "type": "ApplicationComponent", "name": "Customer Core", "levels": ["enterprise", "solution"]},
            {"key": "lib", "type": "ApplicationComponent", "name": "Pricing Library", "levels": ["solution"]},
        ],
    }
    (goldens / "shop.json").write_text(json.dumps(leveled), encoding="utf-8")
    run = _snapshot([("a", "ApplicationComponent", "Customer Core")])
    run["elements"][0]["levels"] = ["enterprise", "solution"]  # a model element without levels is enterprise only
    sessions = [_session(tmp_path, "s1", "shop", [run, run]), _session(tmp_path, "s2", "ledger", [run, run])]

    assert measure(sessions, goldens, references, level="enterprise")["shop"]["recall"] == 1.0
    shop = measure(sessions, goldens, references, level="solution")["shop"]
    assert (shop["source"], shop["recall"]) == ("reference", 0.5)  # the library is missing at the solution level
    # The golden model has no levels: measured on the union only
    assert measure(sessions, goldens, references, level="solution")["ledger"]["source"] is None
    assert measure(sessions, goldens, references, level="enterprise")["ledger"]["source"] is None
    assert measure(sessions, goldens, references, level="union")["ledger"]["source"] == "golden"
    # A reference without solution elements has no solution measure
    (goldens / "shop.json").write_text(json.dumps(REFERENCE), encoding="utf-8")
    assert measure(sessions, goldens, references, level="solution")["shop"]["source"] is None


def test_a_reference_without_level_tags_is_measured_on_the_union_only(tmp_path, folders):
    """Untagged, every reference element would count as enterprise and the solution-level elements a run derives would
    show as missing there: such a reference does not vote on a single level, and says why."""
    from deriva.bench.gate import table_markdown

    goldens, references = folders
    run = _snapshot([("a", "ApplicationComponent", "Customer Core")])
    run["elements"][0]["levels"] = ["enterprise", "solution"]
    sessions = [_session(tmp_path, "s1", "shop", [run, run]), _session(tmp_path, "s2", "ledger", [run, run])]

    for level in ("enterprise", "solution"):
        measured = measure(sessions, goldens, references, level=level)
        for repo in ("shop", "ledger"):  # an untagged development reference, a golden model (no levels)
            assert (measured[repo]["source"], measured[repo]["recall"], measured[repo]["note"]) == (None, None, "no level tags")
        assert "| shop | no level tags |" in "\n".join(table_markdown(measured, level))
    union = measure(sessions, goldens, references, level="union")
    assert (union["shop"]["source"], union["ledger"]["source"]) == ("reference", "golden")
    # One element with levels makes the reference a tagged one (the rest are enterprise, as written)
    tagged = {**REFERENCE, "elements": [{**REFERENCE["elements"][0], "levels": ["enterprise"]}, *REFERENCE["elements"][1:]]}
    (goldens / "shop.json").write_text(json.dumps(tagged), encoding="utf-8")
    assert measure(sessions, goldens, references, level="enterprise")["shop"]["source"] == "reference"


def test_the_overall_verdict_needs_every_measured_level_to_pass():
    from deriva.bench.gate import overall_verdict

    passing = {"verdict": "PASS", "measured": 6, "failures": []}
    failing = {"verdict": "FAIL", "measured": 6, "failures": ["x drops 3.0 points on recall (at most 2.0)"]}
    unmeasured = {"verdict": "FAIL", "measured": 0, "failures": ["no repository has a measure in both the baseline and the candidate"]}

    assert overall_verdict({"enterprise": passing, "solution": unmeasured, "union": passing}) == ("PASS", ["enterprise", "union"])
    assert overall_verdict({"enterprise": passing, "solution": failing, "union": passing})[0] == "FAIL"


def test_a_held_level_does_not_block_a_level_that_passes():
    """The overall verdict passes when no level fails and at least one passes; held everywhere is held, not a pass."""
    from deriva.bench.gate import overall_verdict

    passing = {"verdict": "PASS", "measured": 6, "failures": []}
    held = {"verdict": "HELD", "measured": 6, "failures": [], "held": ["1 of 6 measured repositories better (at least 4)"]}
    failing = {"verdict": "FAIL", "measured": 6, "failures": ["x drops 3.0 points on recall (at most 2.0)"]}

    assert overall_verdict({"enterprise": held, "solution": passing, "union": passing}) == ("PASS", ["enterprise", "solution", "union"])
    assert overall_verdict({"enterprise": held, "solution": held, "union": held})[0] == "HELD"
    assert overall_verdict({"enterprise": held, "solution": failing, "union": passing})[0] == "FAIL"


def test_golden_elements_and_relationships_match_through_structure_refs(tmp_path, folders):
    """A golden element tied to a folder is found by the element derived from it, and its relationships follow."""
    _, references = folders
    (references / "ledger.derivable.json").write_text(
        json.dumps({"g-ledger": {"derivable": True}, "g-reporting": {"derivable": True}, "g-target": {"derivable": False}, "g-group": {"derivable": False}}), encoding="utf-8"
    )
    (references / "ledger.matches.json").write_text(json.dumps({"g-reporting": {"names": [], "structure_refs": ["path:reports"]}}), encoding="utf-8")
    run = {
        "elements": [
            {"identifier": "l", "type": "ApplicationComponent", "name": "Ledger", "source": "unit::ledger::core"},
            {"identifier": "r", "type": "ApplicationComponent", "name": "Statements", "source": "unit::ledger::reports"},
        ],
        "relationships": [{"source": "l", "type": "Serving", "target": "r", "derived_from": "rule"}],
    }

    ledger = measure([_session(tmp_path, "s1", "ledger", [run, run])], *folders)["ledger"]

    assert ledger["recall"] == 1.0 and ledger["precision"] == 1.0  # Statements is the reports folder: Reporting
    assert (ledger["relationship_recall"], ledger["relationship_precision"]) == (1.0, 1.0)
