"""Whole-substrate reads the bundled web UI loads before it mounts.

Deliberately not `@tool`s: they are shaped for a browser, not for an AI
consumer composing primitives over MCP.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from .. import principal_audience, store
from ..request_timing import TimedRoute
from ..server import runtime
from .access import _require_principal

router = APIRouter(route_class=TimedRoute)


@router.get("/api/data")
def get_substrate_dump(request: Request) -> dict[str, Any]:
    """Dump the entire substrate in the shape the UI expects, or as much of
    it as the caller's audience may see.

    See `store.substrate_dump` for the returned shape.
    """
    with principal_audience.reads(_require_principal(request)):
        return store.substrate_dump(store.substrate_connection())


@router.get("/api/substrate-counts")
def get_substrate_counts(request: Request) -> store.SubstrateCounts:
    """What Home shows of the substrate, without the dump behind it."""
    with principal_audience.reads(_require_principal(request)):
        return store.substrate_counts(store.substrate_connection())


@router.get("/api/entity-positions", include_in_schema=False)
def get_entity_positions(request: Request) -> Any:
    """Stream the baked entity layout JSON.

    The bake artifact lives in the data dir (next to the substrate
    DB), not the source tree — so deploys can't accidentally wipe
    it and the systemd hardening's read-only-system protection
    permits the bake to write. The UI fetches from this route
    instead of a static /ui/data/ path; the URL is stable even if
    we change where the file lives on disk.
    """
    from fastapi.responses import FileResponse
    from fastapi.responses import JSONResponse as _JSON

    path = runtime._baker().output_path()
    if not path.exists():
        return _JSON(
            status_code=404, content={"detail": "entity positions not baked yet"}
        )
    principal = _require_principal(request)
    if principal.audience_id is None:
        return FileResponse(path, media_type="application/json")
    with principal_audience.reads(principal):
        visible = {
            str(row["id"])
            for row in store.substrate_connection().execute("SELECT id FROM entities")
        }
    layout = json.loads(path.read_text(encoding="utf-8"))
    layout["nodes"] = [node for node in layout["nodes"] if node["id"] in visible]
    if layout.get("centroid_id") not in visible:
        layout["centroid_id"] = None
    return layout
