import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# server.py builds an app at import. Point it away from the real history
# file first, or importing it would replay -- and fail the in-flight runs
# of -- a server running on this machine.
os.environ["WORKFLOW_HISTORY_PATH"] = str(
    Path(tempfile.mkdtemp(prefix="multi-agent-tests-")) / "workflow_history.jsonl"
)

import agents  # noqa: E402
import server  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a socket -- the suite must run offline."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def history_path(tmp_path, monkeypatch):
    """A fresh history file per test, also for apps built from the environment."""
    path = tmp_path / "workflow_history.jsonl"
    monkeypatch.setenv("WORKFLOW_HISTORY_PATH", str(path))
    return path


@pytest.fixture
def app(monkeypatch, history_path):
    monkeypatch.setattr(agents, "ping", lambda config: False)
    return server.create_app(
        {
            "TESTING": True,
            "WORKFLOW_HISTORY_PATH": str(history_path),
            "STUB_AGENTS": True,
            "OLLAMA_MODEL": "test-model:tag",
            "OLLAMA_BASE_URL": "http://ollama.invalid:11434",
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


EVIDENCE = {"items": [{"name": "alpha", "value": 12.5}], "notes": "supplied by the caller"}


@pytest.fixture
def run(client):
    """A run parked at awaiting_human."""
    response = client.post(
        "/workflow", json={"task": "Plan the next step", "evidence": EVIDENCE, "caller": "tester"}
    )
    assert response.status_code == 201
    return response.get_json()
