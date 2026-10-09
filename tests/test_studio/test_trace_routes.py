"""Element trace over the API: the session builds it, the run's call log supplies the calls."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession
from tests.test_studio.test_runs import finished, llm_session, wait_for


def test_trace_without_a_run_has_no_calls(make_client):
    session = FakeSession(trace_element={"element": {"identifier": "e1"}, "sources": [], "relationships": [], "calls": []})
    client = make_client(session)

    response = client.get("/api/trace/e1")

    assert response.status_code == 200
    assert response.json()["element"] == {"identifier": "e1"}
    assert session.called("trace_element") == [(("e1", []), {})]


def test_trace_reads_the_calls_of_the_run(make_client):
    session = llm_session()
    session.returns["trace_element"] = lambda element_id, calls: {"element_id": element_id, "prompts": [c["prompt"] for c in calls]}
    client = make_client(session)
    run_id = client.post("/api/runs", json={"kind": "extraction"}).json()["run_id"]
    wait_for(lambda: finished(client, run_id))

    response = client.get(f"/api/trace/dir::r::src/main?run_id={run_id}")

    assert response.json() == {"element_id": "dir::r::src/main", "prompts": ["classify a", "classify b", "name it"]}


def test_unknown_element_or_run_is_404(make_client):
    client = make_client(FakeSession(trace_element=None))

    assert client.get("/api/trace/missing").status_code == 404
    assert client.get("/api/trace/e1?run_id=nope").status_code == 404
