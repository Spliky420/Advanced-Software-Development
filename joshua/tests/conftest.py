import os
import sys

import pytest

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


@pytest.fixture(autouse=True)
def _mcp_off_by_default(monkeypatch):
    """Keep every test off the network: an empty MCP_SERVER_URL switches the
    MCP client off. Tests that exercise MCP set their own URL."""
    monkeypatch.setenv("MCP_SERVER_URL", "")
