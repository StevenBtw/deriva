"""Benchmark views over session files: runs, results, flips and the inspector's occurrences."""

from __future__ import annotations

import json
from typing import Any

import pytest

from deriva.common.ocel import create_run_id
from deriva.services.benchmark_views import flips, inspector, results, session_runs
from deriva.services.llm_log import LlmCallLog, run_log_path

QUEUE = {"identifier": "n_queue", "name": "Queue Server", "type": "Node", "source": "tech::r::queue"}
WORKER = {"identifier": "ac_worker", "name": "Worker", "type": "ApplicationComponent", "source": "dir::r::worker"}
SERVES = {"type": "Serving", "source": "n_queue", "target": "ac_worker", "derived_from": "metamodel"}


def write_run(root, session: str, repo: str, model: str, n: int, elements: list[dict[str, Any]], prompt: str | None = None, response: str = "{}") -> None:
    models = root / session / "models"
    models.mkdir(parents=True, exist_ok=True)
    ids = {e["identifier"] for e in elements}
    relationships = [SERVES] if {"n_queue", "ac_worker"} <= ids else []
    snapshot = {
        "elements": elements,
        "relationships": relationships,
        "graph": {},
        "candidates": [{"type": "Node", "source": "tech::r::queue", "stage": "created" if "n_queue" in ids else "llm_rejected"}],
    }
    (models / f"{repo}_{model}_run{n}.json").write_text(json.dumps(snapshot), encoding="utf-8")
    if prompt is not None:
        run_id = create_run_id(session, repo, model, n)
        log = LlmCallLog(run_log_path(root / session / "llm", run_id), run_id)
        log.record(step="Node", prompt=prompt, response=response, cache_key="k1")


@pytest.fixture
def benchmarks(tmp_path):
    root = tmp_path / "benchmarks"
    write_run(root, "s_a", "my_repo", "azure-gpt4", 1, [QUEUE, WORKER], "Candidates: tech::r::queue", '{"keep": true}')
    write_run(root, "s_a", "my_repo", "azure-gpt4", 2, [WORKER], "Candidates: tech::r::queue", '{"keep": false}')
    write_run(root, "s_b", "my_repo", "azure-gpt4", 1, [QUEUE, WORKER])
    return root


def test_runs_of_several_sessions_are_labelled_by_session_and_run(benchmarks):
    runs = session_runs(benchmarks, ["s_a", "s_b"], ["azure-gpt4"])

    assert [(r.label, r.repository, r.model, r.iteration) for r in runs] == [
        ("s_a/1", "my_repo", "azure-gpt4", 1),
        ("s_a/2", "my_repo", "azure-gpt4", 2),
        ("s_b/1", "my_repo", "azure-gpt4", 1),
    ]
    assert runs[0].calls.exists()
    assert not runs[2].calls.exists()


def test_results_group_runs_per_repository_and_model(benchmarks):
    (group,) = results(benchmarks, ["s_a", "s_b"], ["azure-gpt4"])

    rows = {row["key"]: row for row in group["rows"]}
    assert (group["repository"], group["model"], group["runs"]) == ("my_repo", "azure-gpt4", ["s_a/1", "s_a/2", "s_b/1"])
    assert group["counts"] == [
        {"label": "s_a/1", "elements": 2, "relationships": 1},
        {"label": "s_a/2", "elements": 1, "relationships": 0},
        {"label": "s_b/1", "elements": 2, "relationships": 1},
    ]
    assert (rows["el_source"]["common"], rows["el_source"]["union"]) == (1, 2)


def test_flips_read_the_runs_call_logs(benchmarks):
    (flip,) = flips(benchmarks, ["s_a", "s_b"], ["azure-gpt4"], "my_repo")

    assert (flip["source"], flip["present"], flip["missing"]) == ("tech::r::queue", ["s_a/1", "s_b/1"], {"s_a/2": "candidate llm_rejected"})
    assert flip["llm"] == "same prompt, different answer"


def test_inspector_lists_occurrences_with_layer_keys_and_flip_causes(benchmarks):
    view = inspector(benchmarks, ["s_a", "s_b"], ["azure-gpt4"], "my_repo")

    assert view["runs"] == ["s_a/1", "s_a/2", "s_b/1"]
    queue = [o for o in view["elements"] if o["source"] == "tech::r::queue"]
    assert [o["run"] for o in queue] == ["s_a/1", "s_b/1"]
    assert (queue[0]["layer"], queue[0]["by_source"], queue[0]["by_name"]) == ("Technology", "Node|tech::r::queue", "Node|queue server")
    assert view["causes"] == {"Node|tech::r::queue": "Node: candidate llm_rejected in s_a/2 (same prompt, different answer)"}
    assert [(r["run"], r["type"], r["source_by_source"], r["target_by_source"]) for r in view["relationships"]] == [
        ("s_a/1", "Serving", "Node|tech::r::queue", "ApplicationComponent|dir::r::worker"),
        ("s_b/1", "Serving", "Node|tech::r::queue", "ApplicationComponent|dir::r::worker"),
    ]


def test_an_unknown_session_is_an_error(benchmarks):
    with pytest.raises(FileNotFoundError):
        session_runs(benchmarks, ["s_a", "nope"], ["azure-gpt4"])
