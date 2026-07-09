"""End-to-end smoke test against the live MCP tool functions + Ollama.

Exercises every tool, then reopens the data dir to confirm persistence.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mycelium import server, store


def show(label: str, value) -> None:
    print(f"\n--- {label} ---")
    print(value)


def main() -> None:
    data_dir = Path("/tmp/mycelium_smoke")
    if data_dir.exists():
        shutil.rmtree(data_dir)

    server.init(data_dir)

    show(
        "upsert_entity Login",
        server.upsert_entity(
            name="Login",
            description="User authentication surface",
        ),
    )

    login_id = store.get_entity_by_name(server._conn, "Login")["id"]

    b1 = server.upsert_statement(
        text="User logs in with email and password",
        mentions=["Login", "Email"],
        links=[],
    )
    show("upsert_statement #1", b1)

    b2 = server.upsert_statement(
        text="Server issues a session token after a successful login",
        mentions=["Session"],
        links=[{"to_id": b1["statement_id"], "link_type": "triggered_by"}],
    )
    show("upsert_statement #2", b2)

    show("list_link_types", server.list_link_types())

    show(
        "upsert_name (alias)",
        server.upsert_name(
            text="sign-in",
            entity_id=login_id,
        ),
    )

    # Update statement #1 to verify the in-place replace path.
    b1_updated = server.upsert_statement(
        text="A user signs in with their email address and password",
        mentions=["Login", "Email", "Password"],
        links=[],
        id=b1["statement_id"],
    )
    show("upsert_statement #1 update", b1_updated)
    assert b1_updated["statement_id"] == b1["statement_id"]

    hits = server.search_statements(query="how does authentication work", limit=5)
    show("search_statements", hits)
    assert len(hits) == 2
    assert {h["id"] for h in hits} == {b1["statement_id"], b2["statement_id"]}

    # Verify entity auto-creation took effect.
    auto_email = store.get_entity_by_name(server._conn, "Email")
    auto_password = store.get_entity_by_name(server._conn, "Password")
    auto_session = store.get_entity_by_name(server._conn, "Session")
    assert auto_email and auto_password and auto_session, "auto-create entities failed"
    print("\nauto-created entities: Email, Password, Session — OK")

    # Verify upsert_name fails for unknown entity.
    try:
        server.upsert_name(text="bogus", entity_id="ent_does_not_exist")
    except ValueError as e:
        print(f"upsert_name unknown entity correctly raised: {e}")
    else:
        raise AssertionError("upsert_name should have raised on unknown entity")

    # Verify upsert_statement with bad id raises.
    try:
        server.upsert_statement(
            text="x", mentions=[], links=[], id="stm_does_not_exist"
        )
    except ValueError as e:
        print(f"upsert_statement unknown id correctly raised: {e}")
    else:
        raise AssertionError("upsert_statement should have raised on unknown id")

    # Confirm on-disk artifacts and reopen.
    db_path = data_dir / "mycelium.db"
    vec_path = data_dir / "mycelium.vec"
    assert db_path.exists() and vec_path.exists(), "data files missing"
    print(
        f"\nartifacts: {db_path} ({db_path.stat().st_size}B), "
        f"{vec_path} ({vec_path.stat().st_size}B)"
    )

    # Reopen to verify persistence.
    server._conn = None
    server._ctx = None
    server.init(data_dir)
    hits2 = server.search_statements(query="signing in to an account", limit=5)
    show("search after reopen", hits2)
    assert len(hits2) == 2

    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    main()
