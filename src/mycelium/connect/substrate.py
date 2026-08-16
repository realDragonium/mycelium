"""Adapt the running server's stores and indexes to the candidate funnel."""

from __future__ import annotations

import importlib
from types import ModuleType

import numpy as np

from mycelium import mentions, store


def _as_cosine(value: float) -> float:
    """Clamp a computed similarity into the cosine range.

    hnswlib returns a slightly negative distance for a vector identical to the
    query (float32 rounding), so `1 - distance` overshoots 1.0 by ~2e-7; the
    numpy dot product overshoots the same way. Consumers are entitled to a
    number in [-1, 1].
    """
    return max(-1.0, min(1.0, value))


class LiveSubstrate:
    """Expose the running substrate through the funnel's view.

    One instance is meant to serve one batch. Its lazily built name index and matrix
    lookups are snapshots that would become stale in a long-lived instance.
    """

    def __init__(self, server_module: ModuleType | None = None) -> None:
        self._server = server_module or importlib.import_module("mycelium.server")
        self._names: dict[str, list[mentions.IndexedName]] | None = None
        self._admissible_link_types: dict[tuple[str, str], frozenset[str]] = {}

    def _name_index(self) -> dict[str, list[mentions.IndexedName]]:
        if self._names is None:
            self._names = store.build_name_index(self._server._db())
        return self._names

    def embed(self, text: str) -> list[float]:
        """Embed text through the server's retry boundary."""
        return self._server._embed_with_retry(text)

    def neighbours(self, vec: list[float], k: int) -> list[tuple[str, float]]:
        """Resolve vector neighbours to live statement ids and cosine scores."""
        conn = self._server._db()
        resolved = []
        for vector_id, distance in self._server._search_index_with_retry(vec, k):
            statement_id = store.get_statement_id_by_vector_id(conn, vector_id)
            if statement_id is not None:
                resolved.append((statement_id, _as_cosine(1.0 - distance)))
        return resolved

    def similarity(self, vec: list[float], statement_id: str) -> float | None:
        """Compute cosine similarity to a statement's indexed vector."""
        vector_id = store.get_vector_id(self._server._db(), statement_id)
        if vector_id is None:
            return None
        stored = self._server._idx().get_vector(vector_id)
        if stored is None:
            return None
        query_array = np.asarray(vec, dtype=np.float32)
        stored_array = np.asarray(stored, dtype=np.float32)
        query_norm = float(np.linalg.norm(query_array))
        stored_norm = float(np.linalg.norm(stored_array))
        if query_norm == 0 or stored_norm == 0:
            return None
        return _as_cosine(
            float(np.dot(query_array / query_norm, stored_array / stored_norm))
        )

    def entities_in(self, text: str) -> frozenset[str]:
        """Derive the entity identities mentioned by text."""
        result = mentions.match_text(text, self._name_index())
        return frozenset(mention.entity_id for mention in result.mentions)

    def statements_sharing(
        self, entity_ids: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        """Group materialized statement mentions by shared entity identity."""
        if not entity_ids:
            return {}
        grouped: dict[str, set[str]] = {}
        rows = store.statements_sharing_entities(self._server._db(), entity_ids)
        for statement_id, entity_id in rows:
            grouped.setdefault(statement_id, set()).add(entity_id)
        return {
            statement_id: frozenset(shared) for statement_id, shared in grouped.items()
        }

    def kind_of(self, statement_id: str) -> str | None:
        """Return the current kind of a statement that still exists."""
        statement = store.get_statement(self._server._db(), statement_id)
        return None if statement is None else statement["kind"]

    def admissible_link_types(self, from_kind: str, to_kind: str) -> frozenset[str]:
        """Return link types the ontology admits from a source kind to a target."""
        key = (from_kind, to_kind)
        if key not in self._admissible_link_types:
            self._admissible_link_types[key] = store.admissible_link_types(
                self._server._db(), from_kind, to_kind
            )
        return self._admissible_link_types[key]
