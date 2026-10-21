"""Planner, Worker and Reviewer agents.

Feature-agnostic: an agent sees a task string and an evidence object the
calling backend assembled, and nothing else. It never fetches data, never
computes a figure, and knows nothing about any one student's domain -- the
same relay-don't-compute discipline as mcp-server/tools.py.

Every agent returns an AgentResult carrying its output plus the prompt and
raw response, so the store can keep a complete audit record per phase.

STUB_AGENTS=true replaces all three with canned output built in Python from
the evidence's own keys, with no Ollama call, so teammates can integrate
and test against the full contract without a model running.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

# /health must answer fast even when Ollama is missing entirely.
HEALTH_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    model: str
    timeout_seconds: float
    stub: bool


@dataclass
class AgentResult:
    output: object
    prompt: str | None = None
    raw: str | None = None
    extra: dict = field(default_factory=dict)


class AgentUnavailable(Exception):
    """An agent could not run: Ollama unreachable, model missing, or timed out.

    Infrastructure failure, surfaced by the server as a 503 naming the
    problem -- never a 500.
    """


def ping(config: AgentConfig) -> bool:
    """True when Ollama answers at all. Never raises."""
    try:
        response = requests.get(
            f"{config.base_url.rstrip('/')}/api/tags", timeout=HEALTH_TIMEOUT_SECONDS
        )
        return response.ok
    except requests.RequestException:
        return False


# --------------------------------------------------------------------------
# The three agents
# --------------------------------------------------------------------------


def plan(task: str, evidence: dict, config: AgentConfig) -> AgentResult:
    """Planner: task + evidence -> ordered steps, each naming its evidence."""
    if config.stub:
        return AgentResult(output=_stub_plan(evidence))
    raise _not_built("Planner")


def work(task: str, evidence: dict, steps: list, config: AgentConfig) -> AgentResult:
    """Worker: carries out each step using only the supplied evidence."""
    if config.stub:
        return AgentResult(output=_stub_work(steps))
    raise _not_built("Worker")


def review(task: str, evidence: dict, steps: list, work_text: str, config: AgentConfig) -> AgentResult:
    """Reviewer: checks the work against the plan and evidence."""
    if config.stub:
        return AgentResult(output=_stub_review())
    raise _not_built("Reviewer")


def _not_built(agent: str) -> AgentUnavailable:
    return AgentUnavailable(
        f"The {agent} agent is not built yet in this release; "
        "start the server with STUB_AGENTS=true"
    )


# --------------------------------------------------------------------------
# Stub output -- deterministic, derived only from the evidence's keys
# --------------------------------------------------------------------------

STUB_NOTICE = "[stub output -- no model was called]"


def _stub_plan(evidence: dict) -> list:
    keys = list(evidence)
    steps = [
        {"step": index, "action": f"Examine the '{key}' evidence.", "evidence": [key]}
        for index, key in enumerate(keys, start=1)
    ]
    steps.append(
        {
            "step": len(steps) + 1,
            "action": "Summarise what the evidence shows about the task.",
            "evidence": keys,
        }
    )
    return steps


def _stub_work(steps: list) -> str:
    lines = [f"Step {step['step']}: {step['action']} {STUB_NOTICE}" for step in steps]
    return "\n".join(lines)


def _stub_review() -> dict:
    return {
        "risks": [f"No model reviewed this work. {STUB_NOTICE}"],
        "recommendations": [
            "Run with STUB_AGENTS=false against a running Ollama before relying on this output."
        ],
    }
