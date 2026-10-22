"""The multi-agent client -- plan reviews from the team's shared server.

The server (`multi-agent-server/`, a host process on port 5004) runs three
agents over a task and evidence the caller supplies -- a Planner, a Worker
and a Reviewer -- and then holds the run at `awaiting_human` until a person
decides on it. This module is the client. It never computes anything the
agents see: the evidence is assembled in Python by services/review.py, and
the server only coordinates models writing words around it.

**Runs are started with `"async": true`.** The server then answers 202 with
the run id before any agent has run, and the agents' 15-40 seconds happen on
the server while the browser polls through this backend. So every call here
is short -- a quick read or write against the server's own store -- and one
deadline (MULTI_AGENT_TIMEOUT_SECONDS) covers them all. A server that has
not been updated to the async contract runs the agents inside the request
instead, overruns that deadline, and is reported as unavailable rather than
holding a gunicorn thread for a minute.

**Every failure is one exception.** Unreachable, timed out, an error status
or a body that is not the contract all raise MultiAgentUnavailable, with the
cause in the message. The callers decide what that means: starting a review
degrades to the Release 1 path and says so; polling and deciding are 503s.
The two answers the contract defines -- 404 for an unknown run and 409 for a
run in the wrong state -- have their own exceptions, because they are not
outages and the caller handles them differently.
"""

from __future__ import annotations

from typing import Any

import requests
from flask import current_app

from ..errors import ServiceUnavailable

# The status light in the page header calls /api/agents/health on load. It
# must not hold the page up behind a server that is not answering.
HEALTH_TIMEOUT_SECONDS = 3.0

# Connecting to a process on the same host either works at once or not at
# all, so the connect half of the timeout is short whatever the read half is.
CONNECT_TIMEOUT_SECONDS = 3.0

# The statuses a run can be in, from the server's contract.
IN_FLIGHT = ("planning", "working", "reviewing")
AWAITING_HUMAN = "awaiting_human"
COMPLETE = "complete"
FAILED = "failed"


class MultiAgentUnavailable(ServiceUnavailable):
    """The server could not be reached, or did not answer as the contract says."""


class RunNotFound(Exception):
    """The server has no run with this id -- its history was reset, most likely."""


class RunConflict(Exception):
    """The server refused because the run is not in a state that allows it."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    return bool(current_app.config["MULTI_AGENT_ENABLED"])


def server_url() -> str:
    return str(current_app.config["MULTI_AGENT_URL"]).rstrip("/")


def timeout_seconds() -> float:
    return float(current_app.config["MULTI_AGENT_TIMEOUT_SECONDS"])


def caller() -> str:
    return str(current_app.config["MULTI_AGENT_CALLER"])


DISABLED_REASON = "The multi-agent server is disabled by configuration (MULTI_AGENT_ENABLED=false)."


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _request(method: str, path: str, payload: dict | None = None, timeout: float | None = None) -> tuple[int, Any]:
    """One HTTP call to the server. Returns (status, parsed JSON body).

    The one seam the tests replace -- with the real multi-agent server
    running in stub mode, so the contract is exercised end to end with no
    socket opened. Raises MultiAgentUnavailable only for transport failures
    and bodies that are not JSON; reading the status is the callers' job.
    """
    url = f"{server_url()}{path}"
    try:
        response = requests.request(
            method,
            url,
            json=payload,
            timeout=(CONNECT_TIMEOUT_SECONDS, timeout or timeout_seconds()),
        )
    except requests.Timeout as exc:
        raise MultiAgentUnavailable(
            f"the multi-agent server at {url} did not answer within {timeout or timeout_seconds():g}s. "
            "If it is running, check it is a version that supports async runs (POST /workflow "
            'with "async": true).'
        ) from exc
    except requests.RequestException as exc:
        raise MultiAgentUnavailable(
            f"could not reach the multi-agent server at {url}: {exc}. It runs as a host process, "
            "not a container -- check that it is running, and that MULTI_AGENT_URL names a host "
            "this backend can reach."
        ) from exc

    try:
        return response.status_code, response.json()
    except ValueError as exc:
        raise MultiAgentUnavailable(
            f"the multi-agent server at {url} answered HTTP {response.status_code} with a non-JSON body"
        ) from exc


def _unexpected(status: int, body: Any, doing: str) -> MultiAgentUnavailable:
    """An answer outside the contract, with the server's own words when it gave any."""
    detail = (body.get("detail") or body.get("error")) if isinstance(body, dict) else None
    return MultiAgentUnavailable(
        f"the multi-agent server could not {doing}: HTTP {status}" + (f" -- {detail}" if detail else "")
    )


def _require_run_body(body: Any, doing: str) -> dict:
    """A run body has at least a run id and a status; anything less is not the contract."""
    if not isinstance(body, dict) or not isinstance(body.get("run_id"), str) or "status" not in body:
        raise MultiAgentUnavailable(
            f"the multi-agent server answered {doing} without a run_id and status -- "
            "its contract is {run_id, status, plan, work, review, model, stub, human_review, error}."
        )
    return body


# ---------------------------------------------------------------------------
# The operations this backend needs
# ---------------------------------------------------------------------------


def start_review(task: str, evidence: dict) -> dict:
    """POST /workflow, async. Returns the run body at status `planning`.

    201 is accepted as well as 202: it is what a server answers when it ran
    the agents inside the request, and the body is then simply further along.
    """
    status, body = _request(
        "POST", "/workflow", {"task": task, "evidence": evidence, "caller": caller(), "async": True}
    )
    if status not in (201, 202):
        raise _unexpected(status, body, "start a review")
    return _require_run_body(body, "a new review")


def get_run(run_id: str) -> dict:
    """GET /workflow/<run_id> -- the run as it stands."""
    status, body = _request("GET", f"/workflow/{run_id}")
    if status == 404:
        raise RunNotFound(run_id)
    if status != 200:
        raise _unexpected(status, body, "read the review")
    return _require_run_body(body, "a review lookup")


def decide(run_id: str, *, decision: str, note: str, corrected: str | None, reviewer: str) -> dict:
    """POST /workflow/<run_id>/review -- record the human decision on the server.

    The server accepts one decision per run and only while the run is
    awaiting one; anything else is a 409, raised here as RunConflict with the
    server's explanation.
    """
    payload: dict[str, Any] = {"decision": decision, "note": note, "reviewer": reviewer}
    if corrected is not None:
        payload["corrected"] = corrected
    status, body = _request("POST", f"/workflow/{run_id}/review", payload)
    if status == 404:
        raise RunNotFound(run_id)
    if status == 409:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise RunConflict(detail or f"run {run_id} is not awaiting a decision")
    if status != 200:
        raise _unexpected(status, body, "record the decision")
    if not isinstance(body, dict) or body.get("status") != COMPLETE:
        raise MultiAgentUnavailable("the multi-agent server accepted the decision but did not report the run complete")
    return body


def probe() -> dict:
    """Reachability, for /api/agents/health and the header indicator. Never raises."""
    status: dict[str, Any] = {
        "enabled": False,
        "reachable": False,
        "server_url": server_url(),
        "model": None,
        "stub": None,
        "ollama_reachable": None,
        "detail": None,
    }
    if not is_enabled():
        status["detail"] = DISABLED_REASON
        return status

    status["enabled"] = True
    try:
        code, body = _request("GET", "/health", timeout=HEALTH_TIMEOUT_SECONDS)
    except MultiAgentUnavailable as exc:
        status["detail"] = str(exc)
        return status
    if code != 200 or not isinstance(body, dict):
        status["detail"] = f"the multi-agent server answered /health with HTTP {code}"
        return status

    status["reachable"] = True
    status["model"] = body.get("model")
    status["stub"] = body.get("stub")
    status["ollama_reachable"] = body.get("ollama_reachable")
    return status
