"""Portable document history, excluding unrelated draft operations and auth data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from . import docs_store

DB_NAME = "mycelium-drafts.db"
FILE_NAME = "documentation.json"
TABLES = (
    "documentation_runs",
    "generated_documents",
    "generated_document_revisions",
    "generated_document_deliveries",
)


class Archive(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int
    tables: dict[str, list[dict[str, str | int | float | None]]]


def write(data_dir: Path, staging: Path) -> dict[str, int] | None:
    path = data_dir / DB_NAME
    if not path.exists():
        return None
    with closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as source:
        with closing(docs_store.connect(":memory:")) as snapshot:
            source.backup(snapshot)
            docs_store.migrate(snapshot)
            archive = Archive(
                version=1,
                tables={
                    table: [
                        dict(row)
                        for row in snapshot.execute(
                            f"SELECT * FROM {table} ORDER BY rowid"
                        )
                    ]
                    for table in TABLES
                },
            )
    (staging / FILE_NAME).write_text(archive.model_dump_json(), encoding="utf-8")
    return {table: len(rows) for table, rows in archive.tables.items()}


def prepare(staging: Path, *, required: bool) -> Path | None:
    """Validate into a fresh DB before a force restore touches the target."""
    path = staging / FILE_NAME
    if not path.exists():
        if required:
            raise ValueError("archive is missing required documentation.json")
        return None
    archive = Archive.model_validate_json(path.read_text(encoding="utf-8"))
    if archive.version != 1 or set(archive.tables) != set(TABLES):
        raise ValueError("unsupported documentation archive version or tables")
    prepared = staging / "documentation-validated.db"
    with closing(docs_store.connect(prepared)) as conn:
        docs_store.migrate(conn)
        with conn:
            for table in TABLES:
                _insert_rows(conn, table, archive.tables[table])
            _validate_history(conn)
    return prepared


def _insert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict[str, str | int | float | None]],
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for row in rows:
        if not row or set(row) - columns:
            raise ValueError(f"invalid columns in documentation archive: {table}")
        names = list(row)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            [row[name] for name in names],
        )


def _validate_history(conn: sqlite3.Connection) -> None:
    missing = conn.execute(
        "SELECT d.id FROM generated_documents d LEFT JOIN generated_document_revisions r "
        "ON r.document_id = d.id AND r.revision = d.current_revision "
        "WHERE r.document_id IS NULL OR "
        + " OR ".join(
            f"r.{field} IS NOT d.{field}"
            for field in (
                "body",
                "slug",
                "title",
                "guideline_set",
                "document_type",
                "statement_ids",
                "review",
            )
        )
        + " LIMIT 1"
    ).fetchone()
    if missing:
        raise ValueError("documentation archive has an inconsistent current revision")
    for table in ("generated_document_revisions", "generated_document_deliveries"):
        orphan = conn.execute(
            f"SELECT r.document_id FROM {table} r LEFT JOIN generated_documents d "
            "ON d.id = r.document_id WHERE d.id IS NULL LIMIT 1"
        ).fetchone()
        if orphan:
            raise ValueError("documentation archive contains orphaned history")
    missing_receipt_revision = conn.execute(
        "SELECT p.document_id FROM generated_document_deliveries p "
        "LEFT JOIN generated_document_revisions r "
        "ON r.document_id = p.document_id AND r.revision = p.revision "
        "WHERE r.document_id IS NULL LIMIT 1"
    ).fetchone()
    if missing_receipt_revision:
        raise ValueError(
            "documentation archive contains a receipt without its revision"
        )
    missing_published = conn.execute(
        "SELECT d.id FROM generated_documents d "
        "LEFT JOIN generated_document_deliveries p "
        "ON p.document_id = d.id AND p.revision = d.published_revision "
        "WHERE d.published_revision IS NOT NULL AND p.document_id IS NULL LIMIT 1"
    ).fetchone()
    if missing_published:
        raise ValueError("documentation archive is missing a publication receipt")
    _validate_json(conn)


def _validate_json(conn: sqlite3.Connection) -> None:
    fields = {
        "generated_documents": {
            "statement_ids": list,
            "review": dict,
            "delivery_target": dict,
        },
        "generated_document_revisions": {"statement_ids": list, "review": dict},
        "generated_document_deliveries": {"target": dict},
        "documentation_runs": {"profile_revisions": dict, "profile_snapshot": dict},
    }
    for table, types in fields.items():
        for row in conn.execute(f"SELECT {', '.join(types)} FROM {table}"):
            for field, expected in types.items():
                if row[field] is None and field == "delivery_target":
                    continue
                value = json.loads(row[field])
                if not isinstance(value, expected):
                    raise ValueError(
                        f"invalid documentation archive JSON: {table}.{field}"
                    )
                if field == "statement_ids" and any(
                    not isinstance(item, str) for item in value
                ):
                    raise ValueError("invalid documentation statement ids")
                if field in ("target", "delivery_target") and not all(
                    isinstance(value.get(key), str) and value[key]
                    for key in ("host", "owner", "repo", "base_branch")
                ):
                    raise ValueError("invalid documentation delivery coordinates")


def restore(data_dir: Path, prepared: Path | None) -> None:
    path = data_dir / DB_NAME
    if prepared is None and not path.exists():
        return
    with closing(docs_store.connect(path)) as conn:
        docs_store.migrate(conn)
        with conn:
            for table in reversed(TABLES):
                conn.execute(f"DELETE FROM {table}")
            if prepared is not None:
                with closing(docs_store.connect(prepared)) as source:
                    for table in TABLES:
                        _insert_rows(
                            conn,
                            table,
                            [
                                dict(row)
                                for row in source.execute(f"SELECT * FROM {table}")
                            ],
                        )
