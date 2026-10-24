"""Curator confirmation of the AI's new external audience grants."""

from __future__ import annotations

import random

import pytest

from mycelium import (
    ai,
    audience_labelling,
    audience_scope,
    audiences,
    grant_confirmation,
    product_settings,
    store,
)
from mycelium.audiences import Audience
from product_settings_helpers import connection as product_connection
from test_principal_audience import _bearer, client  # noqa: F401 — fixture

INTERNAL = "internal-technical"
EXTERNAL = "external-technical"
OTHER_EXTERNAL = "external-non-technical"
labels = store.audience_labels


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


def _answer(granted: dict[str, list[str]]):
    def call(task, config):
        return (
            audience_labelling.Labelling(
                labels=[
                    audience_labelling.Decision(
                        statement_id=sid,
                        audiences=ids,
                        reason="Integrators see it.",
                        narrowing_reason="",
                    )
                    for sid, ids in granted.items()
                ]
            ),
            ai.Usage(input_tokens=10, output_tokens=10),
        )

    return call


def _visible(db, audience: str) -> frozenset[str]:
    return store.visible_statement_ids(
        db, audiences.sees_of(audience), audience.startswith("internal")
    )


def _label(db, sid: str):
    row = labels.get_label(db, sid)
    assert row is not None
    return row


def test_a_new_external_grant_waits_while_internal_grants_apply(db, prompts):
    sid = store.create_statement(db, "capability", "admins can export invoices")

    audience_labelling.label_batches(db, call=_answer({sid: [INTERNAL, EXTERNAL]}))

    row = _label(db, sid)
    assert labels.label_audiences(row) == [INTERNAL]
    assert labels.label_pending(row) == [EXTERNAL]
    assert sid in _visible(db, INTERNAL)
    assert sid not in _visible(db, EXTERNAL)
    scope = audience_scope.capture(
        db, Audience(EXTERNAL, "External", "external", "x", 1)
    )
    assert sid not in scope.statement_ids


def test_a_waiting_grant_stays_visible_to_the_internal_audiences_including_it(
    db, prompts
):
    sid = store.create_statement(db, "capability", "users can archive projects")

    audience_labelling.label_batches(db, call=_answer({sid: [OTHER_EXTERNAL]}))

    row = _label(db, sid)
    assert labels.label_pending(row) == [OTHER_EXTERNAL]
    assert labels.label_audiences(row) == ["internal-non-technical"]
    assert {
        audience
        for audience in (INTERNAL, "internal-non-technical", EXTERNAL, OTHER_EXTERNAL)
        if sid in _visible(db, audience)
    } == {INTERNAL, "internal-non-technical"}

    grant_confirmation.decide(OTHER_EXTERNAL, [sid], confirm=True, curator="c1")
    assert sid in _visible(db, EXTERNAL)
    # Internal non-technical sees it through the confirmed grant now.
    assert labels.label_audiences(_label(db, sid)) == [OTHER_EXTERNAL]


def test_switching_confirmation_off_applies_external_grants_at_once(
    db, prompts, monkeypatch
):
    sid = store.create_statement(db, "capability", "users reset passwords")
    monkeypatch.setattr(
        product_settings,
        "get",
        lambda model, **_: (
            model(confirm_external_grants=False)
            if model is product_settings.AudienceLabellingSettings
            else model()
        ),
    )

    audience_labelling.label_batches(db, call=_answer({sid: [EXTERNAL]}))

    assert labels.label_pending(_label(db, sid)) == []
    assert sid in _visible(db, EXTERNAL)


def test_a_relabel_keeps_a_visible_grant_and_holds_only_new_ones(db):
    sid = store.create_statement(db, "capability", "workspaces have owners")
    labels.apply_ai_label(
        db, sid, [EXTERNAL], reason="r", model="m", cost_usd=None, hold={EXTERNAL}
    )
    labels.decide_pending(db, sid, EXTERNAL, confirm=True, by="curator-1")

    labels.apply_ai_label(
        db,
        sid,
        [EXTERNAL, OTHER_EXTERNAL],
        reason="r2",
        model="m",
        cost_usd=None,
        hold={EXTERNAL, OTHER_EXTERNAL},
    )

    row = _label(db, sid)
    assert labels.label_audiences(row) == [EXTERNAL]
    assert labels.label_pending(row) == [OTHER_EXTERNAL]
    assert labels.label_decisions(row)[EXTERNAL]["by"] == "curator-1"

    labels.apply_ai_label(db, sid, [], reason="r3", model="m", cost_usd=None)
    row = _label(db, sid)
    assert labels.label_audiences(row) == []
    assert labels.label_pending(row) == []
    assert labels.label_decisions(row) == {}


def test_confirming_grants_and_rejecting_becomes_a_curator_decision(db, prompts):
    kept, refused = (
        store.create_statement(db, "capability", text)
        for text in ("sso supports saml", "the billing worker retries")
    )
    for sid in (kept, refused):
        labels.apply_ai_label(
            db, sid, [EXTERNAL], reason="r", model="m", cost_usd=None, hold={EXTERNAL}
        )

    assert grant_confirmation.decide(EXTERNAL, [kept], confirm=True, curator="c1") == 1
    assert grant_confirmation.decide(EXTERNAL, [refused], confirm=False, curator="c1")
    assert (
        grant_confirmation.decide(EXTERNAL, [refused], confirm=True, curator="c1") == 0
    )

    assert _visible(db, EXTERNAL) == {kept}
    confirmed = labels.label_decisions(_label(db, kept))[EXTERNAL]
    assert (confirmed["decision"], confirmed["by"]) == ("confirmed", "c1")
    rejected = _label(db, refused)
    assert (rejected["source"], rejected["labelled_by"]) == ("curator", "c1")
    assert not labels.apply_ai_label(
        db, refused, [EXTERNAL], reason="again", model="m", cost_usd=None
    )
    assert refused not in _visible(db, EXTERNAL)


def test_a_text_change_withdraws_the_grant_until_it_is_confirmed_again(db):
    sid = store.create_statement(db, "state", "exports are csv")
    labels.apply_ai_label(
        db, sid, [EXTERNAL], reason="r", model="m", cost_usd=None, hold={EXTERNAL}
    )
    labels.decide_pending(db, sid, EXTERNAL, confirm=True, by="c1")
    store.update_statement_text(db, sid, "exports are csv or json")

    assert sid not in _visible(db, EXTERNAL)
    labels.apply_ai_label(
        db, sid, [EXTERNAL], reason="r", model="m", cost_usd=None, hold={EXTERNAL}
    )
    assert labels.label_pending(_label(db, sid)) == [EXTERNAL]


def test_allocation_is_proportional_by_largest_remainder():
    assert grant_confirmation._allocate([9, 6, 5], 4) == [2, 1, 1]
    assert grant_confirmation._allocate([2, 1], 50) == [2, 1]


def _pending_under_concepts(db, count: dict[str, int]) -> list[str]:
    for concept in count:
        store.create_name(db, concept.lower(), store.create_entity(db, None))
    index = store.build_name_index(db)
    ids: list[str] = []
    for concept, n in count.items():
        for number in range(n):
            text = f"{concept.lower()} rule {number}"
            sid = store.create_statement(db, "state", text)
            store.derive_mentions(db, sid, text, index)
            labels.apply_ai_label(
                db,
                sid,
                [EXTERNAL],
                reason="r",
                model="m",
                cost_usd=None,
                hold={EXTERNAL},
            )
            ids.append(sid)
    db.commit()
    return ids


def test_a_sample_is_stratified_and_accepting_the_rest_records_its_precision(
    db, prompts
):
    _pending_under_concepts(db, {"Invoices": 8, "Exports": 4})
    groups = grant_confirmation.groups(db, EXTERNAL)
    assert [(g.concept and g.concept.name, len(g.statements)) for g in groups] == [
        ("invoices", 8),
        ("exports", 4),
    ]

    drawn = grant_confirmation.sample(db, EXTERNAL, 3, random.Random(1))
    assert [len(group.statements) for group in drawn] == [2, 1]
    sample = [item.id for group in drawn for item in group.statements]
    with pytest.raises(ValueError, match="at least one"):
        grant_confirmation.accept_rest(EXTERNAL, sample, curator="c1")

    grant_confirmation.decide(EXTERNAL, sample[:2], confirm=True, curator="c1")
    grant_confirmation.decide(EXTERNAL, sample[2:], confirm=False, curator="c1")
    accepted = grant_confirmation.accept_rest(EXTERNAL, sample, curator="c1")

    assert (accepted.accepted, accepted.sample_size) == (9, 3)
    assert accepted.precision == pytest.approx(0.6667)
    assert accepted.below_threshold
    assert grant_confirmation.pending_counts(db) == {}
    assert sample[2] not in _visible(db, EXTERNAL)
    assert len(_visible(db, EXTERNAL)) == 11
    bulk = next(
        labels.label_decisions(_label(db, sid))[EXTERNAL]
        for sid in _visible(db, EXTERNAL) - set(sample)
    )
    assert bulk["sample"] == {"size": 3, "precision": pytest.approx(0.6667)}


def test_a_pending_statement_reaches_an_external_token_only_once_confirmed(
    client,  # noqa: F811 — the imported fixture
):
    from mycelium import server

    admin, reader = _bearer("admin"), _bearer("reader")
    external = _bearer("reader", EXTERNAL)
    conn = server._db()
    with store.transaction(conn):
        sid = store.create_statement(conn, "capability", "admins can export invoices")
        labels.apply_ai_label(
            conn, sid, [EXTERNAL], reason="r", model="m", cost_usd=None, hold={EXTERNAL}
        )

    def seen() -> int:
        return client.get("/api/substrate-counts", headers=external).json()[
            "statements"
        ]

    assert seen() == 0
    listed = client.get("/api/audiences", headers=admin).json()
    assert listed["pending"] == 1
    page = client.get(f"/api/statements/{sid}/audiences", headers=admin).json()
    assert [a["id"] for a in page["audiences"] if a["pending"]] == [EXTERNAL]
    pending = client.get(f"/api/audiences/{EXTERNAL}/pending", headers=admin).json()
    assert pending["total"] == 1 and pending["sample_size"] == 50

    decide = f"/api/audiences/{EXTERNAL}/pending/decide"
    body = {"statement_ids": [sid], "decision": "confirm"}
    assert client.post(decide, headers=reader, json=body).status_code == 403
    assert client.post(decide, headers=admin, json=body).json() == {"decided": 1}
    assert seen() == 1


def _confirmed(db, text: str, granted: list[str]) -> str:
    sid = store.create_statement(db, "capability", text)
    audience_labelling.label_batches(db, call=_answer({sid: granted}))
    for audience in granted:
        grant_confirmation.decide(audience, [sid], confirm=True, curator="c1")
    return sid


def test_an_edit_keeps_a_confirmed_grant_in_force_for_a_spot_check(db, prompts):
    kept, withdrawn = (
        _confirmed(db, text, [OTHER_EXTERNAL])
        for text in ("exports hold 100 rows", "invoices list 20 lines")
    )
    store.update_statement_text(db, kept, "exports hold 500 rows")
    store.update_statement_text(db, withdrawn, "invoices list 50 lines")

    audience_labelling.label_batches(
        db, call=_answer({kept: [OTHER_EXTERNAL], withdrawn: [OTHER_EXTERNAL]})
    )

    row = _label(db, kept)
    assert (labels.label_audiences(row), labels.label_pending(row)) == (
        [OTHER_EXTERNAL],
        [],
    )
    assert labels.label_decisions(row)[OTHER_EXTERNAL]["by"] == "c1"
    assert {kept, withdrawn} <= _visible(db, EXTERNAL)
    listed = {item.id: item for item in grant_confirmation.spot_checks(db)}
    assert (listed[kept].old_text, listed[kept].text) == (
        "exports hold 100 rows",
        "exports hold 500 rows",
    )

    assert grant_confirmation.decide_spot_check(kept, confirm=True, curator="c2")
    assert grant_confirmation.decide_spot_check(withdrawn, confirm=False, curator="c2")

    assert [item.id for item in grant_confirmation.spot_checks(db)] == []
    assert labels.label_decisions(_label(db, kept))[OTHER_EXTERNAL]["by"] == "c2"
    narrowed = _label(db, withdrawn)
    assert (narrowed["source"], labels.label_audiences(narrowed)) == (
        "curator",
        ["internal-non-technical"],
    )
    assert withdrawn not in _visible(db, EXTERNAL)
    assert withdrawn in _visible(db, INTERNAL)


def test_an_edit_that_reveals_to_a_new_external_audience_waits_again(db, prompts):
    sid = _confirmed(db, "the api pages results", [EXTERNAL])
    store.update_statement_text(db, sid, "the api and the export page results")

    audience_labelling.label_batches(
        db, call=_answer({sid: [EXTERNAL, OTHER_EXTERNAL]})
    )

    row = _label(db, sid)
    assert labels.label_pending(row) == [OTHER_EXTERNAL, EXTERNAL]
    assert grant_confirmation.spot_checks(db) == []
