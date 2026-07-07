"""One-shot recovery for stranded statement vectors.

A stranded vector_id is one that exists in `statement_vector_ids`
(SQLite) but is missing from the on-disk hnsw index — drift
introduced by a partial write or a backup/restore mismatch.
Stranded statements don't surface in `search_statements` and crash
`find_duplicates` if `Index.get_vector` raises (pre-fix only;
the current code skips them silently). This script restores them
to the index by re-embedding the statement text and inserting it
at the existing vector_id with `replace_deleted=True`.

Dry-run by default — only re-embeds when `--apply` is passed.

Usage:
    uv run python scripts/recover_stranded_vectors.py /path/to/data_dir
    uv run python scripts/recover_stranded_vectors.py /path/to/data_dir --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from mycelium import embed, store, vector


def find_stranded(conn, index: vector.Index) -> list[tuple[int, str, str]]:
    """Return (vector_id, statement_id, text) for every statement whose
    vector_id is missing from the on-disk index."""
    stranded: list[tuple[int, str, str]] = []
    rows = conn.execute(
        """
        SELECT bvi.vector_id, bvi.statement_id, b.text
        FROM statement_vector_ids bvi
        JOIN statements b ON b.id = bvi.statement_id
        ORDER BY bvi.vector_id
        """
    ).fetchall()
    for row in rows:
        vid = int(row["vector_id"])
        if index.get_vector(vid) is None:
            stranded.append((vid, row["statement_id"], row["text"]))
    return stranded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, help="mycelium data directory")
    parser.add_argument(
        "--apply", action="store_true", help="Actually re-embed and write. Default is dry-run."
    )
    args = parser.parse_args()

    db_path = args.data_dir / "mycelium.db"
    vec_path = args.data_dir / "mycelium.vec"
    if not db_path.exists() or not vec_path.exists():
        print(f"error: {db_path} or {vec_path} missing", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    store.migrate(conn)

    index = vector.Index()
    index.load(vec_path)

    # Sanity check: confirm we're pointed at the substrate the operator
    # thinks they're pointed at. A wrong data_dir is the most likely
    # reason "no stranded vectors found" is a false negative.
    total_statements = conn.execute("SELECT COUNT(*) AS n FROM statements").fetchone()["n"]
    sample = conn.execute("SELECT text FROM statements LIMIT 1").fetchone()
    sample_preview = (
        sample["text"][:80].replace("\n", " ") if sample else "<empty>"
    )
    print(f"Substrate at {args.data_dir}")
    print(f"  statements: {total_statements}")
    print(f"  sample:    {sample_preview!r}")
    print()

    stranded = find_stranded(conn, index)
    print(f"Found {len(stranded)} stranded vector(s) in {vec_path}")
    for vid, bid, text in stranded:
        preview = text[:80].replace("\n", " ")
        print(f"  vid={vid}  bid={bid}  text={preview!r}")

    if not stranded:
        return 0

    if not args.apply:
        print("\nDry-run. Re-run with --apply to embed and re-insert.")
        return 0

    print("\nRe-embedding…")
    for vid, bid, text in stranded:
        vec = embed.embed(text)
        # Mirror Index.add: write directly via add_items so we land on
        # the existing vector_id rather than allocating a new slot.
        assert index._index is not None
        index._ensure_capacity(index._index.get_current_count() + 1)
        arr = np.asarray(vec, dtype=np.float32).reshape(1, vector.DIM)
        index._index.add_items(
            arr, np.array([vid], dtype=np.int64), replace_deleted=True
        )
        print(f"  recovered vid={vid} bid={bid}")

    index.save(vec_path)
    # Re-check post-write so the operator sees a clean "0 stranded" result
    # before exiting — confirms the save actually took.
    remaining = find_stranded(conn, index)
    print(f"\nSaved {vec_path}. Stranded vectors after recovery: {len(remaining)}")
    print("Verify with `find_duplicates` — recovered statements will surface "
          "if the texts genuinely duplicate existing records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
