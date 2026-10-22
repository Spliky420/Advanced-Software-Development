"""workflow_history.jsonl: every run can be rebuilt from the file alone."""

import json

import pytest

import agents
import server
from conftest import EVIDENCE
from store import RunConflict, WorkflowStore


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _restart(app, history_path):
    """A new app over the same file -- what a server restart does."""
    return server.create_app({**app.config, "WORKFLOW_HISTORY_PATH": str(history_path)})


def test_each_phase_is_written_as_it_happens(run, history_path):
    assert [event["event"] for event in _events(history_path)] == [
        "created", "phase", "status", "phase", "status", "phase", "awaiting_human",
    ]
    for event in _events(history_path):
        assert event["run_id"] == run["run_id"]
        assert event["at"]


def test_a_run_is_rebuilt_exactly_from_the_file(app, client, run, history_path):
    client.post(f"/workflow/{run['run_id']}/review", json={"decision": "partial", "note": "step 1"})
    before = app.extensions["workflow_store"].get(run["run_id"])

    rebuilt = WorkflowStore(history_path).get(run["run_id"])
    assert rebuilt == before
    # The audit record survives too, not just the public body.
    assert rebuilt["evidence"] == EVIDENCE
    assert set(rebuilt["phases"]) == {"plan", "work", "review"}


def test_a_restarted_server_serves_and_reviews_old_runs(app, client, run, history_path):
    restarted = _restart(app, history_path).test_client()
    assert restarted.get(f"/workflow/{run['run_id']}").get_json() == client.get(
        f"/workflow/{run['run_id']}"
    ).get_json()

    assert restarted.post(f"/workflow/{run['run_id']}/review", json={"decision": "approve"}).status_code == 200
    # And the decision itself survives another restart, so a second review is still refused.
    again = _restart(app, history_path).test_client()
    second = again.post(f"/workflow/{run['run_id']}/review", json={"decision": "reject"})
    assert second.status_code == 409
    assert again.get(f"/workflow/{run['run_id']}").get_json()["human_review"]["decision"] == "approve"


def test_a_failed_run_is_rebuilt_with_its_error(app, client, monkeypatch, history_path):
    def down(*args, **kwargs):
        raise agents.AgentUnavailable("Ollama timed out")

    monkeypatch.setattr(agents, "work", down)
    run_id = client.post("/workflow", json={"task": "t", "evidence": {"a": 1}}).get_json()["run_id"]

    rebuilt = WorkflowStore(history_path).get(run_id)
    assert rebuilt["status"] == "failed"
    assert rebuilt["error"]["phase"] == "work"
    assert rebuilt["error"]["detail"] == "Ollama timed out"
    assert rebuilt["plan"], "the phase that finished is kept"


@pytest.mark.parametrize("status, phase", [("planning", "plan"), ("working", "work"), ("reviewing", "review")])
def test_a_run_interrupted_by_a_restart_is_failed(history_path, status, phase):
    store = WorkflowStore(history_path)
    run_id = store.create(task="t", evidence={}, caller="c", model="m", stub=True)["run_id"]
    if status != "planning":
        store.set_status(run_id, status)

    reloaded = WorkflowStore(history_path)
    run = reloaded.get(run_id)
    assert run["status"] == "failed"
    assert run["error"]["phase"] == phase
    assert "restarted" in run["error"]["detail"]
    # Written down, so the next restart does not fail it a second time.
    assert _events(history_path)[-1]["event"] == "failed"
    WorkflowStore(history_path)
    assert sum(event["event"] == "failed" for event in _events(history_path)) == 1

    with pytest.raises(RunConflict):
        reloaded.decide(run_id, decision="approve", note="", corrected=None, reviewer="c")


def test_finished_runs_are_left_alone_on_restart(run, history_path):
    count = len(_events(history_path))
    assert WorkflowStore(history_path).get(run["run_id"])["status"] == "awaiting_human"
    assert len(_events(history_path)) == count


def test_a_truncated_last_line_is_skipped_not_fatal(run, history_path):
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "decided", "run_id": "' + run["run_id"] + '", "huma')
    store = WorkflowStore(history_path)
    assert store.get(run["run_id"])["status"] == "awaiting_human"


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        '{"event": "status", "run_id": "never-created", "status": "working", "at": "x"}',
        '{"event": "mystery", "run_id": "RUN", "at": "x"}',
        '["a list"]',
    ],
)
def test_bad_lines_are_skipped_and_good_ones_kept(run, history_path, line):
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(line.replace("RUN", run["run_id"]) + "\n\n")
    store = WorkflowStore(history_path)
    assert store.get(run["run_id"])["status"] == "awaiting_human"


def test_no_file_yet_means_no_runs(tmp_path):
    path = tmp_path / "missing" / "workflow_history.jsonl"
    store = WorkflowStore(path)
    assert store._runs == {}
    store.create(task="t", evidence={}, caller="c", model="m", stub=True)
    assert path.exists()


def test_non_ascii_survives_the_round_trip(history_path):
    store = WorkflowStore(history_path)
    run_id = store.create(task="Tiết kiệm €", evidence={"ghi_chú": "đ"}, caller="c", model="m", stub=True)["run_id"]
    assert WorkflowStore(history_path).get(run_id)["task"] == "Tiết kiệm €"
    assert "Tiết kiệm €" in history_path.read_text(encoding="utf-8")


def test_a_failed_write_changes_nothing(history_path, monkeypatch):
    store = WorkflowStore(history_path)
    run = store.create(task="t", evidence={}, caller="c", model="m", stub=True)
    store.await_human(run["run_id"])

    def full_disk(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(type(history_path), "open", full_disk)
    with pytest.raises(OSError):
        store.decide(run["run_id"], decision="approve", note="", corrected=None, reviewer="c")
    assert store.get(run["run_id"])["status"] == "awaiting_human"


def test_history_path_comes_from_the_environment(history_path, monkeypatch):
    monkeypatch.setattr(agents, "ping", lambda config: False)
    app = server.create_app({"TESTING": True, "STUB_AGENTS": True})
    assert app.extensions["workflow_store"].path == history_path
