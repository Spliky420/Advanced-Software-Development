"""Run store for the multi-agent server.

Holds every workflow run and its state machine:

    planning -> working -> reviewing -> awaiting_human -> complete
        \\           \\           \\
         +-----------+-----------+--> failed   (an agent could not run)

Only `awaiting_human` accepts a human decision, and the check-and-set is
done under one lock, so two reviewers racing on the same run cannot both
succeed -- the loser gets a conflict, never a silent overwrite.

Every change to a run is one event, appended to workflow_history.jsonl
before it is applied in memory, and both go through the same `_apply`. So
the file is the record and memory is a cache of it: replaying the file on
startup rebuilds every run exactly, prompts and raw replies included.

A run caught mid-flight by a restart can never finish -- the request that
was driving it is gone -- so loading marks it failed, with an event of its
own so the file says so too.

Runs are still served from this process's memory, which is why run.sh
starts a single gunicorn worker (with threads, so a GET can poll while a
POST is blocked). Two processes appending to one file is not supported.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUS_PLANNING = "planning"
STATUS_WORKING = "working"
STATUS_REVIEWING = "reviewing"
STATUS_AWAITING_HUMAN = "awaiting_human"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"

# The phase that was running when a run was left in each in-flight status.
IN_FLIGHT = {STATUS_PLANNING: "plan", STATUS_WORKING: "work", STATUS_REVIEWING: "review"}

log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunNotFound(KeyError):
    """No run has this id."""


class RunConflict(Exception):
    """The run exists but is not in a state that allows this transition."""


class WorkflowStore:
    """Runs in memory, backed by an append-only JSONL file.

    `path=None` keeps runs in memory only, for tests of the state machine
    itself.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.path = Path(path) if path is not None else None
        if self.path is not None:
            self._load()

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
            self._commit({"event": "created", "run_id": run_id, "run": run})
            return copy.deepcopy(self._runs[run_id])

    def get(self, run_id: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._require(run_id))

    def set_status(self, run_id: str, status: str) -> None:
        with self._lock:
            self._require(run_id)
            self._commit({"event": "status", "run_id": run_id, "status": status})

    def record_phase(self, run_id: str, phase: str, *, field: str, output, record: dict) -> None:
        """Store one agent's output and its audit record as soon as it finishes."""
        with self._lock:
            self._require(run_id)
            self._commit(
                {"event": "phase", "run_id": run_id, "phase": phase,
                 "field": field, "output": output, "record": record}
            )

    def fail(self, run_id: str, *, phase: str, error: str) -> None:
        with self._lock:
            self._require(run_id)
            self._commit({"event": "failed", "run_id": run_id, "phase": phase, "detail": error})

    def await_human(self, run_id: str) -> dict:
        with self._lock:
            self._require(run_id)
            self._commit({"event": "awaiting_human", "run_id": run_id})
            return copy.deepcopy(self._runs[run_id])

    def decide(self, run_id: str, *, decision: str, note: str, corrected: str | None, reviewer: str) -> dict:
        """Apply the human decision -- once, and only to a run awaiting one."""
        with self._lock:
            run = self._require(run_id)
            if run["status"] != STATUS_AWAITING_HUMAN:
                raise RunConflict(
                    f"run {run_id} is {run['status']!r}; only a run that is "
                    f"{STATUS_AWAITING_HUMAN!r} can be reviewed"
                )
            self._commit(
                {"event": "decided", "run_id": run_id, "human_review": {
                    "decision": decision,
                    "note": note,
                    "corrected": corrected,
                    "reviewer": reviewer,
                }}
            )
            return copy.deepcopy(self._runs[run_id])

    def _require(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    # ------------------------------------------------------------------
    # The event log
    # ------------------------------------------------------------------

    def _commit(self, event: dict) -> None:
        """Write the event, then apply it. Caller holds the lock.

        Written first so memory never holds a change the file does not: if
        the write fails, the request fails and nothing changed.
        """
        event = {"at": now_iso(), **event}
        if self.path is not None:
            line = json.dumps(event, ensure_ascii=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        _apply(self._runs, event)

    def _load(self) -> None:
        """Rebuild every run from the file, then fail the interrupted ones."""
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                # A crash mid-write leaves a truncated last line. Losing that
                # one event is better than refusing to start.
                try:
                    _apply(self._runs, json.loads(line))
                except (ValueError, KeyError, TypeError) as exc:
                    log.warning("%s line %d skipped: %s", self.path, number, exc)

        with self._lock:
            for run_id, run in self._runs.items():
                phase = IN_FLIGHT.get(run["status"])
                if phase:
                    self._commit(
                        {"event": "failed", "run_id": run_id, "phase": phase,
                         "detail": "the server restarted before this run finished"}
                    )


def _apply(runs: dict, event: dict) -> None:
    """Apply one event to the runs. The only code that changes a run.

    Raises KeyError for an event about a run that was never created, and
    ValueError for an event type it does not know.
    """
    kind = event["event"]
    if kind == "created":
        run = copy.deepcopy(event["run"])
        runs[run["run_id"]] = run
        return

    run = runs[event["run_id"]]
    if kind == "status":
        run["status"] = event["status"]
    elif kind == "phase":
        run[event["field"]] = copy.deepcopy(event["output"])
        run["phases"][event["phase"]] = copy.deepcopy(event["record"])
    elif kind == "failed":
        run["status"] = STATUS_FAILED
        run["error"] = {"phase": event["phase"], "detail": event["detail"], "failed_at": event["at"]}
    elif kind == "awaiting_human":
        run["status"] = STATUS_AWAITING_HUMAN
    elif kind == "decided":
        run["status"] = STATUS_COMPLETE
        run["human_review"] = {**event["human_review"], "decided_at": event["at"]}
    else:
        raise ValueError(f"unknown event type {kind!r}")
