"""Media: the library, uploads, labels, attachments and serving the bytes.

Uploads send the file as the raw request body, with its details in the query
string, so the server needs no multipart parser; the body is read up to the
configured cap and no further. Changing media needs a real writer, as a
curator's audience label does; deleting it needs an admin. The bytes are
served only as one of the sniffed media types, sandboxed and never sniffed
by the browser. Agents reach the same `mycelium.media` functions through
`list_media`, `create_media_upload` and `edit_media`.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .. import media, media_formats
from ..media_store import TargetKind
from ..request_timing import TimedRoute
from ..server import media as media_tools
from .access import _enforce_role, _require_admin, _require_principal

router = APIRouter(route_class=TimedRoute)

#: Routes whose body is a file. The app-wide body limit skips them; each reads
#: its body against the media caps instead.
RAW_BODY = re.compile(
    r"^/api/media(/med_[0-9a-f]{12}/content|"
    + re.escape(media.UPLOAD_PATH.removeprefix("/api/media"))
    + r"[A-Za-z0-9_-]+)?$"
)


class TooLarge(Exception):
    pass


async def _too_large(request: Request, exc: TooLarge) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


async def _rejected(request: Request, exc: media_formats.Rejected) -> JSONResponse:
    return JSONResponse(status_code=415, content={"detail": str(exc)})


async def _body(request: Request) -> bytes:
    cap = await run_in_threadpool(media.max_bytes)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > cap:
            raise TooLarge(f"Media may be at most {cap:,} bytes.")
    if not data:
        raise ValueError("Send the file as the request body.")
    return bytes(data)


def _actor(request: Request) -> str:
    return _require_principal(request).id


@router.get("/api/media")
def media_library_http(
    request: Request,
    show: media.LibraryFilter = "all",
) -> list[media.MediaView]:
    _require_principal(request)
    return media.library(show)


@router.post("/api/media")
async def upload_media_http(
    request: Request,
    alt_text: str = Query(min_length=1, max_length=1000),
    caption: str = Query(default="", max_length=1000),
    source_url: str | None = Query(default=None),
    product_version: str | None = Query(default=None),
    captured_at: str | None = Query(default=None),
    statement_id: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    details = media.Details(
        alt_text=alt_text,
        caption=caption,
        source_url=source_url or None,
        product_version=product_version or None,
        captured_at=captured_at or None,
    )
    attach: list[tuple[TargetKind, str]] = []
    if statement_id:
        attach.append(("statement", statement_id))
    if entity_id:
        attach.append(("entity", entity_id))
    data = await _body(request)
    actor = _actor(request)
    return await run_in_threadpool(
        lambda: media.create(
            data, details, origin="uploaded", actor=actor, attach=attach
        )
    )


@router.post("/api/media/uploads/{token}")
async def complete_media_upload_http(token: str, request: Request) -> JSONResponse:
    """Where an agent posts the bytes for an upload link. The link is the
    credential, so this path needs no sign-in."""
    data = await _body(request)
    try:
        created = await run_in_threadpool(media.complete_upload, token, data)
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return JSONResponse(
        status_code=201,
        content={"media_id": created.id, "content_type": created.content_type},
    )


@router.get("/api/media/{media_id}")
def get_media_http(media_id: str, request: Request) -> media.MediaView:
    _require_principal(request)
    return media.get(media_id)


@router.patch("/api/media/{media_id}")
def update_media_http(
    media_id: str, body: media.Details, request: Request
) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    return media_tools.update_details(media_id, body, _actor(request))


@router.put("/api/media/{media_id}/content")
async def replace_media_http(media_id: str, request: Request) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    data = await _body(request)
    actor = _actor(request)
    return await run_in_threadpool(
        lambda: media.replace_content(media_id, data, actor=actor)
    )


@router.delete("/api/media/{media_id}")
def delete_media_http(media_id: str, request: Request) -> dict[str, bool]:
    _require_admin(request)
    media.delete(media_id)
    return {"deleted": True}


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: None makes the item unlabelled: internal audiences only.
    audiences: list[str] | None = Field(max_length=50)


@router.put("/api/media/{media_id}/audiences")
def label_media_http(
    media_id: str, body: LabelBody, request: Request
) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    return media.set_label(media_id, body.audiences, curator=_actor(request))


@router.post("/api/media/{media_id}/audiences/confirm")
def confirm_media_label_http(media_id: str, request: Request) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    return media.confirm_label(media_id, curator=_actor(request))


class AttachBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: TargetKind
    id: str = Field(min_length=1, max_length=100)


@router.post("/api/media/{media_id}/attachments")
def attach_media_http(
    media_id: str, body: AttachBody, request: Request
) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    return media.attach(media_id, body.kind, body.id, actor=_actor(request))


@router.delete("/api/media/{media_id}/attachments/{kind}/{target_id}")
def detach_media_http(
    media_id: str,
    kind: Literal["statement", "entity"],
    target_id: str,
    request: Request,
) -> media.MediaView:
    _enforce_role(request, "writer", real_role=True)
    return media.detach(media_id, kind, target_id)


@router.get("/api/media/{media_id}/content")
def media_content_http(media_id: str, request: Request) -> Response:
    try:
        row, data = media.content(media_id)
    except LookupError:
        return JSONResponse(status_code=404, content={"detail": "media not found"})
    etag = f'"{row["sha256"]}"'
    headers = {
        "ETag": etag,
        # Revalidated on every use: replacing the content keeps the URL.
        "Cache-Control": "private, no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": (
            f'inline; filename="{media_id}.'
            f'{media_formats.EXTENSIONS[row["content_type"]]}"'
        ),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=row["content_type"], headers=headers)
