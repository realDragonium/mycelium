"""Export / import an instance — substrate plus its steering texts — as a
portable .tar.gz archive.

The same code powers manual exports ("snapshot this for sharing") and
automated backups ("snapshot this on a schedule"). Future automated
destinations (S3, cron, etc.) wrap the same `export_substrate` function;
they don't reimplement serialization.

Archive layout
--------------
    manifest.json              metadata + row counts + flags
    data.jsonl                 relational data, one record per line,
                                discriminated by `_kind`, dependency-ordered
    history.jsonl              audit log events (omit with --no-history)
    prompts.jsonl              editable prompt texts, every version
    vectors/mycelium.vec       statement vector index (omit with --no-vectors)
    vectors/mycelium-names.vec

Records carry their full column set, including audit columns and the
internal autoincrement keys (link_id, node_id) so the substrate
round-trips byte-for-byte at the semantic level. Vector index files are
copied verbatim — they're binary blobs produced by hnswlib.

Prompt texts live in their own DB (`mycelium-prompts.db`) and are instance
configuration, not substrate — but nothing outside the instance can
reconstruct an operator's edit, so they ride along in every archive with no
opt-out flag. The archive carries *every* version, tombstones included: the
store is append-only and a restore is a point-in-time recovery of it, so a
name an operator retired comes back retired.

Two payloads, two postures. The substrate is what the archive is for — no
`mycelium.db`, no export. Prompt texts degrade instead of failing: an
unreadable prompts DB is left out of the archive with a warning, and an
unreadable prompts section is skipped on import, because startup re-seeds
its packaged defaults into an empty store and an instance that comes back
with default steering beats one that doesn't come back.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from . import migrations, store

logger = logging.getLogger(__name__)

# Record kinds from the removed annotation subsystem. Legacy archives
# (exported before annotations were deprecated) still carry these lines;
# the importer skips them rather than erroring on an unknown kind.
_LEGACY_ANNOTATION_KINDS: frozenset[str] = frozenset(
    {
        "annotation",
        "annotation_mention",
        "statement_annotation",
        "entity_annotation",
        "annotation_vector_id",
    }
)

# Archives carry the schema version the substrate was at when exported.
# Sourced from the migration runner so the two stay in lock-step.
SCHEMA_VERSION = migrations.CURRENT_VERSION

# Oldest archive schema the importer still restores. v8 archives differ
# from v9 only by the `link_kind` discriminator on when-node rows, which
# `_load_data_jsonl` strips (entity↔statement rows are dropped — v9
# removed their table, and v8 exports never carried the link rows
# themselves). Anything older predates shapes the loader handles.
_MIN_ARCHIVE_SCHEMA_VERSION = 8

# The editable prompt texts, alongside the substrate in the data dir.
PROMPTS_DB_NAME = "mycelium-prompts.db"


# Tables exported in dependency order. The same order is used on import,
# so foreign keys resolve naturally. Internal mechanism tables that
# depend on others (when_nodes, *_vector_ids) appear after their parents.
_DATA_TABLES: tuple[str, ...] = (
    "entities",
    "names",
    "statements",
    "statement_mentions",
    "statement_links",
    "when_nodes",
    "entity_links",
)

# *_vector_ids are gated on --include-vectors. When vectors aren't
# included the indexes (and these mappings) will be rebuilt by the
# importer from text via embed.
_VECTOR_ID_TABLES: tuple[str, ...] = (
    "statement_vector_ids",
    "name_vector_ids",
)

_VECTOR_FILES: tuple[str, ...] = (
    "mycelium.vec",
    "mycelium-names.vec",
)

# Vector files legacy archives may still carry; ignored on import.
_LEGACY_VECTOR_FILES: tuple[str, ...] = ("mycelium-annotations.vec",)

# Each row dict is tagged with `_kind` so the import dispatcher knows
# which table to insert into. _kind is the singular form (entity, name,
# statement, ...) so a future hand-edited export reads more naturally.
_TABLE_TO_KIND: dict[str, str] = {
    "entities": "entity",
    "names": "name",
    "statements": "statement",
    "statement_mentions": "statement_mention",
    "statement_links": "statement_link",
    "when_nodes": "when_node",
    "entity_links": "entity_link",
    "statement_vector_ids": "statement_vector_id",
    "name_vector_ids": "name_vector_id",
}
_KIND_TO_TABLE: dict[str, str] = {v: k for k, v in _TABLE_TO_KIND.items()}


# --- export -----------------------------------------------------------------


def export_substrate(
    data_dir: Path,
    out_path: Path,
    *,
    include_history: bool = True,
    include_vectors: bool = True,
) -> dict[str, Any]:
    """Snapshot the substrate at `data_dir` to a .tar.gz at `out_path`.

    Returns the manifest dict (also written into the archive) so callers
    (scheduled-backup wrappers, integration tests) can verify what they
    just wrote without reopening the archive.
    """
    data_dir = Path(data_dir)
    out_path = Path(out_path)

    db_path = data_dir / "mycelium.db"
    if not db_path.exists():
        raise FileNotFoundError(f"no substrate at {data_dir!r}")
    history_db_path = data_dir / "mycelium-history.db"
    prompts_db_path = data_dir / PROMPTS_DB_NAME

    # Read everything via a fresh connection — never touch the live one
    # the running server (if any) may be using.
    conn = store.connect(db_path)
    try:
        with tempfile.TemporaryDirectory() as staging_str:
            staging = Path(staging_str)

            row_counts: dict[str, int] = {}
            with (staging / "data.jsonl").open("w", encoding="utf-8") as f:
                _write_tables(conn, f, _DATA_TABLES, row_counts)
                if include_vectors:
                    _write_tables(conn, f, _VECTOR_ID_TABLES, row_counts)

            if include_history and history_db_path.exists():
                history_count = _write_history(
                    history_db_path, staging / "history.jsonl"
                )
                row_counts["history_events"] = history_count

            prompts_count = _archive_prompts(prompts_db_path, staging / "prompts.jsonl")
            if prompts_count is not None:
                row_counts["prompt_texts"] = prompts_count

            if include_vectors:
                vectors_dir = staging / "vectors"
                vectors_dir.mkdir()
                for vf in _VECTOR_FILES:
                    src = data_dir / vf
                    if src.exists():
                        shutil.copy2(src, vectors_dir / vf)

            manifest = {
                "schema_version": SCHEMA_VERSION,
                "exported_at": _now_iso(),
                "includes_history": include_history and history_db_path.exists(),
                "includes_prompts": prompts_count is not None,
                "includes_vectors": include_vectors,
                "row_counts": row_counts,
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            _make_archive(staging, out_path)
            return manifest
    finally:
        conn.close()


def _write_tables(
    conn: sqlite3.Connection,
    fp: TextIO,
    tables: tuple[str, ...],
    row_counts: dict[str, int],
) -> None:
    """Dump each table to JSONL, tagged with `_kind`. Ordering within a
    table is by rowid so autoincrement parents precede their children
    (e.g., when_nodes parent nodes have lower node_ids than their
    descendants — assigned by AUTOINCREMENT in insert order)."""
    for table in tables:
        kind = _TABLE_TO_KIND[table]
        count = 0
        for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            payload: dict[str, Any] = {"_kind": kind}
            for col in row.keys():
                payload[col] = row[col]
            fp.write(json.dumps(payload) + "\n")
            count += 1
        row_counts[table] = count


def _write_history(history_db_path: Path, out_path: Path) -> int:
    """Dump every history event row, one JSONL line per event. Returns
    rows written."""
    conn = sqlite3.connect(str(history_db_path))
    conn.row_factory = sqlite3.Row
    try:
        count = 0
        with out_path.open("w", encoding="utf-8") as fp:
            for row in conn.execute("SELECT * FROM history_events ORDER BY event_id"):
                payload: dict[str, Any] = {"_kind": "history_event"}
                for col in row.keys():
                    payload[col] = row[col]
                fp.write(json.dumps(payload) + "\n")
                count += 1
        return count
    finally:
        conn.close()


def _archive_prompts(prompts_db_path: Path, out_path: Path) -> int | None:
    """Dump every prompt-text row to JSONL. Returns rows written, or None
    when the archive carries no prompts section at all.

    None covers both "this instance has no prompts DB" (a fresh data dir, or
    one from before prompt texts existed) and "its prompts DB would not
    read". Neither aborts the export: the substrate is the payload, and an
    instance restored without steering texts re-seeds the packaged defaults
    at startup.

    Anything the section throws is anything the export survives — a DB that
    won't open, a row SQLite serves but JSON can't hold (a BLOB where text
    belongs, after a hand repair). Scheduled backups and the force-restore
    safety snapshot both run through here, and neither may be stopped by
    the smaller of the two payloads."""
    if not prompts_db_path.exists():
        return None
    try:
        return _write_prompts(prompts_db_path, out_path)
    except Exception:
        logger.warning(
            "could not read prompt texts from %s; the archive carries none",
            prompts_db_path,
            exc_info=True,
        )
        out_path.unlink(missing_ok=True)
        return None


def _write_prompts(prompts_db_path: Path, out_path: Path) -> int:
    """Dump the whole `prompt_texts` table — every version of every name,
    tombstones included — one JSONL line per row. Returns rows written.

    Ordered by (type, name, version) so a hand-read archive shows each
    name's history in the order it was written. Opened through the store's
    own `connect`, whose busy timeout is what lets this read overlap a live
    server saving a version instead of failing the section outright."""
    from . import prompt_store

    conn = prompt_store.connect(prompts_db_path)
    try:
        count = 0
        with out_path.open("w", encoding="utf-8") as fp:
            for row in conn.execute(
                "SELECT * FROM prompt_texts ORDER BY type, name, version"
            ):
                payload: dict[str, Any] = {"_kind": "prompt_text"}
                for col in row.keys():
                    payload[col] = row[col]
                fp.write(json.dumps(payload) + "\n")
                count += 1
        return count
    finally:
        conn.close()


def _make_archive(staging: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w:gz") as tar:
        for item in sorted(staging.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(staging)))


# --- import -----------------------------------------------------------------


def import_substrate(
    archive_path: Path,
    data_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Restore an archive into `data_dir`. By default refuses to clobber an
    instance already there; `force=True` first auto-snapshots the current
    state to `<data_dir>.before-restore.<timestamp>.tar.gz` and then wipes
    the data dir.

    Substrate and prompt texts both count as "already there", and the wipe
    takes both — a restore makes the data dir be the archive, never a mix of
    two instances' steering texts. A dir holding prompt texts but no
    substrate has nothing `export_substrate` can snapshot, so forcing over
    one is the one restore that keeps no safety net.

    Returns the manifest read from the archive.
    """
    archive_path = Path(archive_path)
    data_dir = Path(data_dir)

    db_path = data_dir / "mycelium.db"
    if db_path.exists() or (data_dir / PROMPTS_DB_NAME).exists():
        if not force:
            raise FileExistsError(
                f"data dir {data_dir!r} already contains an instance; "
                "pass force=True to clobber (auto-snapshots first)"
            )
        if db_path.exists():
            _safety_snapshot(data_dir)
        _wipe_data_dir(data_dir)

    data_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)
        with tarfile.open(archive_path, "r:gz") as tar:
            # `filter="data"` rejects unsafe paths (path traversal, absolute
            # paths, etc.) — the Python 3.14+ default. We make it explicit
            # so behavior is identical on 3.11 through 3.14+.
            tar.extractall(staging, filter="data")

        manifest_path = staging / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("archive has no manifest.json — not a mycelium export")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        archive_version = manifest.get("schema_version")
        if (
            not isinstance(archive_version, int)
            or archive_version < _MIN_ARCHIVE_SCHEMA_VERSION
            or archive_version > SCHEMA_VERSION
        ):
            raise ValueError(
                f"archive schema_version {archive_version!r} unsupported "
                f"(this build accepts {_MIN_ARCHIVE_SCHEMA_VERSION}"
                f"..{SCHEMA_VERSION})"
            )

        # Restore relational data into a fresh DB. History DB is only
        # attached when the archive carries one — keeps the import side
        # symmetric with how `connect` works at runtime.
        history_db_path = (
            data_dir / "mycelium-history.db"
            if manifest.get("includes_history")
            else None
        )
        conn = store.connect(db_path, history_path=history_db_path)
        try:
            store.migrate(conn)  # DDL + seed; owns its own commit
            with store.transaction(conn):
                _load_data_jsonl(conn, staging / "data.jsonl")
                if history_db_path is not None and (staging / "history.jsonl").exists():
                    _load_history_jsonl(conn, staging / "history.jsonl")
        finally:
            conn.close()

        # Prompt texts: keyed on the section actually being in the archive,
        # not on what the manifest claims, so a truncated archive degrades
        # the same way one exported without prompts does.
        prompts_jsonl = staging / "prompts.jsonl"
        if prompts_jsonl.exists():
            _restore_prompts(data_dir / PROMPTS_DB_NAME, prompts_jsonl)

        # Vector files: copy back if present in the archive. Otherwise
        # leave the data dir without them — the server's next `init()`
        # will create empty indexes and `_backfill_name_index` will
        # rebuild names. The statement index stays empty until explicit
        # reindex (a separate operation, out of scope here).
        vectors_src = staging / "vectors"
        if vectors_src.is_dir():
            for vf in _VECTOR_FILES:
                src = vectors_src / vf
                if src.exists():
                    shutil.copy2(src, data_dir / vf)

        return manifest


def _table_columns(conn: sqlite3.Connection, table: str) -> frozenset[str]:
    """The columns `table` actually has — the allow-list an archived
    record's column names are checked against.

    `table` is one of this module's own literals, optionally schema-
    qualified (`history.history_events`), never a name from an archive."""
    schema, _, name = table.rpartition(".")
    prefix = f"{schema}." if schema else ""
    rows = conn.execute(f"PRAGMA {prefix}table_info({name})").fetchall()
    return frozenset(r["name"] for r in rows)


def _insert_archived_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    table: str,
    columns: frozenset[str],
    source: str,
) -> None:
    """Insert one archived record with the columns it carries.

    Those column names end up in the statement text, where a bound
    parameter cannot go — so they are checked against the destination
    table first, exact spelling and all. An archive is untrusted input,
    the same reason extraction runs with `filter="data"`. An unexpected
    name fails the restore; the caller's transaction is what keeps a
    refusal from leaving half a database behind."""
    cols = list(row)
    if not cols:
        raise ValueError(f"{source} record for {table} carries no columns")
    unknown = sorted(set(cols) - columns)
    if unknown:
        raise ValueError(
            f"{source} record names columns {table} does not have: {unknown!r}"
        )
    placeholders = ", ".join("?" * len(cols))
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [row[c] for c in cols],
    )


def _load_data_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    """Stream the JSONL back into the freshly-migrated DB. Each line
    becomes an INSERT into the table its `_kind` resolves to."""
    legacy_skipped = 0
    columns = {t: _table_columns(conn, t) for t in _KIND_TO_TABLE.values()}
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.pop("_kind")
            if kind in _LEGACY_ANNOTATION_KINDS:
                legacy_skipped += 1
                continue
            # Old archives carry a `link_kind` discriminator on when-node
            # rows; the entity_statement kind lost its table, so those rows
            # are dropped and the key is stripped from the rest.
            if kind == "when_node":
                if row.get("link_kind") == "entity_statement":
                    continue
                row.pop("link_kind", None)
            table = _KIND_TO_TABLE.get(kind)
            if table is None:
                raise ValueError(f"unknown record kind in archive: {kind!r}")
            _insert_archived_row(
                conn,
                row,
                table=table,
                columns=columns[table],
                source="data.jsonl",
            )
    if legacy_skipped:
        logger.info(
            "skipped %d legacy annotation record(s) from pre-removal archive",
            legacy_skipped,
        )


def _restore_prompts(prompts_db_path: Path, path: Path) -> None:
    """Rebuild the prompts DB from the archive's prompt-text rows.

    Every archived version is inserted exactly as it was written — ids,
    version numbers and tombstones included — so the restored store is the
    one that was backed up rather than a flattened copy of its current
    rows. Nothing is rewritten in place: the store is append-only, and a
    restore appends nothing of its own.

    All-or-nothing, and never fatal. An unreadable or conflicting section
    rolls back to an empty store and logs, because by this point the
    substrate has already landed and an instance whose steering texts fall
    back to the packaged seeds is worth far more than a failed restore."""
    from . import prompt_store

    try:
        conn = prompt_store.connect(prompts_db_path)
        try:
            prompt_store.migrate(conn)
            conn.execute("BEGIN IMMEDIATE")
            try:
                _insert_prompt_rows(conn, path)
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "could not restore prompt texts from the archive; the instance "
            "comes back with none and startup re-seeds its packaged defaults",
            exc_info=True,
        )


def _insert_prompt_rows(conn: sqlite3.Connection, path: Path) -> None:
    """Insert each archived prompt-text row with the columns it carries."""
    columns = _table_columns(conn, "prompt_texts")
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.pop("_kind", None)
            if kind != "prompt_text":
                raise ValueError(f"unknown record kind in prompts.jsonl: {kind!r}")
            _insert_archived_row(
                conn,
                row,
                table="prompt_texts",
                columns=columns,
                source="prompts.jsonl",
            )


def _load_history_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    """Insert each archived audit event into the attached history DB."""
    table = "history.history_events"
    columns = _table_columns(conn, table)
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row.pop("_kind", None)
            _insert_archived_row(
                conn,
                row,
                table=table,
                columns=columns,
                source="history.jsonl",
            )


# --- helpers ---------------------------------------------------------------


def _safety_snapshot(data_dir: Path) -> Path:
    """Snapshot the current data dir before --force clobbers it. The
    archive lands next to (not inside) the data dir so the wipe doesn't
    eat the safety net."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = data_dir.parent / f"{data_dir.name}.before-restore.{timestamp}.tar.gz"
    export_substrate(data_dir, out, include_history=True, include_vectors=True)
    return out


def _wipe_data_dir(data_dir: Path) -> None:
    """Remove every mycelium-owned file from `data_dir`. Other files
    (user notes, unrelated content) are left alone — we don't `rm -rf`
    a directory we don't fully own."""
    for name in (
        "mycelium.db",
        "mycelium-history.db",
        PROMPTS_DB_NAME,
        *_VECTOR_FILES,
        *_LEGACY_VECTOR_FILES,
    ):
        target = data_dir / name
        if target.exists():
            target.unlink()
    # SQLite WAL and shm sidecars (if WAL mode ever gets enabled).
    for sidecar in data_dir.glob("mycelium*.db-*"):
        sidecar.unlink()


def _now_iso() -> str:
    t = datetime.now(timezone.utc)
    return f"{t.strftime('%Y-%m-%dT%H:%M:%S')}.{t.microsecond // 1000:03d}Z"
