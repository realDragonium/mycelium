import numpy as np

from mycelium import vector


def rand_vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(vector.DIM).astype(np.float32).tolist()


def test_add_and_search():
    idx = vector.Index.empty()

    v0 = rand_vec(1)
    v1 = rand_vec(2)
    idx.add(0, v0)
    idx.add(1, v1)

    hits = idx.search(v0, k=2)
    assert len(hits) == 2
    # nearest neighbor of v0 should be itself
    assert hits[0][0] == 0


def test_replace_then_search(tmp_path):
    idx = vector.Index.empty()
    idx.add(0, rand_vec(1))
    idx.add(1, rand_vec(2))

    new_v = rand_vec(99)
    idx.replace(0, new_v)
    hits = idx.search(new_v, k=2)
    assert hits[0][0] == 0


def test_save_and_load(tmp_path):
    path = tmp_path / "x.bin"
    idx = vector.Index.empty()
    idx.add(7, rand_vec(3))
    idx.save(path)

    idx2 = vector.Index.load(path)
    hits = idx2.search(rand_vec(3), k=1)
    assert hits[0][0] == 7


def test_search_empty_index():
    idx = vector.Index.empty()
    assert idx.search(rand_vec(1), k=5) == []


def test_get_vector_returns_none_on_missing_label():
    """Same drift mode as delete(): SQLite vector_id mapping can
    reference a slot the hnsw file doesn't have. get_vector must
    return None rather than raise so audit-shaped callers
    (find_duplicates) can skip stranded ids and finish the pass.
    """
    idx = vector.Index.empty()
    idx.add(0, rand_vec(1))

    assert idx.get_vector(0) is not None
    assert idx.get_vector(999) is None


def test_delete_is_idempotent_on_missing_label():
    """If the vector index falls out of sync with the SQLite vector_id
    mapping (e.g. partial write, backup/restore mismatch) and a caller
    asks to delete a label that hnswlib doesn't have, delete() must
    treat it as a no-op rather than raise. Without this, the
    surrounding cascade in delete_statement raises after partial cleanup
    and leaves the SQL row orphaned with no way for the caller to
    recover except via direct DB surgery.
    """
    idx = vector.Index.empty()
    idx.add(0, rand_vec(1))

    # Slot exists — first delete marks it.
    idx.delete(0)
    # Slot already marked deleted — second delete is a no-op.
    idx.delete(0)
    # Label that was never added — also a no-op.
    idx.delete(999)
