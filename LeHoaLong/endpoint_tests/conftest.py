"""Post-commit endpoint tests: two endpoints, over real HTTP.

These run against a backend that is actually serving -- in CI, the built
backend image on a database the database image seeded -- not Flask's test
client. They live outside tests/ on purpose: that suite's autouse
`no_network` fixture blocks every socket, and opening one is the point here.

    ENDPOINT_BASE_URL   the running backend, e.g. http://127.0.0.1:8061 (required)
    ENDPOINT_DB_PATH    a copy of the database it serves, used as the oracle (required)
    ENDPOINT_REPORT_DIR where the report is written (default: endpoint_tests/report/, git-ignored)

**The oracle.** Both endpoints depend on today's date, so expected figures
cannot be written down in advance. Each test reads the date the response
says it used (`as_at`) and recomputes the figures from the database with
plain SQL plus the documented formula -- a second implementation, not a
call into the backend's own code, so a bug in the service is not mirrored
in its own test.

**Exactly two endpoints.** Every request goes through `Api.get`, which
refuses any path but these two. The suite cannot drift into testing a third
endpoint without that allow-list being changed on purpose.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import requests

ENDPOINTS = {
    "GET /api/goals/<id>/progress": re.compile(r"^/api/goals/[^/]+/progress$"),
    "GET /api/budget/summary": re.compile(r"^/api/budget/summary$"),
}

# (connect, read). Both endpoints are pure Python over SQLite; a second is
# already slow. Generous anyway so a cold CI runner does not flake.
TIMEOUT = (5, 15)

# Cents. The backend rounds to 2dp and the oracle rounds the same way, but
# summing floats in a different order can still differ in the last place.
MONEY = 0.01

_requests: list[dict] = []
_results: list[dict] = []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.exit(f"{name} is not set -- see endpoint_tests/conftest.py", returncode=2)
    return value


@pytest.fixture(scope="session")
def base_url() -> str:
    return _required_env("ENDPOINT_BASE_URL").rstrip("/")


@pytest.fixture(scope="session")
def oracle(base_url) -> sqlite3.Connection:
    path = Path(_required_env("ENDPOINT_DB_PATH"))
    if not path.is_file():
        pytest.exit(f"ENDPOINT_DB_PATH {path} does not exist", returncode=2)
    # Read-only: the oracle must never be the thing that changes the data.
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# HTTP, recorded for the report
# ---------------------------------------------------------------------------


class Api:
    def __init__(self, base_url: str, test_id: str):
        self.base_url = base_url
        self.test_id = test_id
        self.session = requests.Session()
        # Never pick up a proxy or .netrc from the runner's environment.
        self.session.trust_env = False

    def get(self, path: str, params: dict | None = None) -> requests.Response:
        endpoint = next((name for name, pattern in ENDPOINTS.items() if pattern.match(path)), None)
        if endpoint is None:
            raise AssertionError(f"{path} is not one of the two endpoints this suite tests")
        started = time.perf_counter()
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=TIMEOUT)
        _requests.append(
            {
                "test": self.test_id,
                "endpoint": endpoint,
                "url": response.request.path_url,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        return response


@pytest.fixture
def api(base_url, request) -> Api:
    return Api(base_url, request.node.nodeid.split("::", 1)[-1])


def json_body(response: requests.Response) -> dict:
    assert response.headers.get("Content-Type", "").startswith("application/json"), response.headers
    return response.json()


def response_date(body: dict) -> date:
    """The date the backend computed with -- and a check that it is today.

    UTC, as the backend uses. A day either side is allowed so a run that
    straddles midnight UTC does not fail; anything further means the
    container's clock or timezone handling is wrong.
    """
    as_at = date.fromisoformat(body["as_at"])
    today = datetime.now(UTC).date()
    assert abs(as_at - today) <= timedelta(days=1), f"as_at {as_at} is not today ({today} UTC)"
    return as_at


# ---------------------------------------------------------------------------
# The oracle's arithmetic -- written from the documented definitions
# ---------------------------------------------------------------------------


def months_between(start: date, end: date) -> int:
    """Whole months from start to end, rounded up; 0 if end is not after start."""
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        months += 1
    return max(months, 1)


def saved(oracle: sqlite3.Connection, goal_id: int) -> float:
    row = oracle.execute("SELECT COALESCE(SUM(amount), 0) FROM contributions WHERE goal_id = ?", (goal_id,))
    return round(row.fetchone()[0], 2)


# ---------------------------------------------------------------------------
# The report artefact
# ---------------------------------------------------------------------------


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        _results.append(
            {
                "test": report.nodeid.split("::", 1)[-1],
                "file": report.nodeid.split("::", 1)[0].rsplit("/", 1)[-1],
                "outcome": report.outcome,
                "seconds": round(report.duration, 3),
                "detail": str(report.longrepr).splitlines()[-1] if report.failed and report.longrepr else "",
            }
        )


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    out = Path(os.environ.get("ENDPOINT_REPORT_DIR") or Path(__file__).parent / "report")
    out.mkdir(parents=True, exist_ok=True)

    passed = sum(r["outcome"] == "passed" for r in _results)
    meta = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA", "local"),
        "base_url": os.environ.get("ENDPOINT_BASE_URL", ""),
        "endpoints": list(ENDPOINTS),
        "tests": len(_results),
        "passed": passed,
        "failed": len(_results) - passed,
    }
    (out / "endpoint-report.json").write_text(
        json.dumps({**meta, "results": _results, "requests": _requests}, indent=2), encoding="utf-8"
    )

    lines = [
        "# Post-commit endpoint tests",
        "",
        f"- Commit: `{meta['commit']}`",
        f"- Backend: `{meta['base_url']}`",
        f"- Generated: {meta['generated_at']}",
        f"- Result: **{passed}/{len(_results)} passed**",
        "",
        "## Endpoints",
        "",
        "| Endpoint | Requests | Statuses | Slowest |",
        "| -------- | -------- | -------- | ------- |",
    ]
    for name in ENDPOINTS:
        hits = [r for r in _requests if r["endpoint"] == name]
        codes = sorted({r["status"] for r in hits})
        statuses = ", ".join(f"{code} ×{sum(r['status'] == code for r in hits)}" for code in codes)
        slowest = f"{max(r['ms'] for r in hits)} ms" if hits else "-"
        lines.append(f"| `{name}` | {len(hits)} | {statuses or '-'} | {slowest} |")
    lines += ["", "## Tests", "", "| Result | Test | Time |", "| ------ | ---- | ---- |"]
    for r in _results:
        mark = "PASS" if r["outcome"] == "passed" else r["outcome"].upper()
        detail = f" — {r['detail']}" if r["detail"] else ""
        lines.append(f"| {mark} | `{r['test']}`{detail} | {r['seconds']}s |")
    lines += ["", "## Requests", "", "| Status | URL | ms | Test |", "| ------ | --- | -- | ---- |"]
    lines += [f"| {r['status']} | `{r['url']}` | {r['ms']} | `{r['test']}` |" for r in _requests]
    (out / "endpoint-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
