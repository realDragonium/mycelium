"""Second-agent review of pending external audience grants."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

import pytest

from mycelium import (
    agent_tasks,
    ai,
    audience_labelling,
    audience_review,
    audiences,
    auth,
    drafts_store,
    product_settings,
    store,
)
from mycelium.server import agent_tasks as agent_task_server
from product_settings_helpers import connection as product_connection
from product_settings_helpers import set_product
from settings_helpers import assume_configured_models


@pytest.fixture(autouse=True)
def _configured_models(monkeypatch):
    assume_configured_models(monkeypatch)
    audience_review._failed_attempts.clear()


@pytest.fixture
def prompts():
    conn = product_connection()
    audiences.seed(conn)
    return conn


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    store.use_substrate_connection(conn)
    try:
        yield conn
    finally:
        store.reset_substrate()
        conn.close()


@pytest.fixture
def tasks():
    conn = drafts_store.connect(":memory:")
    drafts_store.migrate(conn)
    agent_tasks.migrate(conn)
    drafts_store.use_connection(conn)
    try:
        yield conn
    finally:
        drafts_store.reset()
        conn.close()


EXTERNAL = "external-technical"
OTHER_EXTERNAL = "external-non-technical"
T = TypeVar("T")


def _as(principal: str, call: Callable[[], T]) -> T:
    token = auth.current_principal.set(
        auth.Principal(id=principal, name=principal, role="writer", type="human")
    )
    try:
        return call()
    finally:
        auth.current_principal.reset(token)


def _pending(
    db, text: str, *, model: str = "agent:labeller", audience: str = EXTERNAL
) -> str:
    statement_id = store.create_statement(db, "capability", text)
    store.audience_labels.apply_ai_label(
        db,
        statement_id,
        [audience],
        reason="The first labeller considered this customer-facing.",
        model=model,
        hold={audience},
        graph=audiences.graph(),
    )
    db.commit()
    return statement_id


def _decision(
    statement_id: str, audience_id: str, decision: str, reason: str
) -> dict[str, str]:
    return {
        "statement_id": statement_id,
        "audience_id": audience_id,
        "decision": decision,
        "reason": reason,
    }


def _claim(principal: str):
    return _as(
        principal,
        lambda: agent_task_server.claim_agent_task("audience_review"),
    )


def _submit(principal: str, task_id: str, decisions: list[dict[str, str]]):
    return _as(
        principal,
        lambda: agent_task_server.submit_agent_task(task_id, {"decisions": decisions}),
    )


def test_setting_off_queues_no_review_task(db, prompts, tasks, monkeypatch):
    old_saved = product_settings.AudienceLabellingSettings().model_dump(
        exclude={"ai_grant_review"}
    )
    assert not product_settings.AudienceLabellingSettings.model_validate(
        old_saved
    ).ai_grant_review
    _pending(db, "Workspace owners can export invoices.")
    monkeypatch.setattr(audience_review, "_external", lambda: True)

    assert _claim("reviewer").tasks == []
    assert agent_tasks.open_tasks(tasks, "audience_review") == []


def test_an_agent_cannot_review_its_grants_and_another_agent_decides_them(
    db, prompts, tasks, monkeypatch
):
    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=True))
    confirmed = _pending(db, "Workspace owners can export invoices.")
    rejected = _pending(db, "The invoice worker runs on an internal queue.")
    monkeypatch.setattr(audience_review, "_external", lambda: True)

    withheld = _claim("labeller")
    assert withheld.tasks == []
    assert withheld.note is not None and "grants you labelled" in withheld.note

    [task] = _claim("reviewer").tasks
    status = audience_labelling.status(db)
    assert status.ai_grant_review
    assert [item.id for item in status.review_tasks] == [task.id]
    outcome = _submit(
        "reviewer",
        task.id,
        [
            _decision(confirmed, EXTERNAL, "confirm", "This describes an export."),
            _decision(rejected, EXTERNAL, "reject", "This exposes internals."),
        ],
    )
    assert outcome.status == "accepted"
    assert outcome.message == "Confirmed 1, rejected 1, skipped 0 grants."

    kept = store.audience_labels.get_label(db, confirmed)
    refused = store.audience_labels.get_label(db, rejected)
    assert kept is not None and refused is not None
    kept_decision = store.audience_labels.label_decisions(kept)[EXTERNAL]
    refused_decision = store.audience_labels.label_decisions(refused)[EXTERNAL]
    assert kept_decision == {
        "decision": "confirmed",
        "by": "reviewer",
        "at": kept_decision["at"],
        "reason": "This describes an export.",
    }
    assert refused_decision["by"] == "reviewer"
    assert refused_decision["reason"] == "This exposes internals."
    assert store.audience_labels.label_pending(kept) == []
    assert store.audience_labels.label_pending(refused) == []
    assert refused["source"] == "curator"
    assert refused["reason"] == (
        "reviewer rejected the AI's grant to External technical: "
        "This exposes internals. The labeller said: "
        "The first labeller considered this customer-facing."
    )


def test_missing_and_blank_decisions_are_refused_then_can_be_resubmitted(
    db, prompts, tasks, monkeypatch
):
    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=True))
    first = _pending(db, "Workspace owners can export invoices.")
    second = _pending(db, "Administrators configure SSO.")
    monkeypatch.setattr(audience_review, "_external", lambda: True)
    [task] = _claim("reviewer").tasks

    refused = _submit(
        "reviewer",
        task.id,
        [_decision(first, EXTERNAL, "confirm", "   ")],
    )
    assert refused.status == "refused"
    assert {finding.check for finding in refused.findings} == {"grants"}
    assert {finding.problem for finding in refused.findings} == {
        "give a short reason",
        "no decision given",
    }

    accepted = _submit(
        "reviewer",
        task.id,
        [
            _decision(first, EXTERNAL, "confirm", "The export is customer-facing."),
            _decision(second, EXTERNAL, "confirm", "SSO is administrator-facing."),
        ],
    )
    assert accepted.status == "accepted"


def test_a_grant_changed_after_queueing_is_skipped(db, prompts, tasks, monkeypatch):
    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=True))
    statement_id = _pending(db, "Workspace owners can export invoices.")
    monkeypatch.setattr(audience_review, "_external", lambda: True)
    [task] = _claim("reviewer").tasks
    db.execute(
        "UPDATE statement_audience_labels SET labelled_at = ? WHERE statement_id = ?",
        ("changed-after-queueing", statement_id),
    )
    db.commit()

    outcome = _submit(
        "reviewer",
        task.id,
        [_decision(statement_id, EXTERNAL, "confirm", "The export is public.")],
    )
    assert outcome.message == "Confirmed 0, rejected 0, skipped 1 grants."
    row = store.audience_labels.get_label(db, statement_id)
    assert row is not None
    assert store.audience_labels.label_pending(row) == [EXTERNAL]


def test_internal_review_uses_the_labelling_model_and_setting(db, prompts, monkeypatch):
    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=True))
    confirmed = _pending(db, "Workspace owners can export invoices.", model="labeller")
    rejected = _pending(
        db,
        "The invoice worker runs on an internal queue.",
        model="labeller",
        audience=OTHER_EXTERNAL,
    )
    monkeypatch.setattr(audience_review, "_external", lambda: False)
    monkeypatch.setattr(
        audience_review.model_settings, "credentials_error", lambda _action: None
    )
    calls: list[dict[str, object]] = []

    def call(task, config):
        prompt = json.loads(task.prompt)
        calls.append({"prompt": prompt, "model": config.model})
        return (
            audience_review.Review(
                decisions=[
                    audience_review.Decision(
                        statement_id=confirmed,
                        audience_id=EXTERNAL,
                        decision="confirm",
                        reason="The export is customer-facing.",
                    ),
                    audience_review.Decision(
                        statement_id=rejected,
                        audience_id=OTHER_EXTERNAL,
                        decision="reject",
                        reason="This exposes an internal component.",
                    ),
                ]
            ),
            ai.Usage(input_tokens=10, output_tokens=10),
        )

    audience_labelling.labelling_pass(db, review_call=call)

    assert len(calls) == 1
    assert len(calls[0]["prompt"]["grants"]) == 2
    selected = audience_review.model_settings.require("audience_labelling")
    assert calls[0]["model"] == selected.model
    confirmed_row = store.audience_labels.get_label(db, confirmed)
    rejected_row = store.audience_labels.get_label(db, rejected)
    assert confirmed_row is not None and rejected_row is not None
    assert store.audience_labels.label_decisions(confirmed_row)[EXTERNAL]["by"] == (
        f"model:{selected.model}"
    )
    assert rejected_row["source"] == "curator"

    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=False))
    _pending(db, "Administrators can configure SSO.", model="labeller")
    audience_labelling.labelling_pass(db, review_call=call)
    assert len(calls) == 1


def test_internal_review_stops_retrying_an_omitted_grant_after_three_attempts(
    db, prompts, monkeypatch
):
    set_product(product_settings.AudienceLabellingSettings(ai_grant_review=True))
    statement_id = _pending(db, "Workspace owners can export invoices.")
    monkeypatch.setattr(audience_review, "_external", lambda: False)
    monkeypatch.setattr(
        audience_review.model_settings, "credentials_error", lambda _action: None
    )
    calls = 0

    def call(task, config):
        nonlocal calls
        calls += 1
        return audience_review.Review(decisions=[]), ai.Usage()

    for _ in range(4):
        audience_review.review_batch(db, call=call)

    assert calls == 3
    row = store.audience_labels.get_label(db, statement_id)
    assert row is not None
    assert store.audience_labels.label_pending(row) == [EXTERNAL]
