"""Whole-substrate reads the bundled web UI loads before it mounts.

Deliberately not `@tool`s: they are shaped for a browser, not for an AI
consumer composing primitives over MCP.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from .. import store
from ..server import runtime

router = APIRouter()


@router.get("/api/data")
def get_substrate_dump() -> dict[str, Any]:
    """Dump the entire substrate in the shape the UI expects.

    See `store.substrate_dump` for the returned shape.
    """
    return store.substrate_dump(store.substrate_connection())


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
    return FileResponse(path, media_type="application/json")
