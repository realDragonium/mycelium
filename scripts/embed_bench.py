"""Benchmark embedding-model and alias-augmentation behavior.

Probes two questions:
  1. How well does the current model (and alternatives) handle paraphrase?
     -> paraphrase_pairs section
  2. Does appending alias text to a statement's embedding text improve
     recall for queries that use the alias, without harming recall for
     queries that use the canonical name?
     -> alias_cases section

Run:
  uv run python scripts/embed_bench.py [model_name]
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")

from ollama import Client  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "nomic-embed-text"
client = Client(host=os.environ["OLLAMA_URL"])


def embed(text: str) -> list[float]:
    r = client.embeddings(model=MODEL, prompt=text)
    return list(r["embedding"])


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Paraphrase sensitivity — does the model see semantically-equivalent
# rephrasings as close? Higher is better.
# ---------------------------------------------------------------------------

paraphrase_pairs = [
    (
        "A re-embedding is scheduled for the statement",
        "The record's re-embedding is queued for processing",
    ),
    (
        "The link type is resolved for the edge",
        "The type associated with the edge is determined",
    ),
    (
        "A statement is appended to the next position in a chain",
        "The record advances to the following position",
    ),
    (
        "The count of incoming links can gate a statement merge",
        "A threshold on incoming edges blocks a merge",
    ),
    (
        "A scheduled re-embedding is abandoned",
        "The queued re-embedding is canceled",
    ),
]


# ---------------------------------------------------------------------------
# Alias-augmentation — Statement entity has aliases {record, node, claim}.
# Real statement texts use "statement" or "record". Queries phrased with
# "node" should still hit.
# ---------------------------------------------------------------------------

ENTITY_ALIASES = {
    "Statement": ["record", "node", "claim"],
}

alias_cases = [
    {
        "statement": "The statement is resolved for the query",
        "aliases": ENTITY_ALIASES["Statement"],
        "canonical_query": "how is the statement chosen for a query",
        "alias_query": "how is the node chosen for a query",
        "control_query": "default embedding batch size",
    },
    {
        "statement": "A statement is linked to the starting node of a chain",
        "aliases": ENTITY_ALIASES["Statement"],
        "canonical_query": "where does a statement enter the chain",
        "alias_query": "where does a node enter the chain",
        "control_query": "vector index rebuild schedule",
    },
    {
        "statement": "The server default statement kind is applied",
        "aliases": ENTITY_ALIASES["Statement"],
        "canonical_query": "server default statement kind fallback",
        "alias_query": "server default node kind fallback",
        "control_query": "OIDC token refresh interval",
    },
    {
        "statement": "No embedding on the statement",
        "aliases": ENTITY_ALIASES["Statement"],
        "canonical_query": "statement without an embedding",
        "alias_query": "node without an embedding",
        "control_query": "OAuth callback signing key",
    },
]


def augment(text: str, aliases: list[str]) -> str:
    return text + " | " + ", ".join(aliases)


def run() -> None:
    print(f"# model: {MODEL}\n")

    print("## paraphrase sensitivity (higher = better, semantically equivalent pairs)")
    paraphrase_scores = []
    for a, b in paraphrase_pairs:
        s = cos(embed(a), embed(b))
        paraphrase_scores.append(s)
        print(f"  {s:.3f}  {a[:50]}  ~  {b[:50]}")
    print(f"  mean: {sum(paraphrase_scores) / len(paraphrase_scores):.3f}\n")

    print("## alias augmentation (statement TEXT vs statement TEXT+ALIASES)")
    print("    canonical/alias/control deltas should be: ~0 / positive / ~0")
    deltas_canonical = []
    deltas_alias = []
    deltas_control = []
    raw_alias_plain = []
    raw_alias_aug = []
    for case in alias_cases:
        text = case["statement"]
        aug = augment(text, case["aliases"])
        ev_text = embed(text)
        ev_aug = embed(aug)
        q_canon = embed(case["canonical_query"])
        q_alias = embed(case["alias_query"])
        q_ctrl = embed(case["control_query"])

        c_text = cos(ev_text, q_canon)
        c_aug = cos(ev_aug, q_canon)
        a_text = cos(ev_text, q_alias)
        a_aug = cos(ev_aug, q_alias)
        x_text = cos(ev_text, q_ctrl)
        x_aug = cos(ev_aug, q_ctrl)

        deltas_canonical.append(c_aug - c_text)
        deltas_alias.append(a_aug - a_text)
        deltas_control.append(x_aug - x_text)
        raw_alias_plain.append(a_text)
        raw_alias_aug.append(a_aug)

        print(f"\n  stmt: {text}")
        print(
            f"    canonical q: text={c_text:.3f}  aug={c_aug:.3f}  Δ={c_aug - c_text:+.3f}"
        )
        print(
            f"    alias q    : text={a_text:.3f}  aug={a_aug:.3f}  Δ={a_aug - a_text:+.3f}"
        )
        print(
            f"    control q  : text={x_text:.3f}  aug={x_aug:.3f}  Δ={x_aug - x_text:+.3f}"
        )

    print("\n## summary")
    print(
        f"  mean Δ canonical-query similarity (want ~0): {sum(deltas_canonical) / len(deltas_canonical):+.3f}"
    )
    print(
        f"  mean Δ alias-query    similarity (want +): {sum(deltas_alias) / len(deltas_alias):+.3f}"
    )
    print(
        f"  mean Δ control-query  similarity (want ~0): {sum(deltas_control) / len(deltas_control):+.3f}"
    )
    print(
        f"  mean alias-query similarity, plain  : {sum(raw_alias_plain) / len(raw_alias_plain):.3f}"
    )
    print(
        f"  mean alias-query similarity, augmented: {sum(raw_alias_aug) / len(raw_alias_aug):.3f}"
    )


if __name__ == "__main__":
    run()
