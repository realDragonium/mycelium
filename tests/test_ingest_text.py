"""Test raw-text ingestion through isolated server and draft stores.

Cue-gate cases split tiny carrier vectors from the statement index's 768 dimensions.
"""

from __future__ import annotations

import json
import zlib

import numpy as np
from fastapi.testclient import TestClient

from mycelium import auth_store, drafts_store, embed, server, store
from mycelium.connect import aliases as connect_aliases

TEXT = """When the invite is sent, a reminder is scheduled. Notification cadence can be configured on Company.

- Click Save to apply the change.
- The user logs in and receives a token.
- Blue widgets."""


def _word_embed(text: str) -> list[float]:
    vector = [0.0] * 768
    for word in text.lower().split():
        vector[zlib.crc32(word.encode()) % 768] += 1.0
    return vector


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")
    monkeypatch.setenv("MYCELIUM_DISABLE_MCP_HTTP", "1")
    store.reset_substrate()
    auth_store.reset()
    drafts_store.reset()
    server._ctx = None
    from mycelium import embed

    monkeypatch.setattr(embed, "embed", _word_embed)
    from mycelium.http import app

    return TestClient(app)


def _statement(kind: str, text: str) -> str:
    result = server.upsert_statement(
        kind=kind,
        text=text,
        links=[],
        allow_phrasing_violations=True,
    )
    assert "statement_id" in result, result
    return result["statement_id"]


def _seed_vectors(
    monkeypatch,
    alias_vectors: dict[str, tuple[str, list[float]]],
    cue_vectors: dict[str, list[float]],
) -> None:
    """Replace the alias table with exactly these embedded aliases.

    The gate refuses a half-embedded alias set, so the seeded rows the
    background worker never drained here have to go.
    """
    conn = server._db()
    with store.transaction(conn):
        conn.execute("DELETE FROM link_type_aliases")
        for alias, (link_type, vector) in alias_vectors.items():
            store.upsert_link_type_alias(conn, link_type, alias, provenance="seed")
            store.set_alias_embedding(
                conn,
                link_type,
                alias,
                np.asarray(vector, dtype=np.float32).tobytes(),
            )
        conn.execute("DELETE FROM link_type_alias_embed_queue")

    carriers = {
        connect_aliases.carrier_text(cue): vector for cue, vector in cue_vectors.items()
    }

    def fake_embed(text: str) -> list[float]:
        if text in carriers:
            return carriers[text]
        return _word_embed(text)

    monkeypatch.setattr(embed, "embed", fake_embed)


def _draft_ops(draft_id: str) -> list:
    """Read a draft's raw operation rows."""
    return drafts_store.list_ops(server._drafts_db(), draft_id)


def test_happy_path_writes_connected_items_and_flags(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text(TEXT, title="Invites")

        assert response["draft_id"].startswith("drf_")
        assert response["fragments"] == {
            "total": 7,
            "resolved": 5,
            "flagged": 2,
        }
        assert [
            (item["fragment_index"], item["kind"], item["batch_index"])
            for item in response["items"]
        ] == [
            (0, "event", 0),
            (1, "event", 1),
            (2, "capability", 2),
            (3, "action", 3),
            (6, "property", 4),
        ]
        assert [
            (flag["fragment_index"], flag["reason"]) for flag in response["flags"]
        ] == [(4, "unmatched"), (5, "unmatched")]
        assert response["condition_links"] == 1
        assert response["results"] == [
            {"accepted": True, "batch_index": index} for index in range(5)
        ]
        proposal_count = sum(response["proposals"].values())
        assert response["draft"] == {
            "status": "open",
            "op_count": 1 + proposal_count + 2,
            "flags": 2,
        }

        draft = server.get_draft(response["draft_id"])
        assert draft["title"] == "Invites"
        assert draft["ops"][0]["kind"] == "upsert_statements"
        statements = draft["ops"][0]["payload"]["statements"]
        assert statements[1]["links"] == [{"to_id": "@0", "link_type": "requires"}]
        assert [op["kind"] for op in draft["ops"]][-2:] == ["flag", "flag"]
        for expected_index, expected_text, op in zip(
            (4, 5),
            ("The user logs in", "The user receives a token"),
            draft["ops"][-2:],
            strict=True,
        ):
            assert op["payload"]["reason"] == "unmatched"
            assert op["payload"]["text"] == expected_text
            assert len(op["payload"]["span"]) == 2
            assert op["provenance"] == {
                "source": "shapes",
                "reason": "unmatched",
                "fragment_index": expected_index,
            }


def test_registered_cut_alias_adds_left_to_right_draft_link(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text(
            "The invite is created and then the reminder is scheduled"
        )

        assert response["results"] == [
            {"accepted": True, "batch_index": 0},
            {"accepted": True, "batch_index": 1},
        ]
        draft = server.get_draft(response["draft_id"])
        statements = draft["ops"][0]["payload"]["statements"]
        assert statements[0]["links"] == [{"to_id": "@1", "link_type": "proceeds"}]


def test_apply_draft_skips_flags_and_creates_condition_link(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text(TEXT)

        applied = server.apply_draft(response["draft_id"])

        flag_ops = server.get_draft(response["draft_id"])["ops"][-2:]
        assert [
            result for result in applied["results"] if result["kind"] == "flag"
        ] == [{"seq": op["seq"], "kind": "flag", "skipped": "flag"} for op in flag_ops]
        batch_results = applied["results"][0]["result"]["results"]
        assert len(batch_results) == 5
        assert all("statement_id" in result for result in batch_results)
        condition_id = batch_results[0]["statement_id"]
        claim_id = batch_results[1]["statement_id"]
        assert store.get_links(server._db(), claim_id) == [
            (condition_id, "requires", None)
        ]
        # Replay does not decide the draft: the approve endpoint sets that.
        assert server.get_draft(response["draft_id"])["status"] == "open"


def test_catalog_rejection_becomes_a_flag_op(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text("Every invite is always sent.")

        assert response["items"] == []
        assert response["flags"] == [
            {
                "fragment_index": 0,
                "reason": "phrasing",
                "text": "Every invite is always sent",
            }
        ]
        assert response["results"][0]["rejected"] is True
        assert response["results"][0]["violations"]
        draft = server.get_draft(response["draft_id"])
        assert len(draft["ops"]) == 1
        flag = draft["ops"][0]
        assert flag["kind"] == "flag"
        assert flag["payload"]["reason"] == "phrasing"
        assert "universal_claim" in flag["payload"]["detail"]
        assert "rule_shaped" in flag["payload"]["detail"]
        assert flag["provenance"]["source"] == "phrasing"


def test_all_flags_input_creates_no_batch_op(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text("The user logs in and receives a token.")

        assert response["draft_id"].startswith("drf_")
        assert response["fragments"] == {
            "total": 2,
            "resolved": 0,
            "flagged": 2,
        }
        draft = server.get_draft(response["draft_id"])
        assert [op["kind"] for op in draft["ops"]] == ["flag", "flag"]
        assert response["draft"]["op_count"] == 2
        assert response["items"] == []


def test_empty_text_returns_the_empty_response(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        for text in ("", "   \n "):
            response = server.ingest_text(text)

            assert response["draft_id"] is None
            assert response["draft"] is None
            assert response["fragments"] == {
                "total": 0,
                "resolved": 0,
                "flagged": 0,
            }
            assert response["items"] == []
            assert response["flags"] == []
            assert response["condition_links"] == 0
            assert response["nli"] == "unavailable"


def test_discard_draft_op_strikes_a_flag(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        response = server.ingest_text("The user logs in and receives a token.")
        draft = server.get_draft(response["draft_id"])

        server.discard_draft_op(
            draft_id=response["draft_id"], seq=draft["ops"][0]["seq"]
        )

        assert len(server.get_draft(response["draft_id"])["ops"]) == 1


class _Row:
    def __init__(self, **values):
        self._values = values

    def __getitem__(self, key):
        return self._values[key]


class _ExplodingTools(dict):
    def get(self, key, default=None):
        raise AssertionError("tools_by_name must not be consulted for a flag")


def test_replay_flag_has_its_own_skip_marker():
    op = _Row(seq=7, kind="flag", payload_json="{}")

    assert server._replay_draft_op(op, _ExplodingTools(), {}) == {
        "seq": 7,
        "kind": "flag",
        "skipped": "flag",
    }


def test_replay_unknown_tool_keeps_obsolete_marker():
    op = _Row(seq=8, kind="add_mentions", payload_json="{}")

    assert server._replay_draft_op(op, {}, {}) == {
        "seq": 8,
        "kind": "add_mentions",
        "skipped": "obsolete_tool",
    }


def test_auto_absorption_rides_draft_without_teaching_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {
                "then": ("proceeds", [1.0, 0.0]),
                "includes": ("contains", [0.0, 1.0]),
            },
            {"and also": [1.0, 0.0]},
        )

        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        ops = _draft_ops(response["draft_id"])
        alias_ops = [op for op in ops if op["kind"] == "upsert_link_type_alias"]
        assert len(alias_ops) == 1
        assert json.loads(alias_ops[0]["payload_json"]) == {
            "link_type": "proceeds",
            "alias": "and also",
            "provenance": "auto",
            "score": 1.0,
        }
        provenance = json.loads(alias_ops[0]["provenance_json"])
        assert provenance["source"] == "cue-gate"
        assert provenance["candidates"][0][:2] == ["proceeds", "then"]
        assert not store.link_type_alias_exists(
            server._db(),
            "proceeds",
            "and also",
        )
        assert response["cues"] == {
            "auto": 1,
            "low_confidence": 0,
            "unresolved": 0,
            "strict": 0,
        }
        resolution = response["cue_resolutions"][0]
        assert {
            "cue": resolution["cue"],
            "link_type": resolution["link_type"],
            "alias": resolution["alias"],
            "score": resolution["score"],
        } == {
            "cue": "and also",
            "link_type": "proceeds",
            "alias": "then",
            "score": 1.0,
        }


def test_approval_writes_automatically_absorbed_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {"then": ("proceeds", [1.0, 0.0])},
            {"and also": [1.0, 0.0]},
        )
        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        server.apply_draft(response["draft_id"])

        row = next(
            row
            for row in store.list_link_type_aliases(server._db(), "proceeds")
            if row["alias"] == "and also"
        )
        assert row["provenance"] == "auto"
        assert row["score"] == 1.0


def test_low_confidence_absorption_keeps_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {
                "then": ("proceeds", [1.0, 0.0]),
                "includes": ("contains", [4.0, 1.0]),
            },
            {"and also": [1.0, 0.0]},
        )
        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        alias_op = next(
            op
            for op in _draft_ops(response["draft_id"])
            if op["kind"] == "upsert_link_type_alias"
        )
        assert json.loads(alias_op["payload_json"])["provenance"] == (
            "auto:low-confidence"
        )
        assert response["cues"]["low_confidence"] == 1

        server.apply_draft(response["draft_id"])
        row = next(
            row
            for row in store.list_link_type_aliases(server._db(), "proceeds")
            if row["alias"] == "and also"
        )
        assert row["provenance"] == "auto:low-confidence"


def test_strict_mode_flags_without_embedding_or_alias_op(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "strict")
    with _app(tmp_path, monkeypatch):
        carrier = connect_aliases.carrier_text("and also")

        def fake_embed(text: str) -> list[float]:
            if text == carrier:
                raise AssertionError(f"unexpected embed: {text!r}")
            return _word_embed(text)

        monkeypatch.setattr(embed, "embed", fake_embed)

        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        ops = _draft_ops(response["draft_id"])
        assert any(
            op["kind"] == "flag" and json.loads(op["payload_json"])["reason"] == "cue"
            for op in ops
        )
        assert not any(op["kind"] == "upsert_link_type_alias" for op in ops)
        assert not store.link_type_alias_exists(
            server._db(),
            "proceeds",
            "and also",
        )
        assert response["cues"] == {
            "auto": 0,
            "low_confidence": 0,
            "unresolved": 0,
            "strict": 1,
        }


def test_unresolved_cue_flag_names_near_misses(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {
                "then": ("proceeds", [0.0, 1.0, 0.0]),
                "includes": ("contains", [0.0, 0.0, 1.0]),
            },
            {"and also": [1.0, 0.0, 0.0]},
        )

        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        ops = _draft_ops(response["draft_id"])
        flag = next(op for op in ops if op["kind"] == "flag")
        payload = json.loads(flag["payload_json"])
        provenance = json.loads(flag["provenance_json"])
        assert "and also" in payload["detail"]
        assert {candidate[0] for candidate in provenance["candidates"]} == {
            "contains",
            "proceeds",
        }
        assert not any(op["kind"] == "upsert_link_type_alias" for op in ops)


def test_cue_flags_do_not_change_fragment_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {"then": ("proceeds", [0.0, 1.0])},
            {"and also": [1.0, 0.0]},
        )

        flagged = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )
        no_cue = server.ingest_text("The invite is created; the reminder is scheduled")

        expected = {"total": 2, "resolved": 2, "flagged": 0}
        assert flagged["fragments"] == expected
        assert no_cue["fragments"] == expected
        assert flagged["cues"]["unresolved"] == 1
        assert no_cue["cue_resolutions"] == []


def test_draft_op_count_includes_alias_op(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {"then": ("proceeds", [1.0, 0.0])},
            {"and also": [1.0, 0.0]},
        )

        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        ops = _draft_ops(response["draft_id"])
        assert any(op["kind"] == "upsert_link_type_alias" for op in ops)
        assert response["draft"]["op_count"] == len(ops)


def test_half_embedded_alias_set_flags_instead_of_guessing(tmp_path, monkeypatch):
    monkeypatch.setenv("MYCELIUM_CUE_RESOLUTION", "open")
    with _app(tmp_path, monkeypatch):
        _seed_vectors(
            monkeypatch,
            {"then": ("proceeds", [1.0, 0.0])},
            {"and also": [1.0, 0.0]},
        )
        # One alias still waiting on the worker is enough: its type could have
        # been the runner-up that made this decision low-confidence.
        with store.transaction(server._db()):
            store.upsert_link_type_alias(server._db(), "contains", "includes")

        response = server.ingest_text(
            "The invite is created and also the reminder is scheduled"
        )

        ops = _draft_ops(response["draft_id"])
        assert not any(op["kind"] == "upsert_link_type_alias" for op in ops)
        flag = next(op for op in ops if op["kind"] == "flag")
        assert json.loads(flag["payload_json"])["reason"] == "cue"
        assert response["cues"]["unresolved"] == 1
