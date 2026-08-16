from mycelium import store


def fresh_conn():
    conn = store.connect(":memory:")
    store.migrate(conn)
    return conn


def live_link_types(conn):
    glossary_types = {
        row["link_type"] for row in store.list_statement_link_type_glossary(conn)
    }
    return frozenset(glossary_types | set(store.list_link_types(conn)))


def test_migrate_seeds_matrix_from_direction_rules():
    conn = fresh_conn()
    rows = {
        (row["from_kind"], row["to_kind"], row["link_type"])
        for row in store.list_kind_link_matrix(conn)
    }

    assert rows
    assert ("event", "state", "establishes") in rows
    assert ("event", "event", "teaches") not in rows


def test_known_pair_returns_only_its_configured_types():
    conn = fresh_conn()

    link_types = store.admissible_link_types(conn, "event", "state")

    assert "establishes" in link_types
    assert "triggers" in link_types
    assert "teaches" not in link_types


def test_unknown_kind_on_either_side_returns_live_vocabulary():
    conn = fresh_conn()
    vocabulary = live_link_types(conn)

    assert store.admissible_link_types(conn, "widget", "state") == vocabulary
    assert store.admissible_link_types(conn, "event", "widget") == vocabulary


def test_set_admissible_replaces_pair_rows():
    conn = fresh_conn()

    store.set_admissible(conn, "event", "state", ["triggers"])

    assert store.admissible_link_types(conn, "event", "state") == frozenset(
        {"triggers"}
    )


def test_second_seed_does_not_resurrect_deleted_row():
    conn = fresh_conn()
    conn.execute(
        "DELETE FROM kind_link_matrix "
        "WHERE from_kind = 'event' AND to_kind = 'state' "
        "AND link_type = 'establishes'"
    )

    assert store.seed_kind_link_matrix(conn) == 0

    rows = {
        (row["from_kind"], row["to_kind"], row["link_type"])
        for row in store.list_kind_link_matrix(conn)
    }
    assert ("event", "state", "establishes") not in rows


def test_seed_includes_kind_present_only_on_a_statement():
    conn = store.connect(":memory:")
    conn.executescript(store.SCHEMA)
    store.create_statement(conn, "widget", "A widget exists")

    store.migrate(conn)

    assert any(
        row["from_kind"] == "widget" for row in store.list_kind_link_matrix(conn)
    )
