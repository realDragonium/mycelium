"""End-to-end tests for phrasing validation through upsert_statement,
upsert_statements (batch with cascade), and replace_text."""

import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import embed, server, store


def deterministic_embed(text: str) -> list[float]:
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", deterministic_embed)
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    store.reset_substrate()
    server._ctx = None
    from mycelium.http import app

    return TestClient(app)


# ─── upsert_statement: rejection + bypass ────────────────────────────────────


def test_single_upsert_rejects_phrasing_violation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user must verify email",
                "mentions": [],
                "links": [],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rejected"] is True
        assert "statement_id" not in body
        assert len(body["violations"]) == 1
        v = body["violations"][0]
        assert v["category"] == "rule_shaped"
        assert v["matched_text"].lower() == "must"
        assert "kind='rule'" in v["recommendation"]


def test_single_upsert_bypass_returns_warning(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user must verify email",
                "mentions": [],
                "links": [],
                "allow_phrasing_violations": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "statement_id" in body
        assert body["statement_id"].startswith("stm_")
        assert "phrasing_violations" in body
        assert body["phrasing_violations"][0]["category"] == "rule_shaped"


def test_single_upsert_clean_text_no_violations_field(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user clicks the login button",
                "mentions": [],
                "links": [],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "statement_id" in body
        assert "phrasing_violations" not in body
        assert "rejected" not in body


def test_rejection_does_not_persist_statement(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "every user is required to enable 2FA",
                "mentions": [],
                "links": [],
            },
        )
        # Search for the rejected text — should find nothing.
        hits = client.post(
            "/search-statements",
            json={
                "query": "every user is required to enable 2FA",
                "min_score": -1.0,
            },
        ).json()
        assert all(h["text"] != "every user is required to enable 2FA" for h in hits)


# ─── replace_text: rejection + bypass ───────────────────────────────────────


def test_replace_text_rejects_phrasing_violation(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        original = "user clicks the login button"
        bid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": original,
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]

        r = client.post(
            "/replace-text",
            json={
                "id": bid,
                "text": "user must always verify email",
            },
        )
        body = r.json()
        assert body["rejected"] is True
        assert {v["category"] for v in body["violations"]} == {"rule_shaped"}

        # Confirm the statement text was NOT changed.
        body = client.post("/get-statements", json={"ids": [bid]}).json()["statements"][
            0
        ]
        assert body["text"] == original


def test_replace_text_bypass_updates_with_warning(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        bid = client.post(
            "/upsert-statement",
            json={
                "kind": "event",
                "text": "user clicks the login button",
                "mentions": [],
                "links": [],
            },
        ).json()["statement_id"]

        r = client.post(
            "/replace-text",
            json={
                "id": bid,
                "text": "user must verify email",
                "allow_phrasing_violations": True,
            },
        ).json()
        assert r["statement_id"] == bid
        assert r["phrasing_violations"][0]["category"] == "rule_shaped"

        body = client.post("/get-statements", json={"ids": [bid]}).json()["statements"][
            0
        ]
        assert body["text"] == "user must verify email"


# ─── upsert_statements (batch): per-item, partial success, cascade ──────────


def test_batch_per_item_partial_success(tmp_path, monkeypatch):
    """Clean items pass; rejected items are reported but don't block siblings."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user clicks the login button",
                        "mentions": [],
                        "links": [],
                    },  # @0 clean
                    {
                        "kind": "event",
                        "text": "user must verify email",
                        "mentions": [],
                        "links": [],
                    },  # @1 rejected
                    {
                        "kind": "event",
                        "text": "system sends a verification email",
                        "mentions": [],
                        "links": [],
                    },  # @2 clean
                ],
            },
        ).json()

        results = r["results"]
        assert len(results) == 3
        assert "statement_id" in results[0]
        assert (
            results[1]
            == {
                "rejected": True,
                "violations": results[1]["violations"],
            }
            or results[1]["rejected"] is True
        )
        assert results[1]["violations"][0]["category"] == "rule_shaped"
        assert "statement_id" in results[2]
        # @0 and @2 actually got persisted; @1 did not
        ids = client.post("/list-statements", json={}).json()
        texts = [b["text"] for b in ids["statements"]]
        assert "user clicks the login button" in texts
        assert "system sends a verification email" in texts
        assert "user must verify email" not in texts


def test_batch_per_item_bypass(tmp_path, monkeypatch):
    """Per-item bypass keeps the violator in the batch with a warning."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user clicks the login button",
                        "mentions": [],
                        "links": [],
                    },
                    {
                        "kind": "event",
                        "text": "user must verify email",
                        "mentions": [],
                        "links": [],
                        "allow_phrasing_violations": True,
                    },
                ],
            },
        ).json()
        assert "statement_id" in r["results"][0]
        assert "statement_id" in r["results"][1]
        assert r["results"][1]["phrasing_violations"][0]["category"] == "rule_shaped"


def test_batch_cascade_rejection(tmp_path, monkeypatch):
    """An item that @-references a rejected sibling is itself rejected
    with reason='depends_on_rejected'."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    # @0: rejected (rule_shaped)
                    {
                        "kind": "event",
                        "text": "user must verify email",
                        "mentions": [],
                        "links": [],
                    },
                    # @1: clean text but references @0
                    {
                        "kind": "event",
                        "text": "system sends a confirmation email",
                        "mentions": [],
                        "links": [
                            {"to_id": "@0", "link_type": "triggers"},
                        ],
                    },
                    # @2: clean and unconnected
                    {
                        "kind": "event",
                        "text": "user clicks the home button",
                        "mentions": [],
                        "links": [],
                    },
                ],
            },
        ).json()

        results = r["results"]
        # @0 directly rejected
        assert results[0]["rejected"] is True
        assert results[0]["violations"][0]["category"] == "rule_shaped"
        # @1 cascade-rejected
        assert results[1]["rejected"] is True
        assert results[1]["reason"] == "depends_on_rejected"
        assert results[1]["depends_on"] == [0]
        # @2 untouched, lands cleanly
        assert "statement_id" in results[2]


def test_batch_cascade_is_transitive(tmp_path, monkeypatch):
    """A rejection chain @0→@1→@2: cascade reaches all three."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user must verify email",
                        "mentions": [],
                        "links": [],
                    },  # @0 rejected
                    {  # @1 references @0 → cascade
                        "kind": "event",
                        "text": "system retries the request",
                        "mentions": [],
                        "links": [
                            {"to_id": "@0", "link_type": "triggers"},
                        ],
                    },
                    {  # @2 references @1 → cascade transitively
                        "kind": "event",
                        "text": "system logs the outcome",
                        "mentions": [],
                        "links": [
                            {"to_id": "@1", "link_type": "leads_to"},
                        ],
                    },
                ],
            },
        ).json()
        results = r["results"]
        assert results[0]["rejected"] is True
        assert results[1]["reason"] == "depends_on_rejected"
        assert results[1]["depends_on"] == [0]
        assert results[2]["reason"] == "depends_on_rejected"
        assert results[2]["depends_on"] == [1]


def test_batch_incoming_link_to_rejected_cascades(tmp_path, monkeypatch):
    """Cascade applies via incoming_links too — if @0 is rejected and @1
    declares an incoming_link from @0, @1 cascades."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user must log in",
                        "mentions": [],
                        "links": [],
                    },  # @0 rejected
                    {
                        "kind": "event",
                        "text": "system creates the session",
                        "mentions": [],
                        "links": [],
                        "incoming_links": [
                            {"from_id": "@0", "link_type": "triggers"},
                        ],
                    },
                ],
            },
        ).json()
        assert r["results"][0]["rejected"] is True
        assert r["results"][1]["reason"] == "depends_on_rejected"


def test_batch_when_ref_to_rejected_cascades(tmp_path, monkeypatch):
    """An @-ref in a when tree leaf also triggers cascade."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user must enable 2FA",
                        "mentions": [],
                        "links": [],
                    },  # @0 rejected
                    {
                        "kind": "event",
                        "text": "user opens the dashboard",
                        "mentions": [],
                        "links": [],
                    },  # @1 clean
                    {
                        "kind": "event",
                        "text": "system sends a notification",
                        "mentions": [],
                        "links": [
                            {
                                "to_id": "@1",
                                "link_type": "leads_to",
                                "when": {"statement_id": "@0"},
                            },
                        ],
                    },
                ],
            },
        ).json()
        assert r["results"][0]["rejected"] is True
        assert "statement_id" in r["results"][1]
        assert r["results"][2]["reason"] == "depends_on_rejected"
        assert r["results"][2]["depends_on"] == [0]


def test_batch_clean_items_persist_when_others_rejected(tmp_path, monkeypatch):
    """The persisted record-set matches the per-item results: clean and
    bypassed items end up in the store, rejected/cascaded ones do not."""
    with _client(tmp_path, monkeypatch) as client:
        r = client.post(
            "/upsert-statements",
            json={
                "statements": [
                    {
                        "kind": "event",
                        "text": "user must verify email",
                        "mentions": [],
                        "links": [],
                    },  # rejected
                    {
                        "kind": "event",
                        "text": "user clicks login",
                        "mentions": [],
                        "links": [],
                    },  # clean
                    {  # cascade: references rejected @0
                        "kind": "event",
                        "text": "system sends an email",
                        "mentions": [],
                        "links": [
                            {"to_id": "@0", "link_type": "triggers"},
                        ],
                    },
                    {  # bypassed
                        "kind": "event",
                        "text": "admin can edit any post",
                        "mentions": [],
                        "links": [],
                        "allow_phrasing_violations": True,
                    },
                ],
            },
        ).json()
        results = r["results"]
        assert results[0]["rejected"] is True
        assert "statement_id" in results[1]
        assert results[2]["reason"] == "depends_on_rejected"
        assert "statement_id" in results[3]
        assert results[3]["phrasing_violations"]

        # Sanity-check the store: only @1 and @3 landed
        listed = client.post("/list-statements", json={}).json()["statements"]
        texts = sorted(b["text"] for b in listed)
        assert texts == sorted(["user clicks login", "admin can edit any post"])
