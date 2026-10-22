"""Thin client for the team's shared Multi-Agent Server (multi-agent-server/).

The server runs on the host, never in compose, so from inside the
joshua-backend container it is reached through host.docker.internal. A run
is Planner -> Worker -> Reviewer, then parks at "awaiting_human" until
POST /workflow/<run_id>/review records a person's decision.

Runs are started asynchronously ("async": true): POST /workflow returns 202
at once with the run at status "planning", the agents run on a server-side
thread, and the caller polls GET /workflow/<run_id> to watch each agent
finish. Every call is therefore quick, so this client uses short
(connect, read) timeouts like the MCP and RAG clients -- no long read
timeout, and no long gunicorn/nginx timeouts upstream of it. The overall
deadline for a run belongs to whoever polls (the frontend).

Every public call returns {"ok", "status", "http_status", "data", "error"}
and never raises for a server-side problem. status is one of:

  ok           -- 2xx; data is the server's JSON body
  disabled     -- AI_MODE_ENABLED is false, or MULTI_AGENT_URL is empty
  unreachable  -- connection refused / DNS failure (server not running)
  timeout      -- no response within the read timeout
  rejected     -- the server answered 4xx/5xx; data is its JSON error body
                  ({"error": code, "detail": ..., ...}) and http_status its code
  error        -- the server answered something that is not JSON

A run whose agent could not run is not a "rejected" call: the server
answers 200 with the run at status "failed" and an error object saying
which phase, and that is passed through as ok.
"""

import logging
import os
import re

import requests

import ai_mode

logger = logging.getLogger(__name__)

DEFAULT_MULTI_AGENT_URL = "http://host.docker.internal:5004"
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 10
TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)

CALLER = "joshua"

# The server's run ids are uuid4().hex. Checked before one is put in a URL
# path, so a crafted id can never reach a different route on the server.
RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def get_server_url():
    """The base URL from MULTI_AGENT_URL, or None when it is set but empty."""
    raw = os.environ.get("MULTI_AGENT_URL")
    if raw is None:
        return DEFAULT_MULTI_AGENT_URL
    raw = raw.strip().rstrip("/")
    return raw or None


def is_valid_run_id(run_id):
    return isinstance(run_id, str) and RUN_ID_PATTERN.match(run_id) is not None


def _result(ok, status, http_status=None, data=None, error=None):
    return {"ok": ok, "status": status, "http_status": http_status, "data": data, "error": error}


def _invalid_run_id():
    return _result(False, "rejected", 404, {"error": "not_found", "detail": "not a valid run id"}, "not a valid run id")


def _request(method, path, payload=None):
    if not ai_mode.is_enabled():
        return _result(False, "disabled", error=ai_mode.DISABLED_MESSAGE)

    base_url = get_server_url()
    if base_url is None:
        return _result(False, "disabled", error="Multi-Agent Server is disabled (MULTI_AGENT_URL is empty)")

    url = base_url + path
    try:
        response = requests.request(method, url, json=payload, timeout=TIMEOUT)
    except requests.exceptions.ConnectTimeout:
        logger.warning("Multi-Agent Server unreachable at %s (connect timeout)", url)
        return _result(False, "unreachable", error=f"could not connect to the Multi-Agent Server at {base_url}")
    except requests.exceptions.Timeout:
        logger.warning("Multi-Agent Server timed out at %s", url)
        return _result(False, "timeout", error=f"the Multi-Agent Server did not answer within {READ_TIMEOUT_SECONDS}s")
    except requests.exceptions.RequestException as exc:
        logger.warning("Multi-Agent Server unreachable at %s: %s", url, type(exc).__name__)
        return _result(False, "unreachable", error=f"could not reach the Multi-Agent Server at {base_url}")

    try:
        body = response.json()
    except ValueError:
        body = None

    if not isinstance(body, dict):
        return _result(False, "error", response.status_code, error="the Multi-Agent Server returned a non-JSON response")
    if response.ok:
        return _result(True, "ok", response.status_code, body)

    logger.warning("Multi-Agent Server %s %s -> %s %s", method, path, response.status_code, body.get("error"))
    return _result(False, "rejected", response.status_code, body, body.get("detail") or body.get("error"))


def start_workflow(task, evidence):
    """POST /workflow with "async": true. On success (202) data is the run at
    status "planning": run_id, status, plan, work, review, model, stub,
    human_review, error."""
    return _request("POST", "/workflow", {"task": task, "evidence": evidence, "caller": CALLER, "async": True})


def get_workflow(run_id):
    """GET /workflow/<run_id>: the run's current state. status moves through
    planning -> working -> reviewing -> awaiting_human -> complete, or to
    failed with error {"phase", "detail", ...}."""
    if not is_valid_run_id(run_id):
        return _invalid_run_id()
    return _request("GET", f"/workflow/{run_id}")


def submit_review(run_id, review):
    """POST /workflow/<run_id>/review with the human decision.

    review holds decision, and optionally note and corrected; the server
    enforces which combinations are allowed. On success data is
    {run_id, status: "complete", decision, decided_at}.
    """
    if not is_valid_run_id(run_id):
        return _invalid_run_id()
    body = {key: review[key] for key in ("decision", "note", "corrected") if review.get(key) is not None}
    body["reviewer"] = CALLER
    return _request("POST", f"/workflow/{run_id}/review", body)
