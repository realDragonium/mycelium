"""The hard audience boundary a documentation run's substrate reads see."""

from __future__ import annotations

import numpy as np
import pytest

from mycelium import audience_scope, store, vector
from mycelium.audiences import Audience

INTERNAL = Audience("internal-technical", "Internal technical", "internal", "All.", 1)
EXTERNAL = Audience(
    "external-technical", "External technical", "external", "Integrators.", 1
)


@pytest.fixture
def db(tmp_path):
    conn = store.connect(tmp_path / "mycelium.db")
    store.migrate(conn)
    try:
        yield conn
    finally:
        conn.close()


def _corpus(conn):
    public = store.create_statement(conn, "state", "the workspace export is csv")
    private = store.create_statement(conn, "state", "the export job runs on worker b")
    entity = store.create_entity(conn, "Curator notes on the export.")
    exported = store.create_name(conn, "workspace export", entity)
    store.create_name(conn, "export job", entity)
    other = store.create_entity(conn, "An internal queue.")
    store.create_name(conn, "worker b", other)
    store.insert_entity_links(conn, [(entity, other, "uses")])
    index = store.build_name_index(conn)
    for sid, text in (
        (public, "the workspace export is csv"),
        (private, "the export job runs on worker b"),
    ):
        store.derive_mentions(conn, sid, text, index)
    store.insert_links(conn, [(public, private, "requires", None)])
    store.audience_labels.set_label(
        conn, public, [INTERNAL.id, EXTERNAL.id], source="ai", reason="r"
    )
    conn.commit()
    return public, private, entity, exported, other


def _read(conn, audience, sql):
    scope = audience_scope.capture(conn, audience)
    with audience_scope.applied(conn, scope):
        return [tuple(row) for row in conn.execute(sql)]


def test_an_external_audience_sees_only_granted_statements_and_matched_names(db):
    public, _private, entity, exported, other = _corpus(db)

    assert _read(db, EXTERNAL, "SELECT id FROM statements") == [(public,)]
    assert _read(db, EXTERNAL, "SELECT COUNT(*) FROM statement_links") == [(0,)]
    assert _read(db, EXTERNAL, "SELECT id, description FROM entities") == [
        (entity, None)
    ]
    assert _read(db, EXTERNAL, "SELECT id FROM names") == [(exported,)]
    assert _read(db, EXTERNAL, "SELECT COUNT(*) FROM entity_links") == [(0,)]
    assert other not in {
        row[0] for row in _read(db, EXTERNAL, "SELECT entity_id FROM names")
    }


def test_an_internal_audience_sees_unlabelled_statements_and_curator_prose(db):
    _public, private, entity, _exported, _other = _corpus(db)

    assert private in {
        row[0] for row in _read(db, INTERNAL, "SELECT id FROM statements")
    }
    assert _read(db, INTERNAL, "SELECT COUNT(*) FROM statement_links") == [(1,)]
    assert (entity, "Curator notes on the export.") in _read(
        db, INTERNAL, "SELECT id, description FROM entities"
    )
    assert _read(db, INTERNAL, "SELECT COUNT(*) FROM entity_links") == [(1,)]


def test_scoped_reads_page_by_the_statement_rowid(db):
    public, *_rest = _corpus(db)
    assert _read(
        db, EXTERNAL, "SELECT s.id FROM statements s WHERE s.rowid > 0 ORDER BY rowid"
    ) == [(public,)]


def test_the_scope_is_gone_after_the_read(db):
    _corpus(db)
    _read(db, EXTERNAL, "SELECT 1")
    assert db.execute("SELECT COUNT(*) FROM statements").fetchone()[0] == 2
    assert audience_scope.active() is None


def test_a_restricted_vector_index_ranks_only_visible_statements():
    index = vector.Index.empty()
    near, far = (
        np.zeros(vector.DIM, dtype=np.float32),
        np.zeros(vector.DIM, dtype=np.float32),
    )
    near[0], far[1] = 1.0, 1.0
    index.add(1, near.tolist())
    index.add(2, far.tolist())

    assert [vid for vid, _ in index.restricted(frozenset({2})).search(near, 5)] == [2]
    assert index.restricted(frozenset()).search(near, 5) == []
