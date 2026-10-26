"""hnswlib wrapper for statement embeddings.

Cosine space, 768-dim. In-memory index persisted to disk on every write.
"""

from __future__ import annotations

from pathlib import Path

import hnswlib
import numpy as np
from numpy.typing import NDArray

DIM = 768
INITIAL_CAPACITY = 10_000
EF_CONSTRUCTION = 200
M = 16
EF_SEARCH = 50


class Index:
    def __init__(
        self, index: hnswlib.Index, allowed: frozenset[int] | None = None
    ) -> None:
        self._index = index
        self._allowed = allowed

    def restricted(self, allowed: frozenset[int]) -> Index:
        """A read-only view whose searches rank only `allowed` ids, so a
        top-k is the k nearest allowed vectors rather than whatever of the
        global top-k survives a filter."""
        return Index(self._index, allowed)

    @classmethod
    def empty(cls) -> Index:
        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.init_index(
            max_elements=INITIAL_CAPACITY,
            ef_construction=EF_CONSTRUCTION,
            M=M,
            allow_replace_deleted=True,
        )
        idx.set_ef(EF_SEARCH)
        return cls(idx)

    @classmethod
    def load(cls, path: Path) -> Index:
        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.load_index(str(path), allow_replace_deleted=True)
        if idx.get_max_elements() < INITIAL_CAPACITY:
            idx.resize_index(INITIAL_CAPACITY)
        idx.set_ef(EF_SEARCH)
        return cls(idx)

    def restore(self, path: Path) -> None:
        """Reload a saved index while preserving this wrapper's identity."""
        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.load_index(str(path), allow_replace_deleted=True)
        # hnswlib loads an empty index with zero capacity instead of the saved value.
        if idx.get_max_elements() < INITIAL_CAPACITY:
            idx.resize_index(INITIAL_CAPACITY)
        idx.set_ef(EF_SEARCH)
        self._index = idx

    def save(self, path: Path) -> None:
        self._index.save_index(str(path))

    def _ensure_capacity(self, want: int) -> None:
        cap = self._index.get_max_elements()
        if want >= cap:
            self._index.resize_index(max(cap * 2, want + 1))

    def add(self, vector_id: int, vec: list[float]) -> None:
        """Store `vec` under `vector_id`, overwriting a live or deleted slot
        that already carries the label."""
        arr = np.asarray(vec, dtype=np.float32).reshape(1, DIM)
        labels = np.array([vector_id], dtype=np.int64)
        try:
            self._index.unmark_deleted(vector_id)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "not found" in msg:
                # hnswlib's replace_deleted fills an arbitrary deleted slot
                # without checking that the label is new, and drops whichever
                # label that slot carried from its lookup. Given a label it
                # already holds, that strands the label's own slot and can
                # erase a live label, so reuse a vacant slot only here.
                self._ensure_capacity(self._index.get_current_count() + 1)
                self._index.add_items(arr, labels, replace_deleted=True)
                return
            if "not deleted" not in msg:
                raise
        self._index.add_items(arr, labels)

    def replace(self, vector_id: int, vec: list[float]) -> None:
        """Replace the vector at `vector_id` with `vec`, adding a label the
        index is missing."""
        self.add(vector_id, vec)

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

    def ids(self) -> list[int]:
        """Labels present in the index. May include slots already marked
        deleted (hnswlib keeps them addressable); callers pruning via
        `delete()` don't care — it is idempotent."""
        return [int(x) for x in self._index.get_ids_list()]

    def get_vector(self, vector_id: int) -> NDArray[np.float32] | None:
        """Return the stored vector at `vector_id`, or `None` if the
        slot is missing from the index.

        `None` covers the same drift mode `delete()` documents: the
        SQLite `statement_vector_ids` mapping references a slot that
        was never added to (or has fallen out of) the on-disk hnsw
        file. Callers that walk every statement — `find_duplicates`
        being the canonical one — must skip these stranded ids
        rather than crash the whole pass on the first one.
        """
        try:
            row: NDArray[np.float32] = self._index.get_items([vector_id])[0]
            return row
        except RuntimeError as exc:
            if "not found" in str(exc).lower():
                return None
            raise

    def search(
        self, vec: list[float] | NDArray[np.float32], k: int
    ) -> list[tuple[int, float]]:
        if self._index.get_current_count() == 0:
            return []
        k = min(k, self._index.get_current_count())
        allowed = self._allowed
        if allowed is not None:
            k = min(k, len(allowed))
        arr = np.asarray(vec, dtype=np.float32).reshape(1, DIM)
        # hnswlib's knn_query raises when ef can't fill k non-deleted
        # candidates (small indexes with deletes hit this). Walk k down
        # until it succeeds or hits zero.
        while k > 0:
            try:
                if allowed is None:
                    labels, distances = self._index.knn_query(arr, k=k)
                else:
                    labels, distances = self._index.knn_query(
                        arr, k=k, filter=lambda label: label in allowed
                    )
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
