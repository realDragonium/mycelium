"""Large drafts are reviewed in connected parts; stale drafts and drafts over
the token cap are refused without a model call; the backlog review runs
oldest first and stops on request or at its budget."""

import json

import pytest

from mycelium import (
    ai,
    ai_usage,
    auth,
    draft_review_runs,
    drafts_store,
    product_settings,
    server,
    store,
)
from product_settings_helpers import set_product
from review_helpers import correction
from settings_helpers import save_model
from settings_helpers import set_review_controls as _set_review_controls
from test_internal_draft_review import (
    _assessment,
    _automatic,
    _result,
    _supporting_statement,
    running_app,  # noqa: F401  (fixture)
)
from test_reviewed_application import _principal

pytestmark = pytest.mark.usefixtures("running_app")


def _submitted(*ops, created_at=None):
    """A drafter's submitted draft holding `ops`, (kind, payload) pairs whose
    payloads may name an earlier operation's result as "@{n}" for the n-th
    operation (1-based)."""
    token = _principal("drafter")
    try:
        first_kind, first_payload = ops[0]
        draft_id = getattr(server, first_kind)(**first_payload)["draft_id"]
        conn = server._drafts_db()
        seqs = [server.get_draft(draft_id)["ops"][0]["seq"]]
        with store.transaction(conn):
            for kind, payload in ops[1:]:
                text = json.dumps(payload)
                for index, seq in enumerate(seqs, start=1):
                    text = text.replace(f'"@{index}:', f'"@{seq}:')
                seqs.append(
                    drafts_store.add_op(
                        conn,
                        draft_id=draft_id,
                        kind=kind,
                        payload=json.loads(text),
                        created_by="drafter-1",
                    )
                )
            if created_at:
                conn.execute(
                    "UPDATE drafts SET created_at = ? WHERE id = ?",
                    (created_at, draft_id),
                )
                conn.execute(
                    "UPDATE draft_ops SET created_at = ? WHERE draft_id = ?",
                    (created_at, draft_id),
                )
        server.submit_draft(draft_id)
        return draft_id
    finally:
        auth.current_principal.reset(token)


def _entity(name):
    return "upsert_entity", {"name": name, "description": f"The {name.lower()}."}


def _statement(text):
    return (
        "upsert_statement",
        {"kind": "state", "text": text, "links": [], "allow_phrasing_violations": True},
    )


@pytest.fixture
def small_parts(monkeypatch):
    """Every connected group of operations is its own part."""
    monkeypatch.setattr(draft_review_runs, "_PART_BASE_LIMIT", 1)


def _recording(monkeypatch, decide=lambda context: _assessment()):
    contexts = []

    def model(context):
        contexts.append(json.loads(context))
        return decide(contexts[-1])

    monkeypatch.setattr(draft_review_runs, "RUNNER", model)
    return contexts


def _refs(context):
    return {op["operation_ref"] for op in context["draft"]["ops"]}


def test_connected_operations_are_reviewed_together(monkeypatch, small_parts):
    contexts = _recording(monkeypatch)
    _set_review_controls(mode="review-only")
    batch = {
        "statements": [
            {
                "kind": "state",
                "text": text,
                "links": [],
                "allow_phrasing_violations": True,
            }
            for text in (
                "An invoice is issued monthly.",
                "An invoice lists its line items.",
            )
        ]
    }
    draft_id = _submitted(
        ("upsert_statements", batch),
        (
            "add_links",
            {"links": [{"from_id": "@1:0", "to_id": "@1:1", "link_type": "requires"}]},
        ),
        _entity("Workspace"),
        _statement("A Workspace has members."),
    )
    result = _result(draft_id)

    ops = [op["operation_ref"] for op in server.get_draft(draft_id)["ops"]]
    assert [_refs(context) for context in contexts] == [
        set(ops[:2]),
        set(ops[2:]),
    ]
    assert [context["review_part"]["part"] for context in contexts] == [1, 2]
    others = json.dumps(contexts[0]["review_part"]["other_parts"])
    assert "A Workspace has members." in others
    assert [part["operation_refs"] for part in result["parts"]] == [
        ops[:2],
        ops[2:],
    ]


@pytest.mark.parametrize(
    ("reference", "problem"),
    [("@0", "outside a batch"), ("@{seq}:1", "names no statement"), ("@{seq}:0", None)],
)
def test_a_correction_must_name_draft_statements_the_way_they_resolve(
    monkeypatch, reference, problem
):
    live = _supporting_statement()

    def decide(context):
        seq = context["draft"]["ops"][0]["seq"]
        link = {
            "from_id": live,
            "to_id": reference.format(seq=seq),
            "link_type": "requires",
        }
        fix = correction(
            action="append",
            operation_ref=None,
            tool_name="add_links",
            payload_json=json.dumps({"links": [link]}),
            reason="Connect the new statement.",
        )
        return _assessment("changes_suggested", [fix])

    _recording(monkeypatch, decide)
    _automatic()
    draft_id = _submitted(
        (
            "upsert_statements",
            {"statements": [{"kind": "state", "text": "An invoice is issued."}]},
        )
    )
    result = _result(draft_id)
    if problem is None:
        assert result["application"] == "applied"
    else:
        assert result["status"] == "failed"
        assert problem in result["detail"]


def test_a_small_draft_is_reviewed_whole(monkeypatch):
    contexts = _recording(monkeypatch)
    _set_review_controls(mode="review-only")
    draft_id = _submitted(_entity("Workspace"), _entity("Invoice"))

    result = _result(draft_id)

    [context] = contexts
    assert "review_part" not in context
    assert result["parts"] == []


@pytest.mark.parametrize(
    ("invoice_label", "application", "status"),
    [
        ("good", "applied", "approved"),
        ("reject", "rejected", "rejected"),
        ("needs_context", "needs_human", "submitted"),
    ],
)
def test_the_draft_applies_only_if_every_part_accepts(
    monkeypatch, small_parts, invoice_label, application, status
):
    def decide(context):
        names = json.dumps(context["draft"]["ops"])
        return _assessment(invoice_label if "Invoice" in names else "good")

    _recording(monkeypatch, decide)
    _automatic()
    draft_id = _submitted(_entity("Workspace"), _entity("Invoice"))

    result = _result(draft_id)

    assert result["application"] == application
    assert server.get_draft(draft_id)["status"] == status
    assert [part["label"] for part in result["parts"]] == ["good", invoice_label]
    names = {item["name"] for item in server.list_entities()["entities"]}
    assert ("Workspace" in names) == (application == "applied")
    if invoice_label != "good":
        assert result["label"] == invoice_label
        assert result["rationale"].startswith("Part 2 of 2")
        assert "Part 1" not in result["rationale"]
    if invoice_label == "needs_context":
        assert result["questions"] == _assessment("needs_context").questions


def test_each_part_corrects_its_own_operations_and_they_apply_together(
    monkeypatch, small_parts
):
    def decide(context):
        [op] = context["draft"]["ops"]
        return _assessment(
            "changes_suggested",
            [
                correction(
                    action="edit",
                    operation_ref=op["operation_ref"],
                    description=op["payload"]["name"] + " (fixed)",
                    reason="Clearer description.",
                )
            ],
        )

    _recording(monkeypatch, decide)
    _automatic()
    draft_id = _submitted(_entity("Workspace"), _entity("Invoice"))

    result = _result(draft_id)

    assert result["application"] == "applied", result
    assert len(result["corrections"]) == 2
    descriptions = {item["description"] for item in server.list_entities()["entities"]}
    assert descriptions == {"Workspace (fixed)", "Invoice (fixed)"}


def test_a_part_cannot_correct_another_parts_operation(monkeypatch, small_parts):
    draft_ops = []

    def decide(context):
        if len(draft_ops) == 0:
            draft_ops.append(context)
            return _assessment()
        other = context["review_part"]["other_parts"][0]["operation_ref"]
        return _assessment(
            "changes_suggested",
            [
                correction(
                    action="strike",
                    operation_ref=other,
                    tool_name=None,
                    payload_json=None,
                    reason="Out of scope.",
                )
            ],
        )

    _recording(monkeypatch, decide)
    _set_review_controls(mode="review-only")
    draft_id = _submitted(_entity("Workspace"), _entity("Invoice"))

    result = _result(draft_id)

    assert result["status"] == "failed"
    assert "operation of another part" in result["detail"]


def test_a_draft_over_the_token_cap_is_refused_without_a_model_call(monkeypatch):
    contexts = _recording(monkeypatch)
    save_model("draft_review", openai_model="gpt-5.4")
    set_product(product_settings.ReviewSettings(max_draft_tokens=100))
    _automatic()
    draft_id = _submitted(_entity("Workspace"))

    result = _result(draft_id)

    assert contexts == []
    assert result["application"] == "rejected"
    assert "could use up to" in result["rationale"]


def _replace(statement_id, text):
    return (
        "replace_text",
        {"id": statement_id, "text": text, "allow_phrasing_violations": True},
    )


def _old_statement():
    """A live statement written before any test draft."""
    statement_id = _supporting_statement()
    with store.transaction(server._db()):
        server._db().execute(
            "UPDATE statements SET created_at = ?, updated_at = ? WHERE id = ?",
            ("1999-01-01T00:00:00.000Z", "1999-01-01T00:00:00.000Z", statement_id),
        )
    return statement_id


def _text(statement_id):
    return server.get_statements([statement_id])["statements"][0]["text"]


def test_a_draft_written_before_a_direct_edit_is_refused(monkeypatch):
    contexts = _recording(monkeypatch)
    statement_id = _old_statement()
    draft_id = _submitted(
        _replace(statement_id, "A supporting feature is retired."),
        created_at="2000-01-01T00:00:00.000Z",
    )
    token = _principal()
    try:
        server.replace_text(
            statement_id,
            "A supporting feature is in beta.",
            allow_phrasing_violations=True,
        )
    finally:
        auth.current_principal.reset(token)
    _automatic()
    draft_review_runs.start(draft_id)

    result = _result(draft_id)

    assert contexts == []
    assert result["application"] == "rejected"
    assert "newer knowledge" in result["rationale"]
    assert _text(statement_id) == "A supporting feature is in beta."


@pytest.mark.parametrize("applied_first", ["older", "newer"])
def test_only_the_newer_of_two_drafts_lands_whatever_the_order(
    monkeypatch, applied_first
):
    _recording(monkeypatch)
    statement_id = _old_statement()
    older = _submitted(
        _replace(statement_id, "A supporting feature is retired."),
        created_at="2000-01-01T00:00:00.000Z",
    )
    newer = _submitted(
        _replace(statement_id, "A supporting feature is in beta."),
        created_at="2000-01-02T00:00:00.000Z",
    )
    _automatic()
    first, second = (older, newer) if applied_first == "older" else (newer, older)

    draft_review_runs.start(first)
    _result(first)
    draft_review_runs.start(second)
    _result(second)

    assert server.get_draft(newer)["status"] == "approved"
    assert server.get_draft(older)["status"] == (
        "approved" if applied_first == "older" else "rejected"
    )
    assert _text(statement_id) == "A supporting feature is in beta."


def _waiting(*names):
    """Drafts submitted while review was off, oldest first."""
    _set_review_controls(mode="off")
    return [
        _submitted(_entity(name), created_at=f"2000-01-0{day}T00:00:00.000Z")
        for day, name in enumerate(names, start=1)
    ]


def test_the_backlog_is_reviewed_oldest_first_and_pauses_on_request(monkeypatch):
    reviewed = []

    def decide(context):
        reviewed.append(context["draft"]["id"])
        if len(reviewed) == 1:
            draft_review_runs.pause_backlog()
        return _assessment()

    _recording(monkeypatch, decide)
    drafts = _waiting("Workspace", "Invoice", "Export")
    _automatic()

    draft_review_runs.review_backlog()
    draft_review_runs.wait_backlog()
    paused = draft_review_runs.backlog_job()
    draft_review_runs.resume_backlog()
    draft_review_runs.wait_backlog()

    assert paused is not None
    assert (paused.status, paused.reviewed, paused.remaining) == ("paused", 1, 3)
    assert "administrator" in (paused.detail or "")
    assert reviewed == drafts
    finished = draft_review_runs.backlog_job()
    assert finished is not None
    assert (finished.status, finished.reviewed) == ("finished", 3)


def test_the_backlog_review_stops_at_its_budget(monkeypatch):
    def decide(context):
        with store.transaction(drafts_store.connection()):
            ai_usage.record(
                drafts_store.connection(),
                ai.usage.Call(
                    action="draft_review",
                    provider="openai",
                    model="gpt-fixture",
                    usage=ai.Usage(input_tokens=1000),
                    duration_ms=1,
                    ok=True,
                    run_id="drv_fixture",
                    draft_id=context["draft"]["id"],
                ),
            )
        return _assessment()

    _recording(monkeypatch, decide)
    oldest, *rest = _waiting("Workspace", "Invoice", "Export")
    _automatic()

    draft_review_runs.review_backlog(budget_tokens=1500)
    draft_review_runs.wait_backlog()

    job = draft_review_runs.backlog_job()
    assert job is not None
    assert (job.status, job.reviewed, job.used_tokens) == ("paused", 1, 1000)
    assert "backlog budget" in (job.detail or "")
    assert server.get_draft(oldest)["status"] == "approved"
    assert [server.get_draft(item)["status"] for item in rest] == ["submitted"] * 2
