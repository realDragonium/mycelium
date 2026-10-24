"""Keep shipped prompt defaults current without overriding an operator's edit.

Startup seeds the three loop doctrines into the prompt store as versions
authored by `seed`; the other actions serve their packaged default until
someone saves an override. Versions are append-only and operators edit them,
so a release's new default cannot simply replace what is stored. On every
start, for each action:

- if the newest version is still the seed's own, the new default is appended
  as another `seed` version — nobody chose the old text, so it follows the
  release, and Version history can restore it;
- if a person saved the newest version, it is left alone and reported as
  behind when the current default first appeared here after that save.

`shipped_prompt_texts` records when this instance first saw each default (by
digest), which is what "after that save" is measured against. A default is
backfilled from matching seed versions, and a name with no seed history is
assumed current since it was first written, so the first start of this build
reports only defaults that demonstrably changed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from . import prompt_store, timestamps

SEED_AUTHOR = "seed"
#: Author of a retired default kept as an instance's saved text.
UPGRADE_AUTHOR = "upgrade"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipped_prompt_texts (
    type          TEXT NOT NULL,
    name          TEXT NOT NULL,
    digest        TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (type, name, digest)
);
"""


@dataclass(frozen=True)
class Version:
    text: str
    deleted: bool
    created_at: str
    created_by: str | None


@dataclass(frozen=True)
class Plan:
    append_default: bool
    # First sighting to record for the current default; None when known.
    record_first_seen: str | None
    # When the default an operator's text predates appeared; None when current.
    newer_default_since: str | None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def plan(
    history: Sequence[Version], seen: Mapping[str, str], default: str, now: str
) -> Plan:
    """Decide one name's update. `history` is newest first; `seen` maps the
    digests already recorded for the name to when each was first seen."""
    first_seen = seen.get(digest(default))
    record = None
    if first_seen is None:
        seeded = [
            v.created_at
            for v in history
            if v.created_by == SEED_AUTHOR and not v.deleted and v.text == default
        ]
        if seeded:
            first_seen = min(seeded)
        elif not seen and all(v.created_by != SEED_AUTHOR for v in history):
            first_seen = min((v.created_at for v in history), default=now)
        else:
            first_seen = now
        record = first_seen
    latest = history[0] if history and not history[0].deleted else None
    if latest is None:
        return Plan(False, record, None)
    if latest.created_by == SEED_AUTHOR:
        return Plan(latest.text != default, record, None)
    behind = latest.text != default and latest.created_at < first_seen
    return Plan(False, record, first_seen if behind else None)


def sync(conn: sqlite3.Connection, type: str, name: str, default: str) -> str | None:
    """Apply `plan` to (type, name) in one write transaction. Returns when a
    newer default appeared, if the operator's saved text predates it."""
    with prompt_store._writing(conn):
        result = plan(*_state(conn, type, name), default, timestamps.now())
        if result.record_first_seen is not None:
            conn.execute(
                "INSERT INTO shipped_prompt_texts VALUES (?, ?, ?, ?)",
                (type, name, digest(default), result.record_first_seen),
            )
        if result.append_default:
            prompt_store._append(
                conn,
                type=type,
                name=name,
                text=default,
                deleted=0,
                created_by=SEED_AUTHOR,
            )
    return result.newer_default_since


def keep_retired_default(
    conn: sqlite3.Connection, type: str, name: str, retired: str
) -> bool:
    """Save `retired`, a default this build no longer ships, as the text of
    (type, name) when this instance ran with it and nobody saved one, so the
    instance keeps behaving as before. Returns whether it saved."""
    with prompt_store._writing(conn):
        history, seen = _state(conn, type, name)
        if history or digest(retired) not in seen:
            return False
        prompt_store._append(
            conn,
            type=type,
            name=name,
            text=retired,
            deleted=0,
            created_by=UPGRADE_AUTHOR,
        )
        return True


def newer_default_since(
    conn: sqlite3.Connection, type: str, name: str, default: str
) -> str | None:
    """Read-only `sync`: when a newer default appeared, if the saved text is behind."""
    return plan(
        *_state(conn, type, name), default, timestamps.now()
    ).newer_default_since


def _state(
    conn: sqlite3.Connection, type: str, name: str
) -> tuple[list[Version], dict[str, str]]:
    history = [
        Version(r["text"], bool(r["deleted"]), r["created_at"], r["created_by"])
        for r in conn.execute(
            "SELECT text, deleted, created_at, created_by FROM prompt_texts "
            "WHERE type = ? AND name = ? ORDER BY version DESC",
            (type, name),
        )
    ]
    seen = {
        r["digest"]: r["first_seen_at"]
        for r in conn.execute(
            "SELECT digest, first_seen_at FROM shipped_prompt_texts "
            "WHERE type = ? AND name = ?",
            (type, name),
        )
    }
    return history, seen
