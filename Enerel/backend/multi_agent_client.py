"""HTTP client for the team's shared, non-containerised Multi-Agent Server.

multi-agent-server/server.py runs Planner -> Worker -> Reviewer over a task
and evidence we supply, then holds the run at awaiting_human until a person
decides on it. It is plain JSON over HTTP, so this is a thin requests
wrapper, the same shape as rag_client.py.

Runs are started with "async": true. The server answers 202 straight away
and the agents run on its own thread, so neither nginx's 180s proxy timeout
nor gunicorn's worker timeout is ever in play; the frontend polls
GET /workflow/<run_id> (through this backend) to show each agent finishing.

Multi-agent mode is switched off with MULTI_AGENT_ENABLED=false (CI and the
cloud baseline do this), which makes every call raise MultiAgentDisabledError
instead of trying to reach a server that is not running there.
"""

import os

import requests

DEFAULT_MULTI_AGENT_URL = "http://host.docker.internal:5004"
CALLER = "Enerel"

# An async POST, a poll and a review are all answered in milliseconds; only
# the connect leg needs to fail fast when the server is down.
TIMEOUT_SECONDS = (5, 15)


class MultiAgentDisabledError(Exception):
    """Multi-agent mode is switched off by configuration (MULTI_AGENT_ENABLED=false)."""


class MultiAgentUnavailableError(Exception):
    """The Multi-Agent Server could not be reached, timed out, or answered
    with something unusable. code says which: "unreachable", "timeout",
    "error", or the server's own error code (e.g. "agent_unavailable")."""

    def __init__(self, message, code="error"):
        super().__init__(message)
        self.code = code


class MultiAgentRequestError(Exception):
    """The Multi-Agent Server refused the request (4xx); carries its status and body."""

    def __init__(self, status_code, body):
        super().__init__(body.get("detail") or body.get("error") or f"HTTP {status_code}")
        self.status_code = status_code
        self.body = body
        self.code = body.get("error") or "error"


def multi_agent_enabled():
    return os.environ.get("MULTI_AGENT_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def server_url():
    return os.environ.get("MULTI_AGENT_URL", DEFAULT_MULTI_AGENT_URL).rstrip("/")


def _request(method, path, payload=None):
    if not multi_agent_enabled():
        raise MultiAgentDisabledError("multi-agent mode is disabled (MULTI_AGENT_ENABLED=false)")

    url = server_url() + path
    try:
        response = requests.request(method, url, json=payload, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as exc:
        raise MultiAgentUnavailableError(
            f"the Multi-Agent Server at {url} did not respond: {exc}", code="timeout"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise MultiAgentUnavailableError(
            f"could not reach the Multi-Agent Server at {url}: {exc}", code="unreachable"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise MultiAgentUnavailableError(f"Multi-Agent Server returned a non-JSON response from {url}") from exc
    if not isinstance(data, dict):
        raise MultiAgentUnavailableError(f"Multi-Agent Server returned a non-object response from {url}")

    if response.status_code >= 500:
        detail = data.get("detail") or data.get("error") or f"HTTP {response.status_code}"
        raise MultiAgentUnavailableError(
            f"Multi-Agent Server error from {url}: {detail}", code=data.get("error") or "error"
        )
    if response.status_code >= 400:
        raise MultiAgentRequestError(response.status_code, data)

    return data


def start_workflow(task, evidence):
    """POST /workflow (async) -- returns the run at status 'planning'."""
    data = _request("POST", "/workflow", {
        "task": task,
        "evidence": evidence,
        "caller": CALLER,
        "async": True,
    })
    if not isinstance(data.get("run_id"), str):
        raise MultiAgentUnavailableError("Multi-Agent Server /workflow response had no run_id")
    return data


def get_workflow(run_id):
    """GET /workflow/<run_id> -- the run's current state."""
    return _request("GET", f"/workflow/{run_id}")


def review_workflow(run_id, review):
    """POST /workflow/<run_id>/review -- the human decision."""
    return _request("POST", f"/workflow/{run_id}/review", {**review, "reviewer": CALLER})
