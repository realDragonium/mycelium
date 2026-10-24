"""The internal curation pass with injected model decisions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mycelium import (
    ai,
    auth,
    curation,
    curation_pass,
    drafts_store,
    model_settings,
    product_settings,
    server,
    store,
)
from mycelium.ingest.schema import NothingToIngest
from mycelium.server import curation as server_curation
from mycelium.server import runtime, startup
from settings_helpers import save_model


@pytest.fixture
def configured(tmp_path, monkeypatch):
    from mycelium import auth_store, embed

    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(embed, "embed", lambda text: [0.0] * 768)
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    runtime._ctx = None
    server.init(tmp_path)
    save_model("connect", claude_model="curation-test-model")

    def submit(draft_id):
        with store.transaction(runtime._drafts_db()):
            drafts_store.set_submitted(runtime._drafts_db(), draft_id)
        return True

    monkeypatch.setattr(curation_pass, "_auto_submit", submit)
    yield monkeypatch
    startup.stop_workers()
    runtime._ctx = None
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()


def _settings(**updates):
    current = product_settings.editable(
        product_settings.ConnectSettings(), runtime._prompts_db()
    )
    assert isinstance(current.settings, product_settings.ConnectSettings)
    product_settings.save(
        product_settings.SaveSettings(
            revision=current.revision,
            settings=current.settings.model_copy(update=updates),
        ),
        auth.LOCAL_ADMIN,
    )


def _fake(result: curation_pass.Decisions, calls: list[str]) -> curation_pass.Call:
    def call(task, config):
        calls.append(task.prompt)
        return result, ai.Usage()

    return call


def _submit_status(draft_id):
    row = drafts_store.get_draft(runtime._drafts_db(), draft_id)
    assert row is not None
    return drafts_store.status_for(row)


def _pair(monkeypatch, a_id, b_id, *, kind="statement"):
    item_id = "~".join(sorted((a_id, b_id)))
    text = curation.item_text(runtime._db(), "duplicate", item_id)
    assert text is not None
    if kind == "statement":
        sides = []
        for statement_id in sorted((a_id, b_id)):
            row = store.get_statement(runtime._db(), statement_id)
            assert row is not None
            sides.append({"id": statement_id, "kind": row["kind"], "text": row["text"]})
    else:
        sides = [
            {"id": entity_id, "names": [entity_id], "description": "", "statements": []}
            for entity_id in sorted((a_id, b_id))
        ]
    context = {"kind": kind, "a": sides[0], "b": sides[1], "score": 1.0}
    monkeypatch.setattr(
        server_curation,
        "duplicate_candidates",
        lambda **_kwargs: (
            [curation.DuplicateCandidate(item_id, text)],
            {item_id: context},
        ),
    )
    return item_id


def test_toggles_off_make_no_model_call(configured):
    calls = []

    curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), calls))

    assert calls == []


def test_duplicate_merge_creates_a_submitted_draft(configured):
    first = server.upsert_statement("rule", "An invoice can be exported.", [])[
        "statement_id"
    ]
    second = server.upsert_statement("rule", "Invoices can be exported.", [])[
        "statement_id"
    ]
    item_id = _pair(configured, first, second)
    _settings(decide_duplicates=True)
    calls = []

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                duplicates=[
                    curation_pass.DuplicateDecision(
                        item_id=item_id,
                        decision="duplicate",
                        keep_id=first,
                        reason="They state the same export capability.",
                    )
                ]
            ),
            calls,
        )
    )

    attempt = (
        runtime._db()
        .execute(
            "SELECT outcome, draft_id FROM curation_attempts WHERE item_id = ?",
            (item_id,),
        )
        .fetchone()
    )
    assert attempt["outcome"] == "proposed"
    assert _submit_status(attempt["draft_id"]) == "submitted"
    [operation] = drafts_store.list_ops(runtime._drafts_db(), attempt["draft_id"])
    assert operation["kind"] == "merge_statements"
    evidence_ids = {
        item["statement_id"]
        for item in drafts_store.serialize_op(operation)["evidence"]
    }
    assert evidence_ids == {first, second}
    assert calls


def test_duplicate_proposal_is_recorded_before_submission_can_apply(configured):
    first = server.upsert_statement("rule", "An invoice can be exported.", [])[
        "statement_id"
    ]
    second = server.upsert_statement("rule", "Invoices can be exported.", [])[
        "statement_id"
    ]
    item_id = _pair(configured, first, second)
    _settings(decide_duplicates=True)

    def submit_and_apply(draft_id):
        attempt = (
            runtime._db()
            .execute(
                "SELECT outcome FROM curation_attempts WHERE item_id = ? "
                "AND draft_id = ?",
                (item_id, draft_id),
            )
            .fetchone()
        )
        assert attempt is not None
        assert attempt["outcome"] == "proposed"
        with store.transaction(runtime._drafts_db()):
            drafts_store.set_submitted(runtime._drafts_db(), draft_id)
        server.apply_draft(draft_id)
        return True

    configured.setattr(curation_pass, "_auto_submit", submit_and_apply)
    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                duplicates=[
                    curation_pass.DuplicateDecision(
                        item_id=item_id,
                        decision="duplicate",
                        keep_id=first,
                        reason="They state the same export capability.",
                    )
                ]
            ),
            [],
        )
    )

    assert store.get_statement(runtime._db(), second) is None
    attempt = (
        runtime._db()
        .execute("SELECT outcome FROM curation_attempts WHERE item_id = ?", (item_id,))
        .fetchone()
    )
    assert attempt["outcome"] == "proposed"


def test_overlapping_duplicate_disappearing_does_not_abort_batch(configured):
    ids = [
        server.upsert_statement("rule", text, [])["statement_id"]
        for text in (
            "An invoice can be exported.",
            "Invoices can be exported.",
            "An invoice export is available.",
        )
    ]
    pairs = []
    contexts = {}
    decisions = []
    for outer_id in (ids[0], ids[2]):
        item_id = "~".join(sorted((outer_id, ids[1])))
        text = curation.item_text(runtime._db(), "duplicate", item_id)
        assert text is not None
        pair = curation.DuplicateCandidate(item_id, text)
        pairs.append(pair)
        sides = []
        for statement_id in item_id.split("~"):
            row = store.get_statement(runtime._db(), statement_id)
            assert row is not None
            sides.append({"id": statement_id, "kind": row["kind"], "text": row["text"]})
        contexts[item_id] = {
            "kind": "statement",
            "a": sides[0],
            "b": sides[1],
            "score": 1.0,
        }
        decisions.append(
            curation_pass.DuplicateDecision(
                item_id=item_id,
                decision="duplicate",
                keep_id=outer_id,
                reason="They state the same export capability.",
            )
        )
    configured.setattr(
        server_curation,
        "duplicate_candidates",
        lambda **_kwargs: (pairs, contexts),
    )

    def submit_and_apply(draft_id):
        with store.transaction(runtime._drafts_db()):
            drafts_store.set_submitted(runtime._drafts_db(), draft_id)
        server.apply_draft(draft_id)
        return True

    configured.setattr(curation_pass, "_auto_submit", submit_and_apply)
    _settings(decide_duplicates=True)

    curation_pass.curation_pass(
        call=_fake(curation_pass.Decisions(duplicates=decisions), [])
    )

    attempts = (
        runtime._db()
        .execute(
            "SELECT item_id, outcome FROM curation_attempts WHERE item_id IN (?, ?)",
            [pair.id for pair in pairs],
        )
        .fetchall()
    )
    assert [(row["item_id"], row["outcome"]) for row in attempts] in (
        [(pairs[0].id, "proposed")],
        [(pairs[1].id, "proposed")],
    )
    claims = (
        runtime._db()
        .execute(
            "SELECT item_id FROM curation_claims WHERE item_id IN (?, ?)",
            [pair.id for pair in pairs],
        )
        .fetchall()
    )
    assert claims == []


def test_duplicate_discovery_pages_past_settled_candidates(configured):
    conn = runtime._db()
    rows = [
        (
            f"stm_page_{index:03d}",
            "rule",
            f"Invoice export rule {index}.",
            "2026-08-01T00:00:00.000Z",
        )
        for index in range(202)
    ]
    conn.executemany(
        "INSERT INTO statements (id, kind, text, created_at) VALUES (?, ?, ?, ?)",
        rows,
    )
    raw = [
        {
            "a_id": rows[0][0],
            "a_text": rows[0][2],
            "b_id": rows[index][0],
            "b_text": rows[index][2],
            "score": 1.0 - index / 10_000,
        }
        for index in range(1, 202)
    ]
    first_page = [
        curation.DuplicateCandidate(
            "~".join(sorted((str(item["a_id"]), str(item["b_id"])))),
            curation.item_text(
                conn,
                "duplicate",
                "~".join(sorted((str(item["a_id"]), str(item["b_id"])))),
            )
            or "",
        )
        for item in raw[:200]
    ]
    with store.transaction(conn):
        claimed, _, _ = curation.claim(
            conn,
            runtime._drafts_db(),
            "duplicate",
            limit=200,
            claimant="agent:test",
            now=datetime.now(UTC),
            pairs=first_page,
        )
        curation.release(
            conn,
            [item.id for item in claimed],
            "not_applicable",
            claimant="agent:test",
            now=datetime.now(UTC),
            reason="These statements describe separate rules.",
        )

    configured.setattr(
        server_curation,
        "find_duplicates",
        lambda threshold=None, limit=50: raw[:limit],
    )
    configured.setattr(
        server_curation,
        "find_entity_duplicates",
        lambda threshold=None, limit=50, offset=0: {"candidates": [], "total": 0},
    )

    candidates, _ = server_curation.duplicate_candidates(limit=1)

    assert [candidate.id for candidate in candidates] == ["stm_page_000~stm_page_201"]


def test_distinct_concepts_record_a_model_dismissal(configured):
    a = server.upsert_entity("Login page", "The login screen.")["entity_id"]
    b = server.upsert_entity("Single sign-on", "An authentication protocol.")[
        "entity_id"
    ]
    item_id = _pair(configured, a, b, kind="concept")
    _settings(decide_duplicates=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                duplicates=[
                    curation_pass.DuplicateDecision(
                        item_id=item_id,
                        decision="distinct",
                        reason="A page is not an authentication protocol.",
                    )
                ]
            ),
            [],
        )
    )

    [dismissal] = store.list_entity_duplicate_dismissals(runtime._db())
    assert dismissal["dismissed_by"] == "model:curation-test-model"


def test_description_is_grounded_and_carries_statement_evidence(configured):
    entity_id = server.upsert_entity("Invoice export", "")["entity_id"]
    statement_id = server.upsert_statement(
        "rule", "An invoice export includes paid invoices.", []
    )["statement_id"]
    _settings(describe_concepts=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                descriptions=[
                    curation_pass.DescriptionDecision(
                        item_id=entity_id,
                        decision="describe",
                        description="A downloadable collection of invoice records.",
                        statement_ids=[statement_id],
                        reason="The statement identifies its contents.",
                    )
                ]
            ),
            [],
        )
    )

    attempt = (
        runtime._db()
        .execute(
            "SELECT draft_id FROM curation_attempts WHERE item_id = ?", (entity_id,)
        )
        .fetchone()
    )
    [operation] = drafts_store.list_ops(runtime._drafts_db(), attempt["draft_id"])
    assert operation["kind"] == "upsert_entity"
    [evidence] = drafts_store.serialize_op(operation)["evidence"]
    assert evidence["statement_id"] == statement_id


def test_ungrounded_description_is_skipped_and_not_retried(configured):
    entity_id = server.upsert_entity("Invoice export", "")["entity_id"]
    server.upsert_statement("rule", "An invoice export includes paid invoices.", [])
    _settings(describe_concepts=True)
    calls = []
    fake = _fake(
        curation_pass.Decisions(
            descriptions=[
                curation_pass.DescriptionDecision(
                    item_id=entity_id,
                    decision="describe",
                    description="A downloadable file.",
                    statement_ids=["stm_not_supplied"],
                    reason="Assumed.",
                )
            ]
        ),
        calls,
    )

    curation_pass.curation_pass(call=fake)
    curation_pass.curation_pass(call=fake)

    assert len(calls) == 1
    assert (
        runtime._db()
        .execute(
            "SELECT outcome FROM curation_attempts WHERE item_id = ?", (entity_id,)
        )
        .fetchone()[0]
        == "skipped"
    )


def test_rephrase_and_keep_decisions(configured):
    first = server.upsert_statement("rule", "Invoice Settings accepts due date.", [])[
        "statement_id"
    ]
    second = server.upsert_statement("rule", "Exports are retained.", [])[
        "statement_id"
    ]
    first_gap = store.create_knowledge_gap(
        runtime._db(),
        "Rephrase this statement before it is connected: say what accepts the due date",
        statement_id=first,
    )
    second_gap = store.create_knowledge_gap(
        runtime._db(),
        "Rephrase this statement before it is connected: wording is vague",
        statement_id=second,
    )
    runtime._db().commit()
    _settings(act_on_gaps=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                rephrases=[
                    curation_pass.RephraseDecision(
                        item_id=first_gap,
                        decision="rephrase",
                        text="Invoice settings accept a due date.",
                        reason="Names the subject clearly.",
                    ),
                    curation_pass.RephraseDecision(
                        item_id=second_gap,
                        decision="keep",
                        reason="The current wording is already precise.",
                    ),
                ]
            ),
            [],
        )
    )

    first_attempt = (
        runtime._db()
        .execute(
            "SELECT outcome, draft_id FROM curation_attempts WHERE item_id = ?",
            (first_gap,),
        )
        .fetchone()
    )
    assert first_attempt["outcome"] == "proposed"
    assert (
        drafts_store.list_ops(runtime._drafts_db(), first_attempt["draft_id"])[0][
            "kind"
        ]
        == "patch_statement"
    )
    assert (
        store.get_knowledge_gap(runtime._db(), second_gap)["dismissed_by"]
        == "model:curation-test-model"
    )


def _decided_draft(decision):
    draft_id = drafts_store.create_draft(
        runtime._drafts_db(),
        created_by=None,
        session_id=None,
        title="Original proposal",
    )
    drafts_store.add_op(
        runtime._drafts_db(),
        draft_id=draft_id,
        kind="patch_statement",
        payload={"id": "stm_missing", "text": "Corrected."},
        created_by=None,
    )
    drafts_store.set_decision(
        runtime._drafts_db(), draft_id, decision=decision, by="reviewer"
    )
    runtime._drafts_db().commit()
    return draft_id


def test_rejected_draft_gap_proposes_validated_operations(configured):
    draft_id = _decided_draft("rejected")
    gap_id = store.create_knowledge_gap(
        runtime._db(),
        "The draft contradicted current invoice behavior.",
        draft_id=draft_id,
    )
    runtime._db().commit()
    _settings(act_on_gaps=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                gaps=[
                    curation_pass.GapDecision(
                        item_id=gap_id,
                        decision="propose",
                        reason="Replace the rejected wording.",
                        operations=[
                            curation_pass.ProposedOperation(
                                tool="upsert_statement",
                                arguments_json='{"kind":"rule","text":"Invoice exports include paid invoices.","links":[]}',
                            )
                        ],
                    )
                ]
            ),
            [],
        )
    )

    attempt = (
        runtime._db()
        .execute(
            "SELECT outcome, draft_id FROM curation_attempts WHERE item_id = ?",
            (gap_id,),
        )
        .fetchone()
    )
    assert attempt["outcome"] == "proposed"
    assert (
        drafts_store.list_ops(runtime._drafts_db(), attempt["draft_id"])[0]["kind"]
        == "upsert_statement"
    )
    assert (
        store.get_knowledge_gap(runtime._db(), gap_id)["draft_id"]
        == attempt["draft_id"]
    )


def test_invalid_gap_tool_is_skipped(configured):
    draft_id = _decided_draft("rejected")
    gap_id = store.create_knowledge_gap(
        runtime._db(), "The rejected draft needs another approach.", draft_id=draft_id
    )
    runtime._db().commit()
    _settings(act_on_gaps=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                gaps=[
                    curation_pass.GapDecision(
                        item_id=gap_id,
                        decision="propose",
                        reason="Apply it directly.",
                        operations=[
                            curation_pass.ProposedOperation(
                                tool="approve_draft", arguments_json="{}"
                            )
                        ],
                    )
                ]
            ),
            [],
        )
    )

    assert (
        runtime._db()
        .execute("SELECT outcome FROM curation_attempts WHERE item_id = ?", (gap_id,))
        .fetchone()[0]
        == "skipped"
    )


def test_close_resolves_a_gap_about_an_applied_draft(configured):
    draft_id = _decided_draft("approved")
    gap_id = store.create_knowledge_gap(
        runtime._db(), "The applied draft resolved the conflict.", draft_id=draft_id
    )
    runtime._db().commit()
    _settings(act_on_gaps=True)

    curation_pass.curation_pass(
        call=_fake(
            curation_pass.Decisions(
                gaps=[
                    curation_pass.GapDecision(
                        item_id=gap_id,
                        decision="close",
                        reason="The applied draft settled it.",
                    )
                ]
            ),
            [],
        )
    )

    gap = store.get_knowledge_gap(runtime._db(), gap_id)
    assert (gap["resolved_by"], gap["draft_id"]) == (
        "model:curation-test-model",
        draft_id,
    )


def test_automatic_connect_reuses_the_connect_loop(configured):
    statement_id = server.upsert_statement(
        "rule", "An invoice export includes paid invoices.", []
    )["statement_id"]
    _settings(connect_automatically=True)
    reached = []
    result = NothingToIngest(
        reason="No link was needed.",
        trace={
            "candidate_ledger": [{"candidate": statement_id, "classification": "new"}]
        },
    )
    configured.setattr(
        curation_pass,
        "run_connect",
        lambda targets, **kwargs: (
            reached.append([item.id for item in targets]) or result
        ),
    )
    configured.setattr(
        curation_pass.model_loops,
        "connected",
        lambda actual, targets: reached.append(actual),
    )

    curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), []))

    assert reached == [[statement_id], result]


def test_automatic_connect_stops_after_failures_and_an_edit_retries(configured):
    statement_id = server.upsert_statement(
        "rule", "An invoice export includes paid invoices.", []
    )["statement_id"]
    _settings(connect_automatically=True, connect_retries=1)
    calls = 0

    def fail_connect(targets, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    configured.setattr(curation_pass, "run_connect", fail_connect)

    for _ in range(3):
        curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), []))

    assert calls == 2
    [stopped] = curation_pass.automation_stops.stops(runtime._db())
    assert (stopped.item_id, stopped.failures) == (statement_id, 2)

    store.update_statement_text(
        runtime._db(),
        statement_id,
        "Invoice exports include paid invoices and receipts.",
    )
    runtime._db().commit()
    curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), []))
    assert calls == 3


def test_automatic_connect_stops_a_target_the_run_did_not_inspect(configured):
    statement_id = server.upsert_statement(
        "rule", "Workspace exports include invoices.", []
    )["statement_id"]
    _settings(connect_automatically=True, connect_retries=0)
    configured.setattr(
        curation_pass,
        "run_connect",
        lambda targets, **kwargs: NothingToIngest(
            reason="The run ended before classification.", trace={}
        ),
    )

    curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), []))

    [stopped] = curation_pass.automation_stops.stops(runtime._db())
    assert stopped.item_id == statement_id
    assert stopped.reason == (
        "The connect run ended (nothing_to_ingest) without looking at it."
    )


def test_external_connect_does_nothing(configured):
    current = model_settings.get("connect")
    model_settings.save(
        "connect",
        model_settings.SaveSelection(
            provider=current.provider,
            claude_model=current.claude_model,
            openai_model=current.openai_model,
            external_agent=True,
            revision=current.revision,
        ),
        auth.LOCAL_ADMIN,
    )
    _settings(decide_duplicates=True)
    calls = []

    curation_pass.curation_pass(call=_fake(curation_pass.Decisions(), calls))

    assert calls == []
