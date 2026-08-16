"""Embed and compare link-type aliases stored as float32 blobs.

Cosine comparison is brute-force because a few hundred aliases is far below
the scale where a vector index earns its keep.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from .. import embed, store

CARRIER = "X {alias} Y"


def carrier_text(alias: str) -> str:
    """Render an alias as a sentence-encoder carrier instead of a bare word."""
    return CARRIER.format(alias=alias)


@dataclass(frozen=True)
class AliasVector:
    link_type: str
    alias: str
    vector: np.ndarray


def drain_alias_embeddings(
    conn: sqlite3.Connection,
    *,
    embed_text: Callable[[str], list[float]] = embed.embed,
    chunk: int = 50,
) -> int:
    """Drain alias embedding jobs in transactional chunks."""
    total = 0
    while True:
        with store.transaction(conn):
            rows = store.claim_alias_embeddings(conn, chunk)
            if not rows:
                return total

            for row in rows:
                # Deletion can race an already-claimed job; finishing it keeps
                # the durable queue from retaining work with no target row.
                if not store.link_type_alias_exists(
                    conn, row["link_type"], row["alias"]
                ):
                    continue
                vector = embed_text(carrier_text(row["alias"]))
                blob = np.asarray(vector, dtype=np.float32).tobytes()
                store.set_alias_embedding(conn, row["link_type"], row["alias"], blob)
                total += 1

            store.finish_alias_embeddings(conn, [row["id"] for row in rows])


def alias_vectors(conn: sqlite3.Connection) -> list[AliasVector]:
    """Load persisted float32 alias vectors."""
    return [
        AliasVector(
            link_type=row["link_type"],
            alias=row["alias"],
            vector=np.frombuffer(row["embedding"], dtype=np.float32),
        )
        for row in store.alias_vectors(conn)
    ]


def nearest_aliases(
    vector: np.ndarray,
    vectors: Sequence[AliasVector],
    k: int = 5,
) -> list[tuple[str, str, float]]:
    """Return the nearest aliases by cosine with stable tie ordering."""
    query = np.asarray(vector)
    query_norm = float(np.linalg.norm(query))
    scored: list[tuple[str, str, float]] = []
    for candidate in vectors:
        candidate_norm = float(np.linalg.norm(candidate.vector))
        if query_norm == 0.0 or candidate_norm == 0.0:
            cosine = 0.0
        else:
            cosine = float(
                np.dot(query, candidate.vector) / (query_norm * candidate_norm)
            )
        scored.append((candidate.link_type, candidate.alias, cosine))
    return sorted(scored, key=lambda item: (-item[2], item[0], item[1]))[:k]
