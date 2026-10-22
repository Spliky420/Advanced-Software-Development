"""Shared Multi-Agent Server -- Planner, Worker, Reviewer, then a human gate.

Runs on the host, never in docker-compose.yml (Release 2 brief). Backends
reach it at http://host.docker.internal:5004. Feature-agnostic: it takes a
task plus evidence the calling backend assembled, and coordinates three
agents over it. It never fetches data and never computes a figure.

    POST /workflow                  run all three agents, park the run
                                    at awaiting_human, return 201
                                    ("async": true -- return 202 at once
                                    and run the agents on a thread)
    GET  /workflow/<run_id>         current state of a run
    POST /workflow/<run_id>/review  the human decision that completes it
    GET  /health                    liveness, model tag, Ollama reachability

By default the POST is synchronous: it blocks for all three agents
(15-40s warm on CPU) and the caller only learns the run_id at the end. With
"async": true it returns the run_id straight away and the caller polls the
GET, which shows each phase as it is stored. Both modes run the same
pipeline. Every change is also appended to workflow_history.jsonl, and a
restart rebuilds every run from that file. See README.md for the timeout
chain.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

import agents
from store import (
    STATUS_REVIEWING,
    STATUS_WORKING,
    RunConflict,
    RunNotFound,
    WorkflowStore,
    now_iso,
)

DECISIONS = ("approve", "correct", "partial", "reject")

log = logging.getLogger(__name__)

# Host-process defaults: Ollama on the same host, so localhost rather than
# host.docker.internal. The model fallback matches every other service
# (CLAUDE.md); override with OLLAMA_MODEL in the environment.
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5:0.5b"
# Three agents x 55s stays inside gunicorn's 180s worker timeout in run.sh.
DEFAULT_AGENT_TIMEOUT_SECONDS = 55.0
# Next to this file rather than the working directory, so it is the same
# file however the server is started.
DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent / "workflow_history.jsonl"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes", "on")


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        STUB_AGENTS=_env_flag("STUB_AGENTS"),
        OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        AGENT_TIMEOUT_SECONDS=float(
            os.getenv("AGENT_TIMEOUT_SECONDS", DEFAULT_AGENT_TIMEOUT_SECONDS)
        ),
        WORKFLOW_HISTORY_PATH=os.getenv("WORKFLOW_HISTORY_PATH", str(DEFAULT_HISTORY_PATH)),
    )
    if config:
        app.config.update(config)

    store = WorkflowStore(app.config["WORKFLOW_HISTORY_PATH"])
    app.extensions["workflow_store"] = store

    def agent_config() -> agents.AgentConfig:
        return agents.AgentConfig(
            base_url=app.config["OLLAMA_BASE_URL"],
            model=app.config["OLLAMA_MODEL"],
            timeout_seconds=float(app.config["AGENT_TIMEOUT_SECONDS"]),
            stub=bool(app.config["STUB_AGENTS"]),
        )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/health")
    def health():
        config = agent_config()
        return jsonify(
            {
                "status": "ok",
                "model": config.model,
                "stub": config.stub,
                "ollama_reachable": agents.ping(config),
            }
        )

    @app.post("/workflow")
    def create_workflow():
        body, problem = _json_object()
        if problem:
            return problem

        fields = {}
        task = body.get("task")
        if task is None:
            fields["task"] = "is required"
        elif not isinstance(task, str) or not task.strip():
            fields["task"] = "must be a non-empty string"

        evidence = body.get("evidence")
        if evidence is None:
            fields["evidence"] = "is required"
        elif not isinstance(evidence, dict):
            fields["evidence"] = "must be a JSON object"

        caller = body.get("caller", "unknown")
        if not isinstance(caller, str) or not caller.strip():
            fields["caller"] = "must be a non-empty string when supplied"

        background = body.get("async", False)
        if not isinstance(background, bool):
            fields["async"] = "must be true or false when supplied"

        if fields:
            return _validation_error(fields)

        config = agent_config()
        run = store.create(
            task=task.strip(),
            evidence=evidence,
            caller=caller.strip(),
            model="stub" if config.stub else config.model,
            stub=config.stub,
        )
        run_id = run["run_id"]

        if background:
            # daemon: a run still going at shutdown is failed on the next
            # startup anyway, so it must not hold the process open.
            threading.Thread(
                target=_run_in_background, args=(store, run, config),
                name=f"workflow-{run_id}", daemon=True,
            ).start()
            response = jsonify(_public_view(run))
            response.headers["Location"] = f"/workflow/{run_id}"
            return response, 202

        try:
            finished = _run_agents(store, run, config)
        except agents.AgentUnavailable as exc:
            phase = store.get(run_id)["error"]["phase"]
            return _error(
                503, "agent_unavailable", f"{phase} phase failed: {exc}", run_id=run_id
            )
        return jsonify(_public_view(finished)), 201

    @app.get("/workflow/<run_id>")
    def get_workflow(run_id):
        try:
            run = store.get(run_id)
        except RunNotFound:
            return _unknown_run(run_id)
        return jsonify(_public_view(run))

    @app.post("/workflow/<run_id>/review")
    def review_workflow(run_id):
        # Unknown run is checked first: a 404 is more useful to the caller
        # than a validation error about a body for a run that doesn't exist.
        try:
            run = store.get(run_id)
        except RunNotFound:
            return _unknown_run(run_id)

        body, problem = _json_object()
        if problem:
            return problem

        fields = {}
        decision = body.get("decision")
        if decision is None:
            fields["decision"] = "is required"
        elif decision not in DECISIONS:
            fields["decision"] = f"must be one of: {', '.join(DECISIONS)}"

        note = body.get("note", "")
        if not isinstance(note, str):
            fields["note"] = "must be a string"
        elif decision == "partial" and not note.strip():
            fields["note"] = "is required for a partial decision -- say which part is accepted"

        corrected = body.get("corrected")
        if decision == "correct":
            if not isinstance(corrected, str) or not corrected.strip():
                fields["corrected"] = "is required for a correct decision -- the corrected text"
        elif corrected not in (None, ""):
            fields["corrected"] = "is only accepted with decision 'correct'"

        reviewer = body.get("reviewer", run["caller"])
        if not isinstance(reviewer, str) or not reviewer.strip():
            fields["reviewer"] = "must be a non-empty string when supplied"

        if fields:
            return _validation_error(fields)

        try:
            decided = store.decide(
                run_id,
                decision=decision,
                note=note.strip(),
                corrected=corrected.strip() if decision == "correct" else None,
                reviewer=reviewer.strip(),
            )
        except RunConflict as exc:
            return _error(409, "conflict", str(exc), run_id=run_id)

        return jsonify(
            {
                "run_id": run_id,
                "status": decided["status"],
                "decision": decided["human_review"]["decision"],
                "decided_at": decided["human_review"]["decided_at"],
            }
        )

    # ------------------------------------------------------------------
    # JSON for every error, including the ones Flask raises itself
    # ------------------------------------------------------------------

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return _error(exc.code, exc.name.lower().replace(" ", "_"), exc.description)

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        app.logger.exception("unhandled error")
        return _error(500, "internal_error", str(exc))

    return app


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _run_agents(store: WorkflowStore, run: dict, config: agents.AgentConfig) -> dict:
    """Planner, Worker, Reviewer, each stored as it finishes; park at awaiting_human.

    Any exception fails the run in the store before it propagates, so no
    caller -- a request or a background thread -- can leave a run stuck in
    an in-flight status until the next restart.
    """
    run_id, task, evidence = run["run_id"], run["task"], run["evidence"]
    phase = "plan"

    def run_phase(field, call):
        started_at = now_iso()
        result = call()
        store.record_phase(
            run_id, phase, field=field, output=result.output,
            record=_phase_record(result, started_at),
        )
        return result.output

    try:
        steps = run_phase("plan", lambda: agents.plan(task, evidence, config))

        phase = "work"
        store.set_status(run_id, STATUS_WORKING)
        work_text = run_phase("work", lambda: agents.work(task, evidence, steps, config))

        phase = "review"
        store.set_status(run_id, STATUS_REVIEWING)
        run_phase("review", lambda: agents.review(task, evidence, steps, work_text, config))
    except agents.AgentUnavailable as exc:
        store.fail(run_id, phase=phase, error=str(exc))
        raise
    except Exception as exc:
        store.fail(run_id, phase=phase, error=f"unexpected error: {exc}")
        raise

    return store.await_human(run_id)


def _run_in_background(store: WorkflowStore, run: dict, config: agents.AgentConfig) -> None:
    """Thread target for an async run. The failure is already on the run;
    nobody is waiting for an exception, so log it rather than let the thread
    die noisily."""
    try:
        _run_agents(store, run, config)
    except agents.AgentUnavailable as exc:
        log.warning("workflow %s failed: %s", run["run_id"], exc)
    except Exception:
        log.exception("workflow %s failed unexpectedly", run["run_id"])


def _public_view(run: dict) -> dict:
    """The contract body. Internal audit fields (prompts, evidence) stay out."""
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "plan": run["plan"],
        "work": run["work"],
        "review": run["review"],
        "model": run["model"],
        "stub": run["stub"],
        "human_review": run["human_review"],
        "error": run["error"],
    }


def _phase_record(result: agents.AgentResult, started_at: str) -> dict:
    return {
        "started_at": started_at,
        "finished_at": now_iso(),
        "prompt": result.prompt,
        "raw_response": result.raw,
        **result.extra,
    }


def _json_object():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, _validation_error({"body": "must be a JSON object"})
    return body, None


def _error(status: int, error: str, detail: str, **extra):
    return jsonify({"error": error, "detail": detail, **extra}), status


def _validation_error(fields: dict):
    detail = "; ".join(f"{name} {reason}" for name, reason in fields.items())
    return _error(400, "validation_failed", detail, fields=fields)


def _unknown_run(run_id: str):
    return _error(404, "not_found", f"no workflow run with id {run_id}", run_id=run_id)


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("MULTI_AGENT_PORT", "5004"))
    print("Starting shared Multi-Agent Server...")
    print(f"Listening on http://0.0.0.0:{port}")
    print(f"Stub agents: {app.config['STUB_AGENTS']}  Model: {app.config['OLLAMA_MODEL']}")
    print(f"History: {app.config['WORKFLOW_HISTORY_PATH']}")
    app.run(host="0.0.0.0", port=port, threaded=True)
