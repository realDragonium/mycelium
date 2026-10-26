"""MCP tools for media: the library and what is attached to a statement or
concept, a link to upload a screenshot for a draft, and a curator's edits.

Changing media needs a real writer and deleting it a real admin, as in the web
app's media library, whose routes call the same `mycelium.media` functions.
"""

from __future__ import annotations

import os
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from .. import auth, media, store
from ..media_store import TargetKind
from .registry import tool
from .runtime import _caller, _db


@tool
def list_media(
    statement_id: str | None = None,
    entity_id: str | None = None,
    media_id: str | None = None,
    show: media.LibraryFilter = "all",
) -> list[media.MediaView]:
    """List screenshots and recordings with alt text, caption, origin,
    audience label, attachments and `url` to fetch the bytes over HTTP.

    Give at most one id: `statement_id` or `entity_id` lists what is
    attached to that statement or concept, `media_id` reads one item. With
    none, it lists the media library as the web app does, filtered by
    `show`: all, unattached, no_alt_text, unlabelled or old.
    """
    if sum(value is not None for value in (statement_id, entity_id, media_id)) > 1:
        raise ValueError("Give at most one of statement_id, entity_id or media_id.")
    if media_id is not None:
        return [media.get(media_id)]
    if statement_id is None and entity_id is None:
        return media.library(show)
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
        base_url=_base_url(),
    )


def _base_url() -> str:
    # Without a configured address the path is relative to the server the
    # agent is connected to.
    return (os.environ.get("MYCELIUM_PUBLIC_URL") or "").strip()


class EditDetails(media.Details):
    action: Literal["details"]
    media_id: str


class Relabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["label"]
    media_id: str
    #: None makes the item unlabelled: internal audiences only.
    audiences: list[str] | None = Field(max_length=50)


class ConfirmLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm_label"]
    media_id: str


class Attach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["attach", "detach"]
    media_id: str
    kind: TargetKind
    target_id: str = Field(min_length=1, max_length=100)


class ReplaceContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["replace_content"]
    media_id: str


class Delete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["delete"]
    media_id: str


MediaEdit = Annotated[
    EditDetails | Relabel | ConfirmLabel | Attach | ReplaceContent | Delete,
    Field(discriminator="action"),
]
#: The HTTP mirror and in-process callers pass `request` as a dict.
_media_edit: TypeAdapter[MediaEdit] = TypeAdapter(MediaEdit)


class Deleted(BaseModel):
    deleted: bool = True


def update_details(
    media_id: str, details: media.Details, actor: str
) -> media.MediaView:
    if not details.alt_text:
        raise ValueError("Say what the media shows in the alt text.")
    return media.update(media_id, details, actor=actor)


@tool(role="writer", real_role=True)
def edit_media(request: MediaEdit) -> dict[str, JsonValue]:
    """Change a media item as the web app's media library does, landing
    live. Real writers and admins only; `delete` needs a real admin.

    `details` replaces alt_text, caption, source_url, product_version and
    captured_at (alt text is required); `label` sets the audiences that may
    see it (null for internal audiences only); `confirm_label` keeps the
    label after the content changed; `attach` and `detach` link it to a
    statement or concept (`kind`, `target_id`); `replace_content` returns a
    single-use upload link whose bytes become the item's new content, which
    puts documents that show it out of date; `delete` removes it. Every
    other action returns the item."""
    request = _media_edit.validate_python(request)
    return _edit(request).model_dump(mode="json")


def _edit(request: MediaEdit) -> BaseModel:
    if isinstance(request, Delete):
        if not auth.principal_has_real_role(_caller(), "admin"):
            raise auth.RoleRequired("deleting media requires the admin role")
        media.delete(request.media_id)
        return Deleted()
    actor = _caller().id
    if isinstance(request, EditDetails):
        return update_details(
            request.media_id,
            media.Details(**request.model_dump(exclude={"action", "media_id"})),
            actor,
        )
    if isinstance(request, Relabel):
        return media.set_label(request.media_id, request.audiences, curator=actor)
    if isinstance(request, ConfirmLabel):
        return media.confirm_label(request.media_id, curator=actor)
    if isinstance(request, ReplaceContent):
        return media.create_upload(
            media.Details(),
            actor=actor,
            base_url=_base_url(),
            replaces=request.media_id,
        )
    if request.action == "attach":
        return media.attach(
            request.media_id, request.kind, request.target_id, actor=actor
        )
    return media.detach(request.media_id, request.kind, request.target_id)
