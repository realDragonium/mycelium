"""Regression: restoring a substrate without its .vec files rebuilds both
vector indexes from the DB.

`backup.sh` omits the (re-derivable) `*.vec` files but keeps the whole
`mycelium.db`, including the `statement_vector_ids` / `name_vector_ids`
mappings. On the next `init` the .vec files are missing while the mappings
remain, so both indexes must be rebuilt by re-embedding — reusing the existing
vector ids — or search silently returns nothing against a populated substrate
(DRA-96).
"""

from __future__ import annotations

import zlib

import numpy as np

from mycelium import embed, phrasing, server, store


def _embed(text: str) -> list[float]:
    """Deterministic per-text embedding: identical text → identical vector, so
    querying the exact text scores cosine 1.0 against its own statement/name."""
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    return np.random.default_rng(seed).standard_normal(768).astype(np.float32).tolist()


def _restart(data_dir) -> None:
    """Re-run init against the same dir, simulating a process restart."""
    server._ctx = None
    server.init(data_dir)


def test_restore_without_vec_files_rebuilds_both_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "embed", _embed)
    monkeypatch.setattr(phrasing, "check", lambda text, kind=None: [])
    monkeypatch.setenv("MYCELIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MYCELIUM_AUTH", "off")

    server._ctx = None
    server.init(tmp_path)

    server.upsert_entity(name="candidate", description="a job candidate")
    stmt_text = "the candidate is screened"
    sid = server.upsert_statement(kind="state", text=stmt_text, links=[])[
        "statement_id"
    ]

    conn = store.substrate_connection()
    stmt_vid = store.get_vector_id(conn, sid)
    name_row = store.list_all_names(conn)[0]
    name_vid = store.get_name_vector_id(conn, name_row["id"])
    assert stmt_vid is not None and name_vid is not None

    # Simulate a backup.sh restore: substrate present, .vec files gone.
    (tmp_path / "mycelium.vec").unlink()
    (tmp_path / "mycelium-names.vec").unlink()

    _restart(tmp_path)

    # Statement index rebuilt: the exact-text query finds the statement.
    hits = server.search_statements(stmt_text, limit=5, name_boost=0.0)
    assert sid in {h["id"] for h in hits}

    # Name index rebuilt: querying the name text returns its mapping.
    name_hits = server._name_idx().search(_embed("candidate"), k=1)
    assert name_hits, "name index is empty after restore"
    found_vid = name_hits[0][0]
    assert (
        store.get_name_id_by_vector_id(store.substrate_connection(), found_vid)
        == (name_row["id"])
    )

    # Existing vector ids are reused, not reallocated — rows that reference
    # them stay valid.
    conn = store.substrate_connection()
    assert store.get_vector_id(conn, sid) == stmt_vid
    assert store.get_name_vector_id(conn, name_row["id"]) == name_vid
