from __future__ import annotations

import zlib

from fastapi.testclient import TestClient

from mycelium import auth_store, drafts_store, server, store

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
