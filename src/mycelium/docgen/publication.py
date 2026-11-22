"""A generated document at its destination: publishing it and following its
pull request.

Publishing is one-way. Mycelium's text is the only source: a publish writes
the selected revision over whatever the file holds at the destination, and
nothing is read back from there into a document.

Mycelium learns what became of a pull request by asking GitHub when the
document is read, not through a webhook. This is a single-instance deployment
with no public endpoint to receive one, and a reader opening the document is
when the answer matters.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from .. import docs_store, document_freshness, media, media_formats
from . import destinations, render
from .destinations import DestinationError

logger = logging.getLogger(__name__)

#: Reads closer together than this reuse the last answer, so an agent polling
#: a document does not mint an installation token on every call.
REFRESH_INTERVAL = timedelta(seconds=60)


def publish(
    conn: sqlite3.Connection,
    document_id: str,
    destination: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Publish a selected internal version through its GitHub review flow.

    Existing documents reuse recorded repository coordinates and path. A receipt
    belongs to the captured immutable version even when generation advances the
    document while GitHub is processing the publication.
    """
    with destinations.publication_lock(document_id):
        row = docs_store.get_document(conn, document_id)
        if row is None:
            raise ValueError("generated document not found")
        revision = (
            int(row["current_revision"])
            if expected_revision is None
            else expected_revision
        )
        row = docs_store.require_revision(conn, document_id, revision)
        _check_profile_destination(str(row["guideline_set"]), destination)
        _check_deliverable(str(row["body"]))
        files = _media_files(conn, row)
        try:
            configured, binding = destinations.publishing_destination(row, destination)
            delivery = destinations.deliver_document(
                configured,
                _delivery_document(row, files),
            )
        except DestinationError as exc:
            raise ValueError(str(exc)) from None
        docs_store.record_delivery(
            conn,
            document_id,
            destination=delivery.destination,
            path=delivery.path,
            reference=delivery.reference,
            content_revision=delivery.content_revision,
            target=destinations.target_identity(configured),
            revision=revision,
            binding=binding,
            pull_request_number=delivery.pull_request_number,
        )
        return {**delivery.serialize(), "revision": revision}


def _check_profile_destination(guideline_set: str, destination: str) -> None:
    from .. import documentation_profiles

    profile = next(
        (
            item
            for item in documentation_profiles.capture().profiles
            if item.name == guideline_set
        ),
        None,
    )
    if profile is not None and not profile.may_publish_to(destination):
        raise ValueError(
            f"Writing profile '{guideline_set}' publishes only to "
            + ", ".join(profile.destinations)
            + f", not to '{destination}'."
        )


def _check_deliverable(body: str) -> None:
    """Concept links and flows have no form at a destination yet: delivered as
    written, a reader there would see `[[Name]]` and a flow's bare name."""
    held = [
        what
        for what, found in (
            ("concept links ([[Name]])", render.concept_links(body)),
            ("flow placements", render.flow_placements(body)),
        )
        if found
    ]
    if held:
        raise ValueError(
            f"This document cannot be delivered to GitHub: its body holds "
            f"{' and '.join(held)}, which only Mycelium renders. Read it in "
            "Mycelium, or revise it without them to deliver it."
        )


def _media_files(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> tuple[destinations.MediaFile, ...]:
    """The images the document places, refused when the audience it was
    written for may no longer see one."""
    if not media.referenced(str(row["body"])):
        return ()
    cited = document_freshness.cited_snapshots(conn, [str(row["id"])])
    snapshot = cited.get(str(row["id"]))
    return tuple(
        destinations.MediaFile(
            id=str(item["id"]),
            version=int(item["content_version"]),
            extension=media_formats.EXTENSIONS[str(item["content_type"])],
            data=data,
        )
        for item, data in media.published_files(
            str(row["body"]), snapshot.audience if snapshot is not None else None
        )
    )


def _delivery_document(
    row: sqlite3.Row, files: tuple[destinations.MediaFile, ...] = ()
) -> destinations.DeliveryDocument:
    def optional(column: str) -> str | None:
        value = row[column]
        return None if value is None else str(value)

    return destinations.DeliveryDocument(
        id=str(row["id"]),
        slug=str(row["slug"]),
        title=str(row["title"]),
        body=str(row["body"]),
        guideline_set=str(row["guideline_set"]),
        document_type=str(row["document_type"]),
        statement_ids=tuple(json.loads(row["statement_ids"])),
        delivered_path=optional("delivery_path"),
        media=files,
    )


def refresh_pull_request(
    conn: sqlite3.Connection, document_id: str, *, now: datetime | None = None
) -> None:
    """Ask the destination what became of the document's pull request.

    Best effort: a reader still gets the document, with the last known state
    and when it was read, if GitHub cannot be reached. A merge is final.
    """
    row = docs_store.get_document(conn, document_id)
    if row is None or row["pull_request_number"] is None:
        return
    if row["pull_request_state"] == "merged":
        return
    refreshed = row["pull_request_refreshed_at"]
    current = now or datetime.now(UTC)
    if refreshed and current - datetime.fromisoformat(refreshed) < REFRESH_INTERVAL:
        return
    number = int(row["pull_request_number"])
    try:
        configured, _ = destinations.publishing_destination(
            row, str(row["delivery_destination"])
        )
        state = destinations.pull_request_state(configured, number)
    except DestinationError as exc:
        logger.warning("pull request state for %s is unavailable: %s", document_id, exc)
        return
    docs_store.record_pull_request_state(conn, document_id, number, state)
