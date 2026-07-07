# Mycelium Benchmark Harness

Measures per-operation latency for every `@tool`-decorated MCP function
in `mycelium.server`. Two modes — synthetic substrates of increasing
size for scaling analysis, or an existing KB directory for spot
checks against real data.

The harness exists to **measure before tuning**. If something feels
slow, run a sweep and confirm which op is actually responsible
(and how it scales) before changing the implementation. Every commit
that claims a perf win should reproduce on the bench.

## Quick start

Synthetic sweep (default):

```sh
uv run python bench/run.py --sizes 100,500,1000,2000
```

Builds a fresh substrate at each size, runs every op, prints a
table of p50 / p95 latencies in milliseconds.

Real KB:

```sh
uv run python bench/run.py --data-dir /path/to/.mycelium
```

Connects to the existing substrate (read-only behavior + dedicated
disposable pools for write ops, so your data stays intact) and
reports a single column for that snapshot.

JSON for further analysis:

```sh
uv run python bench/run.py --sizes 100,500,1000,2000 --json results.json
```

## Flags

| Flag | Default | Purpose |
|---|---|---|
| `--sizes` | `100,500,1000,2000` | Comma-separated behavior counts for synthetic mode. Ignored when `--data-dir` is set. |
| `--data-dir DIR` | none | Bench against an existing KB instead of building synthetic. |
| `--runs N` | `20` | Samples per op. Destructive ops automatically run `max(5, N//4)` instead. |
| `--ollama` | off | Use the real Ollama embedder for end-to-end timing. By default a deterministic stub is used. |
| `--json PATH` | none | Also write results to a JSON file for further analysis. |

## Modes — what they answer

**Synthetic** (`--sizes ...`)
> *How does each op scale with dataset size?* Builds substrates in
> tmpdirs at each size, then times the same op set against each.
> Holds the data shape constant so the only variable is N. Catches
> algorithmic regressions in our own code (SQL, hnswlib, Python
> glue).

**Real KB** (`--data-dir ...`)
> *What's the actual latency right now against the data we have?*
> One column of numbers, no scaling info. Useful for sanity-checking
> the synthetic numbers against reality and for after-tuning
> verification.

## Embedder modes

By default, the harness swaps `embed.embed` for a deterministic stub
that hashes the input text into a 768-dim vector. This isolates our
code's cost from Ollama's per-call network latency — Ollama latency
is ~constant per call regardless of dataset size, so it would just
add a flat 30–100ms to every operation that embeds, swamping the
signal we care about.

Pass `--ollama` to use the real embedder for end-to-end numbers
(useful when you want to know "what does the user actually feel?"
including all real-world overhead).

## What gets measured

All 24 MCP tools are exercised. Operations are grouped by category:

**Reads** (12 ops) — never mutate the substrate; safe to run repeatedly:
- `get_behavior`, `get_entity`
- `search_behaviors` at depth 0, depth 2, with mentions filter
- `list_behaviors` (full and entity-filtered)
- `list_entities` with prefix filter
- `list_link_types`, `list_entity_link_types`
- `discover_facts(10)` — 10 candidate texts
- `find_duplicates(threshold=0.92)` — full pairwise audit

**Writes** (10 ops) — mutate the substrate but are append-only or
idempotent, so they can run many times without depleting it:
- `upsert_entity`, `upsert_name`, `upsert_behavior`, `upsert_behaviors(10)`
- `replace_text`, `add_mentions`, `remove_mentions`
- `add_links(10)`, `remove_links(10)`
- `add_entity_links(5)`, `remove_entity_links(5)`
- `move_name`

**Destructive** (3 ops) — actually consume nodes (`merge_*`,
`delete_*`). Each pre-creates its own disposable pool of 25 victims
at factory time and consumes one per iteration. Different ops use
different pools to avoid collisions.

## Output format

```
op                                         N=100                   N=500                  N=1000                  N=2000
                                    p50 / p95 ms            p50 / p95 ms            p50 / p95 ms            p50 / p95 ms
------------------------------------------------------------------------------------------------------------------------
get_behavior                       0.06 /   0.08           0.12 /   0.13           0.19 /   0.21           0.33 /   0.33
search d=2                         2.82 /   3.25           6.05 /   6.62           9.28 /  10.55          15.34 /  16.48
find_duplicates                   16.15 /  16.59         210.80 / 212.36         606.17 / 607.39       1578.76 / 1615.43
...
```

Each cell is `p50 / p95` in milliseconds. p95 is the 95th-percentile
latency from the sample distribution (so for `--runs 20`, that's
roughly the second-slowest sample).

## Reading the numbers

The shape of the column tells you how the op scales:

- **Flat across sizes** → constant-time op (e.g., `list_link_types`,
  `get_behavior` are nearly so).
- **2× growth for 20× data** → log-N (typical for vector search).
- **5–10× growth for 20× data** → roughly linear (`list_behaviors+entity`,
  `discover_facts`, `delete_behavior`).
- **Approaching N² growth** → 100× growth for 20× data, like
  `find_duplicates`. This is the smoking-gun shape that warrants
  optimization.

## Current known scaling (as of last sweep)

From a sweep at sizes 100, 500, 1000, 2000:

- **`find_duplicates`** scales near-N² — 16ms → 1587ms (100× for 20×
  data). This is the dominant pain point at large substrates. Calls
  `index.search(k=20)` once per behavior plus an SQL hydration per
  hit. Three optimization paths if/when needed: cache the result,
  use hnswlib's batch `knn_query`, or apply triangle-inequality
  pruning.
- **`replace_text`** scales sub-linearly (7× for 20×) but starts
  high — 6.5ms at N=100, 46ms at N=2000. Re-embeds the text and
  replaces the vector; the hnswlib replace cost grows with index
  size.
- **Everything else** scales linearly or better. All sub-10ms even
  at N=2000.

If a future sweep shows another op breaking out of these bounds,
that's the signal to optimize. Until then: the substrate is
generally healthy, and `find_duplicates` is the one structural
bottleneck.

## How destructive ops avoid stepping on each other

Earlier versions of this harness ran `merge_behaviors`, `merge_entities`,
and `delete_behavior` against the same back-of-list ids. Each op
walked backward from `behavior_ids[-1]`, so they collided: the
second op silently failed because the first had already deleted
its targets, and `delete_behavior` reported a fake 0.01ms across
all sizes.

The current version pre-allocates dedicated pools (25 fresh victims
per destructive op, created at factory time via `upsert_*` calls).
Each iteration consumes one victim from its op's own pool. Pools
are sized to outlast `--runs 100` so the bench can be cranked up
without re-tuning.

The pool creation happens *outside* the timing window, so the
measurement is just the destructive op itself.

## Adding a new op

In `bench/run.py`, the `make_ops()` function returns the list of
`Op` instances. Each `Op`:

```python
Op(label, factory, needs_writes=False)
```

- `label` — what shows up in the report column.
- `factory` — `Callable[[Substrate], Callable[[], None]]`. Given the
  built substrate, returns a zero-arg function that performs **one
  iteration** of the op. Closures hold any state (counters, pools,
  random seeds).
- `needs_writes=True` — flag for ops that mutate the substrate;
  triggers the lower iteration count.

To add a new op:

1. Write a factory that closes over substrate state and returns a
   zero-arg callable.
2. Append a new `Op(...)` to the list returned from `make_ops()`.
3. Run the bench to confirm sensible numbers (and that pre-existing
   ops haven't shifted).

If the new op is destructive, follow the dedicated-pool pattern —
pre-create everything it'll consume in the factory, consume one per
iteration, swallow any "exhausted" / "not found" errors so iteration
runs that exceed the pool become no-ops rather than hard failures.

## When to re-run

- After any change to the SQL schema, hnswlib usage, or the
  embedding pipeline. Compare against the previous numbers.
- When a user reports the MCP feeling slower. Bench against their
  KB directly with `--data-dir` to confirm whether it's substrate
  growth, a regression, or perception.
- Before claiming a performance optimization. The commit message
  should cite specific before/after numbers from the bench.
