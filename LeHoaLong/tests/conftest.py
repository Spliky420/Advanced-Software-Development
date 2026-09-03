"""Shared pytest fixtures.

Every test gets its own database, built from the real schema.sql and
seed.sql in a temporary directory. That means:

  * tests exercise the same schema the container runs, constraints included
  * a test that writes cannot affect the next test
  * nothing touches a real database file, and no container needs to be up

No test may reach the network. The `no_network` fixture is autouse and makes
any attempt to open a socket fail loudly rather than hang, so a missing mock
shows up as an error naming the test rather than as a slow CI job.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "LeHoaLong" / "backend"
DATABASE_DIR = REPO_ROOT / "LeHoaLong" / "database"

# The backend is a plain directory rather than an installed package, so make
# `import app` and `import config` resolve the same way they do in the
# container, where /app is the working directory.
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402  (import must follow the sys.path edit)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "this test tried to use the network -- mock the Ollama client instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(scope="session")
def seeded_template(tmp_path_factory) -> Path:
    """Build the seeded database once for the whole run.

    Executing seed.sql is by far the most expensive thing in the suite, and
    it produces the same bytes every time. Build it once, then hand each test
    a copy.
    """
    path = tmp_path_factory.mktemp("template") / "template.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript((DATABASE_DIR / "schema.sql").read_text(encoding="utf-8"))
        conn.executescript((DATABASE_DIR / "seed.sql").read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def db_path(tmp_path, seeded_template) -> Path:
    """This test's own private copy of the seeded database."""
    path = tmp_path / "goals.db"
    shutil.copyfile(seeded_template, path)
    return path


@pytest.fixture
def app(db_path):
    """An app wired to the temporary database."""
    application = create_app(
        {
            "TESTING": True,
            "DB_PATH": str(db_path),
            "OLLAMA_BASE_URL": "http://ollama.invalid:11434",
            "OLLAMA_MODEL": "test-model:0.1b",
        }
    )
    yield application


@pytest.fixture
def client(app):
    """A Flask test client. This is what most tests drive."""
    return app.test_client()


@pytest.fixture
def conn(db_path):
    """A direct connection, for asserting on rows the API should have written."""
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


@pytest.fixture
def stub_ollama(monkeypatch):
    """Replace the Ollama reachability probe with a fixed answer.

    Returns a setter so a test can choose the outcome it wants to exercise.
    """
    from app.ai import client as ollama

    def _set(reachable=True, model_available=True, detail=None):
        monkeypatch.setattr(
            ollama,
            "ping",
            lambda: {
                "reachable": reachable,
                "model": "test-model:0.1b",
                "model_available": model_available,
                "base_url": "http://ollama.invalid:11434",
                "detail": detail,
            },
        )

    return _set


@pytest.fixture
def service_conn(app):
    """A connection inside an app context, for testing services directly.

    The agent service reads tolerances from current_app.config, so its unit
    tests need the context that a request would normally have provided.
    """
    from app.db import get_db

    with app.app_context():
        yield get_db()


def echo_descriptions(prompt: str, summary: str | None = None) -> str:
    """A well-behaved model's answer, derived from the prompt it was given.

    Reads the step_order values out of the schedule in the prompt and returns
    one description for each. Deriving it from the prompt rather than hard
    coding orders keeps the tests independent of today's date, which decides
    how many instalments a plan actually has.
    """
    orders = [int(match) for match in re.findall(r"step_order (\d+):", prompt)]
    payload: dict = {
        "steps": [
            {"step_order": order, "description": f"Put aside this month's amount (step {order})"}
            for order in orders
        ]
    }
    if summary is not None:
        payload["summary"] = summary
    return json.dumps(payload)


@pytest.fixture
def fake_model(monkeypatch):
    """Replace Ollama's generate() with a scripted stand-in.

    Call the returned installer with the responses the model should give, in
    order; the last one repeats if it is asked more times than there are
    responses. A response may be:

        a string      -- returned as the raw model output
        a callable    -- called with the prompt, returns the raw output
        an Exception  -- raised, for testing the unreachable path

    The installer returns a `calls` list, so a test can assert on exactly
    what was sent to the model.
    """
    from app.ai import client as ollama

    calls: list[dict] = []

    def install(*responses, model_name="test-model:0.1b"):
        queue = list(responses) or [echo_descriptions]

        def _generate(prompt, *, system=None, json_format=True):
            calls.append({"prompt": prompt, "system": system, "json_format": json_format})
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                return item(prompt), model_name
            return item, model_name

        monkeypatch.setattr(ollama, "generate", _generate)
        return calls

    return install
