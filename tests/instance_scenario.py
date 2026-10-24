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
    _prompts(data_dir)
    _github(data_dir)
    _media(ids)
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
    if _has_table(db, "entity_duplicate_dismissals"):
        db.execute(
            "INSERT INTO entity_duplicate_dismissals VALUES (?, ?, '2026-08-01', NULL)",
            sorted((login, session)),
        )
    if _has_table(db, "statement_audience_labels"):
        db.execute(
            "INSERT INTO statement_audience_labels (statement_id, audiences, source, "
            "reason, model, cost_usd, labelled_at, labelled_by) "
            "VALUES (?, '[\"external-technical\"]', "
            "'curator', 'Integrators configure this.', NULL, NULL, "
            "'2026-08-01T00:00:00Z', 'curator')",
            (ids["expiry"],),
        )
        labels = {
            row[1] for row in db.execute("PRAGMA table_info(statement_audience_labels)")
        }
        if "text_changed_at" in labels:
            db.execute(
                "UPDATE statement_audience_labels SET text_changed_at = "
                "'2026-08-02T00:00:00Z' WHERE statement_id = ?",
                (ids["expiry"],),
            )
        if "pending" in labels:
            db.execute(
                "INSERT INTO statement_audience_labels (statement_id, audiences, "
                "source, reason, model, cost_usd, labelled_at, labelled_by, pending, "
                'decisions) VALUES (?, \'["internal-technical", '
                "\"external-technical\"]', 'ai', 'Users see this.', 'scenario-model', "
                "0.0001, '2026-08-01T00:00:00Z', NULL, "
                '\'["external-non-technical"]\', \'{"external-technical": '
                '{"at": "2026-08-02T00:00:00Z", "by": "curator", '
                '"decision": "confirmed"}}\')',
                (ids["submit"],),
            )
        if "narrowed" in labels:
            db.execute(
                "UPDATE statement_audience_labels SET narrowed = ? "
                "WHERE statement_id = ?",
                (
                    '{"previous": ["external-non-technical"], '
                    '"lost": ["external-non-technical"], '
                    '"reason": "The new text names an internal service."}',
                    ids["submit"],
                ),
            )
        if "kept_on_edit" in labels:
            db.execute(
                "UPDATE statement_audience_labels SET kept_on_edit = ? "
                "WHERE statement_id = ?",
                (
                    '{"audiences": ["external-technical"], '
                    '"old_text": "A user submits the sign-in form.", '
                    '"at": "2026-08-03T00:00:00Z"}',
                    ids["submit"],
                ),
            )
        queue = {
            row[1] for row in db.execute("PRAGMA table_info(audience_label_queue)")
        }
        if "previous" in queue:
            db.execute(
                "INSERT INTO audience_label_queue (statement_id, enqueued_at, "
                "previous) VALUES (?, '2026-08-03T00:00:00Z', ?) "
                "ON CONFLICT (statement_id) DO UPDATE SET previous = excluded.previous",
                (
                    ids["locked"],
                    '{"text": "The account is disabled.", '
                    '"audiences": ["external-non-technical"], '
                    '"reason": "Users see this.", '
                    '"confirmed": {"external-non-technical": {"decision": '
                    '"confirmed", "by": "curator", "at": "2026-08-02T00:00:00Z"}}, '
                    '"confirmed_text": "The account is disabled."}',
                ),
            )
    if _has_table(db, "curation_attempts"):
        db.execute(
            "INSERT INTO curation_attempts SELECT id, text, ?, "
            "'2026-08-01T00:00:00Z', 'scenario-agent', 'no_link', "
            "'Nothing in the code relates it.', NULL FROM statements WHERE id = ?",
            (f'["{ids["expiry"]}"]', ids["submit"]),
        )
    elif _has_table(db, "connect_attempts"):
        db.execute(
            "INSERT INTO connect_attempts SELECT id, text, ?, '2026-08-01T00:00:00Z' "
            "FROM statements WHERE id = ?",
            (f'["{ids["expiry"]}"]', ids["submit"]),
        )
    if _has_table(db, "automation_stops"):
        db.execute(
            "INSERT INTO automation_stops VALUES "
            "('connect', ?, 'A user submits the Login form.', 3, 1, "
            "'The connect run did not inspect the statement.', "
            "'2026-08-03T00:00:00Z')",
            (ids["submit"],),
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
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        if "oauth_refresh_tokens" in tables:
            _, grant = auth.issue_token(
                conn, user_id=admin, name="OAuth: Claude", scope="admin"
            )
            conn.execute(
                "UPDATE mcp_tokens SET client_id = 'client-1', "
                "expires_at = '2026-08-01T01:00:00+00:00' WHERE id = ?",
                (grant,),
            )
            conn.execute(
                "INSERT INTO oauth_refresh_tokens (hash, token_id, created_at, "
                "expires_at) VALUES (?, ?, '2026-08-01T00:00:00+00:00', "
                "'2026-08-31T00:00:00+00:00')",
                (auth.hash_token("mycr_scenario"), grant),
            )
        if "audience_id" in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:
            _, scoped = auth.issue_token(
                conn, user_id=admin, name="external", scope="reader"
            )
            conn.execute(
                "UPDATE mcp_tokens SET audience_id = 'external-technical' WHERE id = ?",
                (scoped,),
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
        _ai_usage(conn, draft)
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


def _ai_usage(conn: sqlite3.Connection, draft: str) -> None:
    try:
        from mycelium import ai_usage
        from mycelium.ai import Usage, usage
    except ImportError:
        return
    ai_usage.record(
        conn,
        usage.Call(
            action="draft_review",
            provider="claude",
            model="claude-sonnet-5-5",
            usage=Usage(input_tokens=1200, output_tokens=300),
            duration_ms=4100,
            ok=True,
            run_id=None,
            draft_id=draft,
        ),
    )


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
        _documentation_plans(conn, run)
        _document_maintenance(conn, document, run)
        _agent_tasks(conn, run)


def _agent_tasks(conn, run: str) -> None:
    try:
        from mycelium import agent_tasks
    except ImportError:
        return
    agent_tasks.create(
        conn,
        "documentation",
        subject_id=run,
        state={"reader": "ada"},
        brief={"instructions": "Write the page.", "input": "Sign-in"},
    )


def _document_maintenance(conn, document: str, run: str) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'document_maintenance'"
    ).fetchone():
        return
    with conn:
        conn.execute(
            "INSERT INTO document_maintenance (document_id, revision, guideline_set, "
            "changes, changed_at, action, acted_at, run_id, delivery) "
            "VALUES (?, 1, 'kb-authoring', '[]', '2026-01-01T00:00:00.000Z', "
            "'auto-revise', '2026-01-01T00:30:00.000Z', ?, 'published')",
            (document, run),
        )


def _documentation_plans(conn, run: str) -> None:
    try:
        from mycelium import doc_plans
    except ImportError:
        return
    plan = doc_plans.create_plan(
        conn,
        guideline_set="kb-authoring",
        audience_id="external-technical",
        created_by="ada",
        provider="claude",
        model="claude-sonnet-4-6",
    )
    item = doc_plans.Item(
        key="create:how-to:title:reset-a-password",
        action="create",
        title="Reset a password",
        document_type="how-to",
        anchor_entity_id=None,
        document_id=None,
        rationale="Users forget passwords.",
        priority="high",
        statement_ids=("stm_sign_in",),
    )
    doc_plans.finish_plan(conn, plan, items=[item], summary={"cost_usd": 0.01})
    [row] = doc_plans.items(conn, plan)
    doc_plans.claim(conn, str(row["id"]), "ada")
    doc_plans.record_run(conn, str(row["id"]), run)
    doc_plans.dismiss(conn, "kb-authoring", "create:reference:title:sso", "SSO", "ada")
    if "automatic" in inspect.signature(doc_plans.create_plan).parameters:
        automatic = doc_plans.create_plan(
            conn,
            guideline_set="kb-authoring",
            audience_id="external-technical",
            created_by=None,
            provider="claude",
            model="claude-sonnet-4-6",
            automatic=True,
        )
        doc_plans.finish_plan(
            conn, automatic, summary={"uncovered": ["stm_sign_in"], "proposed": 0}
        )
        doc_plans.dismiss(conn, "kb-authoring", "statement:stm_sso", "stm_sso", "ada")


def _prompts(data_dir: Path) -> None:
    try:
        from mycelium import prompt_store
    except ImportError:
        return
    with closing(prompt_store.connect(data_dir / "mycelium-prompts.db")) as conn:
        prompt_store.save(conn, type="doctrine", name="ingest", text="Operator edit.")


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


def _media(ids: dict[str, str]) -> None:
    try:
        from mycelium import media
    except ImportError:
        return
    import media_samples

    item = media.create(
        media_samples.png(),
        media.Details(alt_text="The sign-in form", caption="Signing in"),
        origin="uploaded",
        actor="curator",
        attach=[("statement", ids["submit"])],
    )
    media.set_label(item.id, ["external-technical"], curator="curator")
