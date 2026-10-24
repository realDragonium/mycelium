"""MCP tools for media: what is attached to a statement or concept, and a
link to upload a screenshot for a draft."""

from __future__ import annotations

import os

from .. import auth, media, store
from .registry import tool
from .runtime import _db


@tool
def list_media(
    statement_id: str | None = None, entity_id: str | None = None
) -> list[media.MediaView]:
    """List the screenshots and recordings attached to one statement or one
    concept (give exactly one id), with alt text, caption, origin, audience
    label and `url` to fetch the bytes over HTTP.
    """
    if (statement_id is None) == (entity_id is None):
        raise ValueError("Give exactly one of statement_id or entity_id.")
    if statement_id is not None:
        if store.get_statement(_db(), statement_id) is None:
            raise ValueError(f"Statement {statement_id} does not exist.")
        return media.for_target("statement", statement_id)
    assert entity_id is not None
    if store.get_entity_by_id(_db(), entity_id) is None:
        raise ValueError(f"Concept {entity_id} does not exist.")
    return media.for_target("entity", entity_id)


@tool
def create_media_upload(
    alt_text: str,
    caption: str = "",
    source_url: str | None = None,
    product_version: str | None = None,
    captured_at: str | None = None,
) -> media.Upload:
    """Get a single-use link to upload a screenshot (PNG, JPEG, WebP, GIF)
    or short recording (MP4, WebM) of the product. POST the file's bytes to
    `upload_url` within 15 minutes; the response holds its `media_id`. Then
    cite it on the draft operation it illustrates with `set_operation_evidence`
    (`{"kind": "media", "media_id": ..., "claim": ...}`): when the draft is
    applied, the media is attached to what that operation wrote.

    `alt_text` says what the media shows, for readers who cannot see it and
    for the AI that writes documents from it. `source_url` is the page it was
    captured on, `product_version` the version or commit, `captured_at` the
    ISO date. The upload is unlabelled, so only internal audiences see it
    until a curator labels it. Size limits are in `max_bytes`.
    """
    principal = auth.current_principal.get()
    return media.create_upload(
        media.Details(
            alt_text=alt_text,
            caption=caption,
            source_url=source_url,
            product_version=product_version,
            captured_at=captured_at,
        ),
        actor=principal.id if principal is not None else None,
        # Without a configured address the path is relative to the server
        # the agent is connected to.
        base_url=(os.environ.get("MYCELIUM_PUBLIC_URL") or "").strip(),
    )
