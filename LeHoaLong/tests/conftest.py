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
from types import SimpleNamespace

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
            # Off by default, which mirrors the CI environment exactly
            # (MCP_ENABLED=false in the workflow). The `stub_mcp` fixture
            # turns it on for the tests that exercise MCP, so a test that
            # does not ask for MCP cannot accidentally reach for a socket --
            # and the Release 0 tests go on asserting Release 0 behaviour.
            #
            # The URL is pointed at a host that cannot resolve as a second
            # line of defence, and is what shows up in an error message if
            # some future test forgets to stub the transport.
            "MCP_ENABLED": False,
            "MCP_SERVER_URL": "http://mcp.invalid:5002/mcp",
            "MCP_TIMEOUT_SECONDS": 20.0,
            # Same arrangement for RAG: off by default exactly as in CI, and
            # `stub_rag` switches it on for the tests that exercise it.
            "RAG_ENABLED": False,
            "RAG_SERVER_URL": "http://rag.invalid:5003",
            "RAG_TIMEOUT_SECONDS": 150.0,
            "RAG_TOP_K": 5,
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


# ---------------------------------------------------------------------------
# MCP (Release 1)
# ---------------------------------------------------------------------------

# The six tools mcp-server/server.py advertises, in the order it registers
# them. Named here so a test can assert on the two this feature actually uses
# without pretending the others do not exist.
MCP_TOOL_NAMES = (
    "portfolio_snapshot",
    "glossary_lookup",
    "document_search",
    "bill_summary",
    "transaction_summary",
    "goal_progress",
)


def mcp_tool_result(*texts, is_error=False, structured=None):
    """A stand-in for the SDK's CallToolResult.

    Duck-typed rather than constructed from mcp.types on purpose: the test
    suite must not need the MCP SDK installed (CI installs only
    tests/requirements.txt), and app/mcp/client.py reads results by getattr
    for exactly this reason.

    FastMCP serialises a tool's returned dict to one JSON text block, so one
    text argument is the live shape. Several model a tool that returned a
    list; none models a tool that returned None.
    """
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text) for text in texts],
        isError=is_error,
        structuredContent=structured,
    )


@pytest.fixture
def mcp_result():
    """The CallToolResult builder, for tests that need an unusual shape."""
    return mcp_tool_result


class _Immediate:
    """An awaitable that is already finished.

    Lets the fake session satisfy `await session.call_tool(...)` without an
    event loop. `__await__` is a generator that yields nothing and returns the
    value, so awaiting it completes in one step and never suspends.
    """

    def __init__(self, value):
        self.value = value

    def __await__(self):
        yield from ()
        return self.value


def _drive(outcome):
    """Run an awaitable to completion without an event loop.

    The production action may be a plain callable returning an awaitable (one
    tool call) or an async function (several tool calls over one session).
    Both are handled by stepping the awaitable exactly once: because every
    await inside resolves immediately, one `send(None)` finishes it.

    If it ever does suspend, that means the action tried to do real I/O, and
    this raises rather than quietly starting a loop -- which is the property
    that keeps the suite's no_network fixture meaningful.
    """
    if not hasattr(outcome, "__await__"):
        return outcome

    iterator = outcome.__await__()
    try:
        iterator.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError(
        "the fake MCP session suspended -- a stubbed session must never do real I/O"
    )


@pytest.fixture
def stub_mcp(app, monkeypatch):
    """Replace the MCP transport with a scripted in-process server.

    Installing the stub also switches MCP on for this app, because the only
    reason to install it is to exercise MCP. A test that wants the disabled
    path sets `app.config["MCP_ENABLED"] = False` back afterwards, which reads
    as the deliberate choice it is.

    Only `app.mcp.client._invoke` is replaced -- the one function whose whole
    body is transport. The action the caller passed is still executed, against
    a fake session, so the real tools/list and tools/call code, the real
    result parsing and the real error detection all run.

    The fake session's methods are plain functions rather than coroutines, and
    that is the trick that keeps this honest: `session.list_tools()` reads
    identically whether it returns a value or a coroutine, so the production
    lambdas are exercised unchanged while no event loop is ever created. No
    socket is opened either, so the autouse no_network fixture stays strict.

    install() takes:
        tools        the tool names the fake server advertises
        results      {tool_name: payload dict | CallToolResult | Exception}
        unavailable  an exception to raise instead of connecting, for the
                     server-is-down path

    and returns a `calls` list recording every protocol operation, so a test
    can assert on exactly what went over the wire.
    """
    from app.mcp import client as mcp_client

    calls: list[dict] = []

    def install(*, tools=MCP_TOOL_NAMES, results=None, unavailable=None):
        app.config["MCP_ENABLED"] = True
        payloads = dict(results or {})

        class _Session:
            def list_tools(self):
                calls.append({"op": "tools/list"})
                return _Immediate(
                    SimpleNamespace(
                        tools=[
                            SimpleNamespace(
                                name=name,
                                description=f"{name} -- relays figures another backend computed.",
                                inputSchema={"type": "object", "properties": {}},
                            )
                            for name in tools
                        ]
                    )
                )

            def call_tool(self, name, arguments=None):
                calls.append({"op": "tools/call", "tool": name, "arguments": dict(arguments or {})})
                if name not in payloads:
                    # What a real server answers for a name it does not know.
                    return _Immediate(mcp_tool_result(f"Unknown tool: {name}", is_error=True))
                item = payloads[name]
                if isinstance(item, BaseException):
                    raise item
                if isinstance(item, SimpleNamespace):
                    return _Immediate(item)
                return _Immediate(mcp_tool_result(json.dumps(item)))

        def _fake_invoke(action, timeout=None):
            if unavailable is not None:
                raise unavailable
            return _drive(action(_Session()))

        monkeypatch.setattr(mcp_client, "_invoke", _fake_invoke)
        return calls

    return install


# Payloads shaped exactly as the two tools this feature calls really answer.
# bill_summary mirrors hyunwoo/backend's GET /api/bills + /api/summary, whose
# monthly_cost is already converted from each bill's billing frequency by
# hyunwoo/backend/calculations.py. transaction_summary mirrors what
# mcp-server/tools.py extracts from Thomas's backend -- whole-ledger totals,
# with no period attached, which is why nothing divides them.
BILL_SUMMARY_PAYLOAD = {
    "bills": [
        {"bill_id": 1, "name": "Electricity", "amount": 180.40, "billing_frequency": "monthly"},
        {"bill_id": 6, "name": "Gym Membership", "amount": 29.95, "billing_frequency": "fortnightly"},
    ],
    "summary": {
        "active_bill_count": 10,
        "auto_renew_count": 9,
        "monthly_cost": 620.24,
        "annual_cost": 7442.88,
        "category_monthly_costs": {"Utilities": 269.40, "Entertainment": 39.98},
    },
}

TRANSACTION_SUMMARY_PAYLOAD = {
    "total_income": 7200.00,
    "total_expenses": 3410.55,
    "potential_deductions": 480.25,
}


# ---------------------------------------------------------------------------
# RAG (Release 1)
# ---------------------------------------------------------------------------

# Chunks shaped as rag-server/rag_pipeline.py produces them: the chunk_id is
# "<corpus file stem>_<n>", the source_id is the file name, and `distance` is
# Chroma's -- lower is closer. The text is from this feature's own corpus
# contribution, so the tests read the way the demo does.
RAG_SOURCE = "LeHoaLong_goals_budgeting_knowledge.txt"

RAG_CHUNKS = [
    {
        "rank": 1,
        "chunk_id": "LeHoaLong_goals_budgeting_knowledge_4",
        "source_id": RAG_SOURCE,
        "text": (
            "A savings goal is behind when the amount contributed to date is less than the "
            "amount the plan expected by that date."
        ),
        "distance": 0.21,
    },
    {
        "rank": 2,
        "chunk_id": "LeHoaLong_goals_budgeting_knowledge_7",
        "source_id": RAG_SOURCE,
        "text": (
            "When a savings goal is behind, the remaining amount can be spread across the "
            "instalments that remain so the goal still reaches its target date."
        ),
        "distance": 0.33,
    },
    {
        "rank": 3,
        "chunk_id": "LeHoaLong_goals_budgeting_knowledge_9",
        "source_id": RAG_SOURCE,
        "text": "An emergency fund is a savings goal held for unexpected expenses.",
        "distance": 0.47,
    },
]

RAG_ANSWER = (
    "A savings goal is behind when the amount contributed to date is less than the amount "
    "the plan expected by that date. The remaining amount can be spread across the "
    "instalments that remain so the goal still reaches its target date."
)


def rag_citations(chunks=None):
    """Citations as the shared server builds them: one per retrieved chunk."""
    return [
        {"chunk_id": chunk["chunk_id"], "source_id": chunk["source_id"]}
        for chunk in (RAG_CHUNKS if chunks is None else chunks)
    ]


@pytest.fixture
def stub_rag(app, monkeypatch):
    """Replace the RAG server's HTTP calls with a scripted stand-in.

    Only the two transport functions in app/rag/client.py are replaced, so the
    response reading, the citation pass-through, the insufficient-evidence
    detection and the chunk/citation cross-check are all the real code.

    Installing the stub switches RAG on for this app, because that is the only
    reason to install it. A test wanting the disabled path sets
    `app.config["RAG_ENABLED"] = False` back afterwards.

    install() takes:
        answer       the answer text the server returns
        confidence   its confidence_category, passed through untouched
        chunks       what /retrieve returns
        citations    what /answer returns; defaults to one per chunk, which
                     is what the real server does
        overrides    merged into the /answer body, for an unusual shape
        unavailable  an exception to raise instead of answering
        healthy      what GET /health reports

    and returns a `calls` list of {path, payload}, so a test can assert on
    exactly what was sent -- including the `caller` this backend identifies
    itself with in the RAG server's own audit log.
    """
    from app.rag import client as rag_client

    calls: list[dict] = []

    def install(
        *,
        answer=RAG_ANSWER,
        confidence="High",
        chunks=None,
        citations=None,
        overrides=None,
        unavailable=None,
        healthy=True,
    ):
        app.config["RAG_ENABLED"] = True
        retrieved = RAG_CHUNKS if chunks is None else chunks
        cited = rag_citations(retrieved) if citations is None else citations

        def _fake_post(path, payload, timeout=None):
            calls.append({"path": path, "payload": payload, "timeout": timeout})
            if unavailable is not None:
                raise unavailable
            if path == "/retrieve":
                return {"status": "success", "query": payload.get("query"),
                        "k": payload.get("k"), "results": retrieved}
            body = {
                "status": "success",
                "query": payload.get("query"),
                "answer": answer,
                "citations": cited,
                "confidence_category": confidence,
                "retrieval_summary": {"k": payload.get("k"), "retrieved_count": len(retrieved)},
            }
            body.update(overrides or {})
            return body

        def _fake_get(path, timeout):
            calls.append({"path": path, "payload": None, "timeout": timeout})
            if healthy:
                return True, {"status": "ok", "service": "rag-server"}, None
            return False, None, f"could not reach the RAG server at {path}: refused"

        monkeypatch.setattr(rag_client, "_post", _fake_post)
        monkeypatch.setattr(rag_client, "_get", _fake_get)
        return calls

    return install
