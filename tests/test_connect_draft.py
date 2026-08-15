from __future__ import annotations

import zlib

import pytest
from fastapi.testclient import TestClient

from mycelium import auth_store, drafts_store, server, store
from mycelium.connect.draft import BatchInput, assemble_draft, summarize
from mycelium.connect.proposals import Proposal


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


def _statement(kind: str, text: str, *, allow: bool = False) -> str:
    result = server.upsert_statement(
        kind=kind,
        text=text,
        links=[],
        allow_phrasing_violations=allow,
    )
    assert "statement_id" in result, result
    return result["statement_id"]


def _existing_statements() -> tuple[str, str, str]:
    x_id = _statement("state", "the login session is active", allow=True)
    e_id = _statement("property", "the session timeout duration", allow=True)
    y_id = _statement("state", "the account remains locked", allow=True)
    server.add_links(links=[{"from_id": x_id, "to_id": e_id, "link_type": "requires"}])
    return x_id, e_id, y_id


def _text_of(statement_id: str) -> str | None:
    row = store.get_statement(store.substrate_connection(), statement_id)
    return row["text"] if row is not None else None


def _batch(e_id: str) -> list[BatchInput]:
    return [
        BatchInput(
            kind="event",
            text="user clicks the login button",
            links=[{"to_id": e_id, "link_type": "requires"}],
        ),
        BatchInput(
            kind="event",
            text="system sends a verification email",
            links=[{"to_id": "@0", "link_type": "triggers"}],
        ),
    ]


def _proposals(x_id: str, y_id: str) -> list[Proposal]:
    return [
        Proposal(
            kind="link",
            new_index=0,
            target=y_id,
            link_type="requires",
            provenance={
                "source": "rule",
                "pattern": "requires-verb",
                "cue": "requires",
                "target_text": "the account remains locked",
                "score": 0.82,
                "link_type": "requires",
            },
        ),
        Proposal(
            kind="merge",
            new_index=0,
            target=x_id,
            link_type=None,
            provenance={"source": "similarity", "score": 0.93},
        ),
        Proposal(
            kind="conflict",
            new_index=1,
            target=y_id,
            link_type=None,
            provenance={
                "source": "nli",
                "score": 0.78,
                "forward": {"label": "contradiction", "confidence": 0.91},
                "backward": {"label": "neutral", "confidence": 0.73},
            },
        ),
    ]


def _assemble(x_id: str, e_id: str, y_id: str) -> str:
    return assemble_draft(
        server._drafts_db(),
        batch=_batch(e_id),
        proposals=_proposals(x_id, y_id),
        text_of=_text_of,
        created_by="tester",
    )


def _links_from(statement_id: str) -> list[tuple[str, str]]:
    rows = store.substrate_connection().execute(
        "SELECT to_statement_id, link_type FROM statement_links "
        "WHERE from_statement_id = ? ORDER BY to_statement_id, link_type",
        (statement_id,),
    )
    return [(row["to_statement_id"], row["link_type"]) for row in rows]


def test_assemble_and_apply_transfers_links_and_records_proposals(
    tmp_path, monkeypatch
):
    with _app(tmp_path, monkeypatch):
        x_id, e_id, y_id = _existing_statements()
        draft_id = _assemble(x_id, e_id, y_id)

        draft = server.get_draft(draft_id)
        assert [op["kind"] for op in draft["ops"]] == [
            "upsert_statements",
            "add_links",
            "merge_statements",
            "report_knowledge_gap",
        ]
        assert draft["ops"][0]["provenance"] is None
        assert [op["provenance"] for op in draft["ops"][1:]] == [
            proposal.provenance for proposal in _proposals(x_id, y_id)
        ]
        assert draft["ops"][1]["payload"]["links"][0]["from_id"] == "@1:0"
        assert summarize(server._drafts_db(), draft_id) == {
            "draft_id": draft_id,
            "statements": 2,
            "links": 1,
            "merges": 1,
            "conflicts": 1,
        }

        applied = server.apply_draft(draft_id)
        batch_result = applied["results"][0]["result"]["results"]
        merged_id = batch_result[0]["statement_id"]
        sibling_id = batch_result[1]["statement_id"]
        conn = store.substrate_connection()

        assert store.get_statement(conn, merged_id) is None
        assert _links_from(x_id).count((e_id, "requires")) == 1
        assert (y_id, "requires") in _links_from(x_id)
        assert _links_from(sibling_id) == [(x_id, "triggers")]

        gaps = store.list_knowledge_gaps(conn)
        assert len(gaps) == 1
        assert "system sends a verification email" in gaps[0]["text"]
        assert y_id in gaps[0]["text"]
        unresolved_links = conn.execute(
            "SELECT COUNT(*) AS n FROM statement_links "
            "WHERE from_statement_id LIKE '@%:%' OR to_statement_id LIKE '@%:%'"
        ).fetchone()["n"]
        unresolved_gaps = conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_gaps WHERE text LIKE '%@1:%'"
        ).fetchone()["n"]
        assert unresolved_links == 0
        assert unresolved_gaps == 0


def test_merge_proposal_can_be_removed_before_approval(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        x_id, e_id, y_id = _existing_statements()
        draft_id = _assemble(x_id, e_id, y_id)
        merge_op = next(
            op
            for op in server.get_draft(draft_id)["ops"]
            if op["kind"] == "merge_statements"
        )

        server.discard_draft_op(draft_id=draft_id, seq=merge_op["seq"])
        applied = server.apply_draft(draft_id)
        batch_result = applied["results"][0]["result"]["results"]
        first_id = batch_result[0]["statement_id"]

        assert store.get_statement(store.substrate_connection(), first_id) is not None
        assert _links_from(x_id) == [(e_id, "requires")]
        assert (e_id, "requires") in _links_from(first_id)


def test_unresolvable_draft_reference_rolls_back_every_statement(tmp_path, monkeypatch):
    with _app(tmp_path, monkeypatch):
        _, _, y_id = _existing_statements()
        batch = [
            BatchInput(kind="event", text="user clicks the login button"),
            BatchInput(kind="event", text="user must verify email"),
        ]
        proposals = [
            Proposal(
                kind="link",
                new_index=1,
                target=y_id,
                link_type="requires",
                provenance={
                    "source": "rule",
                    "pattern": "requires-must-have",
                    "cue": "must",
                    "target_text": "verify email",
                    "score": 0.8,
                    "link_type": "requires",
                },
            )
        ]
        draft_id = assemble_draft(
            server._drafts_db(),
            batch=batch,
            proposals=proposals,
            text_of=_text_of,
            created_by="tester",
        )
        conn = store.substrate_connection()
        before = conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()["n"]

        with pytest.raises(RuntimeError, match=r"op seq=2 references @1:1"):
            server.apply_draft(draft_id)

        after = conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()["n"]
        assert after == before
