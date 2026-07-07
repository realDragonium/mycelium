"""Test-wide setup.

Disables the MCP-over-HTTP transport for the whole suite. FastMCP's
session manager is a process-singleton with run-once semantics, so
multiple TestClient lifespans against the same module would explode
on the second startup. The MCP REST mirror and `/api/*` endpoints
don't depend on the session manager — only `/mcp` JSON-RPC does.
"""

import os


def pytest_configure(config):
    os.environ.setdefault("MYCELIUM_DISABLE_MCP_HTTP", "1")
    # The async mention-recompute worker spawns a daemon thread per
    # server.init(); across many TestClient lifecycles that races the
    # assertions and leaks threads. Tests that exercise recompute call
    # `mention_worker.drain(conn)` synchronously instead.
    os.environ.setdefault("MYCELIUM_DISABLE_MENTION_WORKER", "1")
