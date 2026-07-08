"""hnswlib wrapper for statement embeddings.

Cosine space, 768-dim. In-memory index persisted to disk on every write.
"""

from __future__ import annotations

from pathlib import Path

import hnswlib
import numpy as np

DIM = 768
INITIAL_CAPACITY = 10_000
EF_CONSTRUCTION = 200
M = 16
EF_SEARCH = 50


class Index:
    def __init__(self) -> None:
        self._index: hnswlib.Index | None = None

    def init_empty(self) -> None:
        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.init_index(
            max_elements=INITIAL_CAPACITY,
            ef_construction=EF_CONSTRUCTION,
            M=M,
            allow_replace_deleted=True,
        )
        idx.set_ef(EF_SEARCH)
        self._index = idx

    def load(self, path: Path) -> None:
        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.load_index(str(path), allow_replace_deleted=True)
        idx.set_ef(EF_SEARCH)
        self._index = idx

    def save(self, path: Path) -> None:
        assert self._index is not None
        self._index.save_index(str(path))

    def _ensure_capacity(self, want: int) -> None:
        assert self._index is not None
        cap = self._index.get_max_elements()
        if want >= cap:
            self._index.resize_index(max(cap * 2, want + 1))

    def add(self, vector_id: int, vec: list[float]) -> None:
        # `replace_deleted=True` is required because next_vector_id allocates
        # MAX(vector_id) + 1 from statement_vector_ids, and merge_statements
        # drops rows from that table — so after a merge the highest live id
        # may be lower than slots hnswlib still has in `mark_deleted` state.
        # A subsequent insert can therefore land on a slot hnswlib considers
        # deleted; without replace_deleted it raises "Can't use addPoint to
        # update deleted elements" mid-upsert, leaving the SQLite row written
        # but the vector missing.
        assert self._index is not None
        self._ensure_capacity(self._index.get_current_count() + 1)
        arr = np.asarray(vec, dtype=np.float32).reshape(1, DIM)
        self._index.add_items(
            arr, np.array([vector_id], dtype=np.int64), replace_deleted=True
        )

    def replace(self, vector_id: int, vec: list[float]) -> None:
        """Replace the vector at `vector_id` with `vec`."""
        assert self._index is not None
        self._index.mark_deleted(vector_id)
        arr = np.asarray(vec, dtype=np.float32).reshape(1, DIM)
        self._index.add_items(
            arr, np.array([vector_id], dtype=np.int64), replace_deleted=True
        )

    def delete(self, vector_id: int) -> None:
        """Mark the vector at `vector_id` deleted. The slot stays
        addressable for `replace()` later but stops surfacing in
        search results.

        Idempotent: if the label is already gone (e.g. the vector
        index file fell out of sync with the SQLite vector_id mapping
        after a partial write or a backup/restore), this is a no-op.
        The contract is "this vector will not surface in search" —
        a missing slot already satisfies that, and raising here would
        strand the caller's surrounding cascade (e.g. delete_statement
        leaves an orphaned SQL row when the vector op raises before
        the row is dropped).
        """
        assert self._index is not None
        try:
            self._index.mark_deleted(vector_id)
        except RuntimeError as exc:
            # hnswlib raises "Label not found" when the slot was never
            # added (vector index out of sync with SQLite mapping) and
            # "The requested to delete element is already deleted"
            # when the slot exists but was already marked deleted.
            # Both satisfy our contract.
            msg = str(exc).lower()
            if "not found" in msg or "already deleted" in msg:
                return
            raise

    def get_vector(self, vector_id: int) -> list[float] | None:
        """Return the stored vector at `vector_id`, or `None` if the
        slot is missing from the index.

        `None` covers the same drift mode `delete()` documents: the
        SQLite `statement_vector_ids` mapping references a slot that
        was never added to (or has fallen out of) the on-disk hnsw
        file. Callers that walk every statement — `find_duplicates`
        being the canonical one — must skip these stranded ids
        rather than crash the whole pass on the first one.
        """
        assert self._index is not None
        try:
            return self._index.get_items([vector_id])[0]
        except RuntimeError as exc:
            if "not found" in str(exc).lower():
                return None
            raise

    def search(self, vec: list[float], k: int) -> list[tuple[int, float]]:
        assert self._index is not None
        if self._index.get_current_count() == 0:
            return []
        k = min(k, self._index.get_current_count())
        arr = np.asarray(vec, dtype=np.float32).reshape(1, DIM)
        # hnswlib's knn_query raises when ef can't fill k non-deleted
        # candidates (small indexes with deletes hit this). Walk k down
        # until it succeeds or hits zero.
        while k > 0:
            try:
                labels, distances = self._index.knn_query(arr, k=k)
                break
            except RuntimeError:
                k -= 1
        else:
            return []
        return list(
            zip(
                (int(x) for x in labels[0]),
                (float(x) for x in distances[0]),
                strict=False,
            )
        )
