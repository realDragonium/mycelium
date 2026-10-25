"""Persistent failure limits for automatic work."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel

from . import model_settings, product_settings, timestamps

Kind = Literal[
    "audience_review",
    "connect",
    "gap_follow_up",
    "draft_review",
    "curation",
    "mention",
    "embedding",
]
KINDS: tuple[Kind, ...] = get_args(Kind)


def limits() -> product_settings.AutomationSettings:
    """The saved Automation limits, or their defaults while they cannot be
    read, so background work still counts its failures toward a bound."""
    try:
        return product_settings.get(product_settings.AutomationSettings)
    except model_settings.Unavailable:
        return product_settings.AutomationSettings()


class Stop(BaseModel):
    kind: Kind
    item_id: str
    failures: int
    reason: str
    updated_at: str


def fail(
    conn: sqlite3.Connection,
    kind: Kind,
    item_id: str,
    inputs: str,
    reason: str,
    *,
    retries: int,
    now: datetime,
) -> bool:
    row = conn.execute(
        "SELECT inputs, failures FROM automation_stops WHERE kind = ? AND item_id = ?",
        (kind, item_id),
    ).fetchone()
    failures = (
        int(row["failures"]) + 1
        if row is not None and str(row["inputs"]) == inputs
        else 1
    )
    is_stopped = failures > retries
    conn.execute(
        "INSERT INTO automation_stops "
        "(kind, item_id, inputs, failures, stopped, reason, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (kind, item_id) DO UPDATE SET "
        "inputs = excluded.inputs, failures = excluded.failures, "
        "stopped = excluded.stopped, reason = excluded.reason, "
        "updated_at = excluded.updated_at",
        (
            kind,
            item_id,
            inputs,
            failures,
            int(is_stopped),
            reason,
            timestamps.of(now),
        ),
    )
    return is_stopped


def stop(
    conn: sqlite3.Connection,
    kind: Kind,
    item_id: str,
    inputs: str,
    reason: str,
    *,
    failures: int,
    now: datetime,
) -> None:
    conn.execute(
        "INSERT INTO automation_stops "
        "(kind, item_id, inputs, failures, stopped, reason, updated_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT (kind, item_id) DO UPDATE SET "
        "inputs = excluded.inputs, failures = excluded.failures, stopped = 1, "
        "reason = excluded.reason, updated_at = excluded.updated_at",
        (kind, item_id, inputs, failures, reason, timestamps.of(now)),
    )


def stopped(conn: sqlite3.Connection, kind: Kind) -> dict[str, str]:
    return {
        str(row["item_id"]): str(row["inputs"])
        for row in conn.execute(
            "SELECT item_id, inputs FROM automation_stops "
            "WHERE kind = ? AND stopped = 1",
            (kind,),
        )
    }


def retried(conn: sqlite3.Connection, kind: Kind, item_id: str, inputs: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM automation_stops WHERE kind = ? AND item_id = ? "
            "AND inputs = ? AND stopped = 0 AND failures = 0",
            (kind, item_id, inputs),
        ).fetchone()
        is not None
    )


def clear(conn: sqlite3.Connection, kind: Kind, item_ids: Sequence[str]) -> None:
    if not item_ids:
        return
    conn.executemany(
        "DELETE FROM automation_stops WHERE kind = ? AND item_id = ?",
        [(kind, item_id) for item_id in item_ids],
    )


def prune(conn: sqlite3.Connection, kind: Kind, current: Mapping[str, str]) -> None:
    stale = [
        str(row["item_id"])
        for row in conn.execute(
            "SELECT item_id, inputs FROM automation_stops WHERE kind = ?", (kind,)
        )
        if current.get(str(row["item_id"])) != str(row["inputs"])
    ]
    clear(conn, kind, stale)


def retry(conn: sqlite3.Connection, kind: Kind, item_id: str) -> bool:
    changed = conn.execute(
        "UPDATE automation_stops SET stopped = 0, failures = 0 "
        "WHERE kind = ? AND item_id = ? AND stopped = 1",
        (kind, item_id),
    )
    return changed.rowcount > 0


def stops(conn: sqlite3.Connection) -> list[Stop]:
    return [
        Stop.model_validate(dict(row))
        for row in conn.execute(
            "SELECT kind, item_id, failures, reason, updated_at "
            "FROM automation_stops WHERE stopped = 1 "
            "ORDER BY updated_at DESC, kind, item_id"
        )
    ]
