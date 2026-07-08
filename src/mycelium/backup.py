"""Export / import the entire substrate as a portable .tar.gz archive.

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
    vectors/mycelium.vec       statement vector index (omit with --no-vectors)
    vectors/mycelium-annotations.vec
    vectors/mycelium-names.vec

Records carry their full column set, including audit columns and the
internal autoincrement keys (link_id, node_id) so the substrate
round-trips byte-for-byte at the semantic level. Vector index files are
copied verbatim — they're binary blobs produced by hnswlib.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, TextIO

from . import migrations, store

# Archives carry the schema version the substrate was at when exported.
# Sourced from the migration runner so the two stay in lock-step.
SCHEMA_VERSION = migrations.CURRENT_VERSION


# Tables exported in dependency order. The same order is used on import,
# so foreign keys resolve naturally. Internal mechanism tables that
# depend on others (when_nodes, *_vector_ids) appear after their parents.
_DATA_TABLES: tuple[str, ...] = (
    "entities",
    "names",
    "statements",
    "annotations",
    "statement_mentions",
    "annotation_mentions",
    "statement_links",
    "when_nodes",
    "entity_links",
    "statement_annotations",
    "entity_annotations",
)

# *_vector_ids are gated on --include-vectors. When vectors aren't
# included the indexes (and these mappings) will be rebuilt by the
# importer from text via embed.
_VECTOR_ID_TABLES: tuple[str, ...] = (
    "statement_vector_ids",
    "name_vector_ids",
    "annotation_vector_ids",
)

_VECTOR_FILES: tuple[str, ...] = (
    "mycelium.vec",
    "mycelium-annotations.vec",
    "mycelium-names.vec",
)

# Each row dict is tagged with `_kind` so the import dispatcher knows
# which table to insert into. _kind is the singular form (entity, name,
# statement, ...) so a future hand-edited export reads more naturally.
_TABLE_TO_KIND: dict[str, str] = {
    "entities": "entity",
    "names": "name",
    "statements": "statement",
    "annotations": "annotation",
    "statement_mentions": "statement_mention",
    "annotation_mentions": "annotation_mention",
    "statement_links": "statement_link",
    "when_nodes": "when_node",
    "entity_links": "entity_link",
    "statement_annotations": "statement_annotation",
    "entity_annotations": "entity_annotation",
    "statement_vector_ids": "statement_vector_id",
    "name_vector_ids": "name_vector_id",
    "annotation_vector_ids": "annotation_vector_id",
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
    """Restore an archive into `data_dir`. By default refuses to clobber
    an existing substrate; `force=True` first auto-snapshots the current
    state to `<data_dir>.before-restore.<timestamp>.tar.gz` and then
    wipes the data dir.

    Returns the manifest read from the archive.
    """
    archive_path = Path(archive_path)
    data_dir = Path(data_dir)

    db_path = data_dir / "mycelium.db"
    if db_path.exists():
        if not force:
            raise FileExistsError(
                f"data dir {data_dir!r} already contains a substrate; "
                "pass force=True to clobber (auto-snapshots first)"
            )
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
        if manifest.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"archive schema_version {manifest.get('schema_version')!r} "
                f"unsupported (this build expects {SCHEMA_VERSION})"
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
            store.migrate(conn)
            _load_data_jsonl(conn, staging / "data.jsonl")
            if history_db_path is not None and (staging / "history.jsonl").exists():
                _load_history_jsonl(conn, staging / "history.jsonl")
            conn.commit()
        finally:
            conn.close()

        # Vector files: copy back if present in the archive. Otherwise
        # leave the data dir without them — the server's next `init()`
        # will create empty indexes and `_backfill_name_index` will
        # rebuild names. Statement / annotation indexes stay empty until
        # explicit reindex (a separate operation, out of scope here).
        vectors_src = staging / "vectors"
        if vectors_src.is_dir():
            for vf in _VECTOR_FILES:
                src = vectors_src / vf
                if src.exists():
                    shutil.copy2(src, data_dir / vf)

        return manifest


def _load_data_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    """Stream the JSONL back into the freshly-migrated DB. Each line
    becomes an INSERT into the table its `_kind` resolves to."""
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.pop("_kind")
            table = _KIND_TO_TABLE.get(kind)
            if table is None:
                raise ValueError(f"unknown record kind in archive: {kind!r}")
            cols = list(row.keys())
            placeholders = ", ".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )


def _load_history_jsonl(conn: sqlite3.Connection, path: Path) -> None:
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row.pop("_kind", None)
            cols = list(row.keys())
            placeholders = ", ".join("?" * len(cols))
            conn.execute(
                f"INSERT INTO history.history_events ({', '.join(cols)}) "
                f"VALUES ({placeholders})",
                [row[c] for c in cols],
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
        *_VECTOR_FILES,
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
