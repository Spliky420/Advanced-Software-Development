import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "mcp-server"))

# The shared tools call the student APIs on the host.
for owner, port in {
    "JOSHUA": 8011, "MAXWELL": 8021, "ENEREL": 8031,
    "HYUNWOO": 8041, "THOMAS": 8051, "LEHOALONG": 8061,
}.items():
    os.environ.setdefault(f"{owner}_BACKEND_URL", f"http://localhost:{port}")

os.environ["MCP_HTTP_HOST"] = "127.0.0.1"
os.environ.setdefault("MCP_HTTP_PORT", "8071")

from server import mcp


# Keep host checks enabled and allow Docker Desktop's host name.
security = mcp.settings.transport_security
if security is not None:
    security.allowed_hosts.append(f"host.docker.internal:{os.environ['MCP_HTTP_PORT']}")

if __name__ == "__main__":
    print(f"Shared MCP server: http://127.0.0.1:{os.environ['MCP_HTTP_PORT']}/mcp", flush=True)
    mcp.run(transport="streamable-http")
