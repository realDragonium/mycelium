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
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Paraphrase sensitivity — does the model see semantically-equivalent
# rephrasings as close? Higher is better.
# ---------------------------------------------------------------------------

paraphrase_pairs = [
    (
        "A rejection is scheduled for the participant",
        "The candidate's rejection is queued for delivery",
    ),
    (
        "The selection flow is resolved for the invite",
        "The flow associated with the invite is determined",
    ),
    (
        "A participant is assigned to the next step",
        "The candidate progresses to the following step",
    ),
    (
        "The count of expected answers can gate flow advancement",
        "A pass threshold on correct answers blocks progression",
    ),
    (
        "A scheduled rejection is abandoned",
        "The queued rejection is canceled",
    ),
]


# ---------------------------------------------------------------------------
# Alias-augmentation — Selection Flow entity has aliases
# {selection-tree, flow, tree}. Real statement texts use "selection flow"
# or "flow". Queries phrased with "tree" should still hit.
# ---------------------------------------------------------------------------

ENTITY_ALIASES = {
    "Selection Flow": ["selection-tree", "flow", "tree"],
}

alias_cases = [
    {
        "statement": "The selection flow is resolved for the invite",
        "aliases": ENTITY_ALIASES["Selection Flow"],
        "canonical_query": "how is the selection flow chosen for an invite",
        "alias_query": "how is the tree chosen for an invite",
        "control_query": "default rejection delay duration",
    },
    {
        "statement": "A participant is assigned to the starting steps of a selection flow",
        "aliases": ENTITY_ALIASES["Selection Flow"],
        "canonical_query": "where does a participant enter the selection flow",
        "alias_query": "where does a participant enter the tree",
        "control_query": "checklist conversation summary message",
    },
    {
        "statement": "The company default selection flow is applied",
        "aliases": ENTITY_ALIASES["Selection Flow"],
        "canonical_query": "company default selection flow fallback",
        "alias_query": "company default tree fallback",
        "control_query": "rejection template configuration",
    },
    {
        "statement": "No job profile on the selection flow",
        "aliases": ENTITY_ALIASES["Selection Flow"],
        "canonical_query": "selection flow without a job profile",
        "alias_query": "tree without a job profile",
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
