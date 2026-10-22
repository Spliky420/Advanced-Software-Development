"""The real Planner, Worker and Reviewer, against a fake Ollama.

`requests.post` is replaced by FakeOllama, which hands back queued replies
and records every payload it was sent. Nothing here touches the network.
"""

import json

import pytest

import agents
from conftest import EVIDENCE

CONFIG = agents.AgentConfig(
    base_url="http://ollama.invalid:11434/", model="test-model:tag", timeout_seconds=55, stub=False
)
TASK = "Plan the next step"


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeOllama:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "payload": json, "timeout": timeout})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, FakeResponse):
            return reply
        return FakeResponse(body={"response": reply})


@pytest.fixture
def ollama(monkeypatch):
    def install(*replies):
        fake = FakeOllama(*replies)
        monkeypatch.setattr(agents.requests, "post", fake)
        return fake

    return install


def plan_reply(*steps):
    return json.dumps({"steps": list(steps)})


# --------------------------------------------------------------------------
# Planner
# --------------------------------------------------------------------------


def test_plan_numbers_steps_in_python(ollama):
    ollama(plan_reply(
        {"step": 9, "action": " Look at the items. ", "evidence": ["items"]},
        {"action": "Read the notes.", "evidence": ["notes"]},
    ))
    result = agents.plan(TASK, EVIDENCE, CONFIG)
    assert result.output == [
        {"step": 1, "action": "Look at the items.", "evidence": ["items"]},
        {"step": 2, "action": "Read the notes.", "evidence": ["notes"]},
    ]
    assert result.extra["fallback"] is False


def test_plan_drops_evidence_keys_the_caller_never_sent(ollama):
    ollama(plan_reply({"action": "Check.", "evidence": ["items", "invented", "items", 3]}))
    assert agents.plan(TASK, EVIDENCE, CONFIG).output[0]["evidence"] == ["items"]


def test_plan_maps_a_field_reference_back_to_its_key(ollama):
    ollama(plan_reply({"action": "Check.", "evidence": ["items[0].value", "notes = text", "itemsx.y"]}))
    assert agents.plan(TASK, EVIDENCE, CONFIG).output[0]["evidence"] == ["items", "notes"]


def test_plan_skips_steps_without_an_action(ollama):
    ollama(plan_reply({"action": ""}, {"evidence": ["items"]}, "text", {"action": "Real step."}))
    output = agents.plan(TASK, EVIDENCE, CONFIG).output
    assert [step["action"] for step in output] == ["Real step."]
    assert output[0]["evidence"] == []


def test_plan_is_capped(ollama):
    ollama(plan_reply(*[{"action": f"Step {n}."} for n in range(20)]))
    assert len(agents.plan(TASK, EVIDENCE, CONFIG).output) == agents.MAX_PLAN_STEPS


def test_plan_accepts_a_bare_list(ollama):
    ollama(json.dumps([{"action": "Only step.", "evidence": "notes"}]))
    assert agents.plan(TASK, EVIDENCE, CONFIG).output == [
        {"step": 1, "action": "Only step.", "evidence": ["notes"]}
    ]


def test_plan_retries_once_after_an_unusable_reply(ollama):
    fake = ollama("not json at all", plan_reply({"action": "Second try."}))
    result = agents.plan(TASK, EVIDENCE, CONFIG)
    assert result.output[0]["action"] == "Second try."
    assert result.extra == {"attempts": ["not json at all", plan_reply({"action": "Second try."})],
                            "fallback": False}
    assert len(fake.calls) == 2


def test_plan_falls_back_to_one_step_per_evidence_key(ollama):
    ollama('{"steps": []}', '{"plan": "wrong shape"}')
    result = agents.plan(TASK, EVIDENCE, CONFIG)
    assert result.extra["fallback"] is True
    assert [step["evidence"] for step in result.output] == [["items"], ["notes"], ["items", "notes"]]
    assert len(result.extra["attempts"]) == 2


def test_plan_does_not_retry_when_the_budget_is_spent(ollama, monkeypatch):
    clock = iter([0.0, 0.0, 52.0])
    monkeypatch.setattr(agents.time, "monotonic", lambda: next(clock))
    fake = ollama("not json")
    result = agents.plan(TASK, EVIDENCE, CONFIG)
    assert result.extra["fallback"] is True
    assert len(fake.calls) == 1


def test_plan_prompt_lists_evidence_and_asks_for_json(ollama):
    fake = ollama(plan_reply({"action": "x"}))
    result = agents.plan(TASK, EVIDENCE, CONFIG)
    payload = fake.calls[0]["payload"]
    assert fake.calls[0]["url"] == "http://ollama.invalid:11434/api/generate"
    assert payload["model"] == "test-model:tag"
    assert payload["format"] == "json"
    assert payload["stream"] is False
    assert payload["options"]["num_predict"] == agents.MAX_REPLY_TOKENS
    assert "Use only these keys: items, notes" in payload["prompt"]
    assert TASK in payload["prompt"]
    assert '"value": 12.5' in payload["prompt"]
    assert result.prompt == payload["prompt"]


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------

STEPS = [
    {"step": 1, "action": "Look at the items.", "evidence": ["items"]},
    {"step": 2, "action": "Summarise.", "evidence": []},
]


def test_work_returns_the_model_text(ollama):
    fake = ollama("  Step 1: alpha is 12.5.\nStep 2: done.  ")
    result = agents.work(TASK, EVIDENCE, STEPS, CONFIG)
    assert result.output == "Step 1: alpha is 12.5.\nStep 2: done."
    assert result.raw == result.output
    payload = fake.calls[0]["payload"]
    assert "format" not in payload
    assert "Step 1: Look at the items. (evidence: items)" in payload["prompt"]
    assert "Step 2: Summarise. (evidence: none)" in payload["prompt"]


# --------------------------------------------------------------------------
# Reviewer
# --------------------------------------------------------------------------


def test_review_parses_risks_and_recommendations(ollama):
    ollama(json.dumps({"risks": ["  Step 2 is thin. ", "", 4], "recommendations": "Add detail."}))
    result = agents.review(TASK, EVIDENCE, STEPS, "Step 1: alpha is 12.5.", CONFIG)
    assert result.output == {"risks": ["Step 2 is thin."], "recommendations": ["Add detail."]}
    assert result.extra["unsupplied_figures"] == []
    assert "WORK:\nStep 1: alpha is 12.5." in result.prompt


def test_review_falls_back_when_unreadable_twice(ollama):
    ollama('{"risks": "fine"}', "nope")
    result = agents.review(TASK, EVIDENCE, STEPS, "Step 1: fine.", CONFIG)
    assert result.extra["fallback"] is True
    assert "could not be read" in result.output["risks"][0]


def test_review_flags_figures_the_evidence_never_supplied(ollama):
    ollama(json.dumps({"risks": [], "recommendations": []}))
    work_text = "Step 1: alpha is 12.50, so the total is 1,250.75 over 3 months."
    result = agents.review(TASK, EVIDENCE, STEPS, work_text, CONFIG)
    assert result.extra["unsupplied_figures"] == ["1,250.75", "3"]
    assert result.output["risks"][0].startswith("Figure check:")
    assert "1,250.75, 3" in result.output["risks"][0]


def test_figure_check_flags_even_when_the_reviewer_fell_back(ollama):
    ollama("bad", "bad")
    result = agents.review(TASK, EVIDENCE, STEPS, "It is 99.", CONFIG)
    assert result.output["risks"][0].startswith("Figure check:")
    assert "could not be read" in result.output["risks"][1]


@pytest.mark.parametrize(
    "work_text, expected",
    [
        ("Step 1: 12.5. Step 2: 12.50.", []),                    # same value, other spelling
        ("Step 3: nothing.", ["3"]),                              # only two steps in the plan
        ("Due 21 October 2026.", []),                             # date parts from the evidence
        ("It grew 4%.", ["4"]),
        ("No figures here.", []),
    ],
)
def test_unsupplied_figures(work_text, expected):
    evidence = {**EVIDENCE, "due": "2026-10-21"}
    assert agents.unsupplied_figures(work_text, TASK, evidence, step_count=2) == expected


@pytest.mark.parametrize(
    "work_text, expected",
    [
        ("The shortfall is 5000.0 - 3200.0 = 1800.0 yuan.", ["5000.0 - 3200.0 = 1800.0"]),
        ("Total: 1,200 + 300 + 50=1,550.", ["1,200 + 300 + 50=1,550"]),
        ("Monthly: 3200 / 5 = 640", ["3200 / 5 = 640"]),
        ("Due 2027-03-31, saved 1800.0.", []),
        ("No sums here = none.", []),
    ],
)
def test_written_calculations(work_text, expected):
    assert agents.written_calculations(work_text) == expected


def test_review_flags_arithmetic_built_only_from_supplied_figures(ollama):
    ollama(json.dumps({"risks": ["Model risk."], "recommendations": []}))
    evidence = {"target": 5000.0, "remaining": 3200.0, "saved": 1800.0}
    result = agents.review(TASK, evidence, STEPS, "Saved 5000.0 - 3200.0 = 1800.0.", CONFIG)
    assert result.extra["unsupplied_figures"] == []
    assert result.output["risks"][0].startswith("Arithmetic check:")
    assert result.output["risks"][1] == "Model risk."


def test_figures_in_the_task_are_allowed():
    assert agents.unsupplied_figures("Save 500.", "Save 500 a month", {}, 0) == []


# --------------------------------------------------------------------------
# Transport failures -> AgentUnavailable
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, message",
    [
        (agents.requests.ConnectionError("refused"), "could not reach Ollama"),
        (agents.requests.Timeout("slow"), "timed out after 55s"),
        (FakeResponse(404), "Run: ollama pull test-model:tag"),
        (FakeResponse(500), "HTTP 500"),
        (FakeResponse(200, None), "unreadable envelope"),
        (FakeResponse(200, {"response": "   "}), "empty response"),
    ],
)
def test_transport_failures_raise_agent_unavailable(ollama, reply, message):
    ollama(reply)
    with pytest.raises(agents.AgentUnavailable, match=message):
        agents.work(TASK, EVIDENCE, STEPS, CONFIG)


def test_each_call_gets_only_the_remaining_budget(ollama, monkeypatch):
    clock = iter([0.0, 10.0, 10.0, 30.0])
    monkeypatch.setattr(agents.time, "monotonic", lambda: next(clock))
    fake = ollama("bad", plan_reply({"action": "x"}))
    agents.plan(TASK, EVIDENCE, CONFIG)
    assert [call["timeout"] for call in fake.calls] == [45.0, 25.0]


# --------------------------------------------------------------------------
# End to end through the server, real agents against the fake Ollama
# --------------------------------------------------------------------------


def test_full_run_with_real_agents(app, ollama):
    app.config["STUB_AGENTS"] = False
    ollama(
        plan_reply({"action": "Look at the items.", "evidence": ["items"]}),
        "Step 1: alpha is 12.5 out of 40.",
        json.dumps({"risks": ["None found."], "recommendations": ["Approve."]}),
    )
    client = app.test_client()
    response = client.post("/workflow", json={"task": TASK, "evidence": EVIDENCE, "caller": "tester"})
    assert response.status_code == 201
    run = response.get_json()
    assert run["status"] == "awaiting_human"
    assert run["stub"] is False
    assert run["model"] == "test-model:tag"
    assert run["plan"] == [{"step": 1, "action": "Look at the items.", "evidence": ["items"]}]
    assert run["work"] == "Step 1: alpha is 12.5 out of 40."
    assert run["review"]["risks"][0].startswith("Figure check:")
    assert "40" in run["review"]["risks"][0]

    stored = app.extensions["workflow_store"].get(run["run_id"])
    assert set(stored["phases"]) == {"plan", "work", "review"}
    assert stored["phases"]["review"]["unsupplied_figures"] == ["40"]
    assert stored["phases"]["plan"]["fallback"] is False
    assert stored["phases"]["work"]["prompt"].startswith("You are the Worker")
