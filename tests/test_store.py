from mycelium import store


def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def test_entity_and_name_roundtrip():
    conn = fresh_conn()
    eid = store.create_entity(conn, "User authentication surface")
    assert eid.startswith("ent_")
    assert store.get_entity_by_id(conn, eid)["description"] == "User authentication surface"

    nid = store.create_name(conn, "Login", eid)
    assert nid.startswith("nam_")

    by_text = store.get_name_by_text(conn, "Login")
    assert by_text["id"] == nid
    assert by_text["entity_id"] == eid

    # Name text must be unique globally
    other = store.create_entity(conn, None)
    try:
        store.create_name(conn, "Login", other)
    except Exception as exc:
        assert "UNIQUE" in str(exc)
    else:
        raise AssertionError("expected UNIQUE constraint to fail")


def test_statement_roundtrip_with_mentions_and_links():
    conn = fresh_conn()
    e1 = store.create_entity(conn, None)
    e2 = store.create_entity(conn, None)
    n1 = store.create_name(conn, "Login", e1)
    n2 = store.create_name(conn, "Session", e2)

    b1 = store.create_statement(conn, "event", "User logs in")
    b2 = store.create_statement(conn, "event", "Server issues a session token")

    store.set_vector_id(conn, b1, store.next_vector_id(conn))
    store.set_vector_id(conn, b2, store.next_vector_id(conn))
    assert store.get_statement_id_by_vector_id(conn, 1) == b2

    store.replace_mentions(conn, b1, [n1, n2])
    rows = store.get_mentions(conn, b1)
    assert {(r["name"], r["entity_id"]) for r in rows} == {("Login", e1), ("Session", e2)}

    # replace narrows the mention set
    store.replace_mentions(conn, b1, [n1])
    rows = store.get_mentions(conn, b1)
    assert [(r["name"], r["entity_id"]) for r in rows] == [("Login", e1)]

    store.replace_links(conn, b1, [(b2, "triggers", None)])
    assert store.get_links(conn, b1) == [(b2, "triggers", None)]
    assert store.get_incoming_links(conn, b2) == [(b1, "triggers", None)]
    assert store.get_incoming_links(conn, b1) == []
    assert store.list_link_types(conn) == ["triggers"]


def test_statement_kind_round_trips_starting_vocabulary():
    """The starting vocabulary (event/state/capability) plus a custom
    kind all round-trip. Substrate is open: it doesn't reject novel kinds."""
    conn = fresh_conn()
    ids = {
        kind: store.create_statement(conn, kind, f"text for {kind}")
        for kind in ("event", "state", "capability", "policy")
    }
    for kind, sid in ids.items():
        row = store.get_statement(conn, sid)
        assert row["kind"] == kind


def test_statement_kind_is_not_null():
    """Substrate enforces NOT NULL on statement kind."""
    import sqlite3

    conn = fresh_conn()
    try:
        store.create_statement(conn, None, "missing kind")  # type: ignore[arg-type]
    except sqlite3.IntegrityError as exc:
        assert "NOT NULL" in str(exc) or "kind" in str(exc)
    else:
        raise AssertionError("expected NOT NULL constraint failure")


def test_list_and_grep_statements_filter_by_kind():
    conn = fresh_conn()
    ev = store.create_statement(conn, "event", "user logs in")
    st = store.create_statement(conn, "state", "session is active")
    cap = store.create_statement(conn, "capability", "admin can revoke session")

    by_event = [r["id"] for r in store.list_statements(conn, kind="event")]
    by_state = [r["id"] for r in store.list_statements(conn, kind="state")]
    by_cap = [r["id"] for r in store.list_statements(conn, kind="capability")]
    assert by_event == [ev]
    assert by_state == [st]
    assert by_cap == [cap]
    assert store.count_statements(conn, kind="event") == 1
    assert store.count_statements(conn, kind="state") == 1

    # grep filter narrows by kind
    hits = [r["id"] for r in store.grep_statements(conn, "session", kind="state")]
    assert hits == [st]
    hits = [r["id"] for r in store.grep_statements(conn, "session", kind="capability")]
    assert hits == [cap]
    assert store.count_grep_statements(conn, "session", kind="state") == 1


def test_reassign_and_set_name_entity():
    conn = fresh_conn()
    src = store.create_entity(conn, "src")
    dst = store.create_entity(conn, "dst")
    n1 = store.create_name(conn, "alpha", src)
    n2 = store.create_name(conn, "beta", src)

    moved = store.reassign_names(conn, src, dst)
    assert moved == 2
    assert store.get_name_by_id(conn, n1)["entity_id"] == dst
    assert store.get_name_by_id(conn, n2)["entity_id"] == dst

    # set_name_entity moves a single name back
    store.set_name_entity(conn, n1, src)
    assert store.get_name_by_id(conn, n1)["entity_id"] == src
    assert store.get_name_by_id(conn, n2)["entity_id"] == dst

    # FK enforcement: deleting an entity that still has names attached fails
    import sqlite3
    try:
        store.delete_entity(conn, dst)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("expected FK violation deleting entity with attached names")

    # Move the remaining name off, then delete cleanly
    store.set_name_entity(conn, n2, src)
    store.delete_entity(conn, dst)
    assert store.get_entity_by_id(conn, dst) is None
