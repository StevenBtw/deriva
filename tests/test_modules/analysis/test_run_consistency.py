"""Run-to-run consistency of benchmark model snapshots, and flips with their causes."""

from __future__ import annotations

from typing import Any

from deriva.modules.analysis.run_consistency import consistency_rows, element_flips, run_sets


def snapshot(elements=(), relationships=(), candidates=(), graph=None) -> dict[str, Any]:
    return {"elements": list(elements), "relationships": list(relationships), "candidates": list(candidates), "graph": graph or {}}


def el(identifier: str, name: str, element_type: str, source: str) -> dict[str, str]:
    return {"identifier": identifier, "name": name, "type": element_type, "source": source}


QUEUE = el("n_queue", "Queue Server", "Node", "tech::r::queue")
BUS = el("n_bus", "Queue Server", "Node", "tech::r::bus")
WORKER = el("ac_worker", "Worker", "ApplicationComponent", "dir::r::worker")
SERVES = {"type": "Serving", "source": "n_queue", "target": "ac_worker", "derived_from": "metamodel"}
GRAPH = {"concepts": [["concept::r::order", ["entity"]]], "technologies": ["tech::r::queue"], "technology_routes": {"tech::r::queue": ["directory"]}}


def rows_by_key(runs):
    return {row["key"]: row for row in consistency_rows(runs)}


def test_identical_runs_are_fully_consistent():
    one = run_sets(snapshot([QUEUE, WORKER], [SERVES], graph=GRAPH))

    rows = rows_by_key([one, run_sets(snapshot([QUEUE, WORKER], [SERVES], graph=GRAPH))])

    for key in ("el_name", "el_source", "rel_name", "rel_source", "graph_technologies"):
        assert (rows[key]["common"], rows[key]["union"], rows[key]["score"]) == (rows[key]["union"], rows[key]["union"], 1.0)
    assert rows["el_source"]["union"] == 2


def test_a_source_flip_lowers_source_identity_only():
    first = run_sets(snapshot([QUEUE, WORKER]))
    second = run_sets(snapshot([BUS, WORKER]))

    rows = rows_by_key([first, second])

    assert rows["el_name"]["score"] == 1.0
    assert (rows["el_source"]["common"], rows["el_source"]["union"]) == (1, 3)


def test_breakdown_rows_follow_the_headline_rows():
    rows = consistency_rows([run_sets(snapshot([QUEUE, WORKER], [SERVES], graph=GRAPH))])
    keys = [row["key"] for row in rows]

    assert keys[:7] == ["graph_concepts", "graph_concept_types", "graph_technologies", "el_name", "el_source", "rel_name", "rel_source"]
    assert {"type:Node", "type:ApplicationComponent", "prov:metamodel", "route:technology:directory"} <= set(keys)
    assert keys[7:] == sorted(keys[7:])


def test_nothing_in_any_run_scores_one():
    rows = rows_by_key([run_sets(snapshot()), run_sets(snapshot())])

    assert (rows["el_source"]["union"], rows["el_source"]["score"]) == (0, 1.0)


def call(step: str, prompt: str, cache_key: str, response: str = "{}") -> dict[str, Any]:
    return {"step": step, "prompt": prompt, "cache_key": cache_key, "response": response, "call_id": f"{cache_key}-{step}"}


def test_flip_rejected_by_the_llm_on_the_same_prompt():
    runs = {
        "s/1": snapshot([QUEUE, WORKER], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created"}]),
        "s/2": snapshot([WORKER], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "llm_rejected"}]),
    }
    calls = {
        "s/1": [call("Node", "Candidates: tech::r::queue (Queue)", "k1", '{"keep": true}')],
        "s/2": [call("Node", "Candidates: tech::r::queue (Queue)", "k1", '{"keep": false}')],
    }

    (flip,) = element_flips(runs, calls)

    assert (flip["type"], flip["source"], flip["present"]) == ("Node", "tech::r::queue", ["s/1"])
    assert flip["missing"] == {"s/2": "candidate llm_rejected"}
    assert flip["llm"] == "same prompt, different answer"
    assert flip["cause"] == "Node: candidate llm_rejected in s/2 (same prompt, different answer)"


def test_flip_with_a_different_prompt_points_upstream():
    runs = {
        "s/1": snapshot([QUEUE], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created"}]),
        "s/2": snapshot([], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "llm_rejected"}]),
    }
    calls = {"s/1": [call("Node", "tech::r::queue among 3", "k1")], "s/2": [call("Node", "tech::r::queue among 4", "k2")]}

    (flip,) = element_flips(runs, calls)

    assert flip["llm"] == "different prompt"


def test_flip_a_refine_step_disabled_names_the_rule():
    """The candidate was created, then a refine rule took the element out: that rule is the cause."""
    runs = {
        "s/1": snapshot([QUEUE], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created"}]),
        "s/2": snapshot([], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created", "refine": "no_cross_layer_anchor"}]),
    }

    (flip,) = element_flips(runs, {})

    assert flip["missing"] == {"s/2": "disabled in refine (no_cross_layer_anchor)"}


def test_flip_that_was_no_candidate_or_whose_source_was_not_extracted():
    runs = {
        "s/1": snapshot([QUEUE, WORKER], graph=GRAPH),
        "s/2": snapshot([], graph={"technologies": []}),
    }

    flips = {f["source"]: f for f in element_flips(runs, {})}

    assert flips["tech::r::queue"]["missing"] == {"s/2": "source not extracted"}
    assert flips["dir::r::worker"]["missing"] == {"s/2": "not a candidate"}
    assert flips["tech::r::queue"]["llm"] is None


def test_same_name_from_another_source_is_a_source_flip():
    runs = {"s/1": snapshot([QUEUE]), "s/2": snapshot([BUS]), "s/3": snapshot([QUEUE])}

    flips = element_flips(runs, {})
    by_source = {f["source"]: f for f in flips}

    assert by_source["tech::r::queue"]["present"] == ["s/1", "s/3"]
    assert by_source["tech::r::bus"]["present"] == ["s/2"]
    assert by_source["tech::r::queue"]["names"] == {"s/1": "Queue Server", "s/3": "Queue Server"}
    assert by_source["tech::r::queue"]["also_from"] == {"s/2": "tech::r::bus"}


def test_stable_elements_are_no_flips():
    runs = {"s/1": snapshot([QUEUE, WORKER]), "s/2": snapshot([QUEUE, WORKER])}

    assert element_flips(runs, {}) == []


def test_an_element_is_traced_per_run_from_the_session_files():
    """Per run: present or not, under which name, the candidate's stage, a refine rule, and the calls that decided it."""
    from deriva.modules.analysis.run_consistency import element_trace

    runs = {
        "s/1": snapshot([QUEUE], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created"}]),
        "s/2": snapshot([], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "created", "refine": "no_cross_layer_anchor"}]),
        "s/3": snapshot([], candidates=[{"type": "Node", "source": "tech::r::queue", "stage": "llm_rejected"}]),
    }
    deciding = call("Node", "Candidates: tech::r::queue (Queue)", "k1", '{"keep": true}')
    calls = {
        "s/1": [deciding, call("DataObject", "Candidates: tech::r::queue", "k2")],
        "s/2": [deciding],
        "s/3": [call("Node", "Candidates: tech::r::queue", "k3", '{"keep": false}')],
    }

    trace = element_trace(runs, calls, "Node", "tech::r::queue")

    assert [(t["run"], t["present"], t["name"], t["stage"], t["refine"]) for t in trace] == [
        ("s/1", True, "Queue Server", "created", None),
        ("s/2", False, None, "created", "no_cross_layer_anchor"),
        ("s/3", False, None, "llm_rejected", None),
    ]
    assert [c["cache_key"] for c in trace[0]["calls"]] == ["k1"]  # only the element's own step decides
    assert trace[2]["calls"][0]["response"] == '{"keep": false}'
    assert trace[1]["cause"] == "disabled in refine (no_cross_layer_anchor)"
    assert trace[0]["cause"] is None


def test_a_source_that_was_no_candidate_says_so():
    from deriva.modules.analysis.run_consistency import element_trace

    (only,) = element_trace({"s/1": snapshot([], graph={"technologies": []})}, {}, "Node", "tech::r::queue")

    assert (only["present"], only["stage"], only["cause"], only["calls"]) == (False, None, "source not extracted", [])
