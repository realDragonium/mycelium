"""A small, realistic instance that puts rows in every table worth keeping.

Shared by the backup round-trip tests and the migration-fixture capture
script (`scripts/capture_migration_fixture.py`), so the data a migration
fixture freezes is the data a backup must carry. The capture script also
runs this against historical builds, so every step that touches a later
table or API checks that it exists first rather than assuming today's code.

Substrate writes go through the server's tools so derived rows (mentions,
plurals, vector ids, history, condition trees) appear the way production
writes them. Rows only reachable through model-driven flows (reviews,
applications, documentation runs) are written through their
stores directly.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path

import numpy as np

from mycelium.server import runtime

STATEMENTS = {
    "submit": ("event", "A user submits the Login form."),
    "session": ("event", "The server issues a Session token."),
    "locked": ("state", "The account is locked."),
    "expiry": ("rule", "A Session token expires after twelve hours."),
}


def embed(text: str) -> list[float]:
    """Deterministic per-text vector: identical text scores cosine 1.0."""
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


def populate(data_dir: Path) -> dict[str, str]:
    """Start a server on `data_dir` and write the scenario; return its ids
    and the raw MCP token it minted.

    The caller stubs `embed.embed` with `embed` and disables phrasing checks;
    the server stays initialized on `data_dir` afterwards.
    """
    from mycelium import server

    runtime._ctx = None
    server.init(data_dir)
    ids = _substrate(server)
    _vocabulary(server)
    ids["token"] = _auth(data_dir)
    _drafts(data_dir, ids)
    _documentation(data_dir)
    _prompts(server)
    _github(data_dir)
    return ids


def _substrate(server) -> dict[str, str]:
    login = server.upsert_entity(name="Login", description="Signing in.")["entity_id"]
    session = server.upsert_entity(
        name="Session", description="An authenticated visit."
    )["entity_id"]
    server.upsert_name(text="Sign-in", entity_id=login)
    server.add_entity_links(
        [{"from_entity_id": login, "to_entity_id": session, "link_type": "contains"}]
    )
    ids = {"login": login, "session_entity": session}
    for key, (kind, text) in STATEMENTS.items():
        ids[key] = server.upsert_statement(kind=kind, text=text, links=[])[
            "statement_id"
        ]
    server.add_links(
        [
            {
                "from_id": ids["submit"],
                "to_id": ids["session"],
                "link_type": "triggers",
                "when": {"op": "not", "of": [{"statement_id": ids["locked"]}]},
            }
        ]
    )
    server.report_knowledge_gap(text="How long does a locked account stay locked?")
    db = _connection(server)
    from mycelium import store

    file_gap = getattr(store, "create_knowledge_gap", None)
    if file_gap is not None and "draft_id" in inspect.signature(file_gap).parameters:
        file_gap(
            db,
            "Draft drf_fixture contradicted the session expiry rule.",
            draft_id="drf_fixture",
            statement_id=ids["expiry"],
        )
    name = db.execute("SELECT id FROM names WHERE text = 'Sign-in'").fetchone()
    db.execute(
        "INSERT INTO pending_mentions (statement_id, name_id, created_at, "
        "approved_at, approved_by) VALUES (?, ?, '2026-08-01', '2026-08-01', "
        "'curator')",
        (ids["submit"], name["id"]),
    )
    if _has_table(db, "mention_recompute_queue"):
        db.execute(
            "INSERT INTO mention_recompute_queue (scan_text, enqueued_at) "
            "VALUES ('sign-in', '2026-08-01T00:00:00Z')"
        )
    if _has_table(db, "reviewed_draft_applications"):
        db.execute(
            "INSERT INTO reviewed_draft_applications VALUES "
            "('app_scenario', 'drf_scenario', 'rev_scenario', "
            "'2026-08-01T00:00:00Z', '{}')"
        )
    db.commit()
    return ids


def _vocabulary(server) -> None:
    if hasattr(server, "upsert_link_type_alias"):
        server.upsert_link_type_alias(link_type="triggers", alias="sets off")


def _auth(data_dir: Path) -> str:
    from mycelium import auth, auth_store

    with closing(auth_store.connect(data_dir / "mycelium-auth.db")) as conn:
        admin = auth.create_user(
            conn, name="Ada", role="admin", type="human", email="ada@example.com"
        )
        token, _ = auth.issue_token(conn, user_id=admin, name="laptop", scope="writer")
        auth.create_invite(
            conn, email="bea@example.com", role="writer", invited_by=admin
        )
        conn.execute(
            "INSERT INTO oauth_clients (client_id, client_name, redirect_uris, "
            "created_at) VALUES ('client-1', 'Claude', '[\"http://localhost/cb\"]', "
            "'2026-08-01T00:00:00Z')"
        )
        conn.commit()
    return token


def _drafts(data_dir: Path, ids: dict[str, str]) -> None:
    from mycelium import drafts_store

    with closing(drafts_store.connect(data_dir / "mycelium-drafts.db")) as conn:
        draft = drafts_store.create_draft(
            conn, created_by="local-admin", session_id="s1", title="Lockout"
        )
        drafts_store.add_op(
            conn,
            draft_id=draft,
            kind="upsert_statement",
            payload={"kind": "state", "text": "The account is unlocked.", "links": []},
            created_by="local-admin",
        )
        if hasattr(drafts_store, "create_review"):
            review = drafts_store.create_review(
                conn,
                draft_id=draft,
                outcome="accepted",
                rationale="Consistent with existing knowledge.",
                draft_revision=1,
                preconditions=[],
                unresolved_questions=[],
                reviewed_by="reviewer",
            )
            application = drafts_store.claim_application(
                conn, draft_id=draft, review_id=review, claimed_by="reviewer"
            )
            drafts_store.finish_application(
                conn, application, status="committed", result={"applied": 1}
            )
        _review_run(conn, draft)
        conn.commit()


def _review_run(conn: sqlite3.Connection, draft: str) -> None:
    try:
        from mycelium import draft_review_store
    except ImportError:
        return
    run = draft_review_store.new(draft, "review-only", 1)
    run.status = "completed"
    run.label = "good"
    run.rationale = "Fits the graph."
    draft_review_store.save(conn, run)


def _documentation(data_dir: Path) -> None:
    try:
        from mycelium import docs_store
    except ImportError:
        return
    with closing(docs_store.connect(data_dir / "mycelium-drafts.db")) as conn:
        run = docs_store.create_run(conn, prompt="Explain sign-in", created_by="ada")
        parameters = inspect.signature(docs_store.upsert_document).parameters
        anchored = "anchor_entity_id" in parameters
        document = docs_store.upsert_document(
            conn,
            slug="sign-in",
            title="Sign-in",
            body="How to sign in.",
            run_id=run,
            **({"anchor_entity_id": "ent_sign_in"} if anchored else {}),
            **(
                {"cited_statements": {"stm_sign_in": "A user signs in."}}
                if "cited_statements" in parameters
                else {}
            ),
        )
        record = getattr(docs_store, "record_delivery", None)
        if record is None or "binding" not in inspect.signature(record).parameters:
            docs_store.finish_run(
                conn, run, outcome="document_written", document_id=document
            )
            return
        docs_store.record_delivery(
            conn,
            document,
            destination="docs",
            binding="approved",
            target=json.dumps(
                {
                    "host": "github.com",
                    "owner": "example",
                    "repo": "docs",
                    "base_branch": "main",
                }
            ),
            path="docs/sign-in.md",
            reference="https://github.com/example/docs/pull/1",
            content_revision="sha",
            revision=1,
            **({"pull_request_number": 1} if anchored else {}),
        )
        docs_store.finish_run(
            conn, run, outcome="document_written", document_id=document
        )


def _prompts(server) -> None:
    if hasattr(server, "save_prompt_text"):
        server.save_prompt_text(type="doctrine", name="ingest", text="Operator edit.")


def _github(data_dir: Path) -> None:
    try:
        from mycelium import github_connections, github_credentials, prompt_store
    except ImportError:
        return
    with closing(prompt_store.connect(data_dir / "mycelium-prompts.db")) as conn:
        github_credentials.import_binding(conn, "github.com", "DOCS_TOKEN")
        connection = github_connections.Connection(
            app_id=1, installation_id=2, repository_id=3, owner="example", repo="docs"
        )
        conn.execute(
            "INSERT INTO github_app_connections VALUES (?, ?)",
            (connection.name, connection.model_dump_json()),
        )
        conn.commit()


def _connection(server) -> sqlite3.Connection:
    return server._db() if hasattr(server, "_db") else server._conn


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )
