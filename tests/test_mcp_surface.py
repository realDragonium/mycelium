"""The MCP surface is a deliberate subset of the registered tools.

`server.MCP_TOOLS` decides what MCP clients are sent; everything else must stay
reachable over HTTP, and `docs/MCP_TOOLS.md` must say which is which.
"""

from __future__ import annotations

import re
from pathlib import Path

from mycelium import server
from mycelium.http import _path_for, app

_MANIFEST = Path(__file__).resolve().parents[1] / "docs" / "MCP_TOOLS.md"


def _registered() -> set[str]:
    return {tool.__name__ for tool in server.TOOLS}


def _manifest_section(heading: str) -> set[str]:
    text = _MANIFEST.read_text()
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `(\w+)` \|", section, flags=re.MULTILINE))


def test_mcp_advertises_exactly_the_allowlisted_tools():
    advertised = {t.name for t in server.mcp._tool_manager.list_tools()}

    assert advertised == server.MCP_TOOLS
    assert server.MCP_TOOLS <= _registered()


def test_every_tool_kept_off_mcp_still_has_an_http_route():
    paths = {getattr(route, "path", None) for route in app.routes}
    off_mcp = _registered() - server.MCP_TOOLS

    assert off_mcp
    assert {name for name in off_mcp if _path_for(name) not in paths} == set()


def test_manifest_documents_each_tool_on_the_side_it_is_on():
    on_mcp = _manifest_section("Over MCP")
    off_mcp = _manifest_section("HTTP and in-process only")

    assert on_mcp == server.MCP_TOOLS
    assert off_mcp == _registered() - server.MCP_TOOLS
