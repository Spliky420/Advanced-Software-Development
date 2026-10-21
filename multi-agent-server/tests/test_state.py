"""The run state machine: progress, the human gate, and one review only."""

import pytest

import agents
from store import RunConflict, WorkflowStore


def _review(client, run_id, **body):
    return client.post(f"/workflow/{run_id}/review", json=body)


def test_run_waits_for_a_human(client, run):
    # Nothing completes a run except a review.
    for _ in range(3):
        assert client.get(f"/workflow/{run['run_id']}").get_json()["status"] == "awaiting_human"


@pytest.mark.parametrize(
    "body, recorded",
    [
        ({"decision": "approve"}, {"decision": "approve", "note": "", "corrected": None}),
        (
            {"decision": "correct", "corrected": "Use step 2 first.", "note": "reordered"},
            {"decision": "correct", "note": "reordered", "corrected": "Use step 2 first."},
        ),
        (
            {"decision": "partial", "note": "steps 1-2 only"},
            {"decision": "partial", "note": "steps 1-2 only", "corrected": None},
        ),
        (
            {"decision": "reject", "note": "wrong task"},
            {"decision": "reject", "note": "wrong task", "corrected": None},
        ),
    ],
)
def test_each_decision_is_recorded_distinctly(client, run, body, recorded):
    assert _review(client, run["run_id"], **body).status_code == 200
    state = client.get(f"/workflow/{run['run_id']}").get_json()
    assert state["status"] == "complete"
    human = state["human_review"]
    for key, value in recorded.items():
        assert human[key] == value
    assert human["decided_at"]
    # The work itself is never overwritten by a correction -- both are kept.
    assert state["work"] == run["work"]


def test_reviewer_defaults_to_caller_and_can_be_named(client, run, app):
    _review(client, run["run_id"], decision="approve")
    stored = app.extensions["workflow_store"].get(run["run_id"])
    assert stored["human_review"]["reviewer"] == "tester"

    other = client.post("/workflow", json={"task": "t", "evidence": {}}).get_json()
    _review(client, other["run_id"], decision="approve", reviewer="alice")
    stored = app.extensions["workflow_store"].get(other["run_id"])
    assert stored["human_review"]["reviewer"] == "alice"


def test_double_review_is_409_and_keeps_the_first_decision(client, run):
    assert _review(client, run["run_id"], decision="approve").status_code == 200

    second = _review(client, run["run_id"], decision="reject", note="changed my mind")
    assert second.status_code == 409
    assert second.get_json()["error"] == "conflict"

    state = client.get(f"/workflow/{run['run_id']}").get_json()
    assert state["human_review"]["decision"] == "approve"


def test_failed_run_cannot_be_reviewed(client, monkeypatch):
    def down(*args, **kwargs):
        raise agents.AgentUnavailable("Ollama timed out")

    monkeypatch.setattr(agents, "review", down)
    failed = client.post("/workflow", json={"task": "t", "evidence": {"a": 1}})
    assert failed.status_code == 503
    run_id = failed.get_json()["run_id"]

    state = client.get(f"/workflow/{run_id}").get_json()
    assert state["status"] == "failed"
    assert state["error"]["phase"] == "review"
    # The phases that did finish are kept.
    assert state["plan"] and state["work"]

    assert _review(client, run_id, decision="approve").status_code == 409


def test_progress_is_visible_while_the_post_is_still_running(client, monkeypatch):
    """Each phase is stored as it finishes, so a poller sees real progress."""
    seen = {}
    real_work, real_review = agents.work, agents.review

    def watching_work(task, evidence, steps, config):
        run_id = _only_run_id(client)
        seen["during_work"] = client.get(f"/workflow/{run_id}").get_json()
        return real_work(task, evidence, steps, config)

    def watching_review(task, evidence, steps, work_text, config):
        run_id = _only_run_id(client)
        seen["during_review"] = client.get(f"/workflow/{run_id}").get_json()
        return real_review(task, evidence, steps, work_text, config)

    monkeypatch.setattr(agents, "work", watching_work)
    monkeypatch.setattr(agents, "review", watching_review)
    client.post("/workflow", json={"task": "t", "evidence": {"a": 1}})

    assert seen["during_work"]["status"] == "working"
    assert seen["during_work"]["plan"], "the plan is already stored"
    assert seen["during_work"]["work"] == ""
    assert seen["during_review"]["status"] == "reviewing"
    assert seen["during_review"]["work"], "the work is already stored"


def _only_run_id(client):
    store = client.application.extensions["workflow_store"]
    (run_id,) = store._runs
    return run_id


def test_phases_record_timestamps(client, run, app):
    stored = app.extensions["workflow_store"].get(run["run_id"])
    assert set(stored["phases"]) == {"plan", "work", "review"}
    for record in stored["phases"].values():
        assert record["started_at"] <= record["finished_at"]


def test_store_decide_is_check_and_set():
    store = WorkflowStore()
    run = store.create(task="t", evidence={}, caller="c", model="m", stub=True)
    with pytest.raises(RunConflict):
        store.decide(run["run_id"], decision="approve", note="", corrected=None, reviewer="c")
    store.await_human(run["run_id"])
    store.decide(run["run_id"], decision="approve", note="", corrected=None, reviewer="c")
    with pytest.raises(RunConflict):
        store.decide(run["run_id"], decision="reject", note="", corrected=None, reviewer="c")
