"""Whether a generated document still says what its sources say.

Each revision keeps the text its cited statements had when it was reviewed.
A document is out of date once any of those statements has been edited,
deleted or merged away since. Comparing text rather than timestamps means a
kind change or an edit that was reverted does not count, and it hands the
reader the old and new wording without reading history.

The check is one keyed lookup of every cited id across the documents asked
about, plus a history read for the few that no longer exist, so listing the
library costs one pass over its citations rather than documents × statements.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from . import store

#: How many changes a revision brief spells out before summarising the rest.
_BRIEF_CHANGES = 10
#: Statements are short; a longer one is cut so one cannot crowd out the rest.
_BRIEF_TEXT_CHARS = 300


@dataclass(frozen=True)
class StatementChange:
    statement_id: str
    change: Literal["edited", "deleted", "merged"]
    old_text: str
    #: Current text: the statement's own when edited, the one it was merged
    #: into when merged, none when deleted.
    new_text: str | None
    merged_into: str | None = None


@dataclass(frozen=True)
class Freshness:
    status: Literal["unknown", "current", "out_of_date"]
    changes: tuple[StatementChange, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "changes": [asdict(change) for change in self.changes],
        }


def assess(
    cited: Mapping[str, str] | None,
    current: Mapping[str, str],
    merged_into: Mapping[str, str],
) -> Freshness:
    """Compare a revision's cited text with what the substrate holds now.

    `cited` is None for a revision saved before citations were recorded.
    """
    if cited is None:
        return Freshness("unknown")
    changes: list[StatementChange] = []
    for statement_id, old_text in cited.items():
        if statement_id in current:
            if current[statement_id] != old_text:
                changes.append(
                    StatementChange(
                        statement_id, "edited", old_text, current[statement_id]
                    )
                )
        elif statement_id in merged_into:
            target = merged_into[statement_id]
            changes.append(
                StatementChange(
                    statement_id, "merged", old_text, current.get(target), target
                )
            )
        else:
            changes.append(StatementChange(statement_id, "deleted", old_text, None))
    return Freshness("out_of_date" if changes else "current", tuple(changes))


def for_documents(
    drafts: sqlite3.Connection,
    substrate: Callable[[], sqlite3.Connection],
    document_ids: Sequence[str],
) -> dict[str, Freshness]:
    """Freshness of each document's current revision.

    The substrate is opened only when some revision recorded citations.
    """
    snapshots = _cited_snapshots(drafts, document_ids)
    cited_ids = sorted({sid for cited in snapshots.values() if cited for sid in cited})
    current: dict[str, str] = {}
    merged_into: dict[str, str] = {}
    if cited_ids:
        conn = substrate()
        current = store.get_statement_texts(conn, cited_ids)
        missing = [sid for sid in cited_ids if sid not in current]
        merged_into = store.merge_targets(conn, missing) if missing else {}
        survivors = sorted(set(merged_into.values()) - current.keys())
        if survivors:
            current.update(store.get_statement_texts(conn, survivors))
    return {
        document_id: assess(snapshots.get(document_id), current, merged_into)
        for document_id in document_ids
    }


def _cited_snapshots(
    conn: sqlite3.Connection, document_ids: Iterable[str]
) -> dict[str, dict[str, str] | None]:
    wanted = list(document_ids)
    snapshots: dict[str, dict[str, str] | None] = {}
    for offset in range(0, len(wanted), 500):
        chunk = wanted[offset : offset + 500]
        placeholders = ", ".join("?" for _document_id in chunk)
        rows = conn.execute(
            "SELECT r.document_id, r.cited_statements "
            "FROM generated_documents AS d JOIN generated_document_revisions AS r "
            "ON r.document_id = d.id AND r.revision = d.current_revision "
            f"WHERE d.id IN ({placeholders})",
            tuple(chunk),
        )
        for row in rows:
            raw = row["cited_statements"]
            snapshots[str(row["document_id"])] = (
                None if raw is None else dict(json.loads(raw))
            )
    return snapshots


def revision_brief(changes: Sequence[StatementChange]) -> str:
    """Instructions for a revision that brings a document up to date."""
    lines = [
        "Bring this document up to date with these knowledge-base changes to "
        "statements it cites. Keep everything else as it is. Read a statement "
        "with get_statements before citing it; never cite a deleted one, and "
        "drop or re-source what rested only on it."
    ]
    for change in changes[:_BRIEF_CHANGES]:
        old = _clip(change.old_text)
        if change.change == "edited":
            lines.append(
                f"- {change.statement_id} was edited. Was: {old!r}. "
                f"Now: {_clip(change.new_text or '')!r}."
            )
        elif change.change == "merged":
            lines.append(
                f"- {change.statement_id} ({old!r}) was merged into "
                f"{change.merged_into}"
                + (
                    f", which says: {_clip(change.new_text)!r}."
                    if change.new_text is not None
                    else "."
                )
            )
        else:
            lines.append(f"- {change.statement_id} ({old!r}) was deleted.")
    if len(changes) > _BRIEF_CHANGES:
        lines.append(
            f"- …and {len(changes) - _BRIEF_CHANGES} more cited statements changed; "
            "re-read every statement the document cites."
        )
    return "\n".join(lines)


def _clip(text: str) -> str:
    if len(text) <= _BRIEF_TEXT_CHARS:
        return text
    return text[: _BRIEF_TEXT_CHARS - 1] + "…"
