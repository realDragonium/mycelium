"""Benchmark sweeps for the Mycelium MCP.

Two modes:

    # Synthetic — build fresh substrates of increasing sizes and time
    # a representative set of operations against each. This catches
    # algorithmic regressions in our own code (SQL, hnswlib, Python
    # glue) by isolating dataset size as the only variable.
    uv run python bench/run.py --sizes 100,500,1000,2000

    # Real — point at an existing KB directory and just time the
    # operations against it. No synthetic build, no dataset sweep —
    # one column of numbers describing what *that* substrate's
    # current performance looks like.
    uv run python bench/run.py --data-dir /path/to/your/kb/data

By default the bench uses a deterministic stub embedder so Ollama
latency (which is constant per-call regardless of dataset size) doesn't
swamp the measurements. Pass --ollama for end-to-end timing including
the real embedder.

Output is a tab-aligned stdout table plus optional `--json out.json`
for machine analysis. Each operation is run a configurable number of
times (default 20) and reported as p50 / p95 latency in milliseconds.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

# Make `mycelium` importable when this file is run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mycelium import embed, server  # noqa: E402


# ---------------------------------------------------------------------------
# Embedder stub
# ---------------------------------------------------------------------------


def deterministic_embed(text: str) -> list[float]:
    """Same text → same vector, no Ollama in the loop. CRC32 seed so the
    output is portable across processes."""
    seed = zlib.crc32(text.encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    return rng.standard_normal(768).astype(np.float32).tolist()


# ---------------------------------------------------------------------------
# Synthetic substrate builder
# ---------------------------------------------------------------------------


@dataclass
class Substrate:
    """Handles to an initialised substrate plus metadata for query selection."""

    behavior_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)


def build_synthetic(size: int, data_dir: Path, ollama: bool) -> Substrate:
    """Populate a fresh substrate with `size` behaviors and ~size/5 entities.
    Each behavior has 1-3 mentions and 1-2 outgoing links to earlier
    behaviors, producing a reasonably linked graph."""
    if not ollama:
        # Patch the embedder before any code path tries to use it.
        embed.embed = deterministic_embed  # type: ignore[assignment]

    # Reset module-level singletons so init can rebuild from this data dir.
    server._conn = None
    server._index = None
    server._index_path = None
    server.init(data_dir)

    sub = Substrate()
    n_entities = max(10, size // 5)
    for i in range(n_entities):
        name = f"Entity{i:04d}"
        result = server.upsert_entity(
            name=name, description=f"synthetic description for entity {i}"
        )
        sub.entity_ids.append(result["entity_id"])
        sub.entity_names.append(name)

    for i in range(size):
        n_mentions = 1 + (i % 3)
        mentions = [f"Entity{(i * 7 + j) % n_entities:04d}" for j in range(n_mentions)]
        n_links = min(len(sub.behavior_ids), 1 + (i % 2))
        links = [
            {
                "to_behavior_id": sub.behavior_ids[(i - j - 1) % len(sub.behavior_ids)],
                "link_type": "triggers" if (i + j) % 2 == 0 else "contains",
            }
            for j in range(n_links)
        ]
        result = server.upsert_behavior(
            text=(
                f"Synthetic behavior {i}: a test fact about "
                f"Entity{(i * 13) % n_entities:04d} that does something"
            ),
            mentions=mentions,
            links=links,
        )
        sub.behavior_ids.append(result["behavior_id"])

    return sub


def attach_existing(data_dir: Path, ollama: bool) -> Substrate:
    """Connect to an existing substrate without populating anything."""
    if not ollama:
        embed.embed = deterministic_embed  # type: ignore[assignment]
    server._conn = None
    server._index = None
    server._index_path = None
    server.init(data_dir)

    assert server._conn is not None
    sub = Substrate()
    sub.behavior_ids = [r["id"] for r in server._conn.execute("SELECT id FROM behaviors").fetchall()]
    rows = server._conn.execute(
        "SELECT e.id AS id, MIN(n.text) AS name "
        "FROM entities e LEFT JOIN names n ON n.entity_id = e.id "
        "GROUP BY e.id"
    ).fetchall()
    for r in rows:
        sub.entity_ids.append(r["id"])
        if r["name"]:
            sub.entity_names.append(r["name"])
    return sub


# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------


@dataclass
class Op:
    label: str
    """Human-readable name for the report column."""
    factory: Callable[[Substrate], Callable[[], object]]
    """Given a substrate, return a zero-arg callable that performs one
    iteration of the operation. The factory closes over substrate-specific
    state (random ids, query texts, etc.)."""
    needs_writes: bool = False
    """If True, the op mutates the substrate. Bench will rebuild between
    runs (more expensive)."""


def make_ops() -> list[Op]:
    """Factories for every MCP tool. Every op listed here corresponds
    1:1 to a `@tool`-decorated function in `mycelium.server`. Destructive
    ops (`needs_writes=True`) get a smaller per-op run count and pull
    from disposable pools the factory pre-allocates against the
    substrate, so they don't deplete it past usefulness."""
    rng = np.random.default_rng(42)

    # ---- pure reads ------------------------------------------------------

    def get_behavior(sub: Substrate):
        ids = sub.behavior_ids

        def f():
            server.get_behavior(ids[rng.integers(0, len(ids))])

        return f

    def get_entity(sub: Substrate):
        ids = sub.entity_ids

        def f():
            server.get_entity(ids[rng.integers(0, len(ids))])

        return f

    def search_d0(sub: Substrate):
        queries = [f"behavior {i} test" for i in range(20)]

        def f():
            server.search_behaviors(query=queries[rng.integers(0, len(queries))], limit=10)

        return f

    def search_d2(sub: Substrate):
        queries = [f"behavior {i} test" for i in range(20)]

        def f():
            server.search_behaviors(
                query=queries[rng.integers(0, len(queries))], limit=10, depth=2,
            )

        return f

    def search_mentions_filter(sub: Substrate):
        names = sub.entity_names

        def f():
            if not names:
                return
            server.search_behaviors(
                query="behavior test",
                limit=10,
                mentions=[names[rng.integers(0, len(names))]],
            )

        return f

    def list_behaviors_page(sub: Substrate):
        def f():
            server.list_behaviors(limit=50, offset=0)

        return f

    def list_behaviors_filtered(sub: Substrate):
        eids = sub.entity_ids

        def f():
            server.list_behaviors(limit=50, offset=0, entity_id=eids[rng.integers(0, len(eids))])

        return f

    def list_entities_prefix(sub: Substrate):
        def f():
            server.list_entities(prefix="Entity0", limit=50)

        return f

    def list_link_types_op(sub: Substrate):
        def f():
            server.list_link_types()

        return f

    def list_entity_link_types_op(sub: Substrate):
        def f():
            server.list_entity_link_types()

        return f

    def discover_facts_10(sub: Substrate):
        texts = [f"a test fact {i}" for i in range(10)]

        def f():
            server.discover_facts(texts=list(texts))

        return f

    def find_duplicates_op(sub: Substrate):
        def f():
            server.find_duplicates(threshold=0.92, limit=50)

        return f

    # ---- writes (non-destructive: append-only) ---------------------------

    def upsert_entity_op(sub: Substrate):
        counter = [0]

        def f():
            counter[0] += 1
            server.upsert_entity(
                name=f"BenchEntity_{counter[0]}_{rng.integers(0, 1_000_000)}",
                description="bench-only entity",
            )

        return f

    def upsert_name_op(sub: Substrate):
        counter = [0]
        eids = sub.entity_ids

        def f():
            counter[0] += 1
            server.upsert_name(
                text=f"bench_alias_{counter[0]}_{rng.integers(0, 1_000_000)}",
                entity_id=eids[rng.integers(0, len(eids))],
            )

        return f

    def upsert_behavior_op(sub: Substrate):
        counter = [0]
        names = sub.entity_names[:5] if sub.entity_names else []

        def f():
            counter[0] += 1
            server.upsert_behavior(
                text=f"benchmark write {counter[0]} for entity sample",
                mentions=names[:1],
                links=[],
            )

        return f

    def upsert_behaviors_batch(sub: Substrate):
        counter = [0]

        def f():
            counter[0] += 1
            server.upsert_behaviors(
                behaviors=[
                    {"text": f"batch write {counter[0]}.{i}", "mentions": [], "links": []}
                    for i in range(10)
                ],
            )

        return f

    def replace_text_op(sub: Substrate):
        # Picks a fresh behavior pool each iteration to avoid re-replacing
        # the same record (which would hit warm caches misleadingly).
        ids = sub.behavior_ids
        counter = [0]

        def f():
            counter[0] += 1
            target = ids[counter[0] % len(ids)]
            server.replace_text(
                id=target, text=f"replaced text {counter[0]} variation"
            )

        return f

    def add_mentions_op(sub: Substrate):
        ids = sub.behavior_ids
        names = sub.entity_names
        counter = [0]

        def f():
            counter[0] += 1
            target = ids[counter[0] % len(ids)]
            picks = [names[(counter[0] + j) % len(names)] for j in range(2)]
            server.add_mentions(id=target, mentions=picks)

        return f

    def remove_mentions_op(sub: Substrate):
        # Pre-add a known mention to behaviors we'll touch, so the remove
        # has something to actually remove. Otherwise it's a no-op and
        # not measuring real work.
        ids = sub.behavior_ids
        names = sub.entity_names
        marker = "BenchMarker_remove_target"
        if names and marker not in names:
            # Create a single throwaway entity + name we'll add then remove.
            server.upsert_entity(name=marker, description="bench-only marker")
        # Pre-attach to the behaviors this op will run against.
        targets = [ids[i] for i in range(min(50, len(ids)))]
        for t in targets:
            try:
                server.add_mentions(id=t, mentions=[marker])
            except Exception:
                pass
        counter = [0]

        def f():
            # Re-attach if exhausted; this keeps the op measuring removal,
            # not "no-op" misses.
            counter[0] += 1
            target = targets[counter[0] % len(targets)]
            try:
                server.add_mentions(id=target, mentions=[marker])
            except Exception:
                pass
            server.remove_mentions(id=target, mentions=[marker])

        return f

    def add_links_op(sub: Substrate):
        # Bulk add 10 edges each call between random pairs. Idempotent
        # via INSERT OR IGNORE so re-runs don't error.
        ids = sub.behavior_ids
        counter = [0]

        def f():
            counter[0] += 1
            edges = []
            for j in range(10):
                a = ids[(counter[0] * 7 + j) % len(ids)]
                b = ids[(counter[0] * 11 + j + 1) % len(ids)]
                if a != b:
                    edges.append({"from_behavior_id": a, "to_behavior_id": b, "link_type": "bench-link"})
            if edges:
                server.add_links(links=edges)

        return f

    def remove_links_op(sub: Substrate):
        # Mirror the add_links pattern so we have something to remove.
        ids = sub.behavior_ids
        counter = [0]

        def f():
            counter[0] += 1
            edges = []
            for j in range(10):
                a = ids[(counter[0] * 7 + j) % len(ids)]
                b = ids[(counter[0] * 11 + j + 1) % len(ids)]
                if a != b:
                    edges.append({"from_behavior_id": a, "to_behavior_id": b, "link_type": "bench-link"})
            if edges:
                server.add_links(links=edges)
                server.remove_links(links=edges)

        return f

    def add_entity_links_op(sub: Substrate):
        eids = sub.entity_ids
        counter = [0]

        def f():
            counter[0] += 1
            edges = []
            for j in range(5):
                a = eids[(counter[0] * 3 + j) % len(eids)]
                b = eids[(counter[0] * 5 + j + 1) % len(eids)]
                if a != b:
                    edges.append({"from_entity_id": a, "to_entity_id": b, "link_type": "bench-elink"})
            if edges:
                server.add_entity_links(links=edges)

        return f

    def remove_entity_links_op(sub: Substrate):
        eids = sub.entity_ids
        counter = [0]

        def f():
            counter[0] += 1
            edges = []
            for j in range(5):
                a = eids[(counter[0] * 3 + j) % len(eids)]
                b = eids[(counter[0] * 5 + j + 1) % len(eids)]
                if a != b:
                    edges.append({"from_entity_id": a, "to_entity_id": b, "link_type": "bench-elink"})
            if edges:
                server.add_entity_links(links=edges)
                server.remove_entity_links(links=edges)

        return f

    def move_name_op(sub: Substrate):
        # Pre-allocate pairs of entities and a name on each from-entity
        # we'll move per iteration. Size keyed off sub size so we don't
        # exhaust at any reasonable run count.
        eids = sub.entity_ids
        # Create N=20 names attached to a "donor" entity, then each
        # iteration moves one of those names to a target entity.
        donor = eids[0]
        targets = eids[1:]
        prepared: list[str] = []
        for i in range(40):
            tag = f"bench_move_{i}_{rng.integers(0, 1_000_000)}"
            try:
                r = server.upsert_entity(name=tag, description="")
                # The name we want is the one auto-attached during
                # upsert_entity; fetch its id.
                name_row = server._conn.execute(  # type: ignore[union-attr]
                    "SELECT id FROM names WHERE text = ?", (tag,)
                ).fetchone()
                if name_row is not None:
                    # Reattach the name to the donor entity so the op
                    # can move it elsewhere.
                    server.move_name(name_id=name_row["id"], to_entity_id=donor)
                    prepared.append(name_row["id"])
            except Exception:
                pass
        counter = [0]

        def f():
            if not prepared:
                return
            counter[0] += 1
            name_id = prepared[counter[0] % len(prepared)]
            target = targets[counter[0] % len(targets)]
            server.move_name(name_id=name_id, to_entity_id=target)

        return f

    # ---- destructive (consume nodes; pre-allocate dedicated pools) -------
    #
    # Each destructive op pre-creates its own disposable victims so they
    # don't collide with each other or with the substrate's structurally
    # linked behaviors. Pools are sized to outlast any reasonable
    # `--runs` value (the runner caps destructive ops at runs//4 anyway).

    POOL = 25  # enough for warmup + samples even at high --runs

    def merge_behaviors_op(sub: Substrate):
        pairs: list[tuple[str, str]] = []
        for i in range(POOL):
            src = server.upsert_behavior(
                text=f"bench_merge_src_{i}_{rng.integers(0, 1_000_000)}",
                mentions=[], links=[],
            )["behavior_id"]
            tgt = server.upsert_behavior(
                text=f"bench_merge_tgt_{i}_{rng.integers(0, 1_000_000)}",
                mentions=[], links=[],
            )["behavior_id"]
            pairs.append((src, tgt))
        counter = [0]

        def f():
            counter[0] += 1
            if counter[0] > len(pairs):
                return
            src, tgt = pairs[counter[0] - 1]
            try:
                server.merge_behaviors(from_behavior_id=src, into_behavior_id=tgt)
            except Exception:
                pass

        return f

    def merge_entities_op(sub: Substrate):
        pairs: list[tuple[str, str]] = []
        for i in range(POOL):
            src = server.upsert_entity(
                name=f"bench_mergeE_src_{i}_{rng.integers(0, 1_000_000)}",
                description="",
            )["entity_id"]
            tgt = server.upsert_entity(
                name=f"bench_mergeE_tgt_{i}_{rng.integers(0, 1_000_000)}",
                description="",
            )["entity_id"]
            pairs.append((src, tgt))
        counter = [0]

        def f():
            counter[0] += 1
            if counter[0] > len(pairs):
                return
            src, tgt = pairs[counter[0] - 1]
            try:
                server.merge_entities(from_entity_id=src, into_entity_id=tgt)
            except Exception:
                pass

        return f

    def delete_behavior_op(sub: Substrate):
        victims: list[str] = []
        for i in range(POOL):
            r = server.upsert_behavior(
                text=f"bench_delete_victim_{i}_{rng.integers(0, 1_000_000)}",
                mentions=[], links=[],
            )
            victims.append(r["behavior_id"])
        counter = [0]

        def f():
            counter[0] += 1
            if counter[0] > len(victims):
                return
            try:
                server.delete_behavior(id=victims[counter[0] - 1])
            except Exception:
                pass

        return f

    return [
        # reads
        Op("get_behavior", get_behavior),
        Op("get_entity", get_entity),
        Op("search d=0", search_d0),
        Op("search d=2", search_d2),
        Op("search mentions=", search_mentions_filter),
        Op("list_behaviors", list_behaviors_page),
        Op("list_behaviors+entity", list_behaviors_filtered),
        Op("list_entities prefix", list_entities_prefix),
        Op("list_link_types", list_link_types_op),
        Op("list_entity_link_types", list_entity_link_types_op),
        Op("discover_facts(10)", discover_facts_10),
        Op("find_duplicates", find_duplicates_op),
        # writes (append/idempotent)
        Op("upsert_entity", upsert_entity_op, needs_writes=True),
        Op("upsert_name", upsert_name_op, needs_writes=True),
        Op("upsert_behavior", upsert_behavior_op, needs_writes=True),
        Op("upsert_behaviors(10)", upsert_behaviors_batch, needs_writes=True),
        Op("replace_text", replace_text_op, needs_writes=True),
        Op("add_mentions", add_mentions_op, needs_writes=True),
        Op("remove_mentions", remove_mentions_op, needs_writes=True),
        Op("add_links(10)", add_links_op, needs_writes=True),
        Op("remove_links(10)", remove_links_op, needs_writes=True),
        Op("add_entity_links(5)", add_entity_links_op, needs_writes=True),
        Op("remove_entity_links(5)", remove_entity_links_op, needs_writes=True),
        Op("move_name", move_name_op, needs_writes=True),
        # destructive (consume nodes)
        Op("merge_behaviors", merge_behaviors_op, needs_writes=True),
        Op("merge_entities", merge_entities_op, needs_writes=True),
        Op("delete_behavior", delete_behavior_op, needs_writes=True),
    ]


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def time_op(fn: Callable[[], object], runs: int) -> dict[str, float]:
    """Run `fn` `runs` times after one warmup. Report p50/p95 in ms."""
    fn()  # warmup (caches, hot path, etc.)
    samples_ms: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
    samples_ms.sort()
    return {
        "p50_ms": samples_ms[len(samples_ms) // 2],
        "p95_ms": samples_ms[min(len(samples_ms) - 1, int(len(samples_ms) * 0.95))],
        "mean_ms": statistics.fmean(samples_ms),
        "n": runs,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_table(results: dict[str, dict[str, dict[str, float]]]) -> None:
    """results: { size_label: { op_label: { p50_ms, p95_ms, n } } }"""
    sizes = list(results.keys())
    if not sizes:
        return
    op_labels = list(results[sizes[0]].keys())

    # Compute column widths
    label_w = max(len(op) for op in op_labels) + 2
    cell_w = 12

    # Header: blank | size1 | size2 | ...
    header = f"{'op':<{label_w}}"
    for s in sizes:
        header += f"{s:>{cell_w * 2}}"
    print(header)
    sub = " " * label_w
    for _ in sizes:
        sub += f"{'p50 / p95 ms':>{cell_w * 2}}"
    print(sub)
    print("-" * len(header))

    for op in op_labels:
        row = f"{op:<{label_w}}"
        for s in sizes:
            r = results[s].get(op)
            if r is None:
                row += f"{'-':>{cell_w * 2}}"
            else:
                cell = f"{r['p50_ms']:6.2f} / {r['p95_ms']:6.2f}"
                row += f"{cell:>{cell_w * 2}}"
        print(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_one(sub: Substrate, ops: list[Op], runs: int, label: str) -> dict[str, dict[str, float]]:
    print(f"  [{label}] running {len(ops)} ops × {runs} samples ...", file=sys.stderr)
    out: dict[str, dict[str, float]] = {}
    for op in ops:
        # Skip write ops by default in synthetic mode? No — we want them
        # measured, just one shot per run rather than 20× compounding.
        # Use a smaller run count for write ops.
        op_runs = max(5, runs // 4) if op.needs_writes else runs
        try:
            fn = op.factory(sub)
            out[op.label] = time_op(fn, op_runs)
        except Exception as exc:
            print(f"    {op.label}: failed — {type(exc).__name__}: {exc}", file=sys.stderr)
            out[op.label] = {"p50_ms": float("nan"), "p95_ms": float("nan"), "n": 0}
    return out


def parse_sizes(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default="100,500,1000,2000",
        help="Synthetic-mode behavior counts (comma-separated)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Real-mode: bench against this existing KB instead of synthetic builds",
    )
    parser.add_argument("--runs", type=int, default=20, help="Samples per operation")
    parser.add_argument(
        "--ollama",
        action="store_true",
        help="Use the real Ollama embedder (slower, includes per-call network latency)",
    )
    parser.add_argument("--json", type=Path, default=None, help="Write results as JSON to this path")
    args = parser.parse_args()

    ops = make_ops()
    results: dict[str, dict[str, dict[str, float]]] = {}

    if args.data_dir is not None:
        label = f"existing:{args.data_dir.name}"
        sub = attach_existing(args.data_dir, ollama=args.ollama)
        print(
            f"  attached: {len(sub.behavior_ids)} behaviors, "
            f"{len(sub.entity_ids)} entities",
            file=sys.stderr,
        )
        results[label] = run_one(sub, ops, args.runs, label)
    else:
        for size in parse_sizes(args.sizes):
            label = f"N={size}"
            with tempfile.TemporaryDirectory(prefix=f"mycelium-bench-{size}-") as td:
                sub = build_synthetic(size, Path(td), ollama=args.ollama)
                print(f"  built {size} behaviors, {len(sub.entity_ids)} entities", file=sys.stderr)
                results[label] = run_one(sub, ops, args.runs, label)

    print()
    print_table(results)

    if args.json is not None:
        args.json.write_text(json.dumps(results, indent=2))
        print(f"\nwrote JSON: {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
