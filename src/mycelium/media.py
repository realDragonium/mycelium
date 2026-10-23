"""Screenshots and short recordings attached to statements and concepts.

A media item is its bytes (sniffed and stripped by `media_formats`), alt text
that says what it shows (also what an AI reads instead of the picture), a
caption, where it came from, and its own audience label. The label works as a
statement's does (`store.audience_labels.grants`): unlabelled media is for
internal audiences only, and only a curator labels it. Media is checked
against its own label wherever it leaves the server, never against the
statement it is attached to, so an internal screenshot on an external
statement stays internal.

An agent uploads in two steps: `create_upload` returns a single-use link, and
the bytes are posted to it outside the tool call, because a model cannot
carry megabytes of base64 through its context. Captured media (browser
automation, not built yet) enters through `create` with `origin="captured"`.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from . import (
    audiences,
    drafts_store,
    media_formats,
    media_store,
    product_settings,
    store,
    timestamps,
)
from .media_store import Origin, TargetKind

#: How a document places media: `![alt](media:med_…)`. The server resolves the
#: reference wherever the document leaves it.
REFERENCE = re.compile(r"media:(med_[0-9a-f]{12})")
IMAGE = re.compile(r"!\[([^\]\n]*)\]\(media:(med_[0-9a-f]{12})\)")
UPLOAD_TTL = timedelta(minutes=15)
UPLOAD_PATH = "/api/media/uploads/"

LibraryFilter = Literal["all", "unattached", "no_alt_text", "unlabelled", "old"]


class Details(BaseModel):
    """What a curator or agent says about a media item."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    alt_text: str = Field(default="", max_length=1000)
    caption: str = Field(default="", max_length=1000)
    source_url: str | None = Field(
        default=None, max_length=1000, pattern=r"^https?://\S+$"
    )
    #: The product version or commit the media was captured against.
    product_version: str | None = Field(default=None, max_length=100)
    #: When it was captured, as an ISO date or timestamp.
    captured_at: str | None = Field(
        default=None, max_length=40, pattern=r"^\d{4}-\d{2}-\d{2}"
    )


class Attachment(BaseModel):
    kind: TargetKind
    id: str


class MediaView(BaseModel):
    id: str
    content_type: str
    byte_size: int
    content_version: int
    content_updated_at: str
    alt_text: str
    caption: str
    origin: Origin
    source_url: str | None
    product_version: str | None
    captured_at: str | None
    #: Audience ids granted; None while unlabelled (internal audiences only).
    audiences: list[str] | None
    labelled_by: str | None
    labelled_at: str | None
    #: Set when the content was replaced after it was labelled.
    content_changed_at: str | None
    attachments: list[Attachment]
    #: Why the item is old, empty when it is not.
    stale: list[str]
    url: str
    created_at: str
    created_by: str | None


class Offer(BaseModel):
    """Media a documentation run may place, as the writer is told about it."""

    id: str
    alt_text: str
    caption: str
    content_type: str
    attached_to: list[str]


def _conn() -> sqlite3.Connection:
    return media_store.connection()


def settings() -> product_settings.MediaSettings:
    return product_settings.get(product_settings.MediaSettings)


def content_url(media_id: str) -> str:
    return f"/api/media/{media_id}/content"


# --- reading ------------------------------------------------------------------


def visible_to(row: sqlite3.Row, audience: audiences.Audience | None) -> bool:
    """Whether the audience may see the item; None is full access by role."""
    return audience is None or store.audience_labels.grants(
        media_store.label(row), audience.id, audience.internal
    )


def stale_reasons(
    row: sqlite3.Row, config: product_settings.MediaSettings, now: datetime
) -> list[str]:
    reasons: list[str] = []
    taken = row["captured_at"] or row["content_updated_at"]
    try:
        when = datetime.fromisoformat(str(taken).replace("Z", "+00:00"))
    except ValueError:
        when = None
    if when is not None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        if now - when > timedelta(days=config.stale_after_days):
            reasons.append(f"older than {config.stale_after_days} days")
    version = row["product_version"]
    if config.product_version and version and version != config.product_version:
        reasons.append(
            f"captured against {version}; the product is at {config.product_version}"
        )
    return reasons


def _view(
    row: sqlite3.Row,
    attached: Sequence[tuple[TargetKind, str]],
    config: product_settings.MediaSettings,
    now: datetime,
) -> MediaView:
    return MediaView(
        id=row["id"],
        content_type=row["content_type"],
        byte_size=row["byte_size"],
        content_version=row["content_version"],
        content_updated_at=row["content_updated_at"],
        alt_text=row["alt_text"],
        caption=row["caption"],
        origin=row["origin"],
        source_url=row["source_url"],
        product_version=row["product_version"],
        captured_at=row["captured_at"],
        audiences=media_store.label(row),
        labelled_by=row["labelled_by"],
        labelled_at=row["labelled_at"],
        content_changed_at=row["content_changed_at"],
        attachments=[Attachment(kind=kind, id=target) for kind, target in attached],
        stale=stale_reasons(row, config, now),
        url=content_url(row["id"]),
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def views(rows: Sequence[sqlite3.Row]) -> list[MediaView]:
    conn = _conn()
    attached = media_store.attachments(conn, [row["id"] for row in rows])
    config, now = settings(), datetime.now(UTC)
    return [_view(row, attached[row["id"]], config, now) for row in rows]


def get(media_id: str) -> MediaView:
    return views([_require(media_id)])[0]


def _require(media_id: str) -> sqlite3.Row:
    row = media_store.get(_conn(), media_id)
    if row is None:
        raise ValueError(f"Media {media_id} does not exist.")
    return row


def for_target(
    kind: TargetKind, target_id: str, audience: audiences.Audience | None
) -> list[MediaView]:
    """The media attached to one statement or concept that the audience may
    see. The caller has checked that the audience may see the target."""
    conn = _conn()
    ids = media_store.attached_to(conn, kind, [target_id]).get(target_id, [])
    rows = {row["id"]: row for row in media_store.get_many(conn, ids)}
    return views(
        [
            rows[item]
            for item in ids
            if item in rows and visible_to(rows[item], audience)
        ]
    )


def library(show: LibraryFilter = "all", limit: int = 200) -> list[MediaView]:
    """Every media item, newest first, narrowed by `show`."""
    conn = _conn()
    where = {
        "all": "1",
        "unattached": "NOT EXISTS (SELECT 1 FROM media_attachments a "
        "WHERE a.media_id = m.id)",
        "no_alt_text": "m.alt_text = ''",
        "unlabelled": "m.audiences IS NULL",
        "old": "1",
    }[show]
    rows = list(
        conn.execute(
            f"SELECT * FROM media_items m WHERE {where} ORDER BY m.created_at DESC"
        )
    )
    if show == "old":
        config, now = settings(), datetime.now(UTC)
        rows = [row for row in rows if stale_reasons(row, config, now)]
    return views(rows[:limit])


class Counts(BaseModel):
    total: int
    old: int


def counts() -> Counts:
    rows = list(_conn().execute("SELECT * FROM media_items"))
    config, now = settings(), datetime.now(UTC)
    return Counts(
        total=len(rows), old=sum(1 for row in rows if stale_reasons(row, config, now))
    )


def content(
    media_id: str, audience: audiences.Audience | None
) -> tuple[sqlite3.Row, bytes]:
    """The item and its bytes, refused as missing when the audience may not
    see it, so a scoped caller learns nothing about internal media."""
    conn = _conn()
    row = media_store.get(conn, media_id)
    data = media_store.blobs.get(conn, media_id) if row is not None else None
    if row is None or data is None or not visible_to(row, audience):
        raise LookupError(media_id)
    return row, data


# --- writing ------------------------------------------------------------------


def _clean(data: bytes) -> media_formats.Cleaned:
    cleaned = media_formats.clean(data)
    config = settings()
    cap = config.video_max_bytes if cleaned.is_video else config.image_max_bytes
    if len(data) > cap:
        raise media_formats.Rejected(
            f"The file is {len(data):,} bytes; "
            f"{'videos' if cleaned.is_video else 'images'} may be at most {cap:,}."
        )
    return cleaned


def max_bytes() -> int:
    config = settings()
    return max(config.image_max_bytes, config.video_max_bytes)


def create(
    data: bytes,
    details: Details,
    *,
    origin: Origin,
    actor: str | None,
    attach: Sequence[tuple[TargetKind, str]] = (),
) -> MediaView:
    cleaned = _clean(data)
    for kind, target in attach:
        _require_target(kind, target)
    media_id = "med_" + uuid.uuid4().hex[:12]
    now = timestamps.now()
    conn = _conn()
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO media_items (id, content_type, byte_size, sha256, "
            "content_updated_at, alt_text, caption, origin, source_url, "
            "product_version, captured_at, created_at, created_by, updated_at, "
            "updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                media_id,
                cleaned.content_type,
                len(cleaned.data),
                hashlib.sha256(cleaned.data).hexdigest(),
                now,
                details.alt_text,
                details.caption,
                origin,
                details.source_url,
                details.product_version or None,
                details.captured_at,
                now,
                actor,
                now,
                actor,
            ),
        )
        media_store.blobs.put(conn, media_id, cleaned.data)
        for kind, target in attach:
            _attach(conn, media_id, kind, target, actor, now)
    return get(media_id)


def replace_content(media_id: str, data: bytes, *, actor: str | None) -> MediaView:
    """New bytes for the same item. Documents that place it become out of
    date, and a label decided before the change is flagged for confirming."""
    cleaned = _clean(data)
    conn = _conn()
    now = timestamps.now()
    with store.transaction(conn):
        row = _require(media_id)
        conn.execute(
            "UPDATE media_items SET content_type = ?, byte_size = ?, sha256 = ?, "
            "content_version = content_version + 1, content_updated_at = ?, "
            "content_changed_at = CASE WHEN audiences IS NULL THEN NULL ELSE ? END, "
            "updated_at = ?, updated_by = ? WHERE id = ?",
            (
                cleaned.content_type,
                len(cleaned.data),
                hashlib.sha256(cleaned.data).hexdigest(),
                now,
                now,
                now,
                actor,
                row["id"],
            ),
        )
        media_store.blobs.put(conn, media_id, cleaned.data)
    return get(media_id)


def update(media_id: str, details: Details, *, actor: str | None) -> MediaView:
    conn = _conn()
    with store.transaction(conn):
        _require(media_id)
        conn.execute(
            "UPDATE media_items SET alt_text = ?, caption = ?, source_url = ?, "
            "product_version = ?, captured_at = ?, updated_at = ?, updated_by = ? "
            "WHERE id = ?",
            (
                details.alt_text,
                details.caption,
                details.source_url,
                details.product_version or None,
                details.captured_at,
                timestamps.now(),
                actor,
                media_id,
            ),
        )
    return get(media_id)


def set_label(
    media_id: str, audience_ids: Sequence[str] | None, *, curator: str | None
) -> MediaView:
    """A curator's decision; None makes the item unlabelled again."""
    if audience_ids is not None:
        known = {item.id for item in audiences.live()}
        unknown = sorted(set(audience_ids) - known)
        if unknown:
            raise ValueError("Unknown audiences: " + ", ".join(unknown))
    conn = _conn()
    with store.transaction(conn):
        _require(media_id)
        conn.execute(
            "UPDATE media_items SET audiences = ?, labelled_by = ?, labelled_at = ?, "
            "content_changed_at = NULL WHERE id = ?",
            (
                None if audience_ids is None else json.dumps(sorted(set(audience_ids))),
                None if audience_ids is None else curator,
                None if audience_ids is None else timestamps.now(),
                media_id,
            ),
        )
    return get(media_id)


def confirm_label(media_id: str, *, curator: str | None) -> MediaView:
    """Keep the label after the content was replaced."""
    row = _require(media_id)
    return set_label(media_id, media_store.label(row), curator=curator)


def _require_target(kind: TargetKind, target_id: str) -> None:
    substrate = store.substrate_connection()
    found = (
        store.get_statement(substrate, target_id)
        if kind == "statement"
        else store.get_entity_by_id(substrate, target_id)
    )
    if found is None:
        noun = "Statement" if kind == "statement" else "Concept"
        raise ValueError(f"{noun} {target_id} does not exist.")


def _attach(
    conn: sqlite3.Connection,
    media_id: str,
    kind: TargetKind,
    target_id: str,
    actor: str | None,
    now: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO media_attachments "
        "(media_id, target_kind, target_id, attached_at, attached_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (media_id, kind, target_id, now, actor),
    )


def attach(
    media_id: str, kind: TargetKind, target_id: str, *, actor: str | None
) -> MediaView:
    _require_target(kind, target_id)
    conn = _conn()
    with store.transaction(conn):
        _require(media_id)
        _attach(conn, media_id, kind, target_id, actor, timestamps.now())
    return get(media_id)


def detach(media_id: str, kind: TargetKind, target_id: str) -> MediaView:
    conn = _conn()
    with store.transaction(conn):
        _require(media_id)
        conn.execute(
            "DELETE FROM media_attachments WHERE media_id = ? AND target_kind = ? "
            "AND target_id = ?",
            (media_id, kind, target_id),
        )
    return get(media_id)


def delete(media_id: str) -> None:
    conn = _conn()
    with store.transaction(conn):
        _require(media_id)
        conn.execute("DELETE FROM media_items WHERE id = ?", (media_id,))


def target_merged(kind: TargetKind, from_id: str, into_id: str) -> None:
    if not media_store.is_configured():
        return
    conn = _conn()
    with store.transaction(conn):
        media_store.move_attachments(conn, kind, from_id, into_id)


def target_deleted(kind: TargetKind, target_id: str) -> None:
    if not media_store.is_configured():
        return
    conn = _conn()
    with store.transaction(conn):
        media_store.clear_attachments(conn, kind, target_id)


# --- two-step upload ------------------------------------------------------------


class Upload(BaseModel):
    upload_url: str
    expires_at: str
    max_bytes: int
    how: str


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_upload(
    details: Details,
    *,
    actor: str | None,
    base_url: str,
) -> Upload:
    """A single-use link that turns the bytes posted to it into a media item
    with these details. The link is the credential, so it expires soon."""
    if not details.alt_text:
        raise ValueError("Say what the media shows in alt_text.")
    token = secrets.token_urlsafe(32)
    created = datetime.now(UTC)
    expires = timestamps.of(created + UPLOAD_TTL)
    conn = _conn()
    with store.transaction(conn):
        conn.execute(
            "DELETE FROM media_uploads WHERE expires_at < ?", (timestamps.of(created),)
        )
        conn.execute(
            "INSERT INTO media_uploads (token_hash, metadata_json, created_by, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                _token_hash(token),
                details.model_dump_json(),
                actor,
                timestamps.of(created),
                expires,
            ),
        )
    url = base_url.rstrip("/") + UPLOAD_PATH + token
    return Upload(
        upload_url=url,
        expires_at=expires,
        max_bytes=max_bytes(),
        how=(
            f"POST the file's bytes as the request body, for example "
            f"`curl --fail --data-binary @screenshot.png {url}`, within 15 "
            "minutes. The response holds the media id; cite it in "
            "set_operation_evidence as evidence of kind 'media'."
        ),
    )


def complete_upload(token: str, data: bytes) -> MediaView:
    """Turn posted bytes into the item. The link stays usable until bytes it
    accepts arrive, so a refused file can be fixed and posted again."""
    conn = _conn()
    with store.transaction(conn):
        row = conn.execute(
            "SELECT * FROM media_uploads WHERE token_hash = ? AND expires_at >= ?",
            (_token_hash(token), timestamps.now()),
        ).fetchone()
        if row is None:
            raise LookupError("This upload link is unknown, used or expired.")
        created = create(
            data,
            Details.model_validate_json(row["metadata_json"]),
            origin="agent",
            actor=row["created_by"],
        )
        conn.execute(
            "DELETE FROM media_uploads WHERE token_hash = ?", (row["token_hash"],)
        )
    return created


# --- documentation ------------------------------------------------------------------


def offers(
    statement_ids: Iterable[str],
    entity_ids: Iterable[str],
    audience: audiences.Audience | None,
) -> list[Offer]:
    """Media attached to these statements and concepts that the audience may
    see and that says what it shows, for a writer to place."""
    if not media_store.is_configured():
        return []
    conn = _conn()
    targets: dict[str, list[str]] = {}
    wanted: tuple[tuple[TargetKind, Iterable[str]], ...] = (
        ("statement", statement_ids),
        ("entity", entity_ids),
    )
    for kind, ids in wanted:
        for target, media_ids in media_store.attached_to(
            conn, kind, sorted(set(ids))
        ).items():
            for media_id in media_ids:
                targets.setdefault(media_id, []).append(target)
    return [
        Offer(
            id=row["id"],
            alt_text=row["alt_text"],
            caption=row["caption"],
            content_type=row["content_type"],
            attached_to=targets[row["id"]],
        )
        for row in media_store.get_many(conn, targets)
        if row["alt_text"] and visible_to(row, audience)
    ]


def referenced(body: str) -> list[str]:
    """Media ids a document body places, in order of first appearance."""
    return list(dict.fromkeys(REFERENCE.findall(body)))


# --- drafts -------------------------------------------------------------------------


def describe_evidence(
    items: list[drafts_store.Evidence],
) -> list[drafts_store.Evidence]:
    """Check that media evidence names real media, and give the reviewer its
    alt text and caption when the producer quoted nothing."""
    described: list[drafts_store.Evidence] = []
    for item in items:
        if item.media_id is not None:
            row = _require(item.media_id)
            if not item.excerpt:
                excerpt = f"Alt text: {row['alt_text']}"
                if row["caption"]:
                    excerpt += f"\nCaption: {row['caption']}"
                item = item.model_copy(update={"excerpt": excerpt[:1500]})
        described.append(item)
    return described


def _written(result: object) -> list[tuple[TargetKind, str]]:
    """The statements and concepts a replayed operation wrote."""
    if not isinstance(result, dict):
        return []
    if isinstance(result.get("statement_id"), str):
        return [("statement", result["statement_id"])]
    if isinstance(result.get("entity_id"), str):
        return [("entity", result["entity_id"])]
    items = result.get("results")
    if isinstance(items, list):
        return [
            ("statement", item["statement_id"])
            for item in items
            if isinstance(item, dict) and isinstance(item.get("statement_id"), str)
        ]
    return []


def attach_applied(
    ops: Sequence[sqlite3.Row],
    results: Sequence[Mapping[str, object]],
    *,
    actor: str | None,
) -> int:
    """Attach each operation's media evidence to what the operation wrote,
    once the draft's substrate writes have committed. Idempotent, so a
    recovered application can run it again."""
    by_seq = {item.get("seq"): item.get("result") for item in results}
    pending: list[tuple[str, TargetKind, str]] = []
    for op in ops:
        if not op["evidence_json"]:
            continue
        evidence = json.loads(op["evidence_json"])
        media_ids = [
            str(item["media_id"])
            for item in evidence
            if isinstance(item, dict) and item.get("media_id")
        ]
        for kind, target in _written(by_seq.get(op["seq"])):
            pending.extend((media_id, kind, target) for media_id in media_ids)
    if not pending or not media_store.is_configured():
        return 0
    conn = _conn()
    now = timestamps.now()
    with store.transaction(conn):
        existing = {
            row["id"] for row in media_store.get_many(conn, (p[0] for p in pending))
        }
        for media_id, kind, target in pending:
            if media_id in existing:
                _attach(conn, media_id, kind, target, actor, now)
    return sum(1 for item in pending if item[0] in existing)
