"""Test-wide setup.

Disables the MCP-over-HTTP transport for the whole suite. FastMCP's
session manager is a process-singleton with run-once semantics, so
multiple TestClient lifespans against the same module would explode
on the second startup. The MCP REST mirror and `/api/*` endpoints
don't depend on the session manager — only `/mcp` JSON-RPC does.
"""

import os

import pytest


def pytest_configure(config):
    _require_spacy_model()
    os.environ.setdefault("MYCELIUM_DISABLE_MCP_HTTP", "1")
    # The async mention-recompute worker spawns a daemon thread per
    # server.init(); across many TestClient lifecycles that races the
    # assertions and leaks threads. Tests that exercise recompute call
    # `mention_worker.drain(conn)` synchronously instead.
    os.environ.setdefault("MYCELIUM_DISABLE_MENTION_WORKER", "1")


def _require_spacy_model():
    """Abort the run with one actionable line when phrasing validation
    can't load its spaCy model. Exercises the real load path rather than
    module discovery, since a half-installed model imports fine and only
    fails at `spacy.load`; the load also warms the cache the suite
    reuses. Without this, ~190 otherwise unrelated tests fail and the
    baseline reads as broken rather than unbootstrapped."""
    from mycelium import phrasing

    try:
        phrasing.check("A user submits the form.")
    except Exception as exc:
        raise pytest.UsageError(f"phrasing validation is unusable: {exc}") from exc
