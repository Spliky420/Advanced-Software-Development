#!/usr/bin/env python3
"""Plan -> Act -> Observe -> Adapt review of the project itself.

joshua/backend/drift.py runs this same four-phase loop over portfolio data --
a product feature reviewing a user's holdings. This script runs the loop over
the repository: whether each student's microservices exist, whether they are
wired into docker-compose.yml, whether each has a CI workflow, whether the
spec's root directories are present, and whether each declared database table
is actually seeded.

The shape deliberately mirrors drift.py: the four phases are the four public
functions below, in order; Plan, Act and Observe are pure Python and involve no
LLM at all; only Adapt talks to the model, and only ever about findings Observe
already produced. Each phase emits one aligned INFO line tagged with the run's
correlation id.

Read-only. Nothing here writes a file, opens a database connection, executes
SQL, or touches a container. Seed row counts come from reading init.sql and
seed.sql as text -- no .db file is opened and no student Python module is
imported for the checks. (joshua/backend/llm.py is imported in Adapt, and only
there, to reuse the team's single approved Ollama client.)

Usage:
    python scripts/review/agentic_review.py            # four phases + record
    python scripts/review/agentic_review.py --no-llm   # stop after Observe
    python scripts/review/agentic_review.py --json     # full result as JSON

Exit status is 0 whenever the review completes, findings or not: this is a
review tool, not a gate. Non-zero means the script itself failed.
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Same alignment rule as drift.py: pad to the width of the longest phase name
# ("OBSERVE") so the four lines of a run line up in a terminal.
PHASE_NAME_WIDTH = 7

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directory names as they appear on disk, which is not uniformly cased.
STUDENTS = ("joshua", "Enerel", "Maxwell", "Thomas", "hyunwoo")

# Every student is expected to ship these three microservices.
EXPECTED_SERVICE_DIRS = ("backend", "frontend", "database")

# Spec 7.1 root directories.
REQUIRED_ROOT_DIRS = ("docs", "shared", "ai-services", "scripts", ".github/workflows")

MINIMUM_SEED_ROWS = 10

CATEGORIES = ("database", "implementation", "architecture", "devops")

REVIEW_SYSTEM_PROMPT = (
    "You are a software project review assistant. You will be given a list of "
    "factual findings from an automated check of a student software project "
    "repository. Each finding states a category, a check identifier, a status, "
    "and a short factual detail. Using only those findings, write a short "
    "plain-English paragraph grouping the issues by category and stating what "
    "was found. Describe only -- never invent findings, never speculate about "
    "causes, never suggest fixes, and never restate or introduce any fact that "
    "is not given to you exactly as provided below."
)


class LLMUnavailableError(Exception):
    """Ollama could not be reached, timed out, or returned nothing usable."""


# ---------------------------------------------------------------------------
# Logging helpers -- same contract as drift.py's
# ---------------------------------------------------------------------------

def _run_id(*sources):
    """The correlation id carried by the first source that has one.

    Falls back to "-" so a caller passing a hand-built dict logs an anonymous
    run instead of raising.
    """
    for source in sources:
        try:
            value = source.get("run_id")
        except AttributeError:
            continue
        if value:
            return value
    return "-"


def _log(level, phase, run_id, template, *args):
    """Emit one aligned agentic-loop line.

    Never raises. Logging is evidence that the loop ran; a phase must not fail
    because a handler, a formatter or a malformed argument did.
    """
    try:
        logger.log(
            level,
            "[agentic-loop %s] %-*s | " + template,
            run_id, PHASE_NAME_WIDTH, phase, *args,
        )
    except Exception:  # noqa: BLE001 -- see docstring
        pass


def _chars(value):
    """Length of a text field for the log line, or -1 if it has none."""
    try:
        return len(value)
    except TypeError:
        return -1


def configure_logging(stream=None):
    """Send the root logger to `stream` (default stdout) at LOG_LEVEL.

    Idempotent, so importing this module and then running it as a script does
    not stack two handlers and print every line twice.
    """
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    for handler in root.handlers:
        if getattr(handler, "name", None) == "agentic-review":
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.name = "agentic-review"
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)


# ---------------------------------------------------------------------------
# SQL text parsing -- read as text, never executed
# ---------------------------------------------------------------------------

def _mask_sql(text):
    """Blank out string literals and comments, preserving overall length.

    Counting value tuples means counting parentheses, and a seed file is full
    of parentheses, commas and semicolons living inside quoted strings and
    `-- comments`. Masking those to 'x' and spaces first means the structural
    scan below only ever sees real syntax.
    """
    out = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "'":
                # '' is an escaped quote inside a SQLite string, not a close.
                if i + 1 < n and text[i + 1] == "'":
                    out.append("xx")
                    i += 2
                    continue
                in_string = False
                out.append("'")
            else:
                out.append("\n" if ch == "\n" else "x")
            i += 1
            continue

        if ch == "'":
            in_string = True
            out.append("'")
            i += 1
        elif ch == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                out.append("\n" if text[i] == "\n" else " ")
                i += 1
            for _ in range(min(2, n - i)):
                out.append(" ")
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

_INSERT_RE = re.compile(
    r"\bINSERT\s+(?:OR\s+[A-Z]+\s+)?INTO\s+[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _declared_tables(init_sql_text):
    """Table names declared by CREATE TABLE, in declaration order."""
    masked = _mask_sql(init_sql_text)
    seen = []
    for match in _CREATE_TABLE_RE.finditer(masked):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def _count_value_tuples(masked, start):
    """Number of top-level (...) groups between `start` and the next `;`.

    A single INSERT commonly carries many rows, so counting statements would
    report 1 where the file seeds 16. Counting the tuples is what answers "is
    this table populated".
    """
    depth = 0
    tuples = 0
    i = start
    n = len(masked)
    while i < n:
        ch = masked[i]
        if ch == "(":
            if depth == 0:
                tuples += 1
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            break
        i += 1
    return tuples


def _count_seed_rows(seed_sql_text):
    """Rows inserted per table, summed across every INSERT in the file."""
    masked = _mask_sql(seed_sql_text)
    counts = {}
    for match in _INSERT_RE.finditer(masked):
        table = match.group(1)
        values = re.compile(r"\bVALUES\b", re.IGNORECASE).search(masked, match.end())
        if values is None:
            # INSERT ... SELECT, or a form with no VALUES clause. Countable
            # rows are unknown, so contribute nothing rather than guess.
            counts.setdefault(table, 0)
            continue
        counts[table] = counts.get(table, 0) + _count_value_tuples(masked, values.end())
    return counts


def _read_text(path):
    """File contents, or None if it is missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# PLAN
# ---------------------------------------------------------------------------

def plan(repo_root):
    """PLAN: decide which checks to run. Resolves paths, performs no I/O."""
    repo_root = Path(repo_root)

    checks = []
    for student in STUDENTS:
        checks.append({
            "check_id": f"structure.{student}",
            "category": "implementation",
            "description": (
                f"{student}/ exists and contains "
                + ", ".join(f"{d}/" for d in EXPECTED_SERVICE_DIRS)
            ),
        })
    for student in STUDENTS:
        checks.append({
            "check_id": f"compose.{student}",
            "category": "architecture",
            "description": f"docker-compose.yml defines a service block for {student}",
        })
    for directory in REQUIRED_ROOT_DIRS:
        checks.append({
            "check_id": f"layout.{directory}",
            "category": "architecture",
            "description": f"spec 7.1 root directory {directory}/ exists",
        })
    for student in STUDENTS:
        checks.append({
            "check_id": f"ci.{student}",
            "category": "devops",
            "description": f".github/workflows/ contains a CI workflow for {student}",
        })
    for student in STUDENTS:
        checks.append({
            "check_id": f"seed.{student}",
            "category": "database",
            "description": (
                f"every table declared in {student}/database/init.sql is seeded "
                f"with >= {MINIMUM_SEED_ROWS} rows by seed.sql"
            ),
        })

    result = {
        "phase": "plan",
        # Plan opens the run, so it is where the correlation id is minted.
        "run_id": uuid.uuid4().hex[:8],
        "description": (
            "Decide which project-level checks to run across the database, "
            "implementation, architecture and DevOps categories."
        ),
        "repo_root": str(repo_root),
        "students": list(STUDENTS),
        "required_root_dirs": list(REQUIRED_ROOT_DIRS),
        "minimum_seed_rows": MINIMUM_SEED_ROWS,
        "checks": checks,
    }

    _log(
        logging.INFO, "PLAN", _run_id(result),
        "checks_planned=%d | categories=%s",
        len(checks), ",".join(CATEGORIES),
    )
    return result


# ---------------------------------------------------------------------------
# ACT
# ---------------------------------------------------------------------------

def _check_structure(repo_root, student):
    student_dir = repo_root / student
    if not student_dir.is_dir():
        return "fail", f"{student}/ does not exist"
    missing = [d for d in EXPECTED_SERVICE_DIRS if not (student_dir / d).is_dir()]
    if missing:
        return "fail", (
            f"{student}/ is missing " + ", ".join(f"{d}/" for d in missing)
        )
    return "pass", f"{student}/ has " + ", ".join(f"{d}/" for d in EXPECTED_SERVICE_DIRS)


def _compose_services(repo_root):
    """Service names in docker-compose.yml, or None if unavailable."""
    path = repo_root / "docker-compose.yml"
    text = _read_text(path)
    if text is None:
        return None, "docker-compose.yml not found"
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is not installed, so docker-compose.yml was not parsed"
    try:
        parsed = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 -- any parse failure is "unknown"
        return None, f"docker-compose.yml could not be parsed: {exc}"
    if not isinstance(parsed, dict) or not isinstance(parsed.get("services"), dict):
        return None, "docker-compose.yml has no services mapping"
    return sorted(parsed["services"]), None


def _check_compose(student, services, problem):
    if services is None:
        return "unknown", problem
    owned = [s for s in services if s.lower().startswith(student.lower() + "-")]
    if not owned:
        return "fail", f"docker-compose.yml defines no service named {student.lower()}-*"
    return "pass", f"docker-compose.yml defines {len(owned)} service(s): " + ", ".join(owned)


def _check_layout(repo_root, directory):
    if (repo_root / directory).is_dir():
        return "pass", f"{directory}/ exists"
    return "fail", f"{directory}/ does not exist"


def _check_ci(repo_root, student):
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return "unknown", ".github/workflows/ does not exist"
    matches = sorted(
        p.name for p in workflows_dir.iterdir()
        if p.is_file() and student.lower() in p.name.lower()
    )
    if not matches:
        return "fail", f"no workflow file in .github/workflows/ names {student}"
    return "pass", "workflow file(s): " + ", ".join(matches)


def _check_seed(repo_root, student):
    """Per-table seeded row counts, read from SQL text only."""
    db_dir = repo_root / student / "database"
    if not db_dir.is_dir():
        return "unknown", f"{student}/database/ does not exist", []

    init_text = _read_text(db_dir / "init.sql")
    if init_text is None:
        return "unknown", f"{student}/database/init.sql is missing or unreadable", []

    tables = _declared_tables(init_text)
    if not tables:
        return "unknown", f"{student}/database/init.sql declares no CREATE TABLE", []

    seed_text = _read_text(db_dir / "seed.sql")
    if seed_text is None:
        return "unknown", (
            f"{student}/database/seed.sql is missing, so row counts for "
            f"{len(tables)} table(s) are unknown"
        ), []

    counts = _count_seed_rows(seed_text)
    per_table = [{"table": t, "rows": counts.get(t, 0)} for t in tables]
    short = [t for t in per_table if t["rows"] < MINIMUM_SEED_ROWS]
    summary = ", ".join(f"{t['table']}={t['rows']}" for t in per_table)

    if short:
        names = ", ".join(f"{t['table']} ({t['rows']})" for t in short)
        return "fail", (
            f"seed.sql populates fewer than {MINIMUM_SEED_ROWS} rows for: {names}"
            f" [all tables: {summary}]"
        ), per_table
    return "pass", f"all {len(tables)} table(s) seeded >= {MINIMUM_SEED_ROWS}: {summary}", per_table


def act(plan_result):
    """ACT: run the planned checks. Pure Python, read-only, no SQL executed."""
    repo_root = Path(plan_result["repo_root"])
    services, compose_problem = _compose_services(repo_root)

    results = []
    seed_detail = {}
    for check in plan_result["checks"]:
        check_id = check["check_id"]
        kind, _, target = check_id.partition(".")

        if kind == "structure":
            status, detail = _check_structure(repo_root, target)
        elif kind == "compose":
            status, detail = _check_compose(target, services, compose_problem)
        elif kind == "layout":
            status, detail = _check_layout(repo_root, target)
        elif kind == "ci":
            status, detail = _check_ci(repo_root, target)
        elif kind == "seed":
            status, detail, per_table = _check_seed(repo_root, target)
            seed_detail[target] = per_table
        else:
            status, detail = "unknown", f"no handler for check kind '{kind}'"

        results.append({
            "check_id": check_id,
            "category": check["category"],
            "status": status,
            "detail": detail,
        })

    tally = {s: sum(1 for r in results if r["status"] == s)
             for s in ("pass", "fail", "unknown")}

    result = {
        "phase": "act",
        "run_id": _run_id(plan_result),
        "description": (
            "Run every planned check against the repository on disk, reading "
            "files as text only."
        ),
        "compose_services": services or [],
        "seed_row_counts": seed_detail,
        "results": results,
        "tally": tally,
    }

    run_id = _run_id(result, plan_result)
    _log(
        logging.INFO, "ACT", run_id,
        "checks_run=%d | pass=%d | fail=%d | unknown=%d",
        len(results), tally["pass"], tally["fail"], tally["unknown"],
    )
    _log(logging.DEBUG, "ACT", run_id, "results=%r", results)
    return result


# ---------------------------------------------------------------------------
# OBSERVE
# ---------------------------------------------------------------------------

def observe(act_result):
    """OBSERVE: keep only the fail/unknown results, grouped by category.

    Pure Python -- no LLM involvement.
    """
    results = act_result["results"]

    findings = [r for r in results if r["status"] in ("fail", "unknown")]
    findings.sort(key=lambda r: (CATEGORIES.index(r["category"])
                                 if r["category"] in CATEGORIES else len(CATEGORIES),
                                 r["check_id"]))

    by_category = {}
    for category in CATEGORIES:
        rows = [r for r in results if r["category"] == category]
        by_category[category] = {
            "total": len(rows),
            "pass": sum(1 for r in rows if r["status"] == "pass"),
            "fail": sum(1 for r in rows if r["status"] == "fail"),
            "unknown": sum(1 for r in rows if r["status"] == "unknown"),
        }

    result = {
        "phase": "observe",
        # Adapt is handed only this dict, so the id has to travel in it.
        "run_id": _run_id(act_result),
        "description": (
            "Group the check results by category and keep only those that "
            "failed or could not be determined."
        ),
        "finding_count": len(findings),
        "passed_count": sum(1 for r in results if r["status"] == "pass"),
        "findings": findings,
        "by_category": by_category,
    }

    summary = "; ".join(
        f"{c} {by_category[c]['fail']}f/{by_category[c]['unknown']}u"
        f"/{by_category[c]['total']}"
        for c in CATEGORIES
    )
    _log(
        logging.INFO, "OBSERVE", _run_id(result, act_result),
        "findings=%d | passed=%d | by_category=%s",
        len(findings), result["passed_count"], summary,
    )
    return result


# ---------------------------------------------------------------------------
# ADAPT -- the only phase that talks to the model
# ---------------------------------------------------------------------------

def build_review_prompt(observe_result):
    """Format the findings as finished facts for the model."""
    lines = [
        f"Findings: {observe_result['finding_count']}",
        "Each line states category, check identifier, status and detail:",
    ]
    for finding in observe_result["findings"]:
        lines.append(
            f"- [{finding['category']}] {finding['check_id']}: "
            f"{finding['status']} -- {finding['detail']}"
        )
    return "\n".join(lines)


def _ollama_generate(prompt, system=None):
    """Fallback twin of joshua/backend/llm.py, same env vars and behaviour."""
    try:
        import requests
    except ImportError as exc:
        raise LLMUnavailableError(f"the requests package is not installed: {exc}") from exc

    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
    url = base.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if system:
        payload["system"] = system

    try:
        response = requests.post(url, json=payload, timeout=60)
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"could not reach Ollama at {url}: {exc}") from exc

    if response.status_code == 404:
        raise LLMUnavailableError(
            f"model '{model}' is not available in the Ollama container "
            f"— pull it with docker compose exec ollama ollama pull {model}"
        )
    try:
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise LLMUnavailableError(f"Ollama returned an error response: {exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMUnavailableError(f"Ollama returned a non-JSON response: {exc}") from exc

    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise LLMUnavailableError("Ollama response did not contain any generated text")
    return text.strip(), model


def load_generate(repo_root=REPO_ROOT):
    """joshua/backend/llm.generate if it imports cleanly, else the local twin.

    The team's rule is one approved Ollama client, so reuse is preferred over a
    second implementation; the twin exists only so this script still runs from
    a checkout where that module cannot be imported.
    """
    backend = str(Path(repo_root) / "joshua" / "backend")
    added = False
    try:
        if backend not in sys.path:
            sys.path.insert(0, backend)
            added = True
        import llm as joshua_llm
    except Exception:  # noqa: BLE001 -- any import problem falls back
        if added:
            try:
                sys.path.remove(backend)
            except ValueError:
                pass
        return _ollama_generate, "local"

    def reused(prompt, system=None):
        try:
            return joshua_llm.generate(prompt, system=system)
        except joshua_llm.LLMUnavailableError as exc:
            raise LLMUnavailableError(str(exc)) from exc

    return reused, "joshua/backend/llm.py"


def adapt(observe_result, generate_fn=None):
    """ADAPT: have the model describe the findings in plain English.

    Only the findings are sent. When there are none, this says so directly and
    never calls the LLM.
    """
    run_id = _run_id(observe_result)

    if observe_result["finding_count"] == 0:
        # The skip is the decision that makes this loop agentic rather than a
        # fixed pipeline, so it is logged as explicitly as a call would be.
        _log(
            logging.INFO, "ADAPT", run_id,
            "llm_called=False | reason=no findings, LLM skipped",
        )
        return {
            "phase": "adapt",
            "run_id": run_id,
            "description": (
                "Report the observed findings in plain English, or state "
                "directly that there were none."
            ),
            "llm_called": False,
            "summary": (
                f"All {observe_result['passed_count']} project checks passed: no "
                f"failing or indeterminate result was found in any of the "
                f"{len(CATEGORIES)} categories."
            ),
            "prompt_sent": None,
            "model_name": None,
            "generate_source": None,
        }

    if generate_fn is not None:
        generate, source = generate_fn, "injected"
    else:
        generate, source = load_generate()

    figures = build_review_prompt(observe_result)
    response_text, model_name = generate(figures, system=REVIEW_SYSTEM_PROMPT)
    prompt_sent = REVIEW_SYSTEM_PROMPT + "\n\n" + figures

    _log(
        logging.INFO, "ADAPT", run_id,
        "llm_called=True | model=%s | prompt_chars=%d | response_chars=%d",
        model_name, _chars(prompt_sent), _chars(response_text),
    )
    _log(logging.DEBUG, "ADAPT", run_id, "prompt_sent=%s", prompt_sent)
    _log(logging.DEBUG, "ADAPT", run_id, "response_text=%s", response_text)

    return {
        "phase": "adapt",
        "run_id": run_id,
        "description": (
            "Report the observed findings in plain English, or state directly "
            "that there were none."
        ),
        "llm_called": True,
        "summary": response_text,
        "prompt_sent": prompt_sent,
        "model_name": model_name,
        "generate_source": source,
    }


# ---------------------------------------------------------------------------
# Review record
# ---------------------------------------------------------------------------

def format_record(plan_result, act_result, observe_result, adapt_result=None):
    """The plain-text review record printed after the four log lines."""
    width = 78
    out = [
        "=" * width,
        f"PROJECT REVIEW RECORD -- run_id {plan_result['run_id']}",
        "=" * width,
        f"repository      : {plan_result['repo_root']}",
        f"checks planned  : {len(plan_result['checks'])}",
        f"checks run      : {len(act_result['results'])}",
        f"pass / fail / unknown : {act_result['tally']['pass']} / "
        f"{act_result['tally']['fail']} / {act_result['tally']['unknown']}",
        "",
        "-" * width,
        "BY CATEGORY",
        "-" * width,
        f"{'CATEGORY':<16}{'TOTAL':>7}{'PASS':>7}{'FAIL':>7}{'UNKNOWN':>9}",
    ]
    for category in CATEGORIES:
        stats = observe_result["by_category"][category]
        out.append(
            f"{category:<16}{stats['total']:>7}{stats['pass']:>7}"
            f"{stats['fail']:>7}{stats['unknown']:>9}"
        )

    out += ["", "-" * width, f"FINDINGS ({observe_result['finding_count']})", "-" * width]
    if not observe_result["findings"]:
        out.append("None. Every check passed.")
    else:
        current = None
        for finding in observe_result["findings"]:
            if finding["category"] != current:
                current = finding["category"]
                out.append(f"\n[{current}]")
            out.append(
                f"  {finding['status'].upper():<8} {finding['check_id']}\n"
                f"           {finding['detail']}"
            )

    out += ["", "-" * width, "PASSED CHECKS", "-" * width]
    for check in act_result["results"]:
        if check["status"] == "pass":
            out.append(f"  PASS     {check['check_id']}\n           {check['detail']}")

    out += ["", "-" * width, "ADAPT", "-" * width]
    if adapt_result is None:
        out.append("Skipped: --no-llm was passed, so the loop stopped after Observe.")
    else:
        out.append(f"llm_called : {adapt_result['llm_called']}")
        if adapt_result["llm_called"]:
            out.append(f"model      : {adapt_result['model_name']}")
            out.append(f"client     : {adapt_result['generate_source']}")
        out.append("")
        out.append(adapt_result["summary"])
    out.append("=" * width)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(repo_root=REPO_ROOT, use_llm=True, generate_fn=None):
    """Run the four phases and return every phase result."""
    plan_result = plan(repo_root)
    act_result = act(plan_result)
    observe_result = observe(act_result)

    adapt_result = None
    llm_error = None
    if use_llm:
        try:
            adapt_result = adapt(observe_result, generate_fn=generate_fn)
        except LLMUnavailableError as exc:
            # A review tool must still deliver its findings when the optional
            # narration is unavailable, so this is recorded, not raised.
            llm_error = str(exc)
            _log(
                logging.WARNING, "ADAPT", _run_id(observe_result),
                "llm_called=False | reason=LLM unavailable: %s", llm_error,
            )

    return {
        "plan": plan_result,
        "act": act_result,
        "observe": observe_result,
        "adapt": adapt_result,
        "llm_error": llm_error,
        "run_id": plan_result["run_id"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Plan -> Act -> Observe -> Adapt review of this repository.",
    )
    parser.add_argument("--json", action="store_true",
                        help="emit the full four-phase result as JSON on stdout")
    parser.add_argument("--no-llm", action="store_true",
                        help="stop after Observe; never contact Ollama")
    parser.add_argument("--repo-root", default=str(REPO_ROOT),
                        help="repository root (defaults to this script's grandparent)")
    args = parser.parse_args(argv)

    # In --json mode the log lines go to stderr so stdout stays parseable.
    configure_logging(stream=sys.stderr if args.json else sys.stdout)

    outcome = run(repo_root=args.repo_root, use_llm=not args.no_llm)

    if args.json:
        json.dump(outcome, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print()
        print(format_record(outcome["plan"], outcome["act"],
                            outcome["observe"], outcome["adapt"]))
        if outcome["llm_error"]:
            print(f"\nADAPT was skipped: {outcome['llm_error']}")

    # Findings are the product, not a failure: always 0 on a completed review.
    return 0


if __name__ == "__main__":
    sys.exit(main())
