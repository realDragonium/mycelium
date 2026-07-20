"""Operation ledger — a bounded, best-effort record of *attempted* tool calls.

Separate SQLite file (`mycelium-ops.db`) from both the working substrate and
the knowledge audit log (`mycelium-history.db`). The three stores own three
different truths:

    substrate           — what is currently true
    history_events      — how the knowledge got that way (permanent provenance)
    operations (here)   — what agents/clients *tried to do* (bounded telemetry)

Why its own file, not a table in the substrate: the substrate is single-writer
SQLite, and recall is read-heavy. Logging every search/no-hit as a write into
the substrate would serialise telemetry against the one knowledge write lock.
A separate file has its own lock (WAL), can be rotated/truncated for retention
without touching knowledge, and — crucially — its failure is isolated: a broken
or locked ledger must NEVER change a tool's result. Every write here is
best-effort and swallows its own errors.

This module is deliberately dependency-light: plain data + SQL, no imports from
`server`/`http`/`auth`. The invocation seam (`server.tool`) gathers the caller
context and hands it here; the ledger only classifies the response envelope,
sanitises content, and appends a row.

Scope note: `correlation_id` / `parent_op_id` / `purpose` / `turn` columns exist
now but are unpopulated — they are the slots the optional client correlation
contract (DRA-229 scope #5) will fill without a migration.
"""

from __future__ import annotations

import itertools
import json as _json
import os
import sqlite3
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import timestamps
from .connections import ConnectionProvider

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id           TEXT NOT NULL UNIQUE,
    at_start        TEXT NOT NULL,
    at_end          TEXT,
    duration_ms     REAL,
    actor           TEXT,
    transport       TEXT,
    tool            TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    -- optional client correlation context (scope #5; nullable, unused today)
    correlation_id  TEXT,
    parent_op_id    TEXT,
    purpose         TEXT,
    session_id      TEXT,
    turn            TEXT,
    -- sanitised content capture (suppressed when capture mode is 'none')
    request_summary TEXT,
    result_summary  TEXT,
    -- structured metadata (kept even when content capture is off)
    result_count    INTEGER,
    result_ids      TEXT,
    draft_id        TEXT,
    error_class     TEXT,
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS operations_at_start ON operations (at_start);
CREATE INDEX IF NOT EXISTS operations_tool ON operations (tool);
CREATE INDEX IF NOT EXISTS operations_outcome ON operations (outcome);
CREATE INDEX IF NOT EXISTS operations_actor ON operations (actor);
CREATE INDEX IF NOT EXISTS operations_correlation ON operations (correlation_id);
"""

# Outcome vocabulary. `succeeded` / `no_hit` / `rejected` / `queued` / `failed`
# are classified generically from the response envelope (see `classify`).
# `timed_out` / `cancelled` need cancellation/deadline signals the seam does not
# yet surface — reserved here, wired later.
OUTCOMES = frozenset(
    {"succeeded", "no_hit", "rejected", "queued", "failed", "timed_out", "cancelled"}
)

# Longest a captured string value is kept before truncation. Keeps the ledger
# a *summary*, not a mirror of full payloads.
_MAX_STR = 500
# Cap on how many returned ids are persisted per operation — a large search
# result shouldn't produce an unbounded result_ids column.
_MAX_IDS = 200
# How often (every Nth append, by rowid) a record() call also trims the ledger
# to its retention bound, so a long-running process stays bounded without a
# separate scheduler.
_PRUNE_EVERY = 1000
# Keys whose values are redacted wholesale. Matched exactly, plus any key that
# *contains* one of `_SECRET_SUBSTRINGS` (so access_token / refresh_token /
# client_secret / x-api-key are all caught without listing every variant).
_SECRET_KEYS = frozenset(
    {"authorization", "cookie", "api_key", "apikey", "private_key", "bearer"}
)
_SECRET_SUBSTRINGS = ("password", "secret", "token", "authorization")


def _is_secret(key: str) -> bool:
    k = key.lower()
    return k in _SECRET_KEYS or any(s in k for s in _SECRET_SUBSTRINGS)


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL + a SHORT busy timeout: the ledger is written from every request
    # thread and read by the operations API concurrently. It's best-effort
    # telemetry, so a contended write must fail fast and be dropped rather than
    # stall the tool call that is waiting on record() to return — hence 250ms,
    # not the multi-second timeout the substrate stores use. Its own file means
    # this never contends with the substrate's write lock. (No-op on :memory:.)
    conn.execute("PRAGMA busy_timeout = 250")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_provider: ConnectionProvider[str] = ConnectionProvider("ops", connect)


def configure(db_path: Path | str) -> None:
    """Point the provider at the ledger file. Threads (re)open lazily."""
    _provider.configure(str(db_path))


def connection() -> sqlite3.Connection:
    return _provider.connection()


def use_connection(conn: sqlite3.Connection) -> None:
    """Pin `conn` as this thread's ledger connection (for :memory: / tests)."""
    _provider.use(conn)


def reset() -> None:
    _provider.reset()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(OPS_SCHEMA)
    conn.commit()


def enabled() -> bool:
    """True when the ledger is configured and not disabled by env.

    `MYCELIUM_OPS_LEDGER=0` (or off/false/no) turns recording off even when a
    file is configured — the kill switch the "disabling telemetry doesn't
    change tool results" guarantee is verified against.
    """
    if not _provider.is_configured():
        return False
    return os.environ.get("MYCELIUM_OPS_LEDGER", "1").lower() not in {
        "0",
        "off",
        "false",
        "no",
    }


def _capture_content() -> bool:
    """Whether free-form request/result summaries are captured. Structured
    metadata (counts, ids, draft/error class) is kept regardless."""
    return os.environ.get("MYCELIUM_OPS_CAPTURE", "summary").lower() != "none"


# --- caller context handed in by the invocation seam ------------------------


@dataclass
class CallContext:
    tool: str
    actor: str | None = None
    transport: str | None = None
    session_id: str | None = None
    # kwargs the tool was invoked with (post draft_id strip); sanitised here.
    request: dict[str, Any] = field(default_factory=dict)


# --- classification & sanitisation (pure) -----------------------------------


def classify(result: Any, error: BaseException | None) -> str:
    """Derive an outcome from the response envelope — no per-tool knowledge.

    The substrate's tools encode their own outcome in the shape they return:
    a phrasing-rejected write returns ``{"rejected": True, ...}``, a draft
    redirect returns ``{"queued": ...}``, and a search returns ``{"results":
    [...]}`` (empty ⇒ no hit). A raised `PermissionError` is a role rejection;
    any other exception is a failure.
    """
    if error is not None:
        return "rejected" if isinstance(error, PermissionError) else "failed"
    if isinstance(result, dict):
        if result.get("rejected"):
            return "rejected"
        if "queued" in result or (result.get("draft_id") and "seq" in result):
            return "queued"
        results = result.get("results")
        if isinstance(results, list) and not results:
            return "no_hit"
    elif isinstance(result, list) and not result:
        # Search/list tools return a bare list; empty ⇒ nothing matched.
        return "no_hit"
    return "succeeded"


def _redact(value: Any, key: str = "") -> Any:
    """Sanitise one value for capture: drop secrets, truncate long strings,
    replace big/opaque structures with a shape hint so the ledger never
    mirrors a full payload (or consumes a stream)."""
    if key and _is_secret(key):
        return "[redacted]"
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in itertools.islice(value.items(), 50)}
    if isinstance(value, list):
        # Long/likely-vector lists collapse to a length hint; short ones keep
        # their (redacted) items.
        if len(value) > 20 or (value and isinstance(value[0], (int, float))):
            return f"[{len(value)} items]"
        return [_redact(v) for v in value]
    return f"<{type(value).__name__}>"


def sanitize_request(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact(v, k) for k, v in kwargs.items()}


def _extract_ids(rows: list[Any]) -> list[str] | None:
    """Pull up to `_MAX_IDS` statement/entity ids out of a result row list."""
    ids: list[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or r.get("statement_id")
        if rid:
            ids.append(str(rid))
            if len(ids) >= _MAX_IDS:
                break
    return ids or None


def summarize_result(result: Any) -> tuple[Any, int | None, list[str] | None, str | None]:
    """Return ``(summary, count, ids, draft_id)`` extracted from a result.

    Handles the two shapes tools actually return — a bare list (search/list
    tools) and a dict — by membership only; it never iterates an unknown object,
    so a streaming/generator result passes through untouched (summary None).
    """
    if isinstance(result, list):
        return _redact(result), len(result), _extract_ids(result), None
    if not isinstance(result, dict):
        return None, None, None, None
    draft_id = result.get("draft_id")
    count: int | None = None
    ids: list[str] | None = None
    results = result.get("results")
    if isinstance(results, list):
        count = len(results)
        ids = _extract_ids(results)
    for single in ("statement_id", "entity_id", "id"):
        if single in result and ids is None:
            ids = [str(result[single])]
            break
    summary = _redact(result)
    return summary, count, ids, draft_id


# --- append -----------------------------------------------------------------


def record(
    ctx: CallContext,
    *,
    at_start: str,
    duration_ms: float,
    result: Any = None,
    error: BaseException | None = None,
) -> str | None:
    """Append one operation row. Best-effort: any failure is swallowed so the
    ledger can never break the underlying tool call. Returns the op_id on a
    successful write, else None.
    """
    op_id = "op_" + _uuid.uuid4().hex[:16]
    try:
        outcome = classify(result, error)
        capture = _capture_content()
        summary, count, ids, draft_id = summarize_result(result)
        request_summary = (
            _json.dumps(sanitize_request(ctx.request)) if capture and ctx.request else None
        )
        result_summary = _json.dumps(summary) if capture and summary is not None else None
        error_class = type(error).__name__ if error is not None else None
        # An exception's text can echo request values (incl. secrets) and be
        # arbitrarily long, so it goes through the same truncation as any other
        # captured string, and is suppressed entirely under capture=none.
        error_message = (
            _redact(str(error)) if (error is not None and capture) else None
        )

        conn = connection()
        cur = conn.execute(
            "INSERT INTO operations (op_id, at_start, at_end, duration_ms, actor, "
            "transport, tool, outcome, session_id, request_summary, result_summary, "
            "result_count, result_ids, draft_id, error_class, error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                op_id,
                at_start,
                timestamps.now(),
                duration_ms,
                ctx.actor,
                ctx.transport,
                ctx.tool,
                outcome,
                ctx.session_id,
                request_summary,
                result_summary,
                count,
                _json.dumps(ids) if ids else None,
                draft_id,
                error_class,
                error_message,
            ),
        )
        conn.commit()
        # Amortise retention across the process's lifetime: roughly every
        # `_PRUNE_EVERY` rows, trim to the configured bound. Keeps a long-running
        # server bounded without a scheduler; still best-effort under the guard.
        if cur.lastrowid and cur.lastrowid % _PRUNE_EVERY == 0:
            prune_configured()
        return op_id
    except Exception:  # never let telemetry break the operation
        import logging

        logging.getLogger(__name__).warning("ops ledger write failed", exc_info=True)
        return None


# --- read -------------------------------------------------------------------


def query(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    tools: set[str] | None = None,
    outcomes: set[str] | None = None,
    actor: str | None = None,
) -> tuple[list[sqlite3.Row], int]:
    """Page over recorded operations, newest first by the monotonic `seq`.

    `tools`/`outcomes` are None for "no filter" or a set to filter by. An
    explicitly empty set means "match nothing" (e.g. the caller intersected an
    unknown `outcome` param with the vocabulary and got nothing) — distinct from
    None, which imposes no filter. Returns `(rows, total)`.
    """
    where: list[str] = []
    params: list[Any] = []

    def _in(col: str, values: set[str] | None) -> None:
        if values is None:
            return
        if not values:
            where.append("0")  # explicit empty filter → no rows
            return
        where.append(f"{col} IN ({','.join('?' for _ in values)})")
        params.extend(sorted(values))

    _in("tool", tools)
    _in("outcome", outcomes)
    if actor:
        where.append("actor = ?")
        params.append(actor)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM operations{where_sql}", params
    ).fetchone()
    total = int(total_row["n"]) if total_row else 0

    rows = conn.execute(
        f"SELECT * FROM operations{where_sql} ORDER BY seq DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return rows, total


# --- retention --------------------------------------------------------------


def prune(conn: sqlite3.Connection, *, keep_days: int | None, keep_rows: int | None) -> int:
    """Trim the ledger to a retention bound. Deletes rows older than
    `keep_days` and, independently, any beyond the newest `keep_rows`.
    Returns the number of rows removed. A `None` bound disables that rule.
    """
    removed = 0
    if keep_days is not None and keep_days >= 0:
        cutoff = timestamps.days_ago(keep_days)
        removed += conn.execute(
            "DELETE FROM operations WHERE at_start < ?", (cutoff,)
        ).rowcount
    if keep_rows is not None and keep_rows >= 0:
        removed += conn.execute(
            "DELETE FROM operations WHERE seq NOT IN "
            "(SELECT seq FROM operations ORDER BY seq DESC LIMIT ?)",
            (keep_rows,),
        ).rowcount
    conn.commit()
    return removed


def prune_configured() -> int:
    """Prune using env-configured bounds. Called at startup; safe to call
    anytime. No-op when the ledger isn't configured."""
    if not _provider.is_configured():
        return 0
    keep_days = _env_int("MYCELIUM_OPS_RETENTION_DAYS", 30)
    keep_rows = _env_int("MYCELIUM_OPS_RETENTION_ROWS", None)
    try:
        return prune(connection(), keep_days=keep_days, keep_rows=keep_rows)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("ops ledger prune failed", exc_info=True)
        return 0


def _env_int(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default
