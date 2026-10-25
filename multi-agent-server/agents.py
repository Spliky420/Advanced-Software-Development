"""Planner, Worker and Reviewer agents.
Feature-agnostic: an agent sees a task string and an evidence object the
calling backend assembled, and nothing else. It never fetches data, never
computes a figure, and knows nothing about any one student's domain -- the
same relay-don't-compute discipline as mcp-server/tools.py.
Every agent returns an AgentResult carrying its output plus the prompt and
raw response, so the store can keep a complete audit record per phase.
The model only writes words. Python owns everything structural: it numbers
the plan's steps, drops evidence keys the caller never sent, and decides
whether a reply is usable. A reply that is not usable is retried once, then
replaced by deterministic output flagged `fallback` in the audit record --
a bad answer is not an error. Ollama being unreachable is, and raises
AgentUnavailable.
STUB_AGENTS=true replaces all three with canned output built in Python from
the evidence's own keys, with no Ollama call, so teammates can integrate
and test against the full contract without a model running.
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
import requests
# /health must answer fast even when Ollama is missing entirely.
HEALTH_TIMEOUT_SECONDS = 2.0
# Low but non-zero: the prose should read naturally without the model
# wandering away from the instructions.
TEMPERATURE = 0.2
# A retry is only attempted when at least this much of the agent's budget is
# left; otherwise the fallback is used straight away.
MIN_RETRY_SECONDS = 5.0
MAX_PLAN_STEPS = 8
# Upper bound on tokens per reply. With format "json" a small model can
# occasionally pad with whitespace until it runs out of context, which on
# CPU takes minutes; capping it turns that into a truncated reply, which the
# retry-then-fallback path already handles.
MAX_REPLY_TOKENS = 768
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
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
    prompt = _render(
        "planner",
        task=task,
        evidence=_evidence_json(evidence),
        evidence_keys=", ".join(evidence) or "(none)",
    )
    return _ask_json(
        prompt, config,
        parse=lambda data: _parse_plan(data, evidence),
        fallback=lambda: _evidence_plan(evidence),
    )
def _work_uses_evidence(work_text: str, evidence: dict, steps: list) -> bool:
    """Require exactly the planned steps, with assigned scalar evidence values."""
    matches = list(re.finditer(r"\bStep\s+(\d+)\s*:", work_text, flags=re.IGNORECASE))
    expected = [step["step"] for step in steps]
    if [int(m.group(1)) for m in matches] != expected:
        return False
    for i, step in enumerate(steps):
        start = matches[i].end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(work_text)
        paragraph = work_text[start:end]
        for key in step["evidence"]:
            if key not in evidence:
                return False
            value = evidence[key]
            if isinstance(value, (dict, list)):
                continue
            if json.dumps(value, ensure_ascii=False) not in paragraph and str(value) not in paragraph:
                return False
    return True


def _evidence_work_fallback(evidence: dict, steps: list) -> str:
    """Relay verified data when the model fails; do not invent analysis."""
    lines = []
    for step in steps:
        values = ", ".join(
            f"{key}={json.dumps(evidence[key], ensure_ascii=False)}"
            for key in step["evidence"] if key in evidence
        )
        lines.append(
            f"Step {step['step']}: {step['action']}. "
            f"Verified evidence: {values or 'No specific evidence keys assigned'}."
        )
    return "\n".join(lines)


def work(task: str, evidence: dict, steps: list, config: AgentConfig) -> AgentResult:
    """Worker: retry incomplete output, then return an auditable data-only fallback."""
    if config.stub:
        return AgentResult(output=_stub_work(steps))

    prompt = _render(
        "worker", task=task, evidence=_evidence_json(evidence), steps=_steps_text(steps)
    )
    deadline = _deadline(config)
    attempts = []
    for attempt in range(2):
        raw = _generate(prompt, config, deadline=deadline, json_format=False)
        attempts.append(raw)
        if _work_uses_evidence(raw, evidence, steps):
            return AgentResult(
                output=raw, prompt=prompt, raw=raw,
                extra={"attempts": attempts, "fallback": False},
            )
        if deadline - time.monotonic() < MIN_RETRY_SECONDS:
            break

    return AgentResult(
        output=_evidence_work_fallback(evidence, steps),
        prompt=prompt,
        raw=attempts[-1] if attempts else None,
        extra={"attempts": attempts, "fallback": True},
    )


def review(task: str, evidence: dict, steps: list, work_text: str, config: AgentConfig) -> AgentResult:
    """Reviewer: checks the work against the plan and evidence.
    Two Python checks run alongside the model, and what they find goes in
    front of the Reviewer's own risks, whatever the Reviewer said, so the
    human gate always sees it: any number in the work that appears nowhere
    in the task or evidence, and any calculation the work writes out.
    """
    if config.stub:
        return AgentResult(output=_stub_review())
    prompt = _render(
        "reviewer",
        task=task,
        evidence=_evidence_json(evidence),
        steps=_steps_text(steps),
        work=work_text,
    )
    result = _ask_json(prompt, config, parse=_parse_review, fallback=_fallback_review)
    unsupplied = unsupplied_figures(work_text, task, evidence, len(steps))
    calculations = written_calculations(work_text)
    result.extra["unsupplied_figures"] = unsupplied
    result.extra["calculations"] = calculations
    checks = []
    if "Verified evidence:" in work_text:
        checks.append(
            "Analysis quality: The Worker used an evidence-only "
            "fallback and did not provide a complete financial analysis."
        )

        result.output["recommendations"].append(
            "Review the transaction records, verify supporting receipts, "
            "and confirm potential tax deductions before acting on this summary."
        )
    if not _work_uses_evidence(work_text, evidence, steps):
        checks.append(
            "Completeness check: the Worker did not include all required evidence "
            "values in their corresponding plan steps."
        )
    if unsupplied:
        checks.append(
            "Figure check: the work states "
            f"{', '.join(unsupplied)}, which do not appear in the task or evidence."
        )
    if calculations:
        checks.append(
            "Arithmetic check: the work calculates "
            f"{'; '.join(calculations)}. Figures must come from the evidence, not the model."
        )
    result.output["risks"][:0] = checks
    return result
# --------------------------------------------------------------------------
# Figure check -- the arithmetic rule, enforced in Python
# --------------------------------------------------------------------------
# Digits with optional thousands separators and decimals. Signs are left
# off on purpose: "2026-10-21" in the evidence must match "21 October 2026"
# in the work, not produce -10 and -21.
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
def _numbers(text: str) -> dict[float, str]:
    """Every number in the text, keyed by value, with its first spelling."""
    found = {}
    for match in _NUMBER.finditer(text):
        found.setdefault(float(match.group().replace(",", "")), match.group())
    return found
def unsupplied_figures(work_text: str, task: str, evidence: dict, step_count: int) -> list[str]:
    """Numbers in the work that the task and evidence never supplied.
    Compared by value, so "12.50" in the work matches 12.5 in the evidence.
    Step numbers are allowed, since the Worker is told to write "Step 2:".
    """
    allowed = set(_numbers(task)) | set(_numbers(json.dumps(evidence)))
    allowed |= {float(number) for number in range(1, step_count + 1)}
    return [
        spelling for value, spelling in _numbers(work_text).items() if value not in allowed
    ]
# A written-out sum: "5000.0 - 3200.0 = 1800.0". Every figure in it can be a
# supplied one and the figure check above still passes, so it is caught
# separately. The "=" is required, which keeps dates like 2027-03-31 out.
_CALCULATION = re.compile(
    r"\d[\d,]*(?:\.\d+)?(?:\s*[-+*/×÷x]\s*\d[\d,]*(?:\.\d+)?)+\s*=\s*\d[\d,]*(?:\.\d+)?"
)
def written_calculations(work_text: str) -> list[str]:
    """Every calculation the work writes out, so the human gate sees it."""
    return list(dict.fromkeys(match.group() for match in _CALCULATION.finditer(work_text)))
# --------------------------------------------------------------------------
# Parsing -- returns None when a reply is unusable
# --------------------------------------------------------------------------
def _parse_plan(data, evidence: dict) -> list | None:
    items = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return None
    steps = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if not isinstance(action, str) or not action.strip():
            continue
        named = item.get("evidence")
        if isinstance(named, str):
            named = [named]
        if not isinstance(named, list):
            named = []
        keys = list(dict.fromkeys(filter(None, (_evidence_key(name, evidence) for name in named))))
        # Recover valid evidence keys mentioned in the action text, even when
        # the small model returns an empty or malformed evidence list.
        keys.extend(key for key in evidence if key not in keys and re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", action
        ))
        steps.append({"step": len(steps) + 1, "action": action.strip(), "evidence": keys})
        if len(steps) == MAX_PLAN_STEPS:
            break
    if not steps:
        return None
    # Reject plans that fail to cover ANY supplied evidence key (i.e., completely unrelated).
    # Allow partial coverage — the Planner may reasonably skip keys like counts/metadata.
    covered = {key for step in steps for key in step["evidence"]}
    if not covered:
        return None
    return steps


def _evidence_key(name, evidence: dict) -> str | None:
    """The top-level evidence key a step refers to, or None if invented.
    Small models often name a field inside the evidence ("goal.saved",
    "items[0]") rather than the key itself; that maps back to its key.
    """
    if not isinstance(name, str):
        return None
    name = name.strip()
    if name in evidence:
        return name
    head = re.split(r"[.\[\s=]", name, maxsplit=1)[0]
    return head if head in evidence else None
def _parse_review(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    review = {}
    for key in ("risks", "recommendations"):
        items = data.get(key)
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list):
            return None
        review[key] = [item.strip() for item in items if isinstance(item, str) and item.strip()]
    return review
def _evidence_plan(evidence: dict) -> list:
    """Deterministic plan: one step per evidence key, then a summary."""
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
def _fallback_review() -> dict:
    return {
        "risks": ["The Reviewer's response could not be read, so no model has reviewed this work."],
        "recommendations": ["Check the work against the evidence by hand before approving it."],
    }
# --------------------------------------------------------------------------
# Ollama transport
# --------------------------------------------------------------------------
def _ask_json(prompt: str, config: AgentConfig, *, parse, fallback) -> AgentResult:
    """Ask for JSON, retry once if the reply is unusable, then fall back.
    Both attempts share one deadline, so an agent never takes longer than
    AGENT_TIMEOUT_SECONDS however many calls it makes.
    """
    deadline = _deadline(config)
    attempts = []
    while True:
        raw = _generate(prompt, config, deadline=deadline, json_format=True)
        attempts.append(raw)
        try:
            output = parse(json.loads(raw))
        except ValueError:
            output = None
        if output is not None:
            return AgentResult(
                output=output, prompt=prompt, raw=raw,
                extra={"attempts": attempts, "fallback": False},
            )
        if len(attempts) == 2 or deadline - time.monotonic() < MIN_RETRY_SECONDS:
            return AgentResult(
                output=fallback(), prompt=prompt, raw=raw,
                extra={"attempts": attempts, "fallback": True},
            )
def _deadline(config: AgentConfig) -> float:
    return time.monotonic() + config.timeout_seconds
def _generate(prompt: str, config: AgentConfig, *, deadline: float, json_format: bool) -> str:
    """One Ollama call. Raises AgentUnavailable, never for a bad answer."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AgentUnavailable(f"Ollama timed out after {config.timeout_seconds:g}s")
    url = f"{config.base_url.rstrip('/')}/api/generate"
    payload = {
        "model": config.model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_predict": MAX_REPLY_TOKENS},
    }
    if json_format:
        payload["format"] = "json"
    try:
        response = requests.post(url, json=payload, timeout=remaining)
    except requests.Timeout as exc:
        raise AgentUnavailable(f"Ollama timed out after {config.timeout_seconds:g}s") from exc
    except requests.RequestException as exc:
        raise AgentUnavailable(f"could not reach Ollama at {url}: {exc}") from exc
    # A running Ollama answers 404 for a tag that has never been pulled -- a
    # different fix from Ollama not running, so the message says which.
    if response.status_code == 404:
        raise AgentUnavailable(
            f"model {config.model!r} is not pulled. Run: ollama pull {config.model}"
        )
    if not response.ok:
        raise AgentUnavailable(f"Ollama returned HTTP {response.status_code}")
    try:
        text = response.json().get("response")
    except (ValueError, AttributeError) as exc:
        raise AgentUnavailable(f"Ollama returned an unreadable envelope: {exc}") from exc
    if not isinstance(text, str) or not text.strip():
        raise AgentUnavailable("Ollama returned an empty response")
    return text.strip()
# --------------------------------------------------------------------------
# Prompt building
# --------------------------------------------------------------------------
def _render(name: str, **values: str) -> str:
    template = Template((PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8"))
    return template.substitute(values)
def _evidence_json(evidence: dict) -> str:
    return json.dumps(evidence, indent=2, ensure_ascii=False)
def _steps_text(steps: list) -> str:
    lines = []
    for step in steps:
        keys = ", ".join(step["evidence"]) or "none"
        lines.append(f"Step {step['step']}: {step['action']} (evidence: {keys})")
    return "\n".join(lines)
# --------------------------------------------------------------------------
# Stub output -- deterministic, derived only from the evidence's keys
# --------------------------------------------------------------------------
STUB_NOTICE = "[stub output -- no model was called]"
def _stub_plan(evidence: dict) -> list:
    return _evidence_plan(evidence)
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
