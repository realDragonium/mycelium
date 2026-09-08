"""Admit manual documentation edits against their original revision and profile."""

from __future__ import annotations

import sqlite3

from . import doc_runs, docs_store
from .docgen.config import Provider
from .docgen.schema import ManualDocument


def start_document_edit(
    conn: sqlite3.Connection,
    document_id: str,
    expected_revision: int,
    document: ManualDocument,
    *,
    created_by: str | None,
    provider: Provider | None = None,
) -> str:
    row = docs_store.require_revision(conn, document_id, expected_revision)
    return doc_runs.start_run(
        conn=conn,
        prompt="Review and save the supplied manual edit without changing its text.",
        guideline_set=str(row["guideline_set"]),
        document_type=str(row["document_type"]),
        created_by=created_by,
        provider=provider,
        target_document_id=document_id,
        expected_revision=expected_revision,
        match_existing=False,
        manual_document=document,
    )


def start_draft_edit(
    conn: sqlite3.Connection,
    run_id: str,
    document: ManualDocument,
    *,
    created_by: str | None,
    provider: Provider | None = None,
) -> str:
    row = docs_store.get_run(conn, run_id)
    if row is None:
        raise ValueError("Documentation run not found")
    if not row["finished_at"] or row["document_id"] or not row["draft_body"]:
        raise ValueError("Only a finished run with an unsaved draft can be edited")
    if row["matched_document_id"] and not row["target_document_id"]:
        raise ValueError("Open the current document to edit this older revision draft")
    return doc_runs.start_run(
        conn=conn,
        prompt=str(row["prompt"]),
        guideline_set=row["guideline_set"],
        document_type=row["document_type"],
        created_by=created_by,
        provider=provider,
        target_document_id=row["target_document_id"],
        expected_revision=row["target_revision"],
        match_existing=False,
        manual_document=document,
    )
