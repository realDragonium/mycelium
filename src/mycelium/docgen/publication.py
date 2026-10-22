"""A generated document at its destination: publishing it, following its pull
request, and deciding which text a revision starts from.

Mycelium learns what became of a pull request by asking GitHub when the
document is read, not through a webhook. This is a single-instance deployment
with no public endpoint to receive one, and a reader opening the document is
when the answer matters.

Once a PR is open, two parties can edit the document: Mycelium, through new
internal revisions, and people, by committing to the PR branch or to the base
branch after merge. Mycelium recognises the texts it has already accounted
for: every blob it published, and the sync point
(`revision_source_content_revision`), the destination text the internal head
was last derived from. Any other destination text holds edits made by people.
A revision starts from that text when the internal head adds nothing since its
publication. When both sides changed, the revision is refused rather than
merged, because a model asked to reconcile two edits can drop either one
without anyone noticing.

Recognising all of them is what lets a closed PR fall back to the base branch,
which holds an earlier published version or the text the closed revision was
built from. The cost is that a person reverting to an earlier Mycelium text is
not seen as an edit, so a later revision proposes the reverted changes again.
That happens in a new pull request the person can close, so nothing they wrote
is lost.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .. import docs_store
from . import destinations
from .destinations import DestinationError
from .schema import CurrentDocument, RevisionBase

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
        try:
            configured, binding = destinations.publishing_destination(row, destination)
            delivery = destinations.deliver_document(
                configured,
                _delivery_document(row, docs_store.published_blobs(conn, document_id)),
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


def _delivery_document(
    row: sqlite3.Row, published: frozenset[str]
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
        delivered_content_revision=optional("delivery_content_revision"),
        revision_source_content_revision=optional("revision_source_content_revision"),
        published_content_revisions=published,
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


def destination_text(row: sqlite3.Row) -> CurrentDocument | None:
    """The document's file as it stands for review at its recorded destination.

    None when the file is absent there. Raises a `ValueError` saying what to
    restore when the destination cannot be read: without that text, Mycelium
    cannot tell whether a revision would discard someone's edits.
    """
    try:
        configured, _ = destinations.publishing_destination(
            row, str(row["delivery_destination"])
        )
        return destinations.read_document(
            configured, str(row["delivery_path"]), str(row["id"]), str(row["slug"])
        )
    except DestinationError as exc:
        raise ValueError(
            "This document cannot be revised until Mycelium can read its published "
            f"copy, to check for edits made there: {exc} Restore the document's "
            "GitHub connection or credential binding, then retry."
        ) from None


@dataclass(frozen=True)
class RevisionStart:
    current: CurrentDocument
    base: RevisionBase


def revision_start(
    row: sqlite3.Row,
    remote: CurrentDocument | None,
    published: frozenset[str],
    *,
    start_from_destination: bool = False,
) -> RevisionStart:
    """Choose the text a revision of a delivered document starts from.

    `remote` is `destination_text(row)` and `published` the document's
    `docs_store.published_blobs`. The result's `content_revision` is the sync
    point the revision records; None keeps the stored one.
    """
    internal = CurrentDocument(body=str(row["body"]))
    if remote is None:
        if start_from_destination:
            raise ValueError(
                "There is no published copy of this document to start from: the "
                "file is absent from its destination. Revise it without "
                "start_from_destination."
            )
        return RevisionStart(internal, "internal")
    from_destination = RevisionStart(remote, "destination")
    if start_from_destination:
        return from_destination
    accounted_for = published | {
        row["revision_source_content_revision"],
        row["delivery_content_revision"],
    }
    if remote.content_revision in accounted_for or remote.body == internal.body:
        return RevisionStart(
            CurrentDocument(internal.body, remote.content_revision), "internal"
        )
    if row["published_revision"] == row["current_revision"]:
        return from_destination
    raise ValueError(_both_edited(row))


def _both_edited(row: sqlite3.Row) -> str:
    published = row["published_revision"]
    current = row["current_revision"]
    since = f"revision {published} was published" if published else "it was published"
    pull_request = (
        f"pull request #{row['pull_request_number']}"
        if row["pull_request_number"] is not None
        else "the pull request"
    )
    return (
        f"This document was edited on GitHub after {since}, and revision "
        f"{current} here has not been published. Mycelium will not merge the "
        "two. To keep the GitHub edits, revise again with start_from_destination: "
        f"the revision starts from the GitHub text and revision {current} stays "
        f"in the history. To keep revision {current}, undo the edits on GitHub or "
        f"close {pull_request} without merging, then revise again."
    )
