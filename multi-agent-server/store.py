"""Run store for the multi-agent server.

Holds every workflow run and its state machine:

    planning -> working -> reviewing -> awaiting_human -> complete
        \\           \\           \\
         +-----------+-----------+--> failed   (an agent could not run)

Only `awaiting_human` accepts a human decision, and the check-and-set is
done under one lock, so two reviewers racing on the same run cannot both
succeed -- the loser gets a conflict, never a silent overwrite.

Release 2 step 1 keeps runs in memory, which is why run.sh starts a single
gunicorn worker (with threads, so a GET can poll while a POST is blocked).
Persistence to workflow_history.jsonl is added behind this same interface.
"""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone

STATUS_PLANNING = "planning"
STATUS_WORKING = "working"
STATUS_REVIEWING = "reviewing"
STATUS_AWAITING_HUMAN = "awaiting_human"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunNotFound(KeyError):
    """No run has this id."""


class RunConflict(Exception):
    """The run exists but is not in a state that allows this transition."""


class WorkflowStore:
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, *, task: str, evidence: dict, caller: str, model: str, stub: bool) -> dict:
        run_id = uuid.uuid4().hex
        run = {
            "run_id": run_id,
            "status": STATUS_PLANNING,
            "caller": caller,
            "task": task,
            "evidence": evidence,
            "model": model,
            "stub": stub,
            "created_at": now_iso(),
            "plan": [],
            "work": "",
            "review": {"risks": [], "recommendations": []},
            # One entry per agent: timestamps, prompt and raw response.
            "phases": {},
            "error": None,
            "human_review": None,
        }
        with self._lock:
            self._runs[run_id] = run
            return copy.deepcopy(run)

    def get(self, run_id: str) -> dict:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            return copy.deepcopy(run)

    def set_status(self, run_id: str, status: str) -> None:
        with self._lock:
            self._require(run_id)["status"] = status

    def record_phase(self, run_id: str, phase: str, *, field: str, output, record: dict) -> None:
        """Store one agent's output and its audit record as soon as it finishes."""
        with self._lock:
            run = self._require(run_id)
            run[field] = output
            run["phases"][phase] = record

    def fail(self, run_id: str, *, phase: str, error: str) -> None:
        with self._lock:
            run = self._require(run_id)
            run["status"] = STATUS_FAILED
            run["error"] = {"phase": phase, "detail": error, "failed_at": now_iso()}

    def await_human(self, run_id: str) -> dict:
        with self._lock:
            run = self._require(run_id)
            run["status"] = STATUS_AWAITING_HUMAN
            return copy.deepcopy(run)

    def decide(self, run_id: str, *, decision: str, note: str, corrected: str | None, reviewer: str) -> dict:
        """Apply the human decision -- once, and only to a run awaiting one."""
        with self._lock:
            run = self._require(run_id)
            if run["status"] != STATUS_AWAITING_HUMAN:
                raise RunConflict(
                    f"run {run_id} is {run['status']!r}; only a run that is "
                    f"{STATUS_AWAITING_HUMAN!r} can be reviewed"
                )
            run["status"] = STATUS_COMPLETE
            run["human_review"] = {
                "decision": decision,
                "note": note,
                "corrected": corrected,
                "reviewer": reviewer,
                "decided_at": now_iso(),
            }
            return copy.deepcopy(run)

    def _require(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run
