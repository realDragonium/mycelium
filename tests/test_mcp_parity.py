"""Every route the web app serves gives agents the same action over MCP, or
says why it does not (`mycelium.http.mcp_parity`)."""

from __future__ import annotations

from starlette.routing import Mount

from mycelium import server
from mycelium.http import _routes
from mycelium.http.mcp_parity import (
    ROUTES,
    Elsewhere,
    NotAnAction,
    ServerOperation,
    Tool,
)
from mycelium.http.tool_routes import _path_for


def _served() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in _routes()
        if not isinstance(route, Mount)
        for method in (getattr(route, "methods", None) or set()) - {"HEAD"}
    }


def _advertised_tool_paths() -> set[str]:
    return {_path_for(name) for name in server.MCP_TOOLS}


def test_every_route_names_its_mcp_tool_or_why_it_has_none():
    missing = sorted(
        (method, path)
        for method, path in _served()
        if path not in _advertised_tool_paths() and (method, path) not in ROUTES
    )

    assert missing == []


def test_the_table_lists_only_served_routes_that_need_an_entry():
    served = _served()
    stale = sorted(key for key in ROUTES if key not in served)
    redundant = sorted(key for key in ROUTES if key[1] in _advertised_tool_paths())

    assert (stale, redundant) == ([], [])


def test_every_named_tool_is_advertised_and_every_exemption_says_why():
    unadvertised = sorted(
        entry.name
        for entry in ROUTES.values()
        if isinstance(entry, Tool) and entry.name not in server.MCP_TOOLS
    )
    unexplained = sorted(
        key
        for key, entry in ROUTES.items()
        if (
            isinstance(entry, ServerOperation | NotAnAction)
            and not entry.reason.strip()
        )
        or (isinstance(entry, Elsewhere) and not (entry.branch and entry.action))
    )

    assert (unadvertised, unexplained) == ([], [])
