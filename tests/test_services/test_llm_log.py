"""The per-run LLM call log: append-only JSON lines, stamped with the step that made the calls."""

from __future__ import annotations

import json
import threading

from deriva.services.llm_log import LlmCallLog, record_call, run_log_path


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_calls_wait_for_their_step_then_land_in_order(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")

    first = log.record(prompt="classify a", response='{"x": 1}', cache_hit=False)
    log.record(prompt="classify b", response='{"x": 2}', cache_hit=True)
    assert not path.exists() or path.read_text(encoding="utf-8") == ""

    log.assign_step("DirectoryClassification")

    rows = lines(path)
    assert [r["prompt"] for r in rows] == ["classify a", "classify b"]
    assert {r["step"] for r in rows} == {"DirectoryClassification"}
    assert [r["seq"] for r in rows] == [1, 2]
    assert rows[0]["call_id"] == first["call_id"]
    assert rows[0]["run_id"] == "r1"


def test_a_known_step_writes_at_once(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")

    log.record(prompt="p", response="a", step="Node")

    assert lines(path)[0]["step"] == "Node"


def test_the_file_is_append_only(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")
    log.record(prompt="one", response="1")
    log.assign_step("A")
    before = path.read_text(encoding="utf-8")

    log.record(prompt="two", response="2")
    log.assign_step("B")

    assert path.read_text(encoding="utf-8").startswith(before)
    assert [r["step"] for r in lines(path)] == ["A", "B"]


def test_close_flushes_calls_without_a_step(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")
    log.record(prompt="late", response="x")

    log.close()

    assert lines(path)[0]["step"] is None


def test_listeners_get_each_call_once_with_its_step(tmp_path):
    seen = []
    log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")
    log.add_listener(seen.append)

    log.record(prompt="p1", response="a")
    log.record(prompt="p2", response="b")
    log.assign_step("BusinessConcept")
    log.close()

    assert [(c["prompt"], c["step"]) for c in seen] == [("p1", "BusinessConcept"), ("p2", "BusinessConcept")]


def test_read_and_find(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")
    call = log.record(prompt="p", response="a", step="Node")

    assert LlmCallLog.read(path)[0]["call_id"] == call["call_id"]
    assert LlmCallLog.find(path, call["call_id"])["prompt"] == "p"
    assert LlmCallLog.find(path, "nope") is None
    assert LlmCallLog.read(tmp_path / "missing.jsonl") == []


def test_two_threads_recording_keep_unique_sequence_numbers(tmp_path):
    path = tmp_path / "llm.jsonl"
    log = LlmCallLog(path, run_id="r1")

    def work(tag):
        for i in range(50):
            log.record(prompt=f"{tag}{i}", response="x", step="S")

    threads = [threading.Thread(target=work, args=(t,)) for t in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = lines(path)
    assert len(rows) == 100
    assert sorted(r["seq"] for r in rows) == list(range(1, 101))


class Answer:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error


class Parsed:
    """A structured answer (response_model) has no content, only its JSON."""

    def model_dump_json(self):
        return '{"roles": {}}'


METRICS = {"cache_key": "k1", "cache_hit": True, "latency_ms": 0.4, "input_tokens": 120, "output_tokens": 9, "error_type": None}


def test_record_call_keeps_prompt_answer_call_kind_and_metrics(tmp_path):
    log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")
    schema = {"name": "directory_classification", "strict": True, "schema": {"type": "object"}}

    record_call(log, METRICS, prompt="Classify", schema=schema, system_prompt="You classify.", response=Answer('{"a": 1}'), step="DirectoryClassification")

    (call,) = LlmCallLog.read(tmp_path / "llm.jsonl")
    assert (call["step"], call["prompt"], call["system_prompt"], call["schema"], call["response"]) == (
        "DirectoryClassification",
        "Classify",
        "You classify.",
        "directory_classification",
        '{"a": 1}',
    )
    assert (call["cache_key"], call["cache_hit"], call["latency_ms"], call["tokens_in"], call["tokens_out"], call["error"]) == ("k1", True, 0.4, 120, 9, None)


def test_record_call_keeps_structured_answers_and_errors(tmp_path):
    log = LlmCallLog(tmp_path / "llm.jsonl", run_id="r1")

    record_call(log, {}, prompt="p1", schema=None, system_prompt=None, response=Parsed(), step="S")
    record_call(log, {}, prompt="p2", schema=None, system_prompt=None, response=Answer(content="", error="refused"), step="S")
    record_call(log, {}, prompt="p3", schema=None, system_prompt=None, response=None, error="provider down", step="S")

    rows = LlmCallLog.read(tmp_path / "llm.jsonl")
    assert [(r["response"], r["error"]) for r in rows] == [('{"roles": {}}', None), ("", "refused"), (None, "provider down")]


def test_run_log_path_is_a_safe_file_name_per_run(tmp_path):
    path = run_log_path(tmp_path, "bench_20261008_013000:TeaStore:mistral-devstral2:1")

    assert path == tmp_path / "bench_20261008_013000_TeaStore_mistral-devstral2_1.jsonl"
