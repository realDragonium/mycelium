"""Browser entry points: the landing redirect, the setup page and the UI paths.

The UI's static files are mounted by the app at `/ui` (a router cannot carry
a mount); this module owns where they live and the redirects around them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from .. import connect_page

router = APIRouter()


@router.get("/connect", include_in_schema=False)
def _connect_page() -> Any:
    """Standalone setup-guide page. Reachable without loading the main
    UI bundle so users coming straight to this URL (from docs, a chat
    handoff, an admin's email) don't pay for the graph viz they're
    not about to use."""
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=connect_page.CONNECT_HTML)


@router.get("/", include_in_schema=False)
def _root_redirect() -> RedirectResponse:
    # The substrate viewer at /ui/ is intentionally not the landing
    # page — it's only useful once you're logged in. Visitors land on
    # the connect / setup page instead, which is public and tells them
    # how to authenticate and get a token.
    return RedirectResponse(url="/connect")


# The browser app is built from `frontend/` into `webui/`, which is committed so
# the server runs without Node.
_WEBUI_DIR = Path(__file__).resolve().parent.parent / "webui"
_UI_DIR = _WEBUI_DIR / "ui"


# Serve the app at the bare /ui path too. Starlette would normally redirect
# /ui -> /ui/ via redirect_slashes, but the catch-all MCP sub-app mounted at "/"
# matches /ui first, so that automatic redirect never fires. The app includes
# this router ahead of the "/" mount.
@router.get("/ui", include_in_schema=False)
def _ui_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# /cockpit was a second app, merged into /ui. Old links redirect permanently;
# the browser keeps the #fragment across a redirect, and /ui resolves the
# cockpit's old hash routes.
@router.get("/cockpit", include_in_schema=False)
@router.get("/cockpit/{rest:path}", include_in_schema=False)
def _cockpit_redirect(rest: str = "") -> RedirectResponse:
    return RedirectResponse(url="/ui/", status_code=301)
