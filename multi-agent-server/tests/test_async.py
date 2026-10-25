"""POST /workflow with "async": true -- 202 at once, agents on a thread.

The synchronous default is pinned by test_contract.py; these only cover
what the flag adds. Threads are real, so every wait has a deadline and a
blocked agent is released in `finally`, never left hanging the suite.
"""

import threading
import time

import pytest

import agents
from conftest import EVIDENCE

DEADLINE_SECONDS = 5


def _start(client, **extra):
    return client.post(
        "/workflow", json={"task": "Plan the next step", "evidence": EVIDENCE, "async": True, **extra}
    )


def _wait_for(client, run_id, *statuses):
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        body = client.get(f"/workflow/{run_id}").get_json()
        if body["status"] in statuses:
            return body
        time.sleep(0.01)
    pytest.fail(f"run {run_id} never reached {statuses}; last status {body['status']!r}")


@pytest.fixture
def held_worker(monkeypatch):
    """Hold the Worker until the test releases it, to look at a run mid-flight."""
    started, release = threading.Event(), threading.Event()
    real_work = agents.work

    def work(*args, **kwargs):
        started.set()
        release.wait(DEADLINE_SECONDS)
        return real_work(*args, **kwargs)

    monkeypatch.setattr(agents, "work", work)
    yield started, release
    release.set()


def test_returns_202_with_the_run_id_before_the_agents_run(client):
    response = _start(client)
    assert response.status_code == 202
    body = response.get_json()
    assert body["run_id"]
    assert body["status"] == "planning"
    assert body["plan"] == [] and body["work"] == ""
    assert response.headers["Location"] == f"/workflow/{body['run_id']}"


def test_the_run_finishes_on_its_own_and_matches_a_synchronous_one(client):
    run_id = _start(client).get_json()["run_id"]
    finished = _wait_for(client, run_id, "awaiting_human")

    sync = client.post("/workflow", json={"task": "Plan the next step", "evidence": EVIDENCE}).get_json()
    # Same pipeline, so the same output -- only the id differs.
    assert {**finished, "run_id": None} == {**sync, "run_id": None}


def test_progress_is_visible_while_an_agent_is_running(client, held_worker):
    started, release = held_worker
    run_id = _start(client).get_json()["run_id"]
    assert started.wait(DEADLINE_SECONDS)

    mid = client.get(f"/workflow/{run_id}").get_json()
    assert mid["status"] == "working"
    assert mid["plan"], "the Planner's output is there before the Worker finishes"
    assert mid["work"] == ""
    # And the human gate is not open yet.
    assert client.post(f"/workflow/{run_id}/review", json={"decision": "approve"}).status_code == 409

    release.set()
    _wait_for(client, run_id, "awaiting_human")
    assert client.post(f"/workflow/{run_id}/review", json={"decision": "approve"}).status_code == 200


def test_an_agent_failure_lands_on_the_run_not_the_response(client, monkeypatch):
    def down(*args, **kwargs):
        raise agents.AgentUnavailable("Ollama timed out after 55s")

    monkeypatch.setattr(agents, "review", down)
    response = _start(client)
    assert response.status_code == 202

    failed = _wait_for(client, response.get_json()["run_id"], "failed")
    assert failed["error"]["phase"] == "review"
    assert failed["error"]["detail"] == "Ollama timed out after 55s"
    assert failed["plan"] and failed["work"], "the phases that finished are kept"


def test_an_unexpected_error_fails_the_run_instead_of_stranding_it(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug in an agent")

    monkeypatch.setattr(agents, "plan", broken)
    failed = _wait_for(client, _start(client).get_json()["run_id"], "failed")
    assert failed["error"]["phase"] == "plan"
    assert "bug in an agent" in failed["error"]["detail"]


def test_the_synchronous_path_also_fails_the_run_on_an_unexpected_error(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bug in an agent")

    monkeypatch.setattr(agents, "plan", broken)
    store = client.application.extensions["workflow_store"]
    response = client.post("/workflow", json={"task": "t", "evidence": {}})
    assert response.status_code == 500
    (run,) = store._runs.values()
    assert run["status"] == "failed"


@pytest.mark.parametrize("value", ["true", 1, None, [True]])
def test_async_must_be_a_boolean(client, value):
    response = client.post("/workflow", json={"task": "t", "evidence": {}, "async": value})
    assert response.status_code == 400
    assert response.get_json()["fields"] == {"async": "must be true or false when supplied"}


def test_async_false_is_the_synchronous_default(client):
    response = client.post("/workflow", json={"task": "t", "evidence": {}, "async": False})
    assert response.status_code == 201
    assert response.get_json()["status"] == "awaiting_human"


def test_validation_still_happens_before_anything_starts(client):
    response = client.post("/workflow", json={"evidence": {}, "async": True})
    assert response.status_code == 400
    assert client.application.extensions["workflow_store"]._runs == {}
